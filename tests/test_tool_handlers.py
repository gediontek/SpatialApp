"""Tests for nl_gis.tool_handlers module."""

import json
import pytest
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl_gis.tool_handlers import (
    dispatch_tool,
    handle_geocode,
    handle_fetch_osm,
    handle_map_command,
    handle_calculate_area,
    handle_measure_distance,
)


class TestDispatchTool:
    """Tests for tool dispatch routing."""

    def test_unknown_tool(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            dispatch_tool("nonexistent_tool", {})

    def test_dispatch_geocode(self):
        with patch("nl_gis.handlers.handle_geocode") as mock:
            mock.return_value = {"lat": 47.6, "lon": -122.3}
            result = dispatch_tool("geocode", {"query": "Seattle"})
            mock.assert_called_once_with({"query": "Seattle"})

    def test_dispatch_map_command(self):
        result = dispatch_tool("map_command", {"action": "zoom", "zoom": 15})
        assert result["success"] is True


class TestHandleGeocode:
    """Tests for geocode handler."""

    def test_empty_query(self):
        result = handle_geocode({"query": ""})
        assert "error" in result

    def test_no_query(self):
        result = handle_geocode({})
        assert "error" in result

    @patch("nl_gis.handlers.navigation.geocode_cache")
    @patch("nl_gis.handlers.navigation.requests.get")
    def test_successful_geocode(self, mock_get, mock_cache):
        mock_cache.get.return_value = None  # Bypass cache
        mock_response = MagicMock()
        mock_response.json.return_value = [{
            "lat": "47.6062",
            "lon": "-122.3321",
            "display_name": "Seattle, King County, Washington, USA",
            "boundingbox": ["47.4", "47.8", "-122.5", "-122.2"]
        }]
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = handle_geocode({"query": "Seattle"})
        assert result["lat"] == 47.6062
        assert result["lon"] == -122.3321
        assert "Seattle" in result["display_name"]
        assert result["bbox"] is not None

    @patch("nl_gis.handlers.navigation.requests.get")
    def test_location_not_found(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = handle_geocode({"query": "xyznonexistent"})
        assert "error" in result
        assert "not found" in result["error"].lower()


class TestHandleMapCommand:
    """Tests for map command handler."""

    def test_pan(self):
        result = handle_map_command({"action": "pan", "lat": 47.6, "lon": -122.3})
        assert result["success"] is True
        assert result["action"] == "pan"
        assert result["lat"] == 47.6

    def test_pan_missing_coords(self):
        result = handle_map_command({"action": "pan"})
        assert "error" in result

    def test_zoom(self):
        result = handle_map_command({"action": "zoom", "zoom": 15})
        assert result["success"] is True
        assert result["zoom"] == 15

    def test_zoom_clamped(self):
        result = handle_map_command({"action": "zoom", "zoom": 25})
        assert result["zoom"] == 20

    def test_zoom_missing(self):
        result = handle_map_command({"action": "zoom"})
        assert "error" in result

    def test_pan_and_zoom(self):
        result = handle_map_command({
            "action": "pan_and_zoom", "lat": 47.6, "lon": -122.3, "zoom": 14
        })
        assert result["success"] is True
        assert result["lat"] == 47.6
        assert result["zoom"] == 14

    def test_fit_bounds(self):
        result = handle_map_command({
            "action": "fit_bounds", "bbox": [47.5, -122.5, 47.7, -122.3]
        })
        assert result["success"] is True
        assert result["bbox"] == [47.5, -122.5, 47.7, -122.3]

    def test_fit_bounds_invalid(self):
        result = handle_map_command({"action": "fit_bounds", "bbox": [1, 2]})
        assert "error" in result

    def test_change_basemap_osm(self):
        result = handle_map_command({"action": "change_basemap", "basemap": "osm"})
        assert result["success"] is True
        assert result["basemap"] == "osm"

    def test_change_basemap_satellite(self):
        result = handle_map_command({"action": "change_basemap", "basemap": "satellite"})
        assert result["basemap"] == "satellite"

    def test_change_basemap_invalid(self):
        result = handle_map_command({"action": "change_basemap", "basemap": "terrain"})
        assert "error" in result

    def test_unknown_action(self):
        result = handle_map_command({"action": "invalid"})
        assert "error" in result


class TestHandleCalculateArea:
    """Tests for area calculation handler."""

    def test_no_input(self):
        result = handle_calculate_area({})
        assert "error" in result

    def test_geometry_input(self):
        """Calculate area of a known polygon."""
        # ~1 degree box near equator
        geometry = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
        }
        result = handle_calculate_area({"geometry": geometry})
        assert "error" not in result
        assert result["total_area_sq_km"] > 12000
        assert result["total_area_sq_km"] < 12500
        assert result["feature_count"] == 1

    def test_layer_store_lookup(self):
        """Calculate area from layer store."""
        layer_store = {
            "test_layer": {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[-122.35, 47.6], [-122.35, 47.61],
                                         [-122.34, 47.61], [-122.34, 47.6],
                                         [-122.35, 47.6]]]
                    },
                    "properties": {}
                }]
            }
        }
        result = handle_calculate_area({"layer_name": "test_layer"}, layer_store)
        assert "error" not in result
        assert result["total_area_sq_m"] > 0
        assert result["feature_count"] == 1

    def test_layer_not_found(self):
        result = handle_calculate_area({"layer_name": "nonexistent"}, {})
        assert "error" in result

    def test_non_polygon_geometry(self):
        """Point geometry should return error."""
        geometry = {"type": "Point", "coordinates": [0, 0]}
        result = handle_calculate_area({"geometry": geometry})
        assert "error" in result


