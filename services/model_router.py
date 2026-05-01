"""Model tiering router (v2.1 Plan 13 M3.2).

Heuristic classifier that decides whether a query is "simple" (cheap
model) or "complex" (full model) based on phrasing patterns.

Conservative bias: when in doubt → complex. Misrouting a complex query
to a small model is a quality regression; misrouting a simple one to
the full model is just a cost regression. Pick the safer side.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Sequence


# Regexes are matched against lowercased message text.
SIMPLE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bwhere is\b"),
    re.compile(r"\bshow (me )?(the )?\w+\b"),
    re.compile(r"\bdisplay\b"),
    re.compile(r"\bhide\b"),
    re.compile(r"\bremove (the )?layer\b"),
    re.compile(r"\bzoom (in|out|to)\b"),
    re.compile(r"\bpan to\b"),
    re.compile(r"\bcolor (the )?\w+\b"),
    re.compile(r"\bgeocode\b"),
    re.compile(r"\bwhat (is|are) (the )?coordinates\b"),
)

# Patterns that disqualify a query from "simple" classification, even if
# a SIMPLE_PATTERN matches. Multi-step / spatial / chained operations.
COMPLEX_DISQUALIFIERS: tuple[re.Pattern, ...] = (
    re.compile(r"\bbuffer\b"),
    re.compile(r"\bintersect"),
    re.compile(r"\boverlap"),
    re.compile(r"\bclip\b"),
    re.compile(r"\bisochrone\b"),
    re.compile(r"\broute\b"),
    re.compile(r"\bnearest\b"),
    re.compile(r"\bclosest\b"),
    re.compile(r"\boptim"),
    re.compile(r"\banimat"),
    re.compile(r"\bclassif"),
    re.compile(r"\bjoin\b"),
    re.compile(r"\bthen\b"),       # explicit chaining
    re.compile(r"\band then\b"),
    re.compile(r"\baggregat"),
)


@dataclass(frozen=True)
class RouterDecision:
    tier: str             # "simple" or "complex"
    model: str            # model id to use
    matched_pattern: str | None  # pattern that drove the classification


class ModelRouter:
    """Pure-function router. State-less; safe to share across threads."""

    def __init__(
        self,
        simple_model: str | None = None,
        complex_model: str | None = None,
        enabled: bool | None = None,
    ):
        # Lazy import: avoid circular config import at module load
        from config import Config
        self._simple_model = simple_model or os.environ.get(
            "SIMPLE_MODEL", "claude-3-5-haiku-latest",
        )
        self._complex_model = complex_model or Config.get_llm_model()
        self._enabled = (
            enabled
            if enabled is not None
            else os.environ.get("MODEL_TIERING_ENABLED", "false").lower() in {"1", "true", "yes"}
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def simple_model(self) -> str:
        return self._simple_model

    @property
    def complex_model(self) -> str:
        return self._complex_model

    def select(self, message: str) -> RouterDecision:
        """Classify a user message and return the model decision."""
        if not self._enabled:
            return RouterDecision("complex", self._complex_model, None)

        text = (message or "").lower().strip()
        if not text:
            return RouterDecision("complex", self._complex_model, None)

        # Long messages are very rarely "simple".
        if len(text.split()) > 25:
            return RouterDecision("complex", self._complex_model, "length>25")

        # If any disqualifier hits, it's complex regardless of simple match
        for pat in COMPLEX_DISQUALIFIERS:
            if pat.search(text):
                return RouterDecision("complex", self._complex_model, pat.pattern)

        for pat in SIMPLE_PATTERNS:
            if pat.search(text):
                return RouterDecision("simple", self._simple_model, pat.pattern)

        return RouterDecision("complex", self._complex_model, None)


# Module-level default router (lazily configured by env vars).
_default_router: ModelRouter | None = None


def get_default_router() -> ModelRouter:
    global _default_router
    if _default_router is None:
        _default_router = ModelRouter()
    return _default_router


def reset_default_router() -> None:
    """Test hook: drop the cached default router so tests can reconfigure
    via env vars."""
    global _default_router
    _default_router = None
