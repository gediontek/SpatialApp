"""Tests for reverse_geocode and batch_geocode handlers."""

import pytest
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl_gis.handlers import dispatch_tool
from nl_gis.handlers.navigation import handle_reverse_geocode, handle_batch_geocode


class TestReverseGeocode:
    """Tests for reverse_geocode handler."""

    def test_missing_lat(self):
        result = handle_reverse_geocode({"lon": -122.3})
        assert "error" in result
        assert "lat and lon are required" in result["error"]

    def test_missing_lon(self):
        result = handle_reverse_geocode({"lat": 47.6})
        assert "error" in result
        assert "lat and lon are required" in result["error"]

    def test_missing_both(self):
        result = handle_reverse_geocode({})
        assert "error" in result

    def test_invalid_lat_type(self):
        result = handle_reverse_geocode({"lat": "not_a_number", "lon": -122.3})
        assert "error" in result
        assert "must be numbers" in result["error"]

    def test_invalid_coordinates_out_of_range(self):
        result = handle_reverse_geocode({"lat": 100, "lon": -122.3})
        assert "error" in result
        assert "Invalid coordinates" in result["error"]

    def test_invalid_lon_out_of_range(self):
        result = handle_reverse_geocode({"lat": 47.6, "lon": 200})
        assert "error" in result
        assert "Invalid coordinates" in result["error"]

    @patch("nl_gis.handlers.navigation.geocode_cache")
    @patch("nl_gis.handlers.navigation.requests.get")
    def test_successful_reverse_geocode(self, mock_get, mock_cache):
        mock_cache.get.return_value = None
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "display_name": "White House, 1600, Pennsylvania Avenue NW, Washington, DC",
            "address": {
                "building": "White House",
                "house_number": "1600",
                "road": "Pennsylvania Avenue NW",
                "city": "Washington",
                "state": "District of Columbia",
            },
            "osm_type": "way",
            "osm_id": 238241022,
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = handle_reverse_geocode({"lat": 38.8977, "lon": -77.0365})
        assert "error" not in result
        assert result["display_name"] == "White House, 1600, Pennsylvania Avenue NW, Washington, DC"
        assert result["lat"] == 38.8977
        assert result["lon"] == -77.0365
        assert result["osm_type"] == "way"
        assert "address" in result
        # Should cache the result
        mock_cache.set.assert_called_once()

    @patch("nl_gis.handlers.navigation.geocode_cache")
    def test_cache_hit(self, mock_cache):
        cached_data = {
            "display_name": "Cached Location",
            "address": {},
            "lat": 47.6,
            "lon": -122.3,
            "osm_type": "node",
            "osm_id": 12345,
        }
        mock_cache.get.return_value = cached_data

        result = handle_reverse_geocode({"lat": 47.6, "lon": -122.3})
        assert result == cached_data

    @patch("nl_gis.handlers.navigation.geocode_cache")
    @patch("nl_gis.handlers.navigation.requests.get")
    def test_no_result_found(self, mock_get, mock_cache):
        mock_cache.get.return_value = None
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": "Unable to geocode"}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = handle_reverse_geocode({"lat": 0.0, "lon": 0.0})
        assert "error" in result
        assert "No result found" in result["error"]

    @patch("nl_gis.handlers.navigation.geocode_cache")
    @patch("nl_gis.handlers.navigation.requests.get")
    def test_network_error(self, mock_get, mock_cache):
        mock_cache.get.return_value = None
        mock_get.side_effect = Exception("Connection timeout")

        result = handle_reverse_geocode({"lat": 47.6, "lon": -122.3})
        assert "error" in result
        assert "Reverse geocoding failed" in result["error"]

    def test_dispatch_reverse_geocode(self):
        """Test that reverse_geocode is registered in dispatch_tool."""
        with patch("nl_gis.handlers.handle_reverse_geocode") as mock:
            mock.return_value = {"display_name": "Test", "lat": 47.6, "lon": -122.3}
            result = dispatch_tool("reverse_geocode", {"lat": 47.6, "lon": -122.3})
            mock.assert_called_once_with({"lat": 47.6, "lon": -122.3})


