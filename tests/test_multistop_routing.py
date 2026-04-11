"""Tests for multi-stop routing (waypoints support)."""

import pytest
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl_gis.handlers.routing import handle_find_route
from services.valhalla_client import get_route, LOCAL_VALHALLA


def _make_valhalla_response(legs_data):
    """Build a mock Valhalla response with multiple legs.

    Args:
        legs_data: list of (encoded_shape, length_km, time_s) tuples per leg.
    """
    import polyline

    total_length = sum(d[1] for d in legs_data)
    total_time = sum(d[2] for d in legs_data)

    legs = []
    for shape_coords, length_km, time_s in legs_data:
        encoded = polyline.encode(shape_coords, 6)
        legs.append({
            "shape": encoded,
            "summary": {"length": length_km, "time": time_s},
            "maneuvers": [
                {"instruction": "Continue", "type": 1, "length": length_km,
                 "time": time_s, "street_names": ["Main St"]}
            ],
        })

    return {
        "trip": {
            "summary": {"length": total_length, "time": total_time},
            "legs": legs,
        }
    }


class TestGetRouteMultiStop:
    """Tests for get_route() with locations list."""

    @patch("services.valhalla_client.valhalla_cache")
    @patch("services.valhalla_client.detect_valhalla_url", return_value=LOCAL_VALHALLA)
    @patch("services.valhalla_client.requests.post")
    def test_two_point_via_locations(self, mock_post, mock_detect, mock_cache):
        """Calling with locations=[(lat,lon),(lat,lon)] works like legacy 2-point."""
        mock_cache.get.return_value = None

        resp = _make_valhalla_response([
            ([(47.6, -122.3), (45.5, -122.6)], 234.0, 10800),
        ])
        mock_response = MagicMock()
        mock_response.json.return_value = resp
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = get_route(locations=[(47.6, -122.3), (45.5, -122.6)], profile="driving")

        assert result is not None
        assert result["distance_km"] == 234.0
        assert result["leg_count"] == 1
        assert result["geometry"]["type"] == "LineString"

    @patch("services.valhalla_client.valhalla_cache")
    @patch("services.valhalla_client.detect_valhalla_url", return_value=LOCAL_VALHALLA)
    @patch("services.valhalla_client.requests.post")
    def test_three_point_route(self, mock_post, mock_detect, mock_cache):
        """Route with origin + 1 waypoint + destination produces 2 legs."""
        mock_cache.get.return_value = None

        resp = _make_valhalla_response([
            ([(47.6, -122.3), (46.5, -122.5)], 120.0, 5400),
            ([(46.5, -122.5), (45.5, -122.6)], 114.0, 5400),
        ])
        mock_response = MagicMock()
        mock_response.json.return_value = resp
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = get_route(
            locations=[(47.6, -122.3), (46.5, -122.5), (45.5, -122.6)],
            profile="driving",
        )

        assert result is not None
        assert result["distance_km"] == 234.0
        assert result["leg_count"] == 2
        assert "legs" in result
        assert len(result["legs"]) == 2
        assert result["legs"][0]["distance_km"] == 120.0
        assert result["legs"][1]["distance_km"] == 114.0
        # Geometry should be combined from both legs
        assert result["geometry"]["type"] == "LineString"
        # 2 coords per leg, but junction point deduplicated: 2 + (2-1) = 3
        assert len(result["geometry"]["coordinates"]) == 3

    @patch("services.valhalla_client.valhalla_cache")
    @patch("services.valhalla_client.detect_valhalla_url", return_value=LOCAL_VALHALLA)
    @patch("services.valhalla_client.requests.post")
    def test_sends_break_type_to_valhalla(self, mock_post, mock_detect, mock_cache):
        """Each location sent to Valhalla should have type=break."""
        mock_cache.get.return_value = None

        resp = _make_valhalla_response([
            ([(47.6, -122.3), (46.5, -122.5)], 120.0, 5400),
            ([(46.5, -122.5), (45.5, -122.6)], 114.0, 5400),
        ])
        mock_response = MagicMock()
        mock_response.json.return_value = resp
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        get_route(
            locations=[(47.6, -122.3), (46.5, -122.5), (45.5, -122.6)],
        )

        # Inspect the payload sent to Valhalla
        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        for loc in payload["locations"]:
            assert loc["type"] == "break"

    def test_too_few_locations(self):
        """locations with fewer than 2 points should return None."""
        result = get_route(locations=[(47.6, -122.3)])
        assert result is None

    @patch("services.valhalla_client.valhalla_cache")
    @patch("services.valhalla_client.detect_valhalla_url", return_value=LOCAL_VALHALLA)
    @patch("services.valhalla_client.requests.post")
    def test_backward_compat_positional_args(self, mock_post, mock_detect, mock_cache):
        """Legacy positional arg calling convention still works."""
        mock_cache.get.return_value = None

        resp = _make_valhalla_response([
            ([(47.6, -122.3), (45.5, -122.6)], 234.0, 10800),
        ])
        mock_response = MagicMock()
        mock_response.json.return_value = resp
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = get_route(-122.3, 47.6, -122.6, 45.5, "driving")
        assert result is not None
        assert result["distance_km"] == 234.0


