"""Tests for advanced analysis tools: point_in_polygon, attribute_join, spatial_statistics."""

import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl_gis.handlers import (
    dispatch_tool,
    handle_point_in_polygon,
    handle_attribute_join,
    handle_spatial_statistics,
    handle_hot_spot_analysis,
)


# ============================================================
# Test fixtures
# ============================================================

def _make_layer_store(layers: dict) -> dict:
    """Create a simple layer store dict from {name: FeatureCollection}."""
    return layers


def _polygon_layer():
    """A layer with two non-overlapping square polygons."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
                },
                "properties": {"name": "zone_A", "id": "1"}
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]
                },
                "properties": {"name": "zone_B", "id": "2"}
            },
        ]
    }


def _point_layer():
    """A layer with 3 points: one inside zone_A, one inside zone_B, one outside both."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0.5, 0.5]},
                "properties": {"label": "pt_in_A"}
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [2.5, 2.5]},
                "properties": {"label": "pt_in_B"}
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
                "properties": {"label": "pt_outside"}
            },
        ]
    }


def _clustered_point_layer():
    """A layer with 20 points spread across a grid but with known spatial pattern.

    Used for both NNI and DBSCAN tests. Points are on a regular grid
    spanning ~1km x ~1km (0.01 degrees ~ 1.1km at equator).
    """
    features = []
    # 4x5 grid of points spanning 0.01 degrees
    for row in range(4):
        for col in range(5):
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [col * 0.0025, row * 0.0025]
                },
                "properties": {"id": row * 5 + col}
            })
    return {"type": "FeatureCollection", "features": features}


# ============================================================
# point_in_polygon tests
# ============================================================

