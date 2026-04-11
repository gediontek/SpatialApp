"""Tests for Phase 4 routing tools (Valhalla engine)."""

import pytest
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl_gis.handlers import (
    dispatch_tool,
    handle_find_route,
    handle_isochrone,
    handle_heatmap,
)
from services.valhalla_client import detect_valhalla_url, PUBLIC_VALHALLA


class TestValhallaClient:
    """Tests for Valhalla client auto-detection."""

    @patch("services.valhalla_client._probe_port", return_value=False)
    def test_fallback_to_public(self, mock_probe):
        import services.valhalla_client as vc
        vc._detected_url = None  # Reset cached detection
        url = detect_valhalla_url()
        assert url == PUBLIC_VALHALLA
        vc._detected_url = None  # Clean up

    @patch("services.valhalla_client._probe_port", return_value=True)
    def test_detect_local(self, mock_probe):
        import services.valhalla_client as vc
        vc._detected_url = None  # Reset cached detection
        url = detect_valhalla_url()
        assert "localhost" in url
        assert "8002" in url
        vc._detected_url = None  # Clean up


class TestHandleFindRoute:
    """Tests for route finding handler (Valhalla)."""

    def test_no_origin(self):
        result = handle_find_route({"to_location": "Portland"})
        assert "error" in result

    def test_no_destination(self):
        result = handle_find_route({"from_location": "Seattle"})
        assert "error" in result

    @patch("nl_gis.handlers.navigation.handle_geocode")
    @patch("services.valhalla_client.requests.post")
    @patch("services.valhalla_client._probe_port", return_value=False)
    def test_route_with_locations(self, mock_probe, mock_post, mock_geocode):
        import services.valhalla_client as vc
        vc._detected_url = None

        mock_geocode.side_effect = [
            {"lat": 47.6062, "lon": -122.3321, "display_name": "Seattle, WA"},
            {"lat": 45.5152, "lon": -122.6784, "display_name": "Portland, OR"},
        ]

        # Valhalla response format
        # polyline6 encode of [(47.6, -122.3), (46.5, -122.5), (45.5, -122.67)]
        import polyline
        shape = polyline.encode([(47.6, -122.3), (46.5, -122.5), (45.5, -122.67)], 6)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "trip": {
                "summary": {"length": 234.0, "time": 10800},
                "legs": [{
                    "summary": {"length": 234.0, "time": 10800},
                    "shape": shape,
                    "maneuvers": [
                        {"instruction": "Head south", "type": 1, "length": 234.0, "time": 10800, "street_names": ["I-5"]}
                    ],
                }],
            }
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

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
        vc._detected_url = None

    @patch("nl_gis.handlers.navigation.handle_geocode")
    @patch("services.valhalla_client.requests.post")
    @patch("services.valhalla_client._probe_port", return_value=False)
    def test_route_with_coords(self, mock_probe, mock_post, mock_geocode):
        import services.valhalla_client as vc
        vc._detected_url = None

        import polyline
        shape = polyline.encode([(47.6, -122.3), (45.5, -122.6)], 6)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "trip": {
                "summary": {"length": 234.0, "time": 10800},
                "legs": [{"summary": {"length": 234.0, "time": 10800}, "shape": shape, "maneuvers": []}],
            }
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = handle_find_route({
            "from_point": {"lat": 47.6, "lon": -122.3},
            "to_point": {"lat": 45.5, "lon": -122.6},
        })
        assert "error" not in result
        assert result["distance_km"] == 234.0
        vc._detected_url = None

    @patch("services.valhalla_client.valhalla_cache")
    @patch("nl_gis.handlers.navigation.handle_geocode")
    @patch("services.valhalla_client.requests.post")
    @patch("services.valhalla_client._probe_port", return_value=False)
    def test_route_service_unavailable(self, mock_probe, mock_post, mock_geocode, mock_cache):
        import services.valhalla_client as vc
        vc._detected_url = None

        mock_cache.get.return_value = None  # No cached result

        mock_geocode.side_effect = [
            {"lat": 47.6, "lon": -122.3, "display_name": "A"},
            {"lat": 45.5, "lon": -122.6, "display_name": "B"},
        ]
        import requests as req
        mock_post.side_effect = req.ConnectionError("Connection refused")

        result = handle_find_route({
            "from_location": "A",
            "to_location": "B",
        })
        assert "error" in result
        vc._detected_url = None


