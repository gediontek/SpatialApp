"""Cross-tool integration pipeline tests.

These tests chain multiple handler functions together to verify
end-to-end workflows work correctly. External APIs (geocoding, OSM)
are mocked; all spatial operations use real handler code.
"""

import sys
import os
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock

from nl_gis.handlers.layers import handle_import_csv, handle_import_wkt
from nl_gis.handlers.analysis import (
    handle_buffer,
    handle_spatial_query,
    handle_intersection,
    handle_calculate_area,
    handle_filter_layer,
    handle_hot_spot_analysis,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    """Create a FeatureCollection of points from [(lon, lat), ...]."""
    features = []
    for i, (lon, lat) in enumerate(points):
        props = properties_list[i] if properties_list else {}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# Pipeline 1: import CSV → buffer → spatial_query
# ---------------------------------------------------------------------------

class TestCSVImportBufferSpatialQuery:
    """Import CSV points -> buffer -> spatial_query to find nearby features."""

    def test_csv_import_buffer_spatial_query(self):
        layer_store = {}

        # Step 1: Import CSV with 3 points
        csv_data = "name,lat,lon\nAlpha,40.0,-74.0\nBravo,40.01,-74.01\nCharlie,40.1,-74.1"
        result = handle_import_csv(
            {"csv_data": csv_data, "layer_name": "csv_points"},
            layer_store=layer_store,
        )
        assert "error" not in result, f"CSV import failed: {result}"
        assert result["imported"] == 3
        assert "csv_points" in layer_store

        # Step 2: Buffer the points (1000m)
        result = handle_buffer(
            {"layer_name": "csv_points", "distance_m": 1000},
            layer_store=layer_store,
        )
        assert "error" not in result, f"Buffer failed: {result}"
        buffer_layer_name = result["layer_name"]
        # Store buffer result in layer_store
        layer_store[buffer_layer_name] = result["geojson"]
        assert result["feature_count"] == 1
        assert result["area_sq_km"] > 0

        # Step 3: Create a second layer with features to query against
        nearby_points = [
            (-74.001, 40.001),   # ~140m from Alpha -- within buffer
            (-74.005, 40.005),   # ~620m from Alpha -- within buffer
            (-75.0, 41.0),       # far away -- outside buffer
        ]
        layer_store["nearby_features"] = _make_point_layer(
            nearby_points,
            [{"id": "near1"}, {"id": "near2"}, {"id": "far1"}],
        )

        # Step 4: Spatial query -- find nearby_features within the buffer
        result = handle_spatial_query(
            {
                "source_layer": "nearby_features",
                "predicate": "within",
                "target_layer": buffer_layer_name,
            },
            layer_store=layer_store,
        )
        assert "error" not in result, f"Spatial query failed: {result}"
        # At least the close points should match
        assert result["feature_count"] >= 1
        assert result["feature_count"] < 3  # the far point should not match

    def test_csv_import_filter_chain(self):
        """Import CSV -> filter by attribute -> verify subset."""
        layer_store = {}

        csv_data = "city,lat,lon,pop\nNYC,40.71,-74.01,8000000\nLA,34.05,-118.24,4000000\nSF,37.77,-122.42,870000"
        result = handle_import_csv(
            {"csv_data": csv_data, "layer_name": "cities"},
            layer_store=layer_store,
        )
        assert "error" not in result
        assert result["imported"] == 3

        # Filter for cities with pop > 5000000
        result = handle_filter_layer(
            {
                "layer_name": "cities",
                "attribute": "pop",
                "operator": "greater_than",
                "value": "5000000",
                "output_name": "big_cities",
            },
            layer_store=layer_store,
        )
        assert "error" not in result, f"Filter failed: {result}"
        assert result["feature_count"] == 1  # Only NYC


# ---------------------------------------------------------------------------
# Pipeline 2: create layers → intersection → calculate_area
# ---------------------------------------------------------------------------

class TestFetchIntersectionArea:
    """Create two overlapping polygon layers -> intersection -> area."""

    def test_intersection_then_area(self):
        layer_store = {}

        # Two overlapping squares (using small degree offsets near equator)
        # A: (0,0)-(1,1), B: (0.5,0.5)-(1.5,1.5) -> overlap: (0.5,0.5)-(1,1)
        layer_store["layer_a"] = _make_polygon_layer([
            [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
        ])
        layer_store["layer_b"] = _make_polygon_layer([
            [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5], [0.5, 0.5]]
        ])

        # Step 1: Intersection
        result = handle_intersection(
            {"layer_a": "layer_a", "layer_b": "layer_b", "output_name": "overlap"},
            layer_store=layer_store,
        )
        assert "error" not in result, f"Intersection failed: {result}"
        assert result["feature_count"] == 1
        assert result["area_sq_km"] > 0
        layer_store["overlap"] = result["geojson"]

        # Step 2: Calculate area of the intersection
        area_result = handle_calculate_area(
            {"layer_name": "overlap"},
            layer_store=layer_store,
        )
        assert "error" not in area_result, f"Area calc failed: {area_result}"
        assert area_result["total_area_sq_m"] > 0
        assert area_result["total_area_sq_km"] > 0
        assert area_result["feature_count"] == 1

        # The intersection area should be smaller than either original
        area_a = handle_calculate_area(
            {"layer_name": "layer_a"}, layer_store=layer_store
        )
        assert area_result["total_area_sq_m"] < area_a["total_area_sq_m"]

    def test_non_overlapping_intersection_empty(self):
        """Non-overlapping layers produce empty intersection."""
        layer_store = {
            "left": _make_polygon_layer([
                [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
            ]),
            "right": _make_polygon_layer([
                [[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]
            ]),
        }

        result = handle_intersection(
            {"layer_a": "left", "layer_b": "right"},
            layer_store=layer_store,
        )
        assert "error" not in result
        assert result["feature_count"] == 0


# ---------------------------------------------------------------------------
# Pipeline 3: batch geocode → hot spot analysis
# ---------------------------------------------------------------------------

class TestBatchGeocodeHotSpot:
    """Batch geocode addresses -> add numeric attribute -> hot_spot_analysis."""

    def test_geocode_then_hot_spot(self):
        """Build point layer with numeric attribute, then run hot spot analysis."""
        layer_store = {}

        # Create a point layer directly (simulating geocoded output)
        # 15 points in a grid pattern with varying "crime_count" values
        points = []
        props = []
        for i in range(5):
            for j in range(3):
                lon = -74.0 + i * 0.01
                lat = 40.7 + j * 0.01
                # Higher values in upper-right cluster (hot spot)
                crime_val = 10 + i * 5 + j * 3
                points.append((lon, lat))
                props.append({"address": f"addr_{i}_{j}", "crime_count": crime_val})

        layer_store["geocoded_points"] = _make_point_layer(points, props)

        # Run hot spot analysis
        result = handle_hot_spot_analysis(
            {
                "layer_name": "geocoded_points",
                "attribute": "crime_count",
                "output_name": "crime_hotspots",
            },
            layer_store=layer_store,
        )
        assert "error" not in result, f"Hot spot failed: {result}"
        assert "analysis" in result
        analysis = result["analysis"]
        assert analysis["total_features"] == 15
        # z-scores should be assigned to all features
        features = result["geojson"]["features"]
        for f in features:
            assert "gi_z_score" in f["properties"]
            assert "gi_p_value" in f["properties"]
            assert f["properties"]["hotspot_class"] in ("hot", "cold", "not_significant")

    def test_hot_spot_insufficient_points(self):
        """Hot spot analysis requires at least 3 points."""
        layer_store = {
            "tiny": _make_point_layer(
                [(-74.0, 40.7), (-74.01, 40.71)],
                [{"val": 1}, {"val": 2}],
            )
        }
        result = handle_hot_spot_analysis(
            {"layer_name": "tiny", "attribute": "val"},
            layer_store=layer_store,
        )
        assert "error" in result
        assert "at least 3" in result["error"].lower()


# ---------------------------------------------------------------------------
# Pipeline 4: Concurrent layer operations
# ---------------------------------------------------------------------------

class TestConcurrentLayerOperations:
    """3 threads writing to different layers simultaneously."""

    def test_concurrent_writes(self):
        layer_store = {}
        errors = []

        def import_csv_thread(name, csv_data):
            try:
                result = handle_import_csv(
                    {"csv_data": csv_data, "layer_name": name},
                    layer_store=layer_store,
                )
                if "error" in result:
                    errors.append(f"{name}: {result['error']}")
            except Exception as e:
                errors.append(f"{name}: {e}")

        def import_wkt_thread(name, wkt):
            try:
                result = handle_import_wkt(
                    {"wkt": wkt, "layer_name": name},
                    layer_store=layer_store,
                )
                if "error" in result:
                    errors.append(f"{name}: {result['error']}")
            except Exception as e:
                errors.append(f"{name}: {e}")

        csv1 = "name,lat,lon\nA,40.0,-74.0\nB,40.1,-74.1"
        csv2 = "city,lat,lon\nX,35.0,-118.0\nY,36.0,-119.0\nZ,37.0,-120.0"
        wkt = "POLYGON((-87.7 41.8, -87.6 41.8, -87.6 41.9, -87.7 41.9, -87.7 41.8))"

        t1 = threading.Thread(target=import_csv_thread, args=("csv_1", csv1))
        t2 = threading.Thread(target=import_wkt_thread, args=("wkt_1", wkt))
        t3 = threading.Thread(target=import_csv_thread, args=("csv_2", csv2))

        t1.start()
        t2.start()
        t3.start()
        t1.join(timeout=10)
        t2.join(timeout=10)
        t3.join(timeout=10)

        assert not errors, f"Thread errors: {errors}"

        # Verify all 3 layers exist
        assert "csv_1" in layer_store, "csv_1 missing"
        assert "wkt_1" in layer_store, "wkt_1 missing"
        assert "csv_2" in layer_store, "csv_2 missing"

        # Verify data integrity
        assert len(layer_store["csv_1"]["features"]) == 2
        assert len(layer_store["wkt_1"]["features"]) == 1
        assert len(layer_store["csv_2"]["features"]) == 3

    def test_concurrent_reads_and_writes(self):
        """Read from one layer while writing to another."""
        layer_store = {
            "existing": _make_point_layer(
                [(-74.0, 40.0), (-74.01, 40.01)],
                [{"name": "A"}, {"name": "B"}],
            )
        }
        errors = []

        def write_thread():
            try:
                csv_data = "name,lat,lon\nNew,41.0,-75.0"
                result = handle_import_csv(
                    {"csv_data": csv_data, "layer_name": "new_layer"},
                    layer_store=layer_store,
                )
                if "error" in result:
                    errors.append(f"write: {result['error']}")
            except Exception as e:
                errors.append(f"write: {e}")

        def read_thread():
            try:
                result = handle_filter_layer(
                    {
                        "layer_name": "existing",
                        "attribute": "name",
                        "operator": "equals",
                        "value": "A",
                    },
                    layer_store=layer_store,
                )
                if "error" in result:
                    errors.append(f"read: {result['error']}")
            except Exception as e:
                errors.append(f"read: {e}")

        t1 = threading.Thread(target=write_thread)
        t2 = threading.Thread(target=read_thread)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not errors, f"Thread errors: {errors}"
        assert "new_layer" in layer_store
        assert "existing" in layer_store


# ---------------------------------------------------------------------------
# Pipeline 5: Import → Buffer → Area measurement chain
# ---------------------------------------------------------------------------

class TestImportBufferMeasure:
    """WKT import -> buffer -> measure area of buffer."""

    def test_wkt_import_buffer_area(self):
        layer_store = {}

        # Import a point via WKT
        result = handle_import_wkt(
            {"wkt": "POINT(-73.97 40.78)", "layer_name": "my_point"},
            layer_store=layer_store,
        )
        assert "error" not in result
        assert "my_point" in layer_store

        # Buffer the point by 500m
        result = handle_buffer(
            {"layer_name": "my_point", "distance_m": 500},
            layer_store=layer_store,
        )
        assert "error" not in result
        buffer_name = result["layer_name"]
        layer_store[buffer_name] = result["geojson"]

        # Calculate area
        area_result = handle_calculate_area(
            {"layer_name": buffer_name},
            layer_store=layer_store,
        )
        assert "error" not in area_result
        # 500m buffer around a point ~ pi * 500^2 ~ 785,000 sq m
        assert 500_000 < area_result["total_area_sq_m"] < 1_500_000
