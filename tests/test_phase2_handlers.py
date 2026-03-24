"""Tests for Phase 2 & 3 tool handlers."""

import json
import pytest
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl_gis.tool_handlers import (
    dispatch_tool,
    handle_buffer,
    handle_spatial_query,
    handle_aggregate,
    handle_search_nearby,
    handle_layer_visibility,
    handle_add_annotation,
    handle_export_annotations,
    handle_get_annotations,
)


# Shared test fixtures
def make_layer_store():
    """Create a layer store with test data."""
    return {
        "buildings": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[-122.35, 47.6], [-122.35, 47.61],
                                         [-122.34, 47.61], [-122.34, 47.6],
                                         [-122.35, 47.6]]]
                    },
                    "properties": {"category_name": "residential", "osm_id": 1}
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[-122.33, 47.6], [-122.33, 47.605],
                                         [-122.325, 47.605], [-122.325, 47.6],
                                         [-122.33, 47.6]]]
                    },
                    "properties": {"category_name": "commercial", "osm_id": 2}
                }
            ]
        },
        "parks": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[-122.34, 47.605], [-122.34, 47.615],
                                         [-122.33, 47.615], [-122.33, 47.605],
                                         [-122.34, 47.605]]]
                    },
                    "properties": {"category_name": "park"}
                }
            ]
        }
    }


class TestHandleBuffer:
    """Tests for buffer tool handler."""

    def test_buffer_layer(self):
        store = make_layer_store()
        result = handle_buffer({"layer_name": "parks", "distance_m": 500}, store)
        assert "error" not in result
        assert result["feature_count"] == 1
        assert result["buffer_distance_m"] == 500
        assert result["area_sq_km"] > 0
        assert "geojson" in result

    def test_buffer_geometry(self):
        geom = {"type": "Point", "coordinates": [-122.3, 47.6]}
        result = handle_buffer({"geometry": geom, "distance_m": 1000})
        assert "error" not in result
        assert result["feature_count"] == 1

    def test_buffer_no_input(self):
        result = handle_buffer({"distance_m": 500})
        assert "error" in result

    def test_buffer_zero_distance(self):
        result = handle_buffer({"geometry": {"type": "Point", "coordinates": [0, 0]}, "distance_m": 0})
        assert "error" in result

    def test_buffer_layer_not_found(self):
        result = handle_buffer({"layer_name": "nonexistent", "distance_m": 500}, {})
        assert "error" in result


class TestHandleSpatialQuery:
    """Tests for spatial query handler."""

    def test_intersects(self):
        store = make_layer_store()
        # Buildings that intersect parks
        result = handle_spatial_query({
            "source_layer": "buildings",
            "predicate": "intersects",
            "target_layer": "parks"
        }, store)
        assert "error" not in result
        assert result["source_total"] == 2
        assert result["feature_count"] >= 0

    def test_within_distance(self):
        store = make_layer_store()
        result = handle_spatial_query({
            "source_layer": "buildings",
            "predicate": "within_distance",
            "target_layer": "parks",
            "distance_m": 2000
        }, store)
        assert "error" not in result
        # With 2km buffer, both buildings should match
        assert result["feature_count"] == 2

    def test_within_distance_no_distance(self):
        store = make_layer_store()
        result = handle_spatial_query({
            "source_layer": "buildings",
            "predicate": "within_distance",
            "target_layer": "parks"
        }, store)
        assert "error" in result

    def test_invalid_predicate(self):
        store = make_layer_store()
        result = handle_spatial_query({
            "source_layer": "buildings",
            "predicate": "invalid",
            "target_layer": "parks"
        }, store)
        assert "error" in result

    def test_source_not_found(self):
        result = handle_spatial_query({
            "source_layer": "nonexistent",
            "predicate": "intersects",
            "target_layer": "parks"
        }, {})
        assert "error" in result

    def test_no_target(self):
        store = make_layer_store()
        result = handle_spatial_query({
            "source_layer": "buildings",
            "predicate": "intersects"
        }, store)
        assert "error" in result


class TestHandleAggregate:
    """Tests for aggregate handler."""

    def test_count(self):
        store = make_layer_store()
        result = handle_aggregate({"layer_name": "buildings", "operation": "count"}, store)
        assert result["total"] == 2

    def test_count_group_by(self):
        store = make_layer_store()
        result = handle_aggregate({
            "layer_name": "buildings",
            "operation": "count",
            "group_by": "category_name"
        }, store)
        assert result["total"] == 2
        assert len(result["groups"]) == 2

    def test_area(self):
        store = make_layer_store()
        result = handle_aggregate({"layer_name": "buildings", "operation": "area"}, store)
        assert "error" not in result
        assert result["total_area_sq_m"] > 0
        assert result["feature_count"] == 2

    def test_group_by(self):
        store = make_layer_store()
        result = handle_aggregate({
            "layer_name": "buildings",
            "operation": "group_by",
            "group_by": "category_name"
        }, store)
        assert len(result["groups"]) == 2

    def test_group_by_missing_attr(self):
        store = make_layer_store()
        result = handle_aggregate({
            "layer_name": "buildings",
            "operation": "group_by"
        }, store)
        assert "error" in result

    def test_layer_not_found(self):
        result = handle_aggregate({"layer_name": "nonexistent", "operation": "count"}, {})
        assert "error" in result


