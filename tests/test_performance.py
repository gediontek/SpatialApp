"""Performance benchmark tests (sanity checks, not strict SLAs).

Each test generates synthetic data and asserts that operations
complete within generous time bounds. These catch regressions
where an O(n) algorithm accidentally becomes O(n^2).
"""

import sys
import os
import random
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from nl_gis.handlers.analysis import (
    handle_spatial_query,
    handle_filter_layer,
    handle_buffer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_point_layer(n, center_lon=-74.0, center_lat=40.7, spread=0.5):
    """Generate a FeatureCollection of n random point features."""
    random.seed(42)
    features = []
    for i in range(n):
        lon = center_lon + random.uniform(-spread, spread)
        lat = center_lat + random.uniform(-spread, spread)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": i,
                "category": random.choice(["A", "B", "C", "D"]),
                "value": round(random.uniform(0, 100), 2),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def _random_polygon_layer(n, center_lon=-74.0, center_lat=40.7, spread=0.5, size=0.01):
    """Generate a FeatureCollection of n small square polygons."""
    random.seed(42)
    features = []
    for i in range(n):
        lon = center_lon + random.uniform(-spread, spread)
        lat = center_lat + random.uniform(-spread, spread)
        half = size / 2
        coords = [
            [lon - half, lat - half],
            [lon + half, lat - half],
            [lon + half, lat + half],
            [lon - half, lat + half],
            [lon - half, lat - half],
        ]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {
                "id": i,
                "category": random.choice(["X", "Y", "Z"]),
                "area_val": round(random.uniform(10, 1000), 2),
            },
        })
    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSpatialQueryPerformance:
    """Spatial query on 1000 features should complete in <2 seconds."""

    def test_spatial_query_1k_features(self):
        layer_store = {}

        # Create layer with 1000 random point features
        layer_store["points_1k"] = _random_point_layer(1000)

        # Query polygon covering ~half the area
        query_polygon = {
            "type": "Polygon",
            "coordinates": [[
                [-74.25, 40.45],
                [-74.0, 40.45],
                [-74.0, 40.7],
                [-74.25, 40.7],
                [-74.25, 40.45],
            ]],
        }

        start = time.time()
        result = handle_spatial_query(
            {
                "source_layer": "points_1k",
                "predicate": "intersects",
                "target_geometry": query_polygon,
            },
            layer_store=layer_store,
        )
        elapsed = time.time() - start

        assert "error" not in result, f"Spatial query failed: {result}"
        assert result["feature_count"] > 0
        assert elapsed < 2.0, f"Spatial query took {elapsed:.2f}s (limit: 2.0s)"


class TestFilterLayerPerformance:
    """Filter 5000 features by attribute should complete in <1 second."""

    def test_filter_layer_5k_features(self):
        layer_store = {}

        layer_store["big_layer"] = _random_point_layer(5000)

        start = time.time()
        result = handle_filter_layer(
            {
                "layer_name": "big_layer",
                "attribute": "category",
                "operator": "equals",
                "value": "A",
                "output_name": "filtered_A",
            },
            layer_store=layer_store,
        )
        elapsed = time.time() - start

        assert "error" not in result, f"Filter failed: {result}"
        assert result["feature_count"] > 0
        assert elapsed < 1.0, f"Filter took {elapsed:.2f}s (limit: 1.0s)"

    def test_filter_numeric_comparison_5k(self):
        """Numeric greater_than filter on 5000 features."""
        layer_store = {"big": _random_point_layer(5000)}

        start = time.time()
        result = handle_filter_layer(
            {
                "layer_name": "big",
                "attribute": "value",
                "operator": "greater_than",
                "value": "50",
            },
            layer_store=layer_store,
        )
        elapsed = time.time() - start

        assert "error" not in result
        assert result["feature_count"] > 0
        assert elapsed < 1.0, f"Numeric filter took {elapsed:.2f}s (limit: 1.0s)"


class TestBufferPerformance:
    """Buffer 100 polygon features should complete in <3 seconds."""

    def test_buffer_100_polygons(self):
        layer_store = {}

        layer_store["polys_100"] = _random_polygon_layer(100)

        start = time.time()
        result = handle_buffer(
            {"layer_name": "polys_100", "distance_m": 1000},
            layer_store=layer_store,
        )
        elapsed = time.time() - start

        assert "error" not in result, f"Buffer failed: {result}"
        assert result["feature_count"] == 1
        assert result["area_sq_km"] > 0
        assert elapsed < 3.0, f"Buffer took {elapsed:.2f}s (limit: 3.0s)"
