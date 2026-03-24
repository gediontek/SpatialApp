"""Tests for Phase 4 routing tools."""

import pytest
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl_gis.tool_handlers import (
    dispatch_tool,
    handle_find_route,
    handle_isochrone,
    handle_heatmap,
)
from services.osrm_client import detect_osrm_url, PUBLIC_OSRM


class TestOSRMClient:
    """Tests for OSRM client auto-detection."""

    @patch("services.osrm_client._probe_port", return_value=False)
    def test_fallback_to_public(self, mock_probe):
        url = detect_osrm_url("driving")
        assert url == PUBLIC_OSRM

    @patch("services.osrm_client._probe_port", return_value=True)
    def test_detect_local_car(self, mock_probe):
        url = detect_osrm_url("driving")
        assert "localhost" in url
        assert "5001" in url

    @patch("services.osrm_client._probe_port", return_value=True)
    def test_detect_local_foot(self, mock_probe):
        url = detect_osrm_url("walking")
        assert "5002" in url


class TestHandleFindRoute:
    """Tests for route finding handler."""

    def test_no_origin(self):
        result = handle_find_route({"to_location": "Portland"})
        assert "error" in result

    def test_no_destination(self):
        result = handle_find_route({"from_location": "Seattle"})
        assert "error" in result

    @patch("nl_gis.tool_handlers.handle_geocode")
    @patch("services.osrm_client.requests.get")
    def test_route_with_locations(self, mock_get, mock_geocode):
        mock_geocode.side_effect = [
            {"lat": 47.6062, "lon": -122.3321, "display_name": "Seattle, WA"},
            {"lat": 45.5152, "lon": -122.6784, "display_name": "Portland, OR"},
        ]

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "Ok",
            "routes": [{
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-122.33, 47.6], [-122.5, 46.5], [-122.67, 45.5]]
                },
                "distance": 234000,
                "duration": 10800,
                "legs": [{"summary": "I-5 South"}]
            }]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = handle_find_route({
            "from_location": "Seattle",
            "to_location": "Portland",
            "profile": "driving"
        })

        assert "error" not in result
        assert result["distance_km"] == 234.0
        assert result["duration_min"] == 180.0
        assert "geojson" in result
        assert result["from_name"] == "Seattle, WA"
        assert result["to_name"] == "Portland, OR"
        assert len(result["geojson"]["features"]) == 3  # route + 2 markers

    @patch("nl_gis.tool_handlers.handle_geocode")
    @patch("services.osrm_client.requests.get")
    def test_route_with_coords(self, mock_get, mock_geocode):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "Ok",
            "routes": [{
                "geometry": {"type": "LineString", "coordinates": [[-122.3, 47.6], [-122.6, 45.5]]},
                "distance": 234000,
                "duration": 10800,
                "legs": [{}]
            }]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = handle_find_route({
            "from_point": {"lat": 47.6, "lon": -122.3},
            "to_point": {"lat": 45.5, "lon": -122.6},
        })
        assert "error" not in result
        assert result["distance_km"] == 234.0

    @patch("nl_gis.tool_handlers.handle_geocode")
    @patch("services.osrm_client.requests.get")
    def test_route_service_unavailable(self, mock_get, mock_geocode):
        mock_geocode.side_effect = [
            {"lat": 47.6, "lon": -122.3, "display_name": "A"},
            {"lat": 45.5, "lon": -122.6, "display_name": "B"},
        ]
        import requests as req
        mock_get.side_effect = req.ConnectionError("Connection refused")

        result = handle_find_route({
            "from_location": "A",
            "to_location": "B",
        })
        assert "error" in result


class TestHandleIsochrone:
    """Tests for isochrone handler."""

    def test_time_based_driving(self):
        result = handle_isochrone({
            "lat": 47.6, "lon": -122.3,
            "time_minutes": 10,
            "profile": "driving"
        })
        assert "error" not in result
        assert result["radius_m"] > 0
        assert result["area_sq_km"] > 0
        assert result["method"] == "buffer_estimate"
        assert "geojson" in result

    def test_time_based_walking(self):
        result = handle_isochrone({
            "lat": 47.6, "lon": -122.3,
            "time_minutes": 15,
            "profile": "walking"
        })
        assert "error" not in result
        # Walking 15min at 5km/h ≈ 1.25km radius
        assert 1000 < result["radius_m"] < 1500

    def test_distance_based(self):
        result = handle_isochrone({
            "lat": 47.6, "lon": -122.3,
            "distance_m": 2000
        })
        assert "error" not in result
        assert result["radius_m"] == 2000

    @patch("nl_gis.tool_handlers.handle_geocode")
    def test_location_name(self, mock_geocode):
        mock_geocode.return_value = {
            "lat": 47.6, "lon": -122.3, "display_name": "Seattle"
        }
        result = handle_isochrone({
            "location": "Seattle",
            "time_minutes": 5,
            "profile": "driving"
        })
        assert "error" not in result

    def test_no_center(self):
        result = handle_isochrone({"time_minutes": 10})
        assert "error" in result

    def test_no_time_or_distance(self):
        result = handle_isochrone({"lat": 47.6, "lon": -122.3})
        assert "error" in result


class TestHandleHeatmap:
    """Tests for heatmap handler."""

    def test_valid_layer(self):
        store = {
            "buildings": {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-122.3, 47.6]}, "properties": {}},
                    {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[-122.35, 47.6], [-122.34, 47.6], [-122.34, 47.61], [-122.35, 47.61], [-122.35, 47.6]]]}, "properties": {}},
                ]
            }
        }
        result = handle_heatmap({"layer_name": "buildings"}, store)
        assert result["success"] is True
        assert result["point_count"] == 2
        assert len(result["points"]) == 2
        # Points should be [lat, lng, intensity]
        assert len(result["points"][0]) == 3

    def test_layer_not_found(self):
        result = handle_heatmap({"layer_name": "nonexistent"}, {})
        assert "error" in result

    def test_empty_layer(self):
        store = {"empty": {"type": "FeatureCollection", "features": []}}
        result = handle_heatmap({"layer_name": "empty"}, store)
        assert "error" in result


class TestPhase4Dispatch:
    """Verify Phase 4 tools are registered."""

    def test_all_registered(self):
        for tool in ["find_route", "isochrone", "heatmap"]:
            try:
                dispatch_tool(tool, {}, {})
            except ValueError:
                pytest.fail(f"Tool '{tool}' not in dispatch")
