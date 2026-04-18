"""Tests for v2.1 Plan 04: spatial context library + attribute validation."""

from __future__ import annotations

import time

import pytest

from nl_gis.context import (
    ANAPHORIC_PATTERNS,
    ReferenceEntry,
    ReferenceTracker,
    contains_anaphor,
    extract_layer_metadata,
    format_layer_summary,
    format_viewport_hint,
    get_layer_attribute_names,
    needs_attribute_context,
)


# ---------------------------------------------------------------------------
# Fixtures — small deterministic GeoJSON samples
# ---------------------------------------------------------------------------


def _point(lat, lon, **props):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }


def _poly(ring, **props):
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": props,
    }


# ---------------------------------------------------------------------------
# M5 E5.1 — extract_layer_metadata
# ---------------------------------------------------------------------------


class TestExtractLayerMetadata:
    def test_empty_layer(self):
        meta = extract_layer_metadata("empty", {"type": "FeatureCollection", "features": []})
        assert meta["feature_count"] == 0
        assert meta["geometry_types"] == set()
        assert meta["bbox"] is None
        assert meta["attributes"] == {}

    def test_point_layer_with_attributes(self):
        fc = {
            "type": "FeatureCollection",
            "features": [
                _point(40.7, -74.0, name="A", height=10),
                _point(40.8, -73.9, name="B", height=20),
            ],
        }
        meta = extract_layer_metadata("pts", fc)
        assert meta["feature_count"] == 2
        assert meta["geometry_types"] == {"Point"}
        assert meta["bbox"] is not None
        assert "name" in meta["attributes"]
        assert meta["attributes"]["name"]["type"] == "string"
        assert meta["attributes"]["height"]["type"] == "number"

    def test_polygon_layer_bbox_correctness(self):
        ring = [[-87.7, 41.85], [-87.6, 41.85], [-87.6, 41.92], [-87.7, 41.92], [-87.7, 41.85]]
        fc = {"type": "FeatureCollection", "features": [_poly(ring, zone="A")]}
        meta = extract_layer_metadata("zone", fc)
        s, w, n, e = meta["bbox"]
        assert abs(s - 41.85) < 0.001
        assert abs(w - (-87.7)) < 0.001
        assert abs(n - 41.92) < 0.001
        assert abs(e - (-87.6)) < 0.001

    def test_mixed_geometry_types(self):
        ring = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
        fc = {
            "type": "FeatureCollection",
            "features": [_point(0.5, 0.5), _poly(ring)],
        }
        meta = extract_layer_metadata("mixed", fc)
        assert meta["geometry_types"] == {"Point", "Polygon"}

    def test_attribute_truncation_at_cap(self):
        # 25 distinct attributes; cap is 20
        props = {f"attr_{i}": i for i in range(25)}
        fc = {"type": "FeatureCollection", "features": [_point(0, 0, **props)]}
        meta = extract_layer_metadata("big", fc, max_attributes=20)
        assert meta["attributes_truncated"] is True
        assert len(meta["attributes"]) == 20

    def test_large_layer_performance(self):
        # 1000 point features — should extract in well under 200ms
        fc = {
            "type": "FeatureCollection",
            "features": [_point(i * 0.01, i * 0.01, id=i) for i in range(1000)],
        }
        start = time.monotonic()
        meta = extract_layer_metadata("large", fc)
        elapsed_ms = (time.monotonic() - start) * 1000
        assert meta["feature_count"] == 1000
        assert elapsed_ms < 500, f"metadata extraction took {elapsed_ms:.0f}ms"


# ---------------------------------------------------------------------------
# M5 E5.2 — format_layer_summary
# ---------------------------------------------------------------------------


class TestFormatLayerSummary:
    def test_summary_under_200_chars(self):
        fc = {
            "type": "FeatureCollection",
            "features": [_point(0, 0, name=f"n_{i}", height=i) for i in range(5)],
        }
        meta = extract_layer_metadata("buildings", fc)
        summary = format_layer_summary(meta)
        assert len(summary) <= 200

    def test_summary_includes_geometry_and_bbox(self):
        fc = {"type": "FeatureCollection", "features": [_point(40, -74, name="x")]}
        meta = extract_layer_metadata("pts", fc)
        summary = format_layer_summary(meta)
        assert "Point" in summary
        assert "bbox" in summary.lower()

    def test_summary_includes_attribute_names(self):
        fc = {"type": "FeatureCollection", "features": [_point(0, 0, city="NY", pop=100)]}
        meta = extract_layer_metadata("pts", fc)
        summary = format_layer_summary(meta)
        assert "city" in summary
        assert "pop" in summary

    def test_summary_truncates_to_max_chars(self):
        fc = {
            "type": "FeatureCollection",
            "features": [_point(0, 0, **{f"very_long_attr_name_{i}": f"v_{i}" for i in range(10)})],
        }
        meta = extract_layer_metadata("x", fc)
        summary = format_layer_summary(meta, max_chars=80)
        assert len(summary) <= 80
        assert summary.endswith("...")


# ---------------------------------------------------------------------------
# M5 E5.3 — ReferenceTracker
# ---------------------------------------------------------------------------


