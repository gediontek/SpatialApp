"""Harness — N1 (test env contamination).

Contract: the test process MUST NOT have any LLM provider API key set
in its environment. If a key is live, tests that hit the chat path will
silently make real API calls — causing cost, flakiness, and confusing
test failures keyed to the dev's local .env state.

The audit symptom: tests/test_chat_api.py:11 (and test_websocket.py)
cleared only ANTHROPIC_API_KEY, leaving GEMINI_API_KEY live. The
test_fallback_unknown test made a real Gemini call.

Centralized fix lives in tests/conftest.py — clears all four keys at
import time. This harness test is the regression guard.
"""
import os

import pytest


GUARDED_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)


@pytest.mark.parametrize("key", GUARDED_KEYS)
def test_llm_provider_keys_cleared(key):
    """Each guarded LLM key MUST be empty/unset in the test process."""
    val = os.environ.get(key, "")
    assert val == "", (
        f"{key} is set in the test environment ({len(val)} chars). "
        "Audit N1: tests will make real API calls. "
        "tests/conftest.py should clear it on import."
    )
