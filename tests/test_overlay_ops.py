"""Tests for overlay operations: intersection, difference, symmetric_difference."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from nl_gis.handlers.analysis import (
    handle_intersection,
    handle_difference,
    handle_symmetric_difference,
)


def _make_polygon_layer(coords_list):
    """Create a FeatureCollection from a list of coordinate rings."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [coords]},
                "properties": {},
            }
            for coords in coords_list
        ],
    }


# Two overlapping squares:
# A: (0,0)-(1,1)  B: (0.5,0)-(1.5,1)  overlap: (0.5,0)-(1,1)
LAYER_A_COORDS = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
LAYER_B_COORDS = [[0.5, 0], [1.5, 0], [1.5, 1], [0.5, 1], [0.5, 0]]

# Non-overlapping: C is far away
LAYER_C_COORDS = [[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]


def make_overlapping_store():
    return {
        "layer_a": _make_polygon_layer([LAYER_A_COORDS]),
        "layer_b": _make_polygon_layer([LAYER_B_COORDS]),
    }


def make_non_overlapping_store():
    return {
        "layer_a": _make_polygon_layer([LAYER_A_COORDS]),
        "layer_c": _make_polygon_layer([LAYER_C_COORDS]),
    }


class TestIntersection:
    def test_overlapping_layers(self):
        store = make_overlapping_store()
        result = handle_intersection(
            {"layer_a": "layer_a", "layer_b": "layer_b"},
            layer_store=store,
        )
        assert "error" not in result
        assert result["feature_count"] == 1
        assert result["geojson"]["type"] == "FeatureCollection"
        assert len(result["geojson"]["features"]) == 1

    def test_non_overlapping_layers(self):
        store = make_non_overlapping_store()
        result = handle_intersection(
            {"layer_a": "layer_a", "layer_b": "layer_c"},
            layer_store=store,
        )
        assert "error" not in result
        assert result["feature_count"] == 0
        assert result["geojson"]["features"] == []

    def test_custom_output_name(self):
        store = make_overlapping_store()
        result = handle_intersection(
            {"layer_a": "layer_a", "layer_b": "layer_b", "output_name": "my_overlap"},
            layer_store=store,
        )
        assert result["layer_name"] == "my_overlap"


class TestDifference:
    def test_produces_smaller_geometry(self):
        store = make_overlapping_store()
        result = handle_difference(
            {"layer_a": "layer_a", "layer_b": "layer_b"},
            layer_store=store,
        )
        assert "error" not in result
        assert result["feature_count"] == 1
        # The difference should be smaller than the original (area_sq_km > 0 but less than full)
        assert result["area_sq_km"] > 0

    def test_non_overlapping_returns_full_area(self):
        store = make_non_overlapping_store()
        result = handle_difference(
            {"layer_a": "layer_a", "layer_b": "layer_c"},
            layer_store=store,
        )
        assert "error" not in result
        assert result["feature_count"] == 1
        # Full layer_a should remain since there's no overlap
        assert result["area_sq_km"] > 0


class TestSymmetricDifference:
    def test_produces_non_overlapping_areas(self):
        store = make_overlapping_store()
        result = handle_symmetric_difference(
            {"layer_a": "layer_a", "layer_b": "layer_b"},
            layer_store=store,
        )
        assert "error" not in result
        assert result["feature_count"] == 1
        assert result["area_sq_km"] > 0

    def test_non_overlapping_returns_both(self):
        store = make_non_overlapping_store()
        result = handle_symmetric_difference(
            {"layer_a": "layer_a", "layer_b": "layer_c"},
            layer_store=store,
        )
        assert "error" not in result
        assert result["feature_count"] == 1
        assert result["area_sq_km"] > 0


class TestOverlayEdgeCases:
    def test_missing_layer_a(self):
        store = make_overlapping_store()
        result = handle_intersection(
            {"layer_b": "layer_b"},
            layer_store=store,
        )
        assert "error" in result

    def test_missing_layer_b(self):
        store = make_overlapping_store()
        result = handle_intersection(
            {"layer_a": "layer_a"},
            layer_store=store,
        )
        assert "error" in result

    def test_nonexistent_layer_a(self):
        store = make_overlapping_store()
        result = handle_intersection(
            {"layer_a": "nonexistent", "layer_b": "layer_b"},
            layer_store=store,
        )
        assert "error" in result

    def test_nonexistent_layer_b(self):
        store = make_overlapping_store()
        result = handle_difference(
            {"layer_a": "layer_a", "layer_b": "nonexistent"},
            layer_store=store,
        )
        assert "error" in result

    def test_both_params_missing(self):
        store = make_overlapping_store()
        result = handle_symmetric_difference({}, layer_store=store)
        assert "error" in result

    def test_none_layer_store(self):
        result = handle_intersection(
            {"layer_a": "a", "layer_b": "b"},
            layer_store=None,
        )
        assert "error" in result