class TestHandleSearchNearby:
    """Tests for search nearby handler (validation only)."""

    def test_no_location_no_coords(self):
        result = handle_search_nearby({"feature_type": "building"})
        assert "error" in result

    def test_invalid_feature_type(self):
        result = handle_search_nearby({
            "feature_type": "invalid",
            "lat": 47.6,
            "lon": -122.3
        })
        assert "error" in result

    @patch("nl_gis.tool_handlers.requests.get")
    def test_successful_search(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "elements": [
                {"type": "node", "id": 1, "lat": 47.6, "lon": -122.3},
                {"type": "node", "id": 2, "lat": 47.601, "lon": -122.3},
                {"type": "node", "id": 3, "lat": 47.601, "lon": -122.299},
                {"type": "node", "id": 4, "lat": 47.6, "lon": -122.299},
                {"type": "way", "id": 100, "nodes": [1, 2, 3, 4, 1], "tags": {"building": "yes"}},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = handle_search_nearby({
            "feature_type": "building",
            "lat": 47.6,
            "lon": -122.3,
            "radius_m": 500
        })
        assert "error" not in result
        assert result["feature_count"] == 1
        assert "nearby_building" in result["layer_name"]


class TestHandleLayerVisibility:
    """Tests for layer visibility handlers."""

    def test_show(self):
        result = handle_layer_visibility({"layer_name": "test"}, "show")
        assert result["success"] is True
        assert result["action"] == "show"

    def test_hide(self):
        result = handle_layer_visibility({"layer_name": "test"}, "hide")
        assert result["action"] == "hide"

    def test_remove(self):
        result = handle_layer_visibility({"layer_name": "test"}, "remove")
        assert result["action"] == "remove"

    def test_no_layer_name(self):
        result = handle_layer_visibility({}, "show")
        assert "error" in result


class TestHandleAnnotation:
    """Tests for annotation handler."""

    def test_add_annotation_with_geometry(self):
        """Test annotation via Flask test client (imports from app work)."""
        from app import app, geo_coco_annotations
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False

        initial_count = len(geo_coco_annotations)
        store = make_layer_store()

        result = handle_add_annotation({
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
            "category_name": "test_area",
            "color": "#ff0000"
        }, store)

        assert result["success"] is True
        assert result["added"] == 1
        assert len(geo_coco_annotations) == initial_count + 1

        # Cleanup
        geo_coco_annotations.pop()

    def test_add_annotation_from_layer(self):
        """Test bulk annotation from layer."""
        from app import geo_coco_annotations
        initial_count = len(geo_coco_annotations)
        store = make_layer_store()

        result = handle_add_annotation({
            "layer_name": "buildings",
            "category_name": "buildings_label"
        }, store)

        assert result["success"] is True
        assert result["added"] == 2

        # Cleanup
        for _ in range(2):
            geo_coco_annotations.pop()

    def test_add_annotation_no_input(self):
        result = handle_add_annotation({"category_name": "test"}, {})
        assert "error" in result

    def test_dispatch_known_tools(self):
        """Verify all Phase 2+3 tools are registered in dispatch."""
        store = make_layer_store()
        phase2_tools = ["buffer", "spatial_query", "aggregate", "show_layer", "hide_layer", "remove_layer"]
        phase3_tools = ["add_annotation", "classify_landcover", "export_annotations", "get_annotations"]

        for tool in phase2_tools + phase3_tools:
            # Just verify they don't raise ValueError (unknown tool)
            # They may return errors for missing params, but that's fine
            try:
                dispatch_tool(tool, {}, store)
            except ValueError:
                pytest.fail(f"Tool '{tool}' not registered in dispatch_tool")


class TestHandleExportAnnotations:
    """Tests for export handler."""

    def test_invalid_format(self):
        result = handle_export_annotations({"format": "csv"})
        assert "error" in result

    def test_valid_format_no_annotations(self):
        from app import geo_coco_annotations
        original = geo_coco_annotations.copy()
        geo_coco_annotations.clear()

        result = handle_export_annotations({"format": "geojson"})
        assert "error" in result
        assert "No annotations" in result["error"]

        # Restore
        geo_coco_annotations.extend(original)

    def test_valid_format_with_annotations(self):
        from app import geo_coco_annotations
        geo_coco_annotations.append({"type": "Feature", "geometry": {}, "properties": {}})

        result = handle_export_annotations({"format": "geojson"})
        assert result["success"] is True
        assert result["download_url"] == "/export_annotations/geojson"

        geo_coco_annotations.pop()


class TestHandleGetAnnotations:
    """Tests for get annotations handler."""

    def test_returns_structure(self):
        result = handle_get_annotations({})
        assert "total" in result
        assert "categories" in result
        assert "geojson" in result
