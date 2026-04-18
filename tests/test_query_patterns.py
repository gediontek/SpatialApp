"""Tests for v2.1 Plan 03: query patterns, parameter threading, chain validation."""

from __future__ import annotations

import pytest

from nl_gis.query_patterns import (
    QueryPattern,
    get_all_patterns,
    match_patterns,
    resolve_step_references,
    validate_plan_chain,
)


# ---------------------------------------------------------------------------
# M5 E5.1 — match_patterns tests (12+ cases)
# ---------------------------------------------------------------------------


class TestMatchPatterns:
    def test_catalog_has_ten_patterns(self):
        patterns = get_all_patterns()
        assert len(patterns) == 10
        names = {p.name for p in patterns}
        expected = {
            "proximity-search", "overlay-analysis", "compare-layers",
            "buffer-and-count", "route-with-nearby", "coverage-analysis",
            "cluster-and-hotspot", "multi-criteria-filter",
            "import-and-analyze", "spatial-join",
        }
        assert names == expected

    def test_proximity_search_matches_example(self):
        hits = match_patterns("Find parks within 2km of Central Park")
        names = [p.name for p, _ in hits]
        assert "proximity-search" in names

    def test_buffer_and_count_matches_example(self):
        hits = match_patterns("How many cafes are within 500m of Times Square?")
        names = [p.name for p, _ in hits]
        assert "buffer-and-count" in names
        assert "proximity-search" in names  # overlap is OK — both trigger
        # Whichever ranks first, both should score >= 0.5
        for p, score in hits:
            if p.name in ("buffer-and-count", "proximity-search"):
                assert score >= 0.5

    def test_overlay_analysis_matches_example(self):
        hits = match_patterns("Where do parks and flood zones overlap in Portland?")
        assert any(p.name == "overlay-analysis" for p, _ in hits)

    def test_compare_layers_matches_example(self):
        hits = match_patterns("Subtract water from the land area in Seattle")
        assert any(p.name == "compare-layers" for p, _ in hits)

    def test_route_with_nearby_matches_example(self):
        hits = match_patterns("Find restaurants along my route from A to B")
        assert any(p.name == "route-with-nearby" for p, _ in hits)

    def test_coverage_analysis_matches_example(self):
        hits = match_patterns("What is the 15-minute coverage of hospitals in Chicago?")
        assert any(p.name == "coverage-analysis" for p, _ in hits)

    def test_cluster_and_hotspot_matches_example(self):
        hits = match_patterns("Find clusters of crime and show hot spots")
        assert any(p.name == "cluster-and-hotspot" for p, _ in hits)

    def test_multi_criteria_filter_matches_example(self):
        hits = match_patterns("How many buildings taller than 50 meters are in downtown Seattle?")
        assert any(p.name == "multi-criteria-filter" for p, _ in hits)

    def test_import_and_analyze_matches_example(self):
        hits = match_patterns("Import this CSV and show a heatmap of the points")
        assert any(p.name == "import-and-analyze" for p, _ in hits)

    def test_spatial_join_matches_example(self):
        hits = match_patterns("Tag each store with its census tract")
        assert any(p.name == "spatial-join" for p, _ in hits)

    def test_non_matching_query_returns_empty(self):
        hits = match_patterns("hello world")
        assert hits == []

    def test_empty_query_returns_empty(self):
        assert match_patterns("") == []

    def test_hits_are_sorted_descending(self):
        hits = match_patterns("How many cafes are within 500m of Times Square?")
        scores = [s for _, s in hits]
        assert scores == sorted(scores, reverse=True)

    def test_min_score_threshold_is_honored(self):
        # A query that weakly matches — forcing min_score=0.9 should filter it out.
        hits_low = match_patterns("find restaurants near", min_score=0.3)
        hits_high = match_patterns("find restaurants near", min_score=0.9)
        assert len(hits_high) <= len(hits_low)


# ---------------------------------------------------------------------------
# M5 E5.2 — resolve_step_references tests (5+ cases)
# ---------------------------------------------------------------------------


