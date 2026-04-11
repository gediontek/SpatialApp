"""Tests for Milestone 5: Missing Capabilities (8 new tools).

Covers: reproject_layer, detect_crs, od_matrix, split_feature,
        merge_features, extract_vertices, temporal_filter, attribute_statistics.
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock
from nl_gis.handlers import (
    dispatch_tool,
    handle_reproject_layer,
    handle_detect_crs,
    handle_split_feature,
    handle_merge_features,
    handle_extract_vertices,
    handle_temporal_filter,
    handle_attribute_statistics,
)
from nl_gis.handlers.routing import handle_od_matrix


# ============================================================
# Test fixtures
# ============================================================

def _make_layer_store(layers: dict) -> dict:
    return layers


def _polygon_layer():
    """Two simple polygons with a 'zone' attribute."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
                },
                "properties": {"zone": "A", "name": "square1"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[2, 0], [4, 0], [4, 2], [2, 2], [2, 0]]],
                },
                "properties": {"zone": "A", "name": "square2"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 2], [2, 2], [2, 4], [0, 4], [0, 2]]],
                },
                "properties": {"zone": "B", "name": "square3"},
            },
        ],
    }


def _point_layer_with_values():
    """Points with numeric values."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
                "properties": {"value": 10, "name": "A"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1.0, 0.0]},
                "properties": {"value": 20, "name": "B"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0.0, 1.0]},
                "properties": {"value": 30, "name": "C"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
                "properties": {"value": 40, "name": "D"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0.5, 0.5]},
                "properties": {"value": 25, "name": "E"},
            },
        ],
    }


def _line_layer():
    """A layer with a LineString."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[0, 0], [1, 1], [2, 0]],
                },
                "properties": {"name": "line1"},
            },
        ],
    }


