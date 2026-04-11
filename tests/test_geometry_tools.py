"""Tests for geometry tools: convex_hull, centroid, simplify, bounding_box, dissolve, clip, voronoi."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from nl_gis.handlers.analysis import (
    handle_convex_hull,
    handle_centroid,
    handle_simplify,
    handle_bounding_box,
    handle_dissolve,
    handle_clip,
    handle_voronoi,
)


# ============================================================
# Test fixtures
# ============================================================

def _make_polygon_layer(coords_list, properties_list=None):
    """Create a FeatureCollection from a list of coordinate rings."""
    features = []
    for i, coords in enumerate(coords_list):
        props = properties_list[i] if properties_list else {}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": features}


def _make_point_layer(points, properties_list=None):
    """Create a FeatureCollection of Points from [(lon, lat), ...]."""
    features = []
    for i, (lon, lat) in enumerate(points):
        props = properties_list[i] if properties_list else {}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": features}


# Two squares: A at (0,0)-(1,1), B at (0.5,0)-(1.5,1)
SQUARE_A = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
SQUARE_B = [[0.5, 0], [1.5, 0], [1.5, 1], [0.5, 1], [0.5, 0]]
# A complex polygon with more vertices
DETAILED_POLYGON = [
    [-77.05, 38.89], [-77.04, 38.89], [-77.03, 38.895],
    [-77.02, 38.90], [-77.025, 38.91], [-77.03, 38.915],
    [-77.04, 38.91], [-77.05, 38.905], [-77.05, 38.89],
]

# Points for voronoi
POINT_COORDS = [(0, 0), (1, 0), (0.5, 1), (0, 1), (1, 1)]


# ============================================================
# ConvexHull tests
# ============================================================

class TestConvexHull:
    def test_happy_path(self):
        store = {"my_layer": _make_polygon_layer([SQUARE_A, SQUARE_B])}
        result = handle_convex_hull({"layer_name": "my_layer"}, layer_store=store)
        assert "error" not in result
        assert result["feature_count"] == 1
        assert result["geojson"]["type"] == "FeatureCollection"
        assert result["layer_name"] == "convex_hull_my_layer"

    def test_custom_output_name(self):
        store = {"my_layer": _make_polygon_layer([SQUARE_A])}
        result = handle_convex_hull(
            {"layer_name": "my_layer", "output_name": "hull_out"},
            layer_store=store,
        )
        assert result["layer_name"] == "hull_out"

    def test_missing_layer(self):
        result = handle_convex_hull({"layer_name": "nope"}, layer_store={})
        assert "error" in result

    def test_missing_layer_name_param(self):
        result = handle_convex_hull({}, layer_store={})
        assert "error" in result


# ============================================================
# Centroid tests
# ============================================================

class TestCentroid:
    def test_polygon_centroids(self):
        store = {"polys": _make_polygon_layer([SQUARE_A], [{"name": "A"}])}
        result = handle_centroid({"layer_name": "polys"}, layer_store=store)
        assert "error" not in result
        assert result["feature_count"] == 1
        # Centroid should be a Point
        geom = result["geojson"]["features"][0]["geometry"]
        assert geom["type"] == "Point"
        # Properties should be preserved
        assert result["geojson"]["features"][0]["properties"]["name"] == "A"

    def test_point_centroids(self):
        """Centroid of a point is the point itself."""
        store = {"pts": _make_point_layer([(1, 2), (3, 4)])}
        result = handle_centroid({"layer_name": "pts"}, layer_store=store)
        assert "error" not in result
        assert result["feature_count"] == 2

    def test_missing_layer(self):
        result = handle_centroid({"layer_name": "nope"}, layer_store={})
        assert "error" in result

    def test_empty_layer(self):
        store = {"empty": {"type": "FeatureCollection", "features": []}}
        result = handle_centroid({"layer_name": "empty"}, layer_store=store)
        assert "error" in result


# ============================================================
# Simplify tests
# ============================================================

class TestSimplify:
    def test_simplify_reduces_vertices(self):
        store = {"detail": _make_polygon_layer([DETAILED_POLYGON])}
        result = handle_simplify(
            {"layer_name": "detail", "tolerance": 500},
            layer_store=store,
        )
        assert "error" not in result
        assert result["feature_count"] == 1
        # The simplified polygon should have fewer or equal vertices
        orig_vertices = len(DETAILED_POLYGON)
        simplified_coords = result["geojson"]["features"][0]["geometry"]["coordinates"][0]
        assert len(simplified_coords) <= orig_vertices

    def test_default_tolerance(self):
        store = {"detail": _make_polygon_layer([DETAILED_POLYGON])}
        result = handle_simplify({"layer_name": "detail"}, layer_store=store)
        assert "error" not in result
        assert result["tolerance_m"] == 10

    def test_invalid_tolerance(self):
        store = {"detail": _make_polygon_layer([DETAILED_POLYGON])}
        result = handle_simplify(
            {"layer_name": "detail", "tolerance": -5},
            layer_store=store,
        )
        assert "error" in result

    def test_missing_layer(self):
        result = handle_simplify({"layer_name": "nope"}, layer_store={})
        assert "error" in result


# ============================================================
# BoundingBox tests
# ============================================================

class TestBoundingBox:
    def test_happy_path(self):
        store = {"my_layer": _make_polygon_layer([SQUARE_A, SQUARE_B])}
        result = handle_bounding_box({"layer_name": "my_layer"}, layer_store=store)
        assert "error" not in result
        assert result["feature_count"] == 1
        geom = result["geojson"]["features"][0]["geometry"]
        assert geom["type"] == "Polygon"
        assert result["layer_name"] == "bbox_my_layer"

    def test_single_point_layer(self):
        """Bounding box of a single point should still work (degenerate bbox)."""
        store = {"pt": _make_point_layer([(1.0, 2.0)])}
        result = handle_bounding_box({"layer_name": "pt"}, layer_store=store)
        assert "error" not in result
        assert result["feature_count"] == 1

    def test_missing_layer(self):
        result = handle_bounding_box({"layer_name": "nope"}, layer_store={})
        assert "error" in result


# ============================================================
# Dissolve tests
# ============================================================

class TestDissolve:
    def test_dissolve_by_attribute(self):
        props = [{"zone": "A"}, {"zone": "A"}, {"zone": "B"}]
        # Three adjacent squares, two with zone A
        coords_list = [
            SQUARE_A,
            [[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]],
            [[3, 0], [4, 0], [4, 1], [3, 1], [3, 0]],
        ]
        store = {"zones": _make_polygon_layer(coords_list, props)}
        result = handle_dissolve(
            {"layer_name": "zones", "by": "zone"},
            layer_store=store,
        )
        assert "error" not in result
        # Should produce 2 features (one for A, one for B)
        assert result["feature_count"] == 2
        assert result["dissolved_by"] == "zone"

    def test_missing_attribute(self):
        store = {"zones": _make_polygon_layer([SQUARE_A], [{"name": "x"}])}
        result = handle_dissolve(
            {"layer_name": "zones", "by": "nonexistent"},
            layer_store=store,
        )
        assert "error" in result

    def test_missing_by_param(self):
        store = {"zones": _make_polygon_layer([SQUARE_A])}
        result = handle_dissolve({"layer_name": "zones"}, layer_store=store)
        assert "error" in result

    def test_missing_layer(self):
        result = handle_dissolve({"layer_name": "nope", "by": "x"}, layer_store={})
        assert "error" in result


# ============================================================
# Clip tests
# ============================================================

class TestClip:
    def test_clip_overlap(self):
        """Clip square A by square B -- should produce the overlapping region."""
        store = {
            "features": _make_polygon_layer([SQUARE_A]),
            "mask": _make_polygon_layer([SQUARE_B]),
        }
        result = handle_clip(
            {"clip_layer": "features", "mask_layer": "mask"},
            layer_store=store,
        )
        assert "error" not in result
        assert result["feature_count"] == 1
        assert result["layer_name"] == "clipped_features"

    def test_clip_no_overlap(self):
        """Clipping by a non-overlapping mask should produce 0 features."""
        far_square = [[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]
        store = {
            "features": _make_polygon_layer([SQUARE_A]),
            "mask": _make_polygon_layer([far_square]),
        }
        result = handle_clip(
            {"clip_layer": "features", "mask_layer": "mask"},
            layer_store=store,
        )
        assert "error" not in result
        assert result["feature_count"] == 0

    def test_missing_clip_layer(self):
        store = {"mask": _make_polygon_layer([SQUARE_B])}
        result = handle_clip(
            {"clip_layer": "nope", "mask_layer": "mask"},
            layer_store=store,
        )
        assert "error" in result

    def test_missing_mask_layer(self):
        store = {"features": _make_polygon_layer([SQUARE_A])}
        result = handle_clip(
            {"clip_layer": "features", "mask_layer": "nope"},
            layer_store=store,
        )
        assert "error" in result


# ============================================================
# Voronoi tests
# ============================================================

class TestVoronoi:
    def test_voronoi_from_points(self):
        store = {"stations": _make_point_layer(POINT_COORDS)}
        result = handle_voronoi({"layer_name": "stations"}, layer_store=store)
        assert "error" not in result
        assert result["feature_count"] >= 2  # At least some polygons
        assert result["layer_name"] == "voronoi_stations"

    def test_voronoi_from_polygons_uses_centroids(self):
        """Voronoi should work on polygon layers by using centroids."""
        store = {
            "polys": _make_polygon_layer([
                SQUARE_A,
                [[3, 3], [4, 3], [4, 4], [3, 4], [3, 3]],
            ])
        }
        result = handle_voronoi({"layer_name": "polys"}, layer_store=store)
        assert "error" not in result
        assert result["feature_count"] >= 2

    def test_voronoi_single_point_error(self):
        """Voronoi requires at least 2 points."""
        store = {"one": _make_point_layer([(0, 0)])}
        result = handle_voronoi({"layer_name": "one"}, layer_store=store)
        assert "error" in result

    def test_missing_layer(self):
        result = handle_voronoi({"layer_name": "nope"}, layer_store={})
        assert "error" in result


# ============================================================
# Dispatch integration tests
# ============================================================

class TestDispatchIntegration:
    """Verify all 7 tools are registered in dispatch_tool."""

    def test_all_tools_dispatched(self):
        from nl_gis.handlers import dispatch_tool
        store = {"layer": _make_polygon_layer([SQUARE_A, SQUARE_B])}

        # Each tool should be dispatchable without ValueError
        tools_and_params = [
            ("convex_hull", {"layer_name": "layer"}),
            ("centroid", {"layer_name": "layer"}),
            ("simplify", {"layer_name": "layer"}),
            ("bounding_box", {"layer_name": "layer"}),
            ("clip", {"clip_layer": "layer", "mask_layer": "layer"}),
            ("voronoi", {"layer_name": "layer"}),
        ]
        for tool_name, params in tools_and_params:
            result = dispatch_tool(tool_name, params, layer_store=store)
            assert "error" not in result, f"{tool_name} returned error: {result.get('error')}"

    def test_dissolve_dispatched(self):
        from nl_gis.handlers import dispatch_tool
        store = {"layer": _make_polygon_layer(
            [SQUARE_A, SQUARE_B],
            [{"cat": "x"}, {"cat": "y"}],
        )}
        result = dispatch_tool("dissolve", {"layer_name": "layer", "by": "cat"}, layer_store=store)
        assert "error" not in result

    def test_all_in_layer_producing_tools(self):
        from nl_gis.handlers import LAYER_PRODUCING_TOOLS
        expected = {"convex_hull", "centroid", "simplify", "bounding_box", "dissolve", "clip", "voronoi"}
        assert expected.issubset(LAYER_PRODUCING_TOOLS)
