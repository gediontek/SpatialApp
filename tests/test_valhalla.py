"""Tests for services.valhalla_client module."""

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.valhalla_client import (
    _decode_polyline6,
    get_route,
    get_isochrone,
    detect_valhalla_url,
    reset_detection,
    PUBLIC_VALHALLA,
    LOCAL_VALHALLA,
)


class TestDecodePolyline6:
    """Tests for polyline6 decoding."""

    def test_basic_decode(self):
        """Decode a known polyline6 string."""
        import polyline
        # Encode a known set of coords at precision 6
        coords = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
        encoded = polyline.encode(coords, 6)

        result = _decode_polyline6(encoded)
        # Result should be [lon, lat] for GeoJSON
        assert len(result) == 3
        assert abs(result[0][0] - (-120.2)) < 0.001  # lon
        assert abs(result[0][1] - 38.5) < 0.001  # lat

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Invalid polyline"):
            _decode_polyline6("")

    def test_none_raises(self):
        with pytest.raises(ValueError, match="Invalid polyline"):
            _decode_polyline6(None)

    def test_non_string_raises(self):
        with pytest.raises(ValueError, match="Invalid polyline"):
            _decode_polyline6(12345)


class TestCacheKeyGeneration:
    """Test that cache keys are deterministic and unique."""

    def test_route_cache_key_format(self):
        """Route cache keys should encode origin, dest, and costing."""
        # This tests indirectly by checking the get_route function builds
        # consistent keys — we just verify the format by calling with mocked cache
        with patch("services.valhalla_client.valhalla_cache") as mock_cache:
            mock_cache.get.return_value = {"cached": True}  # Force cache hit
            with patch("services.valhalla_client.detect_valhalla_url", return_value=LOCAL_VALHALLA):
                result = get_route(-122.33, 47.60, -122.68, 45.51, "driving")

            # Verify cache.get was called with a deterministic key
            call_args = mock_cache.get.call_args[0][0]
            assert call_args.startswith("route:")
            assert "auto" in call_args  # costing for 'driving'
            assert result == {"cached": True}


class TestGetRoute:
    """Tests for get_route with mocked HTTP."""

    @patch("services.valhalla_client.valhalla_cache")
    @patch("services.valhalla_client.detect_valhalla_url", return_value=LOCAL_VALHALLA)
    @patch("services.valhalla_client.requests.post")
    def test_successful_route(self, mock_post, mock_detect, mock_cache):
        mock_cache.get.return_value = None  # No cache hit

        import polyline
        coords = [(47.6, -122.33), (45.51, -122.68)]
        encoded = polyline.encode(coords, 6)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "trip": {
                "legs": [{
                    "shape": encoded,
                    "summary": {"length": 278.5, "time": 10200},
                    "maneuvers": [
                        {"instruction": "Go north", "type": 1, "length": 100, "time": 3600, "street_names": ["I-5"]},
                    ],
                }],
                "summary": {"length": 278.5, "time": 10200},
            }
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = get_route(-122.33, 47.6, -122.68, 45.51, "driving")
        assert result is not None
        assert result["distance_km"] == 278.5
        assert result["duration_min"] == round(10200 / 60, 1)
        assert result["geometry"]["type"] == "LineString"
        assert len(result["geometry"]["coordinates"]) == 2
        assert result["steps"][0]["instruction"] == "Go north"

    @patch("services.valhalla_client.valhalla_cache")
    @patch("services.valhalla_client.detect_valhalla_url", return_value=LOCAL_VALHALLA)
    @patch("services.valhalla_client.requests.post")
    def test_route_timeout(self, mock_post, mock_detect, mock_cache):
        import requests as req
        mock_cache.get.return_value = None
        mock_post.side_effect = req.Timeout("timed out")

        result = get_route(-122.33, 47.6, -122.68, 45.51)
        assert result is None

    @patch("services.valhalla_client.valhalla_cache")
    @patch("services.valhalla_client.detect_valhalla_url", return_value=LOCAL_VALHALLA)
    @patch("services.valhalla_client.requests.post")
    def test_route_connection_error(self, mock_post, mock_detect, mock_cache):
        import requests as req
        mock_cache.get.return_value = None
        mock_post.side_effect = req.ConnectionError("refused")

        result = get_route(-122.33, 47.6, -122.68, 45.51)
        assert result is None

    @patch("services.valhalla_client.valhalla_cache")
    @patch("services.valhalla_client.detect_valhalla_url", return_value=LOCAL_VALHALLA)
    @patch("services.valhalla_client.requests.post")
    def test_route_no_trip(self, mock_post, mock_detect, mock_cache):
        mock_cache.get.return_value = None
        mock_response = MagicMock()
        mock_response.json.return_value = {"trip": None}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = get_route(-122.33, 47.6, -122.68, 45.51)
        assert result is None


