"""Tests for network analysis tools: closest_facility and optimize_route."""

import pytest
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl_gis.handlers import (
    dispatch_tool,
    handle_closest_facility,
    handle_optimize_route,
)
from nl_gis.handlers.routing import _nearest_neighbor_order
from nl_gis.geo_utils import ValidatedPoint


class TestHandleClosestFacility:
    """Tests for closest_facility handler."""

    def test_missing_feature_type(self):
        result = handle_closest_facility({"lat": 47.6, "lon": -122.3})
        assert "error" in result
        assert "feature_type" in result["error"]

    def test_missing_location(self):
        result = handle_closest_facility({"feature_type": "hospital"})
        assert "error" in result

    def test_invalid_count(self):
        result = handle_closest_facility({
            "lat": 47.6, "lon": -122.3,
            "feature_type": "hospital",
            "count": 25,
        })
        assert "error" in result
        assert "count" in result["error"]

    def test_invalid_count_zero(self):
        result = handle_closest_facility({
            "lat": 47.6, "lon": -122.3,
            "feature_type": "hospital",
            "count": 0,
        })
        assert "error" in result

    def test_invalid_radius(self):
        result = handle_closest_facility({
            "lat": 47.6, "lon": -122.3,
            "feature_type": "hospital",
            "max_radius_m": 100000,
        })
        assert "error" in result
        assert "max_radius_m" in result["error"]

    def test_unknown_feature_type_no_osm_key(self):
        result = handle_closest_facility({
            "lat": 47.6, "lon": -122.3,
            "feature_type": "martian_base",
        })
        assert "error" in result
        assert "Unknown feature type" in result["error"]

    @patch("nl_gis.handlers.routing.requests.get")
    @patch("nl_gis.handlers.routing.overpass_limiter")
    def test_successful_search(self, mock_limiter, mock_get):
        """Successful closest facility search with mock Overpass response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "elements": [
                {
                    "type": "node",
                    "id": 1001,
                    "lat": 47.605,
                    "lon": -122.330,
                    "tags": {"name": "Hospital A", "amenity": "hospital"},
                },
                {
                    "type": "node",
                    "id": 1002,
                    "lat": 47.615,
                    "lon": -122.340,
                    "tags": {"name": "Hospital B", "amenity": "hospital"},
                },
                {
                    "type": "node",
                    "id": 1003,
                    "lat": 47.620,
                    "lon": -122.350,
                    "tags": {"name": "Hospital C", "amenity": "hospital"},
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = handle_closest_facility({
            "lat": 47.606,
            "lon": -122.332,
            "feature_type": "hospital",
            "count": 2,
        })

        assert "error" not in result
        assert "geojson" in result
        assert result["feature_count"] == 2
        assert result["requested_count"] == 2
        assert result["layer_name"] == "closest_hospital_2"

        # Verify features are sorted by distance
        features = result["geojson"]["features"]
        assert len(features) == 2
        distances = [f["properties"]["distance_m"] for f in features]
        assert distances == sorted(distances)
        assert all(d > 0 for d in distances)

    @patch("nl_gis.handlers.routing.requests.get")
    @patch("nl_gis.handlers.routing.overpass_limiter")
    def test_no_results(self, mock_limiter, mock_get):
        """Empty Overpass response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"elements": []}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = handle_closest_facility({
            "lat": 47.6, "lon": -122.3,
            "feature_type": "hospital",
            "count": 5,
        })

        assert "error" not in result
        assert result["feature_count"] == 0

    @patch("nl_gis.handlers.navigation.handle_geocode")
    @patch("nl_gis.handlers.routing.requests.get")
    @patch("nl_gis.handlers.routing.overpass_limiter")
    def test_location_name_resolution(self, mock_limiter, mock_get, mock_geocode):
        """Resolve center from location name."""
        mock_geocode.return_value = {
            "lat": 47.6, "lon": -122.3, "display_name": "Seattle, WA",
        }

        mock_response = MagicMock()
        mock_response.json.return_value = {"elements": []}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = handle_closest_facility({
            "location": "Seattle",
            "feature_type": "hospital",
        })

        assert "error" not in result
        mock_geocode.assert_called_once()

    @patch("nl_gis.handlers.routing.requests.get")
    @patch("nl_gis.handlers.routing.overpass_limiter")
    def test_overpass_timeout(self, mock_limiter, mock_get):
        import requests as req
        mock_get.side_effect = req.Timeout("timed out")

        result = handle_closest_facility({
            "lat": 47.6, "lon": -122.3,
            "feature_type": "hospital",
        })

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch("nl_gis.handlers.routing.requests.get")
    @patch("nl_gis.handlers.routing.overpass_limiter")
    def test_custom_osm_key_value(self, mock_limiter, mock_get):
        """Custom OSM key/value for unknown feature types."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"elements": []}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = handle_closest_facility({
            "lat": 47.6, "lon": -122.3,
            "feature_type": "custom_type",
            "osm_key": "shop",
            "osm_value": "bicycle",
        })

        assert "error" not in result

    @patch("nl_gis.handlers.routing.requests.get")
    @patch("nl_gis.handlers.routing.overpass_limiter")
    def test_count_caps_results(self, mock_limiter, mock_get):
        """Verify count parameter limits results even when more are available."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "elements": [
                {"type": "node", "id": i, "lat": 47.6 + i * 0.001, "lon": -122.3,
                 "tags": {"amenity": "cafe"}}
                for i in range(10)
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = handle_closest_facility({
            "lat": 47.6, "lon": -122.3,
            "feature_type": "cafe",
            "count": 3,
        })

        assert "error" not in result
        assert result["feature_count"] == 3


