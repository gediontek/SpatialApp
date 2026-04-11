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
    handle_highlight_features,
    handle_add_annotation,
    handle_export_annotations,
    handle_get_annotations,
    handle_import_layer,
    handle_merge_layers,
    MAX_BUFFER_DISTANCE_M,
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

    @patch("nl_gis.handlers.navigation.requests.get")
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
        phase2_tools = ["buffer", "spatial_query", "aggregate", "show_layer", "hide_layer", "remove_layer", "highlight_features"]
        phase3_tools = ["add_annotation", "classify_landcover", "export_annotations", "get_annotations"]

        for tool in phase2_tools + phase3_tools:
            # Just verify they don't raise ValueError (unknown tool)
            # They may return errors for missing params, but that's fine
            try:
                dispatch_tool(tool, {}, store)
            except ValueError:
                pytest.fail(f"Tool '{tool}' not registered in dispatch_tool")


class TestHighlightFeatures:
    """Tests for highlight_features handler."""

    def test_highlight_matching(self):
        store = make_layer_store()
        result = handle_highlight_features({
            "layer_name": "buildings",
            "attribute": "category_name",
            "value": "residential",
            "color": "#ff0000"
        }, store)
        assert result["success"] is True
        assert result["highlighted"] == 1
        assert result["total"] == 2

    def test_highlight_no_match(self):
        store = make_layer_store()
        result = handle_highlight_features({
            "layer_name": "buildings",
            "attribute": "category_name",
            "value": "nonexistent"
        }, store)
        assert result["success"] is True
        assert result["highlighted"] == 0

    def test_highlight_layer_not_found(self):
        result = handle_highlight_features({
            "layer_name": "nope",
            "attribute": "category_name",
            "value": "test"
        }, {})
        assert "error" in result

    def test_highlight_missing_params(self):
        result = handle_highlight_features({"layer_name": "x"}, {})
        assert "error" in result

    def test_dispatch_highlight(self):
        store = make_layer_store()
        result = dispatch_tool("highlight_features", {
            "layer_name": "buildings",
            "attribute": "category_name",
            "value": "commercial"
        }, store)
        assert result["success"] is True
        assert result["highlighted"] == 1


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


class TestBufferEdgeCases:
    """Edge case tests for buffer tool."""

    def test_buffer_exceeds_max(self):
        result = handle_buffer({"distance_m": MAX_BUFFER_DISTANCE_M + 1}, {})
        assert "error" in result
        assert "100" in result["error"]  # mentions 100 km limit

    def test_buffer_negative(self):
        result = handle_buffer({"distance_m": -500}, {})
        assert "error" in result

    def test_buffer_zero(self):
        result = handle_buffer({"distance_m": 0}, {})
        assert "error" in result

    def test_buffer_at_max(self):
        """Buffer at exactly the max distance should succeed if geometry provided."""
        store = make_layer_store()
        result = handle_buffer({"distance_m": MAX_BUFFER_DISTANCE_M, "layer_name": "buildings"}, store)
        assert "error" not in result


class TestImportLayerEdgeCases:
    """Edge case tests for import_layer tool."""

    def test_import_inline_geojson(self):
        store = {}
        geojson = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {}}
        ]}
        result = handle_import_layer({"layer_name": "test", "geojson": geojson}, store)
        assert "error" not in result
        assert result["feature_count"] == 1
        assert "test" in store

    def test_import_no_geojson_no_file(self):
        result = handle_import_layer({"layer_name": "test"}, {})
        assert "upload_url" in result  # Tells user how to upload

    def test_import_no_name(self):
        result = handle_import_layer({}, {})
        assert "error" in result

    def test_import_invalid_geojson_type(self):
        result = handle_import_layer({
            "layer_name": "bad",
            "geojson": {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}}
        }, {})
        assert "error" in result  # Not a FeatureCollection

    def test_import_empty_fc(self):
        store = {}
        result = handle_import_layer({
            "layer_name": "empty",
            "geojson": {"type": "FeatureCollection", "features": []}
        }, store)
        assert result["feature_count"] == 0


class TestMergeLayersEdgeCases:
    """Edge case tests for merge_layers tool."""

    def test_merge_union(self):
        store = make_layer_store()
        # Add a second layer
        store["parks"] = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[-122.4, 47.6], [-122.4, 47.61], [-122.39, 47.61], [-122.39, 47.6], [-122.4, 47.6]]]},
                "properties": {"category_name": "park"}
            }]
        }
        result = handle_merge_layers({
            "layer_a": "buildings",
            "layer_b": "parks",
            "output_name": "merged",
            "operation": "union"
        }, store)
        assert "error" not in result
        assert result["feature_count"] == 3  # 2 buildings + 1 park
        assert "merged" in store

    def test_merge_missing_layer(self):
        store = make_layer_store()
        result = handle_merge_layers({
            "layer_a": "buildings",
            "layer_b": "nonexistent",
            "output_name": "merged"
        }, store)
        assert "error" in result

    def test_merge_no_store(self):
        result = handle_merge_layers({
            "layer_a": "a", "layer_b": "b", "output_name": "c"
        }, None)
        assert "error" in result

    def test_merge_missing_params(self):
        result = handle_merge_layers({"layer_a": "a"}, {})
        assert "error" in result

    def test_merge_spatial_join(self):
        store = make_layer_store()
        store["parks"] = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[-122.36, 47.59], [-122.36, 47.62], [-122.33, 47.62], [-122.33, 47.59], [-122.36, 47.59]]]},
                "properties": {"park_name": "Central"}
            }]
        }
        result = handle_merge_layers({
            "layer_a": "buildings",
            "layer_b": "parks",
            "output_name": "joined",
            "operation": "spatial_join"
        }, store)
        assert "error" not in result
        assert result["operation"] == "spatial_join"