class TestResolveStepReferences:
    def test_simple_string_reference(self):
        outputs = {1: {"layer_name": "parks_chicago"}}
        resolved = resolve_step_references({"source": "$step1.layer_name"}, outputs)
        assert resolved == {"source": "parks_chicago"}

    def test_nested_dict_reference(self):
        outputs = {2: {"geojson": {"type": "FeatureCollection", "features": []}}}
        resolved = resolve_step_references(
            {"input": {"geometry": "$step2.geojson"}},
            outputs,
        )
        assert resolved == {"input": {"geometry": {"type": "FeatureCollection", "features": []}}}

    def test_list_containing_reference(self):
        outputs = {1: {"lat": 40.7}, 2: {"lat": 41.8}}
        resolved = resolve_step_references(
            {"points": ["$step1.lat", "$step2.lat"]},
            outputs,
        )
        assert resolved == {"points": [40.7, 41.8]}

    def test_string_interpolation_preserves_prefix(self):
        outputs = {1: {"layer_name": "parks"}}
        resolved = resolve_step_references(
            {"display": "layer=$step1.layer_name"},
            outputs,
        )
        assert resolved == {"display": "layer=parks"}

    def test_missing_step_raises_value_error(self):
        outputs = {1: {"layer_name": "parks"}}
        with pytest.raises(ValueError) as exc:
            resolve_step_references({"source": "$step5.layer_name"}, outputs)
        assert "step 5" in str(exc.value).lower()
        assert "has not executed" in str(exc.value).lower()

    def test_missing_field_raises_value_error(self):
        outputs = {1: {"layer_name": "parks"}}
        with pytest.raises(ValueError) as exc:
            resolve_step_references({"source": "$step1.nonexistent"}, outputs)
        assert "nonexistent" in str(exc.value)
        assert "step 1" in str(exc.value).lower()

    def test_no_references_returns_unchanged(self):
        params = {"a": 1, "b": "hello", "c": [1, 2, 3]}
        resolved = resolve_step_references(params, {})
        assert resolved == params

    def test_type_preserved_for_single_reference(self):
        outputs = {1: {"count": 42, "flag": True}}
        resolved = resolve_step_references({"n": "$step1.count", "ok": "$step1.flag"}, outputs)
        assert resolved["n"] == 42
        assert resolved["n"] is not "42"  # noqa: F632 — intent is to catch type drift
        assert resolved["ok"] is True


# ---------------------------------------------------------------------------
# M5 E5.3 — validate_plan_chain tests (3+ cases)
# ---------------------------------------------------------------------------


class TestValidatePlanChain:
    def test_valid_proximity_chain_produces_no_warnings(self):
        steps = [
            {"step": 1, "tool": "geocode", "params": {"query": "Central Park"}},
            {"step": 2, "tool": "buffer", "params": {"geometry": "$step1.bbox", "distance_m": 2000}},
            {"step": 3, "tool": "fetch_osm", "params": {"feature_type": "park", "location": "NYC"}},
            {"step": 4, "tool": "spatial_query", "params": {
                "source_layer": "$step3.layer_name",
                "target_layer": "$step2.layer_name",
                "predicate": "within",
            }},
        ]
        assert validate_plan_chain(steps) == []

    def test_invalid_chain_catches_type_mismatch(self):
        # geocode outputs lat/lon (number), not a layer_name. Feeding step 1
        # output as source_layer to filter_layer should warn.
        steps = [
            {"step": 1, "tool": "geocode", "params": {"query": "NYC"}},
            {"step": 2, "tool": "filter_layer", "params": {
                "layer_name": "$step1.lat",  # wrong type: number instead of layer_name
                "attribute": "x",
                "operator": "equals",
                "value": "1",
            }},
        ]
        warnings = validate_plan_chain(steps)
        assert warnings, "expected a warning for step 2's type mismatch"
        assert any("filter_layer" in w and "layer_name" in w for w in warnings)

    def test_chain_with_no_references_has_no_warnings(self):
        # Each step is independent; no $stepN references to validate.
        steps = [
            {"step": 1, "tool": "geocode", "params": {"query": "London"}},
            {"step": 2, "tool": "geocode", "params": {"query": "Paris"}},
        ]
        assert validate_plan_chain(steps) == []

    def test_missing_tool_name_produces_warning(self):
        steps = [{"step": 1, "params": {}}]
        warnings = validate_plan_chain(steps)
        assert warnings
        assert "missing tool name" in warnings[0].lower()

    def test_unknown_tool_is_skipped_not_flagged(self):
        # Conservative: unknown tools don't produce warnings.
        steps = [
            {"step": 1, "tool": "an_experimental_tool_not_in_registry", "params": {}},
            {"step": 2, "tool": "fetch_osm", "params": {"location": "$step1.something"}},
        ]
        warnings = validate_plan_chain(steps)
        # No warning about the unknown tool's type.
        assert not any("an_experimental_tool" in w for w in warnings)