def _dated_layer():
    """Layer with date attributes."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {"event_date": "2023-01-15", "name": "jan"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1, 0]},
                "properties": {"event_date": "2023-06-15", "name": "jun"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [2, 0]},
                "properties": {"event_date": "2023-12-15", "name": "dec"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [3, 0]},
                "properties": {"event_date": "2024-03-01", "name": "mar24"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [4, 0]},
                "properties": {"name": "no_date"},
            },
        ],
    }


# ============================================================
# Epic 5.1: Coordinate Tools
# ============================================================

class TestReprojectLayer:
    def test_reproject_adds_crs_metadata(self):
        store = _make_layer_store({"pts": _point_layer_with_values()})
        result = handle_reproject_layer(
            {"layer_name": "pts", "from_crs": 32632, "to_crs": 4326},
            store,
        )
        assert "error" not in result
        assert result["feature_count"] == 5
        feat = result["geojson"]["features"][0]
        assert feat["properties"]["source_crs"] == "EPSG:32632"
        assert feat["properties"]["display_crs"] == "EPSG:4326"

    def test_reproject_missing_layer(self):
        result = handle_reproject_layer({"layer_name": "nope", "from_crs": 32632}, {})
        assert "error" in result

    def test_reproject_missing_from_crs(self):
        store = _make_layer_store({"pts": _point_layer_with_values()})
        result = handle_reproject_layer({"layer_name": "pts"}, store)
        assert "error" in result

    def test_reproject_via_dispatch(self):
        store = _make_layer_store({"pts": _point_layer_with_values()})
        result = dispatch_tool(
            "reproject_layer",
            {"layer_name": "pts", "from_crs": 4326, "output_name": "pts_tagged"},
            store,
        )
        assert "error" not in result
        assert result["layer_name"] == "pts_tagged"


class TestDetectCRS:
    def test_detect_wgs84(self):
        store = _make_layer_store({"pts": _point_layer_with_values()})
        result = handle_detect_crs({"layer_name": "pts"}, store)
        assert "error" not in result
        assert result["detected_crs"] == "EPSG:4326"
        assert result["confidence"] == "high"

    def test_detect_projected(self):
        """Coordinates outside WGS84 range indicate projected CRS."""
        projected_layer = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [500000, 4500000]},
                    "properties": {},
                },
            ],
        }
        store = _make_layer_store({"proj": projected_layer})
        result = handle_detect_crs({"layer_name": "proj"}, store)
        assert "error" not in result
        assert result["detected_crs"] == "unknown_projected"
        assert result["confidence"] == "low"

    def test_detect_missing_layer(self):
        result = handle_detect_crs({"layer_name": "nope"}, {})
        assert "error" in result

    def test_detect_via_dispatch(self):
        store = _make_layer_store({"pts": _point_layer_with_values()})
        result = dispatch_tool("detect_crs", {"layer_name": "pts"}, store)
        assert "error" not in result
        assert result["detected_crs"] == "EPSG:4326"


# ============================================================
# Epic 5.2: Advanced Network
# ============================================================

class TestODMatrix:
    def test_basic_matrix(self):
        result = handle_od_matrix({
            "origins": [
                {"lat": 0.0, "lon": 0.0},
                {"lat": 1.0, "lon": 0.0},
            ],
            "destinations": [
                {"lat": 0.0, "lon": 1.0},
                {"lat": 1.0, "lon": 1.0},
            ],
        })
        assert "error" not in result
        assert result["origins_count"] == 2
        assert result["destinations_count"] == 2
        assert len(result["matrix"]) == 2
        assert len(result["matrix"][0]) == 2
        # Distance from (0,0) to (0,1) should be ~111km
        assert result["matrix"][0][0] > 100000
        assert result["matrix"][0][0] < 120000

    def test_empty_origins(self):
        result = handle_od_matrix({
            "origins": [],
            "destinations": [{"lat": 0, "lon": 0}],
        })
        assert "error" in result

    def test_empty_destinations(self):
        result = handle_od_matrix({
            "origins": [{"lat": 0, "lon": 0}],
            "destinations": [],
        })
        assert "error" in result

    def test_single_pair(self):
        result = handle_od_matrix({
            "origins": [{"lat": 0, "lon": 0}],
            "destinations": [{"lat": 0, "lon": 0}],
        })
        assert "error" not in result
        assert result["matrix"][0][0] == 0.0

    def test_via_dispatch(self):
        result = dispatch_tool("od_matrix", {
            "origins": [{"lat": 0, "lon": 0}],
            "destinations": [{"lat": 1, "lon": 1}],
        })
        assert "error" not in result
        assert result["method"] == "geodesic"


# ============================================================
# Epic 5.3: Geometry Editing
# ============================================================

class TestSplitFeature:
    def test_split_polygon(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        # Split the first polygon (0,0)-(2,2) with a vertical line at x=1
        result = handle_split_feature({
            "layer_name": "polys",
            "feature_index": 0,
            "split_line": {
                "type": "LineString",
                "coordinates": [[1, -1], [1, 3]],
            },
        }, store)
        assert "error" not in result
        assert result["split_into"] >= 2
        # Original had 3 features, split adds at least 1 more
        assert result["feature_count"] >= 4

    def test_split_bad_index(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = handle_split_feature({
            "layer_name": "polys",
            "feature_index": 99,
            "split_line": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        }, store)
        assert "error" in result

    def test_split_missing_line(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = handle_split_feature({
            "layer_name": "polys",
            "feature_index": 0,
        }, store)
        assert "error" in result

    def test_split_via_dispatch(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = dispatch_tool("split_feature", {
            "layer_name": "polys",
            "feature_index": 0,
            "split_line": {"type": "LineString", "coordinates": [[1, -1], [1, 3]]},
            "output_name": "split_result",
        }, store)
        assert "error" not in result
        assert result["layer_name"] == "split_result"


class TestMergeFeatures:
    def test_merge_by_zone(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = handle_merge_features({
            "layer_name": "polys",
            "by": "zone",
        }, store)
        assert "error" not in result
        # Zone A has 2 features, Zone B has 1 -> 2 merged groups
        assert result["feature_count"] == 2
        assert result["original_count"] == 3

    def test_merge_missing_attribute(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = handle_merge_features({
            "layer_name": "polys",
            "by": "nonexistent",
        }, store)
        assert "error" in result

    def test_merge_missing_layer(self):
        result = handle_merge_features({"layer_name": "nope", "by": "zone"}, {})
        assert "error" in result

    def test_merge_via_dispatch(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = dispatch_tool("merge_features", {
            "layer_name": "polys",
            "by": "zone",
            "output_name": "merged",
        }, store)
        assert "error" not in result
        assert result["layer_name"] == "merged"


class TestExtractVertices:
    def test_extract_from_polygon(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = handle_extract_vertices({"layer_name": "polys"}, store)
        assert "error" not in result
        assert result["feature_count"] > 0
        # Each polygon has 5 coords (closed ring) * 3 polygons = 15
        assert result["feature_count"] == 15
        # Check output is points
        for f in result["geojson"]["features"]:
            assert f["geometry"]["type"] == "Point"

    def test_extract_from_line(self):
        store = _make_layer_store({"lines": _line_layer()})
        result = handle_extract_vertices({"layer_name": "lines"}, store)
        assert "error" not in result
        assert result["feature_count"] == 3  # 3 vertices in the LineString

    def test_extract_missing_layer(self):
        result = handle_extract_vertices({"layer_name": "nope"}, {})
        assert "error" in result

    def test_extract_via_dispatch(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = dispatch_tool("extract_vertices", {
            "layer_name": "polys",
            "output_name": "verts",
        }, store)
        assert "error" not in result
        assert result["layer_name"] == "verts"


# ============================================================
# Epic 5.4: Temporal & Attribute
# ============================================================

class TestTemporalFilter:
    def test_filter_after(self):
        store = _make_layer_store({"events": _dated_layer()})
        result = handle_temporal_filter({
            "layer_name": "events",
            "date_attribute": "event_date",
            "after": "2023-06-01",
        }, store)
        assert "error" not in result
        # jun, dec, mar24 pass; jan fails; no_date skipped
        assert result["feature_count"] == 3
        assert result["skipped_no_date"] == 1

    def test_filter_before(self):
        store = _make_layer_store({"events": _dated_layer()})
        result = handle_temporal_filter({
            "layer_name": "events",
            "date_attribute": "event_date",
            "before": "2023-06-30",
        }, store)
        assert "error" not in result
        # jan, jun pass; dec, mar24 fail; no_date skipped
        assert result["feature_count"] == 2

    def test_filter_range(self):
        store = _make_layer_store({"events": _dated_layer()})
        result = handle_temporal_filter({
            "layer_name": "events",
            "date_attribute": "event_date",
            "after": "2023-06-01",
            "before": "2023-12-31",
        }, store)
        assert "error" not in result
        # jun, dec pass
        assert result["feature_count"] == 2

    def test_filter_no_bounds(self):
        store = _make_layer_store({"events": _dated_layer()})
        result = handle_temporal_filter({
            "layer_name": "events",
            "date_attribute": "event_date",
        }, store)
        assert "error" in result

    def test_filter_bad_date_format(self):
        store = _make_layer_store({"events": _dated_layer()})
        result = handle_temporal_filter({
            "layer_name": "events",
            "date_attribute": "event_date",
            "after": "not-a-date",
        }, store)
        assert "error" in result

    def test_filter_via_dispatch(self):
        store = _make_layer_store({"events": _dated_layer()})
        result = dispatch_tool("temporal_filter", {
            "layer_name": "events",
            "date_attribute": "event_date",
            "after": "2024-01-01",
            "output_name": "events_2024",
        }, store)
        assert "error" not in result
        assert result["layer_name"] == "events_2024"
        assert result["feature_count"] == 1  # only mar24


class TestAttributeStatistics:
    def test_basic_stats(self):
        store = _make_layer_store({"pts": _point_layer_with_values()})
        result = handle_attribute_statistics({
            "layer_name": "pts",
            "attribute": "value",
        }, store)
        assert "error" not in result
        assert result["count"] == 5
        assert result["min"] == 10.0
        assert result["max"] == 40.0
        assert result["mean"] == 25.0
        assert result["median"] == 25.0
        assert "percentiles" in result
        assert result["percentiles"]["25"] == 20.0
        assert result["percentiles"]["75"] == 30.0
        assert len(result["histogram"]) == 10

    def test_missing_attribute(self):
        store = _make_layer_store({"pts": _point_layer_with_values()})
        result = handle_attribute_statistics({
            "layer_name": "pts",
            "attribute": "nonexistent",
        }, store)
        assert "error" in result

    def test_non_numeric_attribute(self):
        store = _make_layer_store({"pts": _point_layer_with_values()})
        result = handle_attribute_statistics({
            "layer_name": "pts",
            "attribute": "name",
        }, store)
        assert "error" in result

    def test_via_dispatch(self):
        store = _make_layer_store({"pts": _point_layer_with_values()})
        result = dispatch_tool("attribute_statistics", {
            "layer_name": "pts",
            "attribute": "value",
        }, store)
        assert "error" not in result
        assert result["count"] == 5


# ============================================================
# Tool schema registration
# ============================================================

class TestToolSchemas:
    def test_all_new_tools_registered_in_dispatch(self):
        """All 8 new tools should be callable via dispatch_tool."""
        store = _make_layer_store({"pts": _point_layer_with_values()})
        tool_names = [
            "reproject_layer", "detect_crs", "od_matrix",
            "split_feature", "merge_features", "extract_vertices",
            "temporal_filter", "attribute_statistics",
        ]
        for name in tool_names:
            # Should not raise ValueError for unknown tool
            try:
                dispatch_tool(name, {}, store)
            except ValueError:
                pytest.fail(f"Tool '{name}' not registered in dispatch_tool")

    def test_schemas_present(self):
        """All 8 new tools should have schemas in get_tool_definitions."""
        from nl_gis.tools import get_tool_definitions
        defs = get_tool_definitions()
        tool_names = {d["name"] for d in defs}
        for name in [
            "reproject_layer", "detect_crs", "od_matrix",
            "split_feature", "merge_features", "extract_vertices",
            "temporal_filter", "attribute_statistics",
        ]:
            assert name in tool_names, f"Schema for '{name}' not found in tool definitions"

    def test_layer_producing_tools_updated(self):
        """Layer-producing tools should include the new ones."""
        from nl_gis.handlers import LAYER_PRODUCING_TOOLS
        for name in [
            "reproject_layer", "split_feature", "merge_features",
            "extract_vertices", "temporal_filter",
        ]:
            assert name in LAYER_PRODUCING_TOOLS, f"'{name}' not in LAYER_PRODUCING_TOOLS"