class TestPointInPolygon:
    """Tests for point_in_polygon handler."""

    def test_single_point_inside(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = handle_point_in_polygon(
            {"polygon_layer": "polys", "lat": 0.5, "lon": 0.5},
            layer_store=store,
        )
        assert result["found"] is True
        assert result["polygon"]["name"] == "zone_A"

    def test_single_point_outside(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = handle_point_in_polygon(
            {"polygon_layer": "polys", "lat": 5.0, "lon": 5.0},
            layer_store=store,
        )
        assert result["found"] is False

    def test_single_point_in_second_polygon(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = handle_point_in_polygon(
            {"polygon_layer": "polys", "lat": 2.5, "lon": 2.5},
            layer_store=store,
        )
        assert result["found"] is True
        assert result["polygon"]["name"] == "zone_B"

    def test_batch_point_layer(self):
        store = _make_layer_store({
            "polys": _polygon_layer(),
            "points": _point_layer(),
        })
        result = handle_point_in_polygon(
            {"polygon_layer": "polys", "point_layer": "points"},
            layer_store=store,
        )
        assert "geojson" in result
        assert result["total_points"] == 3
        assert result["inside"] == 2
        assert result["outside"] == 1
        assert result["layer_name"] == "pip_polys"

        # Check merged properties
        feats = result["geojson"]["features"]
        labels = {f["properties"]["label"]: f["properties"]["in_polygon"] for f in feats}
        assert labels["pt_in_A"] is True
        assert labels["pt_in_B"] is True
        assert labels["pt_outside"] is False

    def test_missing_polygon_layer(self):
        result = handle_point_in_polygon({"polygon_layer": "nonexistent"}, layer_store={})
        assert "error" in result

    def test_no_point_input(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = handle_point_in_polygon(
            {"polygon_layer": "polys"},
            layer_store=store,
        )
        assert "error" in result
        assert "Provide" in result["error"]

    def test_dispatch(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = dispatch_tool(
            "point_in_polygon",
            {"polygon_layer": "polys", "lat": 0.5, "lon": 0.5},
            layer_store=store,
        )
        assert result["found"] is True


# ============================================================
# attribute_join tests
# ============================================================

class TestAttributeJoin:
    """Tests for attribute_join handler."""

    def test_basic_join(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        join_data = [
            {"id": "1", "population": 5000, "area_name": "Alpha"},
            {"id": "2", "population": 3000, "area_name": "Beta"},
        ]
        result = handle_attribute_join(
            {
                "layer_name": "polys",
                "join_data": join_data,
                "layer_key": "id",
                "data_key": "id",
            },
            layer_store=store,
        )
        assert "geojson" in result
        assert result["matched"] == 2
        assert result["unmatched"] == 0
        assert result["total_features"] == 2

        # Verify joined properties are prefixed
        feat0 = result["geojson"]["features"][0]
        assert feat0["properties"]["joined_population"] == 5000
        assert feat0["properties"]["joined_area_name"] == "Alpha"
        # Original properties preserved
        assert feat0["properties"]["name"] == "zone_A"

    def test_partial_match(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        join_data = [
            {"id": "1", "population": 5000},
        ]
        result = handle_attribute_join(
            {
                "layer_name": "polys",
                "join_data": join_data,
                "layer_key": "id",
                "data_key": "id",
            },
            layer_store=store,
        )
        assert result["matched"] == 1
        assert result["unmatched"] == 1

    def test_no_match(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        join_data = [
            {"id": "99", "population": 9999},
        ]
        result = handle_attribute_join(
            {
                "layer_name": "polys",
                "join_data": join_data,
                "layer_key": "id",
                "data_key": "id",
            },
            layer_store=store,
        )
        assert result["matched"] == 0
        assert result["unmatched"] == 2

    def test_missing_layer(self):
        result = handle_attribute_join(
            {
                "layer_name": "nonexistent",
                "join_data": [{"id": "1"}],
                "layer_key": "id",
                "data_key": "id",
            },
            layer_store={},
        )
        assert "error" in result

    def test_missing_required_params(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = handle_attribute_join({"layer_name": "polys"}, layer_store=store)
        assert "error" in result

    def test_empty_join_data(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = handle_attribute_join(
            {
                "layer_name": "polys",
                "join_data": [],
                "layer_key": "id",
                "data_key": "id",
            },
            layer_store=store,
        )
        assert "error" in result

    def test_dispatch(self):
        store = _make_layer_store({"polys": _polygon_layer()})
        result = dispatch_tool(
            "attribute_join",
            {
                "layer_name": "polys",
                "join_data": [{"id": "1", "val": 42}],
                "layer_key": "id",
                "data_key": "id",
            },
            layer_store=store,
        )
        assert result["matched"] == 1


# ============================================================
# spatial_statistics tests
# ============================================================

class TestSpatialStatistics:
    """Tests for spatial_statistics handler."""

    def test_nearest_neighbor_basic(self):
        """Verify NNI computation runs and returns correct structure."""
        store = _make_layer_store({"pts": _clustered_point_layer()})
        result = handle_spatial_statistics(
            {"layer_name": "pts", "method": "nearest_neighbor"},
            layer_store=store,
        )
        assert "error" not in result
        assert result["method"] == "nearest_neighbor"
        assert result["point_count"] == 20
        assert result["nni"] > 0
        assert result["interpretation"] in ("clustered", "random", "dispersed")
        assert "observed_mean_distance_m" in result
        assert "expected_mean_distance_m" in result
        assert result["observed_mean_distance_m"] > 0
        assert result["expected_mean_distance_m"] > 0
        assert result["study_area_sq_m"] > 0

    def test_nearest_neighbor_clustered_pattern(self):
        """Verify truly clustered points yield NNI < 1.

        Strategy: place 48 points tightly clustered in a small area, plus
        2 outliers far apart to create a large convex hull. The observed
        mean NN distance stays small (dominated by 48 close neighbors)
        while the expected mean grows with the large study area.
        """
        features = []
        # 48 points in a tight 6x8 grid, each ~1m apart (0.00001 deg ~ 1.1m)
        idx = 0
        for row in range(6):
            for col in range(8):
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [col * 0.00001, row * 0.00001]
                    },
                    "properties": {"id": idx}
                })
                idx += 1
        # 2 outliers to create a large rectangular study area
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0.1, 0.0]},
            "properties": {"id": idx}
        })
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0.0, 0.1]},
            "properties": {"id": idx + 1}
        })
        layer = {"type": "FeatureCollection", "features": features}
        store = _make_layer_store({"pts": layer})
        result = handle_spatial_statistics(
            {"layer_name": "pts", "method": "nearest_neighbor"},
            layer_store=store,
        )
        assert "error" not in result
        # 48 tightly packed points + 2 far outliers:
        # Most NN distances are ~1m, expected is much larger due to big study area
        assert result["nni"] < 1.0

    def test_nearest_neighbor_few_points(self):
        """At least 2 points required."""
        single_pt = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "properties": {}
                }
            ]
        }
        store = _make_layer_store({"pts": single_pt})
        result = handle_spatial_statistics(
            {"layer_name": "pts", "method": "nearest_neighbor"},
            layer_store=store,
        )
        assert "error" in result

    def test_dbscan_basic(self):
        store = _make_layer_store({"pts": _clustered_point_layer()})
        result = handle_spatial_statistics(
            {
                "layer_name": "pts",
                "method": "dbscan",
                "eps": 50,
                "min_samples": 3,
            },
            layer_store=store,
        )
        assert "error" not in result
        assert result["method"] == "dbscan"
        assert result["total_points"] == 20
        assert "n_clusters" in result
        assert "noise_points" in result
        assert "geojson" in result
        assert result["layer_name"] == "dbscan_pts"

        # Each feature should have a cluster_id property
        for feat in result["geojson"]["features"]:
            assert "cluster_id" in feat["properties"]

    def test_dbscan_with_output_name(self):
        store = _make_layer_store({"pts": _clustered_point_layer()})
        result = handle_spatial_statistics(
            {
                "layer_name": "pts",
                "method": "dbscan",
                "eps": 50,
                "min_samples": 3,
                "output_name": "my_clusters",
            },
            layer_store=store,
        )
        assert result["layer_name"] == "my_clusters"

    def test_missing_layer(self):
        result = handle_spatial_statistics(
            {"layer_name": "nonexistent"},
            layer_store={},
        )
        assert "error" in result

    def test_unknown_method(self):
        store = _make_layer_store({"pts": _clustered_point_layer()})
        result = handle_spatial_statistics(
            {"layer_name": "pts", "method": "kmeans"},
            layer_store=store,
        )
        assert "error" in result
        assert "Unknown method" in result["error"]

    def test_dispatch(self):
        store = _make_layer_store({"pts": _clustered_point_layer()})
        result = dispatch_tool(
            "spatial_statistics",
            {"layer_name": "pts", "method": "nearest_neighbor"},
            layer_store=store,
        )
        assert result["method"] == "nearest_neighbor"
        assert "nni" in result


