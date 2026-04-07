"""Tests for handle_filter_layer in nl_gis.tool_handlers."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl_gis.tool_handlers import dispatch_tool


def _make_layer(features):
    """Helper: build a GeoJSON FeatureCollection from a list of property dicts."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": props,
            }
            for props in features
        ],
    }


@pytest.fixture
def layer_store():
    """Layer store with a sample layer for filtering tests."""
    return {
        "buildings": _make_layer([
            {"category_name": "residential", "height": "10"},
            {"category_name": "commercial", "height": "50"},
            {"category_name": "residential", "height": "20"},
            {"category_name": "industrial", "height": "15"},
        ]),
        "empty_layer": _make_layer([]),
    }


class TestFilterLayerByPropertyValue:
    """Test filtering by exact property value."""

    def test_filter_equals(self, layer_store):
        result = dispatch_tool("filter_layer", {
            "layer_name": "buildings",
            "attribute": "category_name",
            "operator": "equals",
            "value": "residential",
        }, layer_store)
        assert "error" not in result
        assert result["feature_count"] == 2
        assert result["original_count"] == 4

    def test_filter_not_equals(self, layer_store):
        result = dispatch_tool("filter_layer", {
            "layer_name": "buildings",
            "attribute": "category_name",
            "operator": "not_equals",
            "value": "residential",
        }, layer_store)
        assert result["feature_count"] == 2
        for feat in result["geojson"]["features"]:
            assert feat["properties"]["category_name"] != "residential"

    def test_filter_contains(self, layer_store):
        result = dispatch_tool("filter_layer", {
            "layer_name": "buildings",
            "attribute": "category_name",
            "operator": "contains",
            "value": "ial",
        }, layer_store)
        # "residential", "commercial", "industrial" all contain "ial"
        assert result["feature_count"] == 4

    def test_filter_starts_with(self, layer_store):
        result = dispatch_tool("filter_layer", {
            "layer_name": "buildings",
            "attribute": "category_name",
            "operator": "starts_with",
            "value": "res",
        }, layer_store)
        assert result["feature_count"] == 2

    def test_filter_case_insensitive(self, layer_store):
        result = dispatch_tool("filter_layer", {
            "layer_name": "buildings",
            "attribute": "category_name",
            "operator": "equals",
            "value": "RESIDENTIAL",
        }, layer_store)
        assert result["feature_count"] == 2


class TestFilterLayerNoMatches:
    """Test when filter returns no features."""

    def test_no_matches(self, layer_store):
        result = dispatch_tool("filter_layer", {
            "layer_name": "buildings",
            "attribute": "category_name",
            "operator": "equals",
            "value": "nonexistent_category",
        }, layer_store)
        assert "error" not in result
        assert result["feature_count"] == 0
        assert result["original_count"] == 4
        assert result["geojson"]["features"] == []


class TestFilterLayerNonExistentLayer:
    """Test filtering a layer that doesn't exist."""

    def test_layer_not_found(self, layer_store):
        result = dispatch_tool("filter_layer", {
            "layer_name": "nonexistent_layer",
            "attribute": "category_name",
            "value": "residential",
        }, layer_store)
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_empty_layer_store(self):
        result = dispatch_tool("filter_layer", {
            "layer_name": "buildings",
            "attribute": "category_name",
            "value": "residential",
        }, {})
        assert "error" in result


class TestFilterLayerEmptyFeatures:
    """Test filtering a layer with empty features."""

    def test_empty_features(self, layer_store):
        result = dispatch_tool("filter_layer", {
            "layer_name": "empty_layer",
            "attribute": "category_name",
            "value": "residential",
        }, layer_store)
        assert "error" not in result
        assert result["feature_count"] == 0
        assert result["original_count"] == 0


class TestFilterLayerValidation:
    """Test input validation for filter_layer."""

    def test_missing_layer_name(self, layer_store):
        result = dispatch_tool("filter_layer", {
            "attribute": "category_name",
            "value": "residential",
        }, layer_store)
        assert "error" in result

    def test_missing_attribute(self, layer_store):
        result = dispatch_tool("filter_layer", {
            "layer_name": "buildings",
            "value": "residential",
        }, layer_store)
        assert "error" in result

    def test_output_name(self, layer_store):
        result = dispatch_tool("filter_layer", {
            "layer_name": "buildings",
            "attribute": "category_name",
            "value": "residential",
            "output_name": "my_filtered",
        }, layer_store)
        assert result["layer_name"] == "my_filtered"

    def test_default_output_name(self, layer_store):
        result = dispatch_tool("filter_layer", {
            "layer_name": "buildings",
            "attribute": "category_name",
            "value": "residential",
        }, layer_store)
        assert result["layer_name"] == "filtered_buildings"


class TestFilterLayerOSMTags:
    """Test filtering by OSM tags (nested in properties)."""

    def test_filter_by_osm_tag(self):
        store = {
            "osm_layer": _make_layer([
                {"category_name": "building", "osm_tags": {"building": "yes", "name": "Library"}},
                {"category_name": "building", "osm_tags": {"building": "yes", "name": "School"}},
                {"category_name": "building", "osm_tags": {"building": "residential"}},
            ]),
        }
        result = dispatch_tool("filter_layer", {
            "layer_name": "osm_layer",
            "attribute": "name",
            "operator": "equals",
            "value": "Library",
        }, store)
        assert result["feature_count"] == 1