class TestHandleOptimizeRoute:
    """Tests for optimize_route handler."""

    def test_too_few_locations(self):
        result = handle_optimize_route({
            "locations": [{"lat": 47.6, "lon": -122.3}, {"lat": 45.5, "lon": -122.6}]
        })
        assert "error" in result
        assert "at least 3" in result["error"]

    def test_too_many_locations(self):
        locs = [{"lat": i, "lon": i} for i in range(21)]
        result = handle_optimize_route({"locations": locs})
        assert "error" in result
        assert "Maximum 20" in result["error"]

    def test_invalid_location_format(self):
        result = handle_optimize_route({
            "locations": ["not a dict", {"lat": 1, "lon": 2}, {"lat": 3, "lon": 4}]
        })
        assert "error" in result

    def test_missing_coords_and_name(self):
        result = handle_optimize_route({
            "locations": [
                {"lat": 1, "lon": 2},
                {"lat": 3, "lon": 4},
                {},  # missing both lat/lon and location
            ]
        })
        assert "error" in result
        assert "Location 3" in result["error"]

    @patch("services.valhalla_client.get_route")
    @patch("nl_gis.handlers.routing._try_valhalla_optimized_route")
    def test_with_nearest_neighbor_fallback(self, mock_valhalla_opt, mock_get_route):
        """Fallback to nearest-neighbor when Valhalla optimized_route unavailable."""
        mock_valhalla_opt.return_value = None  # Valhalla optimized_route not available

        import polyline
        shape_encoded = polyline.encode([(47.6, -122.3), (47.61, -122.31), (47.62, -122.32)], 6)

        mock_get_route.return_value = {
            "geometry": {"type": "LineString", "coordinates": [[-122.3, 47.6], [-122.31, 47.61], [-122.32, 47.62]]},
            "distance_km": 5.0,
            "duration_min": 10.0,
            "distance_m": 5000,
            "duration_s": 600,
            "leg_count": 2,
        }

        result = handle_optimize_route({
            "locations": [
                {"lat": 47.6, "lon": -122.3},
                {"lat": 47.62, "lon": -122.32},
                {"lat": 47.61, "lon": -122.31},
            ],
            "profile": "auto",
        })

        assert "error" not in result
        assert "geojson" in result
        assert result["total_distance_km"] == 5.0
        assert result["total_duration_min"] == 10.0
        assert len(result["optimized_order"]) == 3
        assert result["layer_name"] == "optimized_route_3stops"

        # Check GeoJSON structure
        features = result["geojson"]["features"]
        assert any(f["geometry"]["type"] == "LineString" for f in features)
        # Should have 3 point markers (one per stop)
        point_features = [f for f in features if f["geometry"]["type"] == "Point"]
        assert len(point_features) == 3
        # Check roles
        roles = [f["properties"]["role"] for f in point_features]
        assert "origin" in roles
        assert "destination" in roles

    @patch("services.valhalla_client.get_route")
    @patch("nl_gis.handlers.routing._try_valhalla_optimized_route")
    def test_with_valhalla_optimized_route(self, mock_valhalla_opt, mock_get_route):
        """When Valhalla optimized_route succeeds."""
        mock_valhalla_opt.return_value = [0, 2, 1]  # Optimized order

        mock_get_route.side_effect = [
            # Optimized route
            {
                "geometry": {"type": "LineString", "coordinates": [[-122.3, 47.6], [-122.32, 47.62], [-122.31, 47.61]]},
                "distance_km": 4.0,
                "duration_min": 8.0,
                "distance_m": 4000,
                "duration_s": 480,
                "leg_count": 2,
            },
            # Original order route
            {
                "geometry": {"type": "LineString", "coordinates": [[-122.3, 47.6], [-122.31, 47.61], [-122.32, 47.62]]},
                "distance_km": 6.0,
                "duration_min": 12.0,
                "distance_m": 6000,
                "duration_s": 720,
                "leg_count": 2,
            },
        ]

        result = handle_optimize_route({
            "locations": [
                {"lat": 47.6, "lon": -122.3},
                {"lat": 47.61, "lon": -122.31},
                {"lat": 47.62, "lon": -122.32},
            ],
        })

        assert "error" not in result
        assert result["optimized_order"] == [1, 3, 2]  # 1-indexed
        assert result["distance_saved_km"] == 2.0
        assert result["time_saved_min"] == 4.0

    @patch("services.valhalla_client.get_route")
    @patch("nl_gis.handlers.routing._try_valhalla_optimized_route")
    def test_routing_service_unavailable(self, mock_valhalla_opt, mock_get_route):
        """When both optimized_route and regular routing fail."""
        mock_valhalla_opt.return_value = None
        mock_get_route.return_value = None  # Routing unavailable

        result = handle_optimize_route({
            "locations": [
                {"lat": 47.6, "lon": -122.3},
                {"lat": 47.61, "lon": -122.31},
                {"lat": 47.62, "lon": -122.32},
            ],
        })

        assert "error" in result
        assert "unavailable" in result["error"].lower()

    @patch("nl_gis.handlers.navigation.handle_geocode")
    @patch("services.valhalla_client.get_route")
    @patch("nl_gis.handlers.routing._try_valhalla_optimized_route")
    def test_location_name_geocoding(self, mock_valhalla_opt, mock_get_route, mock_geocode):
        """Locations specified by name are geocoded."""
        mock_valhalla_opt.return_value = None
        mock_geocode.return_value = {
            "lat": 47.61, "lon": -122.31, "display_name": "Space Needle, Seattle",
        }
        mock_get_route.return_value = {
            "geometry": {"type": "LineString", "coordinates": [[-122.3, 47.6], [-122.31, 47.61], [-122.32, 47.62]]},
            "distance_km": 5.0,
            "duration_min": 10.0,
            "distance_m": 5000,
            "duration_s": 600,
            "leg_count": 2,
        }

        result = handle_optimize_route({
            "locations": [
                {"lat": 47.6, "lon": -122.3},
                {"location": "Space Needle"},
                {"lat": 47.62, "lon": -122.32},
            ],
        })

        assert "error" not in result
        mock_geocode.assert_called_once()

    @patch("nl_gis.handlers.navigation.handle_geocode")
    def test_geocode_failure(self, mock_geocode):
        """Geocoding failure returns error."""
        mock_geocode.return_value = {"error": "Location not found"}

        result = handle_optimize_route({
            "locations": [
                {"lat": 47.6, "lon": -122.3},
                {"location": "Nonexistent Place XYZ"},
                {"lat": 47.62, "lon": -122.32},
            ],
        })

        assert "error" in result
        assert "Could not geocode" in result["error"]