# ============================================================
# hot_spot_analysis tests
# ============================================================

def _hot_spot_layer_clustered():
    """Layer with spatially clustered high/low values for hot spot analysis.

    Left cluster (x ~ 0): high values (100)
    Right cluster (x ~ 1): low values (1)
    Center points: medium values (50)
    """
    features = []
    # Hot cluster: high values near (0, 0)
    for i in range(10):
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [i * 0.001, 0.0]},
            "properties": {"count": 100, "label": "hot"},
        })
    # Cold cluster: low values near (1, 0)
    for i in range(10):
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [1.0 + i * 0.001, 0.0]},
            "properties": {"count": 1, "label": "cold"},
        })
    # Medium buffer between clusters
    for i in range(5):
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0.5 + i * 0.001, 0.0]},
            "properties": {"count": 50, "label": "mid"},
        })
    return {"type": "FeatureCollection", "features": features}


def _hot_spot_layer_uniform():
    """Layer with uniform values — no hot/cold spots expected."""
    features = []
    for i in range(20):
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [i * 0.01, 0.0]},
            "properties": {"count": 42},
        })
    return {"type": "FeatureCollection", "features": features}


class TestHotSpotAnalysis:
    """Tests for hot_spot_analysis handler (Getis-Ord Gi*)."""

    def test_clustered_data_produces_hot_spots(self):
        """Spatially clustered high values should produce hot spots (z > 1.96)."""
        store = _make_layer_store({"data": _hot_spot_layer_clustered()})
        result = handle_hot_spot_analysis(
            {"layer_name": "data", "attribute": "count"},
            layer_store=store,
        )
        assert "error" not in result
        assert "geojson" in result
        assert result["layer_name"] == "hotspot_data"

        analysis = result["analysis"]
        assert analysis["total_features"] == 25
        assert analysis["attribute"] == "count"
        assert analysis["significance_level"] == 0.05
        assert analysis["bandwidth_m"] > 0

        # Should find at least some hot spots in the high-value cluster
        assert analysis["hot_spots"] > 0

        # Verify z-scores exist on features
        feats = result["geojson"]["features"]
        for f in feats:
            assert "gi_z_score" in f["properties"]
            assert "gi_p_value" in f["properties"]
            assert "hotspot_class" in f["properties"]
            assert f["properties"]["hotspot_class"] in ("hot", "cold", "not_significant")

        # At least one feature in the high-value cluster should have z > 1.96
        hot_features = [f for f in feats if f["properties"]["hotspot_class"] == "hot"]
        assert len(hot_features) > 0
        assert any(f["properties"]["gi_z_score"] > 1.96 for f in hot_features)

    def test_uniform_data_no_significant_results(self):
        """Uniform attribute values should produce no significant hot/cold spots."""
        store = _make_layer_store({"data": _hot_spot_layer_uniform()})
        result = handle_hot_spot_analysis(
            {"layer_name": "data", "attribute": "count"},
            layer_store=store,
        )
        assert "error" not in result
        analysis = result["analysis"]
        assert analysis["hot_spots"] == 0
        assert analysis["cold_spots"] == 0
        assert analysis["not_significant"] == 20

    def test_missing_attribute_error(self):
        """Missing attribute parameter should return error."""
        store = _make_layer_store({"data": _hot_spot_layer_clustered()})
        result = handle_hot_spot_analysis(
            {"layer_name": "data"},
            layer_store=store,
        )
        assert "error" in result
        assert "attribute" in result["error"]

    def test_non_numeric_attribute_error(self):
        """Non-numeric attribute values should be skipped, too few valid -> error."""
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {"name": "alpha"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1, 0]},
                "properties": {"name": "beta"},
            },
        ]
        layer = {"type": "FeatureCollection", "features": features}
        store = _make_layer_store({"data": layer})
        result = handle_hot_spot_analysis(
            {"layer_name": "data", "attribute": "name"},
            layer_store=store,
        )
        assert "error" in result
        assert "at least 3" in result["error"]

    def test_too_few_features_error(self):
        """Fewer than 3 valid features should return error."""
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {"val": 10},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1, 0]},
                "properties": {"val": 20},
            },
        ]
        layer = {"type": "FeatureCollection", "features": features}
        store = _make_layer_store({"data": layer})
        result = handle_hot_spot_analysis(
            {"layer_name": "data", "attribute": "val"},
            layer_store=store,
        )
        assert "error" in result
        assert "at least 3" in result["error"]

    def test_missing_layer_error(self):
        """Nonexistent layer should return error."""
        result = handle_hot_spot_analysis(
            {"layer_name": "nonexistent", "attribute": "val"},
            layer_store={},
        )
        assert "error" in result

    def test_custom_output_name(self):
        """Custom output_name should be used."""
        store = _make_layer_store({"data": _hot_spot_layer_clustered()})
        result = handle_hot_spot_analysis(
            {"layer_name": "data", "attribute": "count", "output_name": "my_hotspots"},
            layer_store=store,
        )
        assert "error" not in result
        assert result["layer_name"] == "my_hotspots"

    def test_colors_in_result(self):
        """Result should include color mapping for rendering."""
        store = _make_layer_store({"data": _hot_spot_layer_clustered()})
        result = handle_hot_spot_analysis(
            {"layer_name": "data", "attribute": "count"},
            layer_store=store,
        )
        assert "colors" in result
        assert result["colors"]["hot"] == "#ff0000"
        assert result["colors"]["cold"] == "#0000ff"
        assert result["colors"]["not_significant"] == "#808080"

    def test_dispatch(self):
        """Verify dispatch_tool routes to hot_spot_analysis."""
        store = _make_layer_store({"data": _hot_spot_layer_clustered()})
        result = dispatch_tool(
            "hot_spot_analysis",
            {"layer_name": "data", "attribute": "count"},
            layer_store=store,
        )
        assert "error" not in result
        assert "geojson" in result
        assert result["analysis"]["total_features"] == 25