class TestHandleMeasureDistance:
    """Tests for distance measurement handler."""

    def test_coordinate_points(self):
        """Measure distance with explicit coordinates."""
        result = handle_measure_distance({
            "from_point": {"lat": 47.6062, "lon": -122.3321},
            "to_point": {"lat": 45.5152, "lon": -122.6784},
        })
        assert "error" not in result
        assert 230 < result["distance_km"] < 240  # Seattle to Portland
        assert result["distance_mi"] > 0
        assert result["distance_m"] > 0

    def test_no_from(self):
        result = handle_measure_distance({
            "to_point": {"lat": 45.5, "lon": -122.6}
        })
        assert "error" in result

    def test_no_to(self):
        result = handle_measure_distance({
            "from_point": {"lat": 47.6, "lon": -122.3}
        })
        assert "error" in result

    @patch("nl_gis.handlers.navigation.handle_geocode")
    def test_location_names(self, mock_geocode):
        """Measure distance using place names."""
        mock_geocode.side_effect = [
            {"lat": 47.6062, "lon": -122.3321, "display_name": "Seattle, WA"},
            {"lat": 45.5152, "lon": -122.6784, "display_name": "Portland, OR"},
        ]
        result = handle_measure_distance({
            "from_location": "Seattle",
            "to_location": "Portland",
        })
        assert "error" not in result
        assert 230 < result["distance_km"] < 240
        assert result["from_name"] == "Seattle, WA"
        assert result["to_name"] == "Portland, OR"

    @patch("nl_gis.handlers.navigation.handle_geocode")
    def test_geocode_failure(self, mock_geocode):
        mock_geocode.return_value = {"error": "Location not found"}
        result = handle_measure_distance({
            "from_location": "nonexistent",
            "to_location": "Portland",
        })
        assert "error" in result


class TestHandleFetchOSM:
    """Tests for OSM fetch handler (validation only, no network)."""

    def test_invalid_feature_type(self):
        result = handle_fetch_osm({
            "feature_type": "invalid_type",
            "category_name": "test",
            "bbox": "47.5,-122.5,47.7,-122.3",
        })
        assert "error" in result
        assert "Unknown feature type" in result["error"]

    def test_no_bbox_no_location(self):
        result = handle_fetch_osm({
            "feature_type": "building",
            "category_name": "test",
        })
        assert "error" in result

    @patch("nl_gis.handlers.navigation.requests.get")
    def test_successful_fetch(self, mock_get):
        """Test with mocked Overpass response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "elements": [
                {"type": "node", "id": 1, "lat": 47.6, "lon": -122.3},
                {"type": "node", "id": 2, "lat": 47.61, "lon": -122.3},
                {"type": "node", "id": 3, "lat": 47.61, "lon": -122.29},
                {"type": "node", "id": 4, "lat": 47.6, "lon": -122.29},
                {
                    "type": "way",
                    "id": 100,
                    "nodes": [1, 2, 3, 4, 1],
                    "tags": {"building": "yes"},
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = handle_fetch_osm({
            "feature_type": "building",
            "category_name": "test_buildings",
            "bbox": "47.5,-122.5,47.7,-122.3",
        })
        assert "error" not in result
        assert result["feature_count"] == 1
        assert result["layer_name"] == "building_test_buildings"
        geojson = result["geojson"]
        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) == 1

    @patch("nl_gis.handlers.navigation.requests.get")
    def test_timeout(self, mock_get):
        import requests as req
        from services.cache import overpass_cache
        overpass_cache.clear()
        mock_get.side_effect = req.Timeout("timed out")
        result = handle_fetch_osm({
            "feature_type": "building",
            "category_name": "test",
            "bbox": "47.5,-122.5,47.7,-122.3",
        })
        assert "error" in result
        assert "timed out" in result["error"].lower()