class TestGetIsochrone:
    """Tests for get_isochrone with mocked HTTP."""

    @patch("services.valhalla_client.valhalla_cache")
    @patch("services.valhalla_client.detect_valhalla_url", return_value=LOCAL_VALHALLA)
    @patch("services.valhalla_client.requests.post")
    def test_successful_isochrone(self, mock_post, mock_detect, mock_cache):
        mock_cache.get.return_value = None

        iso_geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-122.3, 47.5], [-122.4, 47.6], [-122.3, 47.7], [-122.3, 47.5]]],
                },
                "properties": {"contour": 15},
            }],
        }

        mock_response = MagicMock()
        mock_response.json.return_value = iso_geojson
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = get_isochrone(-122.33, 47.6, time_minutes=15, profile="driving")
        assert result is not None
        assert result["type"] == "FeatureCollection"
        assert len(result["features"]) == 1

    @patch("services.valhalla_client.valhalla_cache")
    @patch("services.valhalla_client.detect_valhalla_url", return_value=LOCAL_VALHALLA)
    @patch("services.valhalla_client.requests.post")
    def test_isochrone_timeout(self, mock_post, mock_detect, mock_cache):
        import requests as req
        mock_cache.get.return_value = None
        mock_post.side_effect = req.Timeout("timed out")

        result = get_isochrone(-122.33, 47.6, time_minutes=15)
        assert result is None

    def test_isochrone_no_contour(self):
        """Must provide either time_minutes or distance_km."""
        result = get_isochrone(-122.33, 47.6)
        assert result is None

    @patch("services.valhalla_client.valhalla_cache")
    @patch("services.valhalla_client.detect_valhalla_url", return_value=LOCAL_VALHALLA)
    @patch("services.valhalla_client.requests.post")
    def test_isochrone_bad_format(self, mock_post, mock_detect, mock_cache):
        mock_cache.get.return_value = None
        mock_response = MagicMock()
        mock_response.json.return_value = {"type": "unexpected"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = get_isochrone(-122.33, 47.6, time_minutes=15)
        assert result is None


class TestDetectValhallaURL:
    """Tests for detect_valhalla_url with mocked probing."""

    def setup_method(self):
        """Reset detection cache before each test."""
        reset_detection()

    @patch("services.valhalla_client._probe_port", return_value=True)
    def test_local_instance_detected(self, mock_probe):
        url = detect_valhalla_url()
        assert url == LOCAL_VALHALLA
        mock_probe.assert_called_once_with("localhost", 8002)

    @patch("services.valhalla_client._probe_port", return_value=False)
    def test_falls_back_to_public(self, mock_probe):
        url = detect_valhalla_url()
        assert url == PUBLIC_VALHALLA

    @patch("services.valhalla_client._probe_port", return_value=True)
    def test_detection_cached(self, mock_probe):
        url1 = detect_valhalla_url()
        url2 = detect_valhalla_url()
        assert url1 == url2
        # Should only probe once due to TTL cache
        assert mock_probe.call_count == 1

    @patch("services.valhalla_client._probe_port", return_value=True)
    def test_reset_forces_reprobe(self, mock_probe):
        detect_valhalla_url()
        reset_detection()
        detect_valhalla_url()
        assert mock_probe.call_count == 2


class TestFallbackWhenValhallaDown:
    """Test behavior when Valhalla is completely unreachable."""

    @patch("services.valhalla_client.valhalla_cache")
    @patch("services.valhalla_client._probe_port", return_value=False)
    @patch("services.valhalla_client.requests.post")
    @patch("services.valhalla_client.valhalla_limiter")
    def test_route_returns_none_on_failure(self, mock_limiter, mock_post, mock_probe, mock_cache):
        import requests as req
        reset_detection()
        mock_cache.get.return_value = None
        mock_post.side_effect = req.ConnectionError("Connection refused")

        result = get_route(-122.33, 47.6, -122.68, 45.51)
        assert result is None

    @patch("services.valhalla_client.valhalla_cache")
    @patch("services.valhalla_client._probe_port", return_value=False)
    @patch("services.valhalla_client.requests.post")
    @patch("services.valhalla_client.valhalla_limiter")
    def test_isochrone_returns_none_on_failure(self, mock_limiter, mock_post, mock_probe, mock_cache):
        import requests as req
        reset_detection()
        mock_cache.get.return_value = None
        mock_post.side_effect = req.ConnectionError("Connection refused")

        result = get_isochrone(-122.33, 47.6, time_minutes=15)
        assert result is None