class TestBatchGeocode:
    """Tests for batch_geocode handler."""

    def test_empty_addresses(self):
        result = handle_batch_geocode({"addresses": []})
        assert "error" in result
        assert "addresses list is required" in result["error"]

    def test_missing_addresses(self):
        result = handle_batch_geocode({})
        assert "error" in result
        assert "addresses list is required" in result["error"]

    def test_too_many_addresses(self):
        addresses = [f"Address {i}" for i in range(51)]
        result = handle_batch_geocode({"addresses": addresses})
        assert "error" in result
        assert "Maximum 50" in result["error"]

    @patch("nl_gis.handlers.navigation.handle_geocode")
    def test_successful_batch(self, mock_geocode):
        mock_geocode.side_effect = [
            {"lat": 47.6, "lon": -122.3, "display_name": "Seattle, WA"},
            {"lat": 45.5, "lon": -122.7, "display_name": "Portland, OR"},
        ]

        result = handle_batch_geocode({
            "addresses": ["Seattle, WA", "Portland, OR"],
            "layer_name": "my_points",
        })
        assert "error" not in result
        assert result["geocoded"] == 2
        assert result["total"] == 2
        assert result["failed"] == []
        assert result["layer_name"] == "my_points"
        assert result["geojson"]["type"] == "FeatureCollection"
        assert len(result["geojson"]["features"]) == 2

        # Check GeoJSON structure
        feat = result["geojson"]["features"][0]
        assert feat["type"] == "Feature"
        assert feat["geometry"]["type"] == "Point"
        assert feat["geometry"]["coordinates"] == [-122.3, 47.6]  # [lon, lat]
        assert feat["properties"]["address"] == "Seattle, WA"

    @patch("nl_gis.handlers.navigation.handle_geocode")
    def test_partial_failures(self, mock_geocode):
        mock_geocode.side_effect = [
            {"lat": 47.6, "lon": -122.3, "display_name": "Seattle, WA"},
            {"error": "Location not found: Nowhereville"},
            {"lat": 45.5, "lon": -122.7, "display_name": "Portland, OR"},
        ]

        result = handle_batch_geocode({
            "addresses": ["Seattle, WA", "Nowhereville", "Portland, OR"],
        })
        assert "error" not in result
        assert result["geocoded"] == 2
        assert result["total"] == 3
        assert result["failed"] == ["Nowhereville"]
        assert len(result["geojson"]["features"]) == 2

    @patch("nl_gis.handlers.navigation.handle_geocode")
    def test_all_failures(self, mock_geocode):
        mock_geocode.return_value = {"error": "Location not found"}

        result = handle_batch_geocode({
            "addresses": ["Nowhere1", "Nowhere2"],
        })
        assert "error" not in result  # Not an error — just empty results
        assert result["geocoded"] == 0
        assert result["total"] == 2
        assert len(result["failed"]) == 2
        assert result["geojson"]["features"] == []

    @patch("nl_gis.handlers.navigation.handle_geocode")
    def test_default_layer_name(self, mock_geocode):
        mock_geocode.return_value = {"lat": 47.6, "lon": -122.3, "display_name": "Seattle"}

        result = handle_batch_geocode({"addresses": ["Seattle"]})
        assert result["layer_name"] == "geocoded_points"

    def test_dispatch_batch_geocode(self):
        """Test that batch_geocode is registered in dispatch_tool."""
        with patch("nl_gis.handlers.handle_batch_geocode") as mock:
            mock.return_value = {"geojson": {}, "layer_name": "test", "geocoded": 0, "failed": [], "total": 0}
            result = dispatch_tool("batch_geocode", {"addresses": ["Seattle"]})
            mock.assert_called_once()

    def test_batch_geocode_in_layer_producing_tools(self):
        """batch_geocode should be in LAYER_PRODUCING_TOOLS."""
        from nl_gis.handlers import LAYER_PRODUCING_TOOLS
        assert "batch_geocode" in LAYER_PRODUCING_TOOLS

    def test_reverse_geocode_not_in_layer_producing_tools(self):
        """reverse_geocode is query-only — should NOT be in LAYER_PRODUCING_TOOLS."""
        from nl_gis.handlers import LAYER_PRODUCING_TOOLS
        assert "reverse_geocode" not in LAYER_PRODUCING_TOOLS