class TestHandleFindRouteMultiStop:
    """Tests for handle_find_route with waypoints."""

    @patch("nl_gis.handlers.navigation.handle_geocode")
    @patch("services.valhalla_client.requests.post")
    @patch("services.valhalla_client._probe_port", return_value=False)
    def test_route_no_waypoints_backward_compat(self, mock_probe, mock_post, mock_geocode):
        """Route without waypoints works exactly as before."""
        import services.valhalla_client as vc
        vc._detected_url = None

        mock_geocode.side_effect = [
            {"lat": 47.6, "lon": -122.3, "display_name": "Seattle, WA"},
            {"lat": 45.5, "lon": -122.6, "display_name": "Portland, OR"},
        ]

        resp = _make_valhalla_response([
            ([(47.6, -122.3), (45.5, -122.6)], 234.0, 10800),
        ])
        mock_response = MagicMock()
        mock_response.json.return_value = resp
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = handle_find_route({
            "from_location": "Seattle",
            "to_location": "Portland",
            "profile": "driving",
        })

        assert "error" not in result
        assert result["distance_km"] == 234.0
        assert result["from_name"] == "Seattle, WA"
        assert result["to_name"] == "Portland, OR"
        # Should have route line + origin marker + dest marker = 3 features
        assert len(result["geojson"]["features"]) == 3
        assert "waypoint_names" not in result
        vc._detected_url = None

    @patch("nl_gis.handlers.navigation.handle_geocode")
    @patch("services.valhalla_client.requests.post")
    @patch("services.valhalla_client._probe_port", return_value=False)
    def test_route_with_one_coord_waypoint(self, mock_probe, mock_post, mock_geocode):
        """Route with 1 coordinate-based waypoint."""
        import services.valhalla_client as vc
        vc._detected_url = None

        mock_geocode.side_effect = [
            {"lat": 47.6, "lon": -122.3, "display_name": "Seattle, WA"},
            {"lat": 45.5, "lon": -122.6, "display_name": "Portland, OR"},
        ]

        resp = _make_valhalla_response([
            ([(47.6, -122.3), (46.5, -122.5)], 120.0, 5400),
            ([(46.5, -122.5), (45.5, -122.6)], 114.0, 5400),
        ])
        mock_response = MagicMock()
        mock_response.json.return_value = resp
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = handle_find_route({
            "from_location": "Seattle",
            "to_location": "Portland",
            "waypoints": [{"lat": 46.5, "lon": -122.5}],
            "profile": "driving",
        })

        assert "error" not in result
        assert result["distance_km"] == 234.0
        assert result["waypoint_count"] == 1
        assert result["leg_count"] == 2
        # route line + origin + dest + 1 waypoint = 4 features
        assert len(result["geojson"]["features"]) == 4
        # Check waypoint marker
        wp_features = [f for f in result["geojson"]["features"]
                       if f["properties"].get("role") == "waypoint"]
        assert len(wp_features) == 1
        assert wp_features[0]["properties"]["waypoint_index"] == 1
        vc._detected_url = None

    @patch("nl_gis.handlers.navigation.handle_geocode")
    @patch("services.valhalla_client.requests.post")
    @patch("services.valhalla_client._probe_port", return_value=False)
    def test_route_with_location_name_waypoint(self, mock_probe, mock_post, mock_geocode):
        """Route with a waypoint specified by location name (needs geocoding)."""
        import services.valhalla_client as vc
        vc._detected_url = None

        # geocode calls: origin, destination, then waypoint
        mock_geocode.side_effect = [
            {"lat": 47.6, "lon": -122.3, "display_name": "Seattle, WA"},
            {"lat": 45.5, "lon": -122.6, "display_name": "Portland, OR"},
            {"lat": 46.8, "lon": -122.7, "display_name": "Olympia, WA"},
        ]

        resp = _make_valhalla_response([
            ([(47.6, -122.3), (46.8, -122.7)], 100.0, 4500),
            ([(46.8, -122.7), (45.5, -122.6)], 170.0, 7200),
        ])
        mock_response = MagicMock()
        mock_response.json.return_value = resp
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = handle_find_route({
            "from_location": "Seattle",
            "to_location": "Portland",
            "waypoints": [{"location": "Olympia"}],
            "profile": "driving",
        })

        assert "error" not in result
        assert result["distance_km"] == 270.0
        assert result["waypoint_count"] == 1
        assert "Olympia, WA" in result["waypoint_names"]
        # Check that the waypoint marker has the geocoded coords
        wp_features = [f for f in result["geojson"]["features"]
                       if f["properties"].get("role") == "waypoint"]
        assert len(wp_features) == 1
        assert wp_features[0]["geometry"]["coordinates"] == [-122.7, 46.8]
        vc._detected_url = None

    def test_route_with_invalid_waypoint(self):
        """Waypoint with neither coords nor location returns error."""
        result = handle_find_route({
            "from_point": {"lat": 47.6, "lon": -122.3},
            "to_point": {"lat": 45.5, "lon": -122.6},
            "waypoints": [{}],
        })
        assert "error" in result
        assert "Waypoint 1" in result["error"]

    @patch("nl_gis.handlers.navigation.handle_geocode")
    def test_route_with_failed_waypoint_geocode(self, mock_geocode):
        """Waypoint geocode failure returns clear error."""
        mock_geocode.side_effect = [
            {"lat": 47.6, "lon": -122.3, "display_name": "Seattle"},
            {"lat": 45.5, "lon": -122.6, "display_name": "Portland"},
            {"error": "Not found"},
        ]

        result = handle_find_route({
            "from_location": "Seattle",
            "to_location": "Portland",
            "waypoints": [{"location": "Nowheresville"}],
        })
        assert "error" in result
        assert "waypoint" in result["error"].lower()
