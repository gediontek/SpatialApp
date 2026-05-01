"""LLM response cache (v2.1 Plan 13 M3.1).

Thread-safe TTL cache for full LLM responses, keyed on the hash of
(system_prompt, last_N_messages, tools). Default TTL: 5 minutes,
default capacity: 500 entries.

Cache hit path emits the same SSE events as a fresh API call by storing
the raw response. Cache miss falls through to the API.

Pattern mirrors `_spatial_cache` in `nl_gis/handlers/analysis.py`.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from typing import Any


class LLMCache:
    """LRU + TTL cache for normalized LLM responses."""

    def __init__(self, ttl_seconds: float = 300.0, max_entries: int = 500):
        self._ttl = float(ttl_seconds)
        self._max = int(max_entries)
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        # Light-weight stats so callers can build hit/miss metrics
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    @staticmethod
    def make_key(*, system: str, messages: list, tools: list,
                 last_n: int = 6, model: str | None = None) -> str:
        """Build a stable cache key from the relevant request inputs."""
        # Only the last N messages matter for context; older messages are
        # already represented in the assistant's prior outputs.
        tail = messages[-last_n:] if last_n > 0 else messages
        try:
            tail_blob = json.dumps(tail, sort_keys=True, default=str)
        except (TypeError, ValueError):
            tail_blob = repr(tail)
        try:
            tools_blob = json.dumps(
                [{"name": t.get("name"), "description": t.get("description")}
                 for t in (tools or [])],
                sort_keys=True,
            )
        except (TypeError, ValueError):
            tools_blob = repr(tools)
        sys_hash = hashlib.sha256((system or "").encode()).hexdigest()[:16]
        digest = hashlib.sha256(
            (sys_hash + "\n" + tail_blob + "\n" + tools_blob + "\n" + (model or "")).encode()
        ).hexdigest()
        return digest

    def get(self, key: str) -> Any | None:
        now = time.time()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            ts, value = entry
            if now - ts > self._ttl:
                # Expired
                self._data.pop(key, None)
                self._evictions += 1
                self._misses += 1
                return None
            # LRU touch
            self._data.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        now = time.time()
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self._data[key] = (now, value)
                return
            self._data[key] = (now, value)
            while len(self._data) > self._max:
                self._data.popitem(last=False)
                self._evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    def stats(self) -> dict:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "size": len(self._data),
                "max": self._max,
                "ttl_seconds": self._ttl,
            }

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._data)


# Module-level default cache (lazy init so env vars are read at first use).
_default: LLMCache | None = None
_default_lock = threading.Lock()


def get_default_cache() -> LLMCache:
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                ttl = float(os.environ.get("LLM_CACHE_TTL", "300"))
                cap = int(os.environ.get("LLM_CACHE_MAX_ENTRIES", "500"))
                _default = LLMCache(ttl_seconds=ttl, max_entries=cap)
    return _default


def reset_default_cache() -> None:
    """Test hook."""
    global _default
    with _default_lock:
        _default = None


# Bypass tokens — phrases that force a fresh API call regardless of cache.
BYPASS_PHRASES = ("recalculate", "fresh", "refresh", "force re-run", "no cache")


def should_bypass(message: str) -> bool:
    if not message:
        return False
    text = message.lower()
    return any(p in text for p in BYPASS_PHRASES)
