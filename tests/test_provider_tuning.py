"""Tests for v2.1 Plan 07 provider-tuning mechanism.

Covers the surgical mechanism — `apply_provider_hints`,
`get_system_prompt`, and the `compare_providers` / `check_parity`
helpers in the eval runner. Does NOT make any live API calls.
"""

from __future__ import annotations

import pytest

from nl_gis.chat import (
    ANTHROPIC_ADDENDUM,
    GEMINI_ADDENDUM,
    OPENAI_ADDENDUM,
    PROVIDER_ADDENDA,
    SYSTEM_PROMPT,
    get_system_prompt,
)
from nl_gis.llm_provider import (
    PROVIDER_NOTES,
    apply_provider_hints,
)
from nl_gis.tools import get_tool_definitions
from tests.eval.run_eval import check_parity, compare_providers


# ---------------------------------------------------------------------------
# get_system_prompt
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    def test_returns_base_when_no_provider(self):
        assert get_system_prompt(None) == SYSTEM_PROMPT
        assert get_system_prompt("") == SYSTEM_PROMPT

    def test_unknown_provider_returns_base(self):
        # No crash, no addendum
        out = get_system_prompt("imaginary_provider")
        assert out == SYSTEM_PROMPT

    def test_anthropic_addendum_appended(self):
        out = get_system_prompt("anthropic")
        assert out.startswith(SYSTEM_PROMPT)
        assert "Anthropic" in out
        assert ANTHROPIC_ADDENDUM in out

    def test_openai_addendum_appended(self):
        out = get_system_prompt("openai")
        assert out.startswith(SYSTEM_PROMPT)
        assert OPENAI_ADDENDUM in out
        # Should reference the closest_facility / search_nearby distinction
        assert "closest_facility" in out

    def test_gemini_addendum_appended(self):
        out = get_system_prompt("gemini")
        assert out.startswith(SYSTEM_PROMPT)
        assert GEMINI_ADDENDUM in out

    def test_case_insensitive(self):
        assert get_system_prompt("OPENAI") == get_system_prompt("openai")

    def test_addenda_are_distinct(self):
        # Each addendum must be unique — otherwise tuning bleeds across providers
        addenda = list(PROVIDER_ADDENDA.values())
        assert len(set(addenda)) == len(addenda)


# ---------------------------------------------------------------------------
# apply_provider_hints
# ---------------------------------------------------------------------------

class TestApplyProviderHints:
    def test_no_hints_passthrough(self):
        tools = [{"name": "x", "description": "Y", "input_schema": {"type": "object"}}]
        out = apply_provider_hints(tools, "openai")
        assert out[0]["description"] == "Y"
        # provider_hints field must not be present
        assert "provider_hints" not in out[0]

    def test_matching_provider_appended(self):
        tools = [{
            "name": "x", "description": "Y",
            "input_schema": {"type": "object"},
            "provider_hints": {"openai": {"description_suffix": "USE THIS WHEN Z."}},
        }]
        out = apply_provider_hints(tools, "openai")
        assert out[0]["description"].endswith("USE THIS WHEN Z.")
        assert "provider_hints" not in out[0]

    def test_non_matching_provider_strips_hints_but_keeps_base(self):
        tools = [{
            "name": "x", "description": "Y",
            "input_schema": {"type": "object"},
            "provider_hints": {"openai": {"description_suffix": "Foo"}},
        }]
        out = apply_provider_hints(tools, "anthropic")
        assert out[0]["description"] == "Y"
        assert "provider_hints" not in out[0]

    def test_empty_suffix_no_op(self):
        tools = [{
            "name": "x", "description": "Y",
            "provider_hints": {"openai": {"description_suffix": ""}},
        }]
        out = apply_provider_hints(tools, "openai")
        assert out[0]["description"] == "Y"

    def test_does_not_mutate_input(self):
        original = [{
            "name": "x", "description": "Y",
            "input_schema": {"type": "object"},
            "provider_hints": {"openai": {"description_suffix": "Z"}},
        }]
        before = original[0]["description"]
        apply_provider_hints(original, "openai")
        assert original[0]["description"] == before
        assert "provider_hints" in original[0]

    def test_unknown_provider(self):
        tools = [{
            "name": "x", "description": "Y",
            "provider_hints": {"openai": {"description_suffix": "Z"}},
        }]
        out = apply_provider_hints(tools, "ghost")
        assert out[0]["description"] == "Y"

    def test_real_tool_definitions_apply_cleanly(self):
        # Run apply_provider_hints over the actual tool catalog for each
        # provider; nothing should crash, and nothing should retain
        # provider_hints.
        tools = get_tool_definitions()
        for prov in ("openai", "anthropic", "gemini"):
            out = apply_provider_hints(tools, prov)
            assert len(out) == len(tools)
            for tool in out:
                assert "provider_hints" not in tool
                assert tool.get("description")  # non-empty

    def test_closest_facility_has_openai_hint(self):
        # Sanity check: the canonical tool we tuned should carry an OpenAI
        # suffix that mentions 'search_nearby'.
        tools = get_tool_definitions()
        cf = next(t for t in tools if t["name"] == "closest_facility")
        out = apply_provider_hints([cf], "openai")
        assert "search_nearby" in out[0]["description"]
        # Non-OpenAI provider does not get the suffix
        out_anth = apply_provider_hints([cf], "anthropic")
        assert "NOT search_nearby" not in out_anth[0]["description"]