class TestNearestNeighborOrder:
    """Tests for the nearest-neighbor TSP heuristic."""

    def test_three_points_in_line(self):
        """Points in a line should be visited in geographic order."""
        points = [
            (ValidatedPoint(lat=0.0, lon=0.0), "A"),
            (ValidatedPoint(lat=0.0, lon=2.0), "C"),
            (ValidatedPoint(lat=0.0, lon=1.0), "B"),
        ]
        order = _nearest_neighbor_order(points)
        # Starting from A(0,0), nearest is B(0,1), then C(0,2)
        assert order == [0, 2, 1]

    def test_single_swap(self):
        """Three points where NN should swap middle two vs original order."""
        points = [
            (ValidatedPoint(lat=0.0, lon=0.0), "A"),
            (ValidatedPoint(lat=10.0, lon=10.0), "Far"),
            (ValidatedPoint(lat=0.01, lon=0.01), "Near"),
        ]
        order = _nearest_neighbor_order(points)
        # From A, nearest is Near, then Far
        assert order[0] == 0
        assert order[1] == 2  # Near is closer
        assert order[2] == 1  # Far is last


class TestNetworkAnalysisDispatch:
    """Verify new tools are registered in dispatch."""

    def test_closest_facility_registered(self):
        try:
            dispatch_tool("closest_facility", {"feature_type": "hospital"}, {})
        except ValueError:
            pytest.fail("Tool 'closest_facility' not in dispatch")

    def test_optimize_route_registered(self):
        try:
            dispatch_tool("optimize_route", {}, {})
        except ValueError:
            pytest.fail("Tool 'optimize_route' not in dispatch")


class TestNetworkAnalysisSchemas:
    """Verify tool schemas are defined."""

    def test_schemas_exist(self):
        from nl_gis.tools import get_tool_definitions
        tools = get_tool_definitions()
        names = [t["name"] for t in tools]
        assert "closest_facility" in names
        assert "optimize_route" in names

    def test_closest_facility_schema(self):
        from nl_gis.tools import get_tool_definitions
        tools = {t["name"]: t for t in get_tool_definitions()}
        schema = tools["closest_facility"]["input_schema"]
        assert "feature_type" in schema["required"]
        props = schema["properties"]
        assert "lat" in props
        assert "lon" in props
        assert "location" in props
        assert "count" in props
        assert "max_radius_m" in props

    def test_optimize_route_schema(self):
        from nl_gis.tools import get_tool_definitions
        tools = {t["name"]: t for t in get_tool_definitions()}
        schema = tools["optimize_route"]["input_schema"]
        assert "locations" in schema["required"]
        props = schema["properties"]
        assert "locations" in props
        assert "profile" in props
        assert props["locations"]["type"] == "array"


class TestLayerProducingTools:
    """Verify new tools are in LAYER_PRODUCING_TOOLS."""

    def test_in_layer_producing(self):
        from nl_gis.handlers import LAYER_PRODUCING_TOOLS
        assert "closest_facility" in LAYER_PRODUCING_TOOLS
        assert "optimize_route" in LAYER_PRODUCING_TOOLS