class TestReferenceTracker:
    def test_add_and_get_recent(self):
        t = ReferenceTracker()
        t.add(ReferenceEntry(turn=1, type="layer", name="parks_chicago"))
        t.add(ReferenceEntry(turn=2, type="location", name="Chicago"))
        t.add(ReferenceEntry(turn=3, type="layer", name="buildings_nyc"))
        recent = t.get_recent(2)
        assert len(recent) == 2
        assert recent[-1].name == "buildings_nyc"

    def test_resolve_those_to_most_recent_layer(self):
        t = ReferenceTracker()
        t.add(ReferenceEntry(turn=1, type="location", name="Chicago"))
        t.add(ReferenceEntry(turn=2, type="layer", name="buildings_nyc"))
        resolved = t.resolve("color those red")
        assert resolved is not None
        assert resolved.name == "buildings_nyc"

    def test_resolve_that_area_to_location(self):
        t = ReferenceTracker()
        t.add(ReferenceEntry(turn=1, type="location", name="Central Park"))
        t.add(ReferenceEntry(turn=2, type="layer", name="trees"))
        resolved = t.resolve("how many crimes in that area")
        assert resolved is not None
        assert resolved.name == "Central Park"

    def test_resolve_the_parks_by_substring(self):
        t = ReferenceTracker()
        t.add(ReferenceEntry(turn=1, type="layer", name="buildings_nyc"))
        t.add(ReferenceEntry(turn=2, type="layer", name="parks_chicago"))
        resolved = t.resolve("hide the parks")
        assert resolved is not None
        assert resolved.name == "parks_chicago"

    def test_resolve_unknown_returns_none(self):
        t = ReferenceTracker()
        t.add(ReferenceEntry(turn=1, type="layer", name="x"))
        assert t.resolve("something totally unrelated") is None

    def test_ring_buffer_eviction(self):
        t = ReferenceTracker(capacity=3)
        for i in range(5):
            t.add(ReferenceEntry(turn=i, type="layer", name=f"L{i}"))
        all_entries = t.all()
        assert len(all_entries) == 3
        # Oldest entries L0 and L1 should be evicted
        assert all_entries[0].name == "L2"
        assert all_entries[-1].name == "L4"


# ---------------------------------------------------------------------------
# M5 E5.4 — get_layer_attribute_names + anaphor / attribute scanners
# ---------------------------------------------------------------------------


class TestHelperScanners:
    def test_contains_anaphor_true_positives(self):
        assert contains_anaphor("hide those buildings")
        assert contains_anaphor("show me that area")
        assert contains_anaphor("color it red")

    def test_contains_anaphor_true_negatives(self):
        assert not contains_anaphor("show parks in Chicago")
        assert not contains_anaphor("")

    def test_needs_attribute_context(self):
        assert needs_attribute_context("buildings taller than 20m")
        assert needs_attribute_context("color residential red")
        assert not needs_attribute_context("show parks in Chicago")

    def test_get_layer_attribute_names(self):
        store = {
            "parks": {
                "type": "FeatureCollection",
                "features": [_point(0, 0, name="A"), _point(0, 0, area_m2=100)],
            }
        }
        attrs = get_layer_attribute_names(store, "parks")
        assert "name" in attrs
        assert "area_m2" in attrs

    def test_get_layer_attribute_names_missing_layer(self):
        assert get_layer_attribute_names({}, "nonexistent") == []


# ---------------------------------------------------------------------------
# M5 E5.5 — handler attribute validation
# ---------------------------------------------------------------------------


class TestHandlerAttributeValidation:
    def test_filter_layer_reports_available_attributes(self):
        from nl_gis.handlers.analysis import handle_filter_layer
        store = {
            "parks": {
                "type": "FeatureCollection",
                "features": [_point(0, 0, name="A", area_m2=100)],
            }
        }
        result = handle_filter_layer(
            {"layer_name": "parks", "attribute": "nonexistent", "operator": "equals", "value": "x"},
            layer_store=store,
        )
        assert "error" in result
        assert "nonexistent" in result["error"]
        assert "Available attributes" in result["error"]
        assert "name" in result["error"]

    def test_filter_layer_existing_attribute_still_works(self):
        from nl_gis.handlers.analysis import handle_filter_layer
        store = {
            "parks": {
                "type": "FeatureCollection",
                "features": [_point(0, 0, name="A"), _point(0, 0, name="B")],
            }
        }
        result = handle_filter_layer(
            {"layer_name": "parks", "attribute": "name", "operator": "equals", "value": "A"},
            layer_store=store,
        )
        assert "error" not in result

    def test_highlight_features_reports_available_attributes(self):
        from nl_gis.handlers.layers import handle_highlight_features
        store = {
            "parks": {
                "type": "FeatureCollection",
                "features": [_point(0, 0, name="A")],
            }
        }
        result = handle_highlight_features(
            {"layer_name": "parks", "attribute": "fake_attr", "value": "x"},
            layer_store=store,
        )
        assert "error" in result
        assert "fake_attr" in result["error"]
        assert "name" in result["error"]


# ---------------------------------------------------------------------------
# M5 E5.6 — format_viewport_hint
# ---------------------------------------------------------------------------


class TestFormatViewportHint:
    def test_with_bounds_and_center(self):
        h = format_viewport_hint({
            "bounds": {"south": 1, "west": 2, "north": 3, "east": 4},
            "center": {"lat": 2, "lng": 3},
        })
        assert "viewport" in h
        assert "center" in h

    def test_missing_returns_empty(self):
        assert format_viewport_hint(None) == ""
        assert format_viewport_hint({}) == ""