class TestHandleIsochrone:
    """Tests for isochrone handler (Valhalla network-based)."""

    @patch("services.valhalla_client.requests.post")
    @patch("services.valhalla_client._probe_port", return_value=False)
    def test_time_based_valhalla(self, mock_probe, mock_post):
        """True network isochrone from Valhalla."""
        import services.valhalla_client as vc
        vc._detected_url = None

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-122.3, 47.6], [-122.25, 47.62], [-122.2, 47.6],
                        [-122.25, 47.58], [-122.3, 47.6]
                    ]]
                },
                "properties": {"time": 10, "metric": "time"},
            }],
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = handle_isochrone({
            "lat": 47.6, "lon": -122.3,
            "time_minutes": 10,
            "profile": "driving"
        })
        assert "error" not in result
        assert result["method"] == "valhalla_network"
        assert result["area_sq_km"] > 0
        assert "geojson" in result
        # Should have isochrone polygon + center marker
        features = result["geojson"]["features"]
        assert any(f["geometry"]["type"] == "Polygon" for f in features)
        assert any(f.get("properties", {}).get("role") == "center" for f in features)
        vc._detected_url = None

    @patch("services.valhalla_client.requests.post")
    @patch("services.valhalla_client._probe_port", return_value=False)
    def test_distance_based_valhalla(self, mock_probe, mock_post):
        """Distance-based isochrone from Valhalla."""
        import services.valhalla_client as vc
        vc._detected_url = None

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-122.3, 47.6], [-122.28, 47.61], [-122.26, 47.6],
                        [-122.28, 47.59], [-122.3, 47.6]
                    ]]
                },
                "properties": {"distance": 2, "metric": "distance"},
            }],
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = handle_isochrone({
            "lat": 47.6, "lon": -122.3,
            "distance_m": 2000
        })
        assert "error" not in result
        assert result["method"] == "valhalla_network"
        vc._detected_url = None

    def test_fallback_to_buffer(self):
        """Falls back to buffer when Valhalla is unavailable."""
        with patch("services.valhalla_client.requests.post") as mock_post, \
             patch("services.valhalla_client._probe_port", return_value=False):
            import services.valhalla_client as vc
            vc._detected_url = None
            import requests as req
            mock_post.side_effect = req.ConnectionError("No connection")

            result = handle_isochrone({
                "lat": 47.6, "lon": -122.3,
                "time_minutes": 15,
                "profile": "walking"
            })
            assert "error" not in result
            assert result["method"] == "buffer_estimate"
            assert result["radius_m"] > 0
            # Walking 15min at 5km/h ≈ 1.25km radius
            assert 1000 < result["radius_m"] < 1500
            vc._detected_url = None

    @patch("nl_gis.handlers.navigation.handle_geocode")
    @patch("services.valhalla_client.requests.post")
    @patch("services.valhalla_client._probe_port", return_value=False)
    def test_location_name(self, mock_probe, mock_post, mock_geocode):
        import services.valhalla_client as vc
        vc._detected_url = None

        mock_geocode.return_value = {
            "lat": 47.6, "lon": -122.3, "display_name": "Seattle"
        }
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[-122.3, 47.6], [-122.25, 47.62], [-122.2, 47.6], [-122.25, 47.58], [-122.3, 47.6]]]},
                "properties": {"time": 5},
            }],
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = handle_isochrone({
            "location": "Seattle",
            "time_minutes": 5,
            "profile": "driving"
        })
        assert "error" not in result
        assert result["method"] == "valhalla_network"
        vc._detected_url = None

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