# ---------------------------------------------------------------------------
# Provider notes
# ---------------------------------------------------------------------------

class TestProviderNotes:
    def test_all_three_providers_documented(self):
        for prov in ("anthropic", "openai", "gemini"):
            assert prov in PROVIDER_NOTES
            entry = PROVIDER_NOTES[prov]
            assert "strengths" in entry
            assert "weaknesses" in entry
            assert "tuning_applied" in entry
            assert all(isinstance(s, str) for s in entry["strengths"])


# ---------------------------------------------------------------------------
# compare_providers + check_parity
# ---------------------------------------------------------------------------

def _make_batch(accuracy, by_category=None):
    return {
        "accuracy": accuracy,
        "by_category": by_category or {},
    }


def _make_results(provider, accuracy, raw, by_category=None):
    return {
        "provider": provider,
        "batch": _make_batch(accuracy, by_category),
        "raw": raw,
    }


class TestCompareProviders:
    def test_identical_runs_have_zero_delta(self):
        raw = [{"query_id": "Q1", "actual_tools": ["geocode"], "actual_params": {}}]
        a = _make_results("anthropic", 0.85, raw)
        b = _make_results("openai", 0.85, raw)
        cmp = compare_providers(a, b)
        assert cmp["overall"]["delta"] == 0.0
        assert cmp["disagreements"] == []

    def test_disagreement_recorded(self):
        a = _make_results("anthropic", 0.5, [
            {"query_id": "Q1", "actual_tools": ["closest_facility"], "actual_params": {}},
        ])
        b = _make_results("openai", 0.5, [
            {"query_id": "Q1", "actual_tools": ["search_nearby"], "actual_params": {}},
        ])
        cmp = compare_providers(a, b)
        assert len(cmp["disagreements"]) == 1
        d = cmp["disagreements"][0]
        assert d["query_id"] == "Q1"
        assert d["anthropic_tools"] == ["closest_facility"]
        assert d["openai_tools"] == ["search_nearby"]

    def test_category_deltas(self):
        a = _make_results(
            "anthropic", 0.7, [],
            by_category={
                "routing": {"accuracy": 0.9},
                "viz": {"accuracy": 0.6},
            },
        )
        b = _make_results(
            "openai", 0.65, [],
            by_category={
                "routing": {"accuracy": 0.8},  # delta = -0.1
                "viz": {"accuracy": 0.65},      # delta = +0.05
            },
        )
        cmp = compare_providers(a, b)
        assert pytest.approx(cmp["category_deltas"]["routing"]["delta"]) == -0.1
        assert pytest.approx(cmp["category_deltas"]["viz"]["delta"]) == 0.05

    def test_category_only_in_one_provider(self):
        a = _make_results("anthropic", 0.5, [], by_category={"routing": {"accuracy": 1.0}})
        b = _make_results("openai", 0.5, [], by_category={"viz": {"accuracy": 1.0}})
        cmp = compare_providers(a, b)
        # Both categories appear in deltas; missing side is 0.0
        assert cmp["category_deltas"]["routing"]["accuracy_b"] == 0.0
        assert cmp["category_deltas"]["viz"]["accuracy_a"] == 0.0


class TestCheckParity:
    def test_within_threshold_returns_empty(self):
        cmp = {"category_deltas": {"a": {"delta": 0.04}, "b": {"delta": -0.03}}}
        assert check_parity(cmp, 0.05) == []

    def test_over_threshold_lists_categories(self):
        cmp = {"category_deltas": {"a": {"delta": 0.06}, "b": {"delta": -0.10}, "c": {"delta": 0.0}}}
        out = check_parity(cmp, 0.05)
        assert sorted(out) == ["a", "b"]

    def test_no_categories_returns_empty(self):
        assert check_parity({}, 0.05) == []
