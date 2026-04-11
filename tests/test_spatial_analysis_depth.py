"""Tests for Milestone 1: Spatial Analysis Depth tools.

Covers: interpolate, validate_topology, repair_topology, service_area.
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock
from nl_gis.handlers import (
    dispatch_tool,
    handle_interpolate,
    handle_validate_topology,
    handle_repair_topology,
    handle_service_area,
)


# ============================================================
# Test fixtures
# ============================================================

def _make_layer_store(layers: dict) -> dict:
    return layers


def _point_layer_with_values():
    """A layer of 5 points with numeric 'value' attribute."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
                "properties": {"value": 10, "name": "A"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1.0, 0.0]},
                "properties": {"value": 20, "name": "B"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0.0, 1.0]},
                "properties": {"value": 30, "name": "C"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
                "properties": {"value": 40, "name": "D"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0.5, 0.5]},
                "properties": {"value": 25, "name": "E"},
            },
        ],
    }


def _layer_with_valid_geoms():
    """A layer with all valid geometries."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                },
                "properties": {"name": "valid_square"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0.5, 0.5]},
                "properties": {"name": "valid_point"},
            },
        ],
    }


def _layer_with_invalid_geoms():
    """A layer with a mix of valid and invalid geometries."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                },
                "properties": {"name": "valid_square"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    # Self-intersecting bowtie polygon
                    "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]],
                },
                "properties": {"name": "bowtie"},
            },
            {
                "type": "Feature",
                "geometry": None,
                "properties": {"name": "null_geom"},
            },
        ],
    }


def _empty_layer():
    """A layer with no features."""
    return {"type": "FeatureCollection", "features": []}


# ============================================================
# Interpolation tests
# ============================================================


class TestInterpolate:
    """Tests for handle_interpolate."""

    def test_happy_path(self):
        """Interpolation of 5 points with numeric values produces contour features."""
        store = _make_layer_store({"pts": _point_layer_with_values()})
        result = handle_interpolate(
            {"layer_name": "pts", "attribute": "value", "resolution": 10, "contour_levels": 3},
            layer_store=store,
        )
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "geojson" in result
        assert result["feature_count"] >= 1
        assert result["method"] == "linear"
        assert result["attribute"] == "value"
        assert "value_range" in result
        assert result["value_range"]["min"] == 10.0
        assert result["value_range"]["max"] == 40.0

    def test_too_few_points(self):
        """Interpolation fails with fewer than 3 valid points."""
        layer = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "properties": {"value": 10},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [1, 1]},
                    "properties": {"value": 20},
                },
            ],
        }
        store = _make_layer_store({"pts": layer})
        result = handle_interpolate(
            {"layer_name": "pts", "attribute": "value"},
            layer_store=store,
        )
        assert "error" in result
        assert "at least 3" in result["error"]

    def test_non_numeric_attribute(self):
        """Interpolation fails when attribute values are not numeric."""
        layer = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [i, i]},
                    "properties": {"value": "not_a_number"},
                }
                for i in range(5)
            ],
        }
        store = _make_layer_store({"pts": layer})
        result = handle_interpolate(
            {"layer_name": "pts", "attribute": "value"},
            layer_store=store,
        )
        assert "error" in result
        assert "at least 3" in result["error"]

    def test_missing_layer(self):
        """Interpolation fails with missing layer."""
        result = handle_interpolate(
            {"layer_name": "nonexistent", "attribute": "value"},
            layer_store={},
        )
        assert "error" in result

    def test_missing_attribute_param(self):
        """Interpolation fails without attribute parameter."""
        store = _make_layer_store({"pts": _point_layer_with_values()})
        result = handle_interpolate(
            {"layer_name": "pts"},
            layer_store=store,
        )
        assert "error" in result
        assert "attribute" in result["error"]

    def test_invalid_method(self):
        """Interpolation fails with invalid method."""
        store = _make_layer_store({"pts": _point_layer_with_values()})
        result = handle_interpolate(
            {"layer_name": "pts", "attribute": "value", "method": "spline"},
            layer_store=store,
        )
        assert "error" in result
        assert "Invalid method" in result["error"]

    def test_dispatch_interpolate(self):
        """Interpolate is accessible via dispatch_tool."""
        store = _make_layer_store({"pts": _point_layer_with_values()})
        result = dispatch_tool(
            "interpolate",
            {"layer_name": "pts", "attribute": "value", "resolution": 10, "contour_levels": 3},
            layer_store=store,
        )
        assert "error" not in result


# ============================================================
# Topology validation tests
# ============================================================


class TestValidateTopology:
    """Tests for handle_validate_topology."""

    def test_all_valid(self):
        """All-valid layer reports zero invalid."""
        store = _make_layer_store({"valid": _layer_with_valid_geoms()})
        result = handle_validate_topology(
            {"layer_name": "valid"},
            layer_store=store,
        )
        assert "error" not in result
        assert result["valid_count"] == 2
        assert result["invalid_count"] == 0
        assert result["errors"] == []

    def test_mixed_validity(self):
        """Layer with invalid geometries reports correct counts and errors."""
        store = _make_layer_store({"mixed": _layer_with_invalid_geoms()})
        result = handle_validate_topology(
            {"layer_name": "mixed"},
            layer_store=store,
        )
        assert "error" not in result
        assert result["valid_count"] >= 1
        assert result["invalid_count"] >= 1
        assert len(result["errors"]) >= 1
        # Check error structure
        err = result["errors"][0]
        assert "index" in err
        assert "error_type" in err
        assert "explanation" in err

    def test_empty_layer(self):
        """Empty layer returns error."""
        store = _make_layer_store({"empty": _empty_layer()})
        result = handle_validate_topology(
            {"layer_name": "empty"},
            layer_store=store,
        )
        assert "error" in result

    def test_missing_layer(self):
        """Missing layer returns error."""
        result = handle_validate_topology(
            {"layer_name": "nonexistent"},
            layer_store={},
        )
        assert "error" in result

    def test_dispatch_validate_topology(self):
        """validate_topology is accessible via dispatch_tool."""
        store = _make_layer_store({"valid": _layer_with_valid_geoms()})
        result = dispatch_tool(
            "validate_topology",
            {"layer_name": "valid"},
            layer_store=store,
        )
        assert "error" not in result


# ============================================================
# Topology repair tests
# ============================================================


class TestRepairTopology:
    """Tests for handle_repair_topology."""

    def test_repair_invalid(self):
        """Repairing invalid geometries produces valid output."""
        store = _make_layer_store({"mixed": _layer_with_invalid_geoms()})
        result = handle_repair_topology(
            {"layer_name": "mixed"},
            layer_store=store,
        )
        assert "error" not in result
        assert "geojson" in result
        assert result["repaired_count"] >= 1
        assert result["already_valid_count"] >= 1
        assert result["layer_name"] == "repaired_mixed"

    def test_all_valid_layer(self):
        """Repairing an all-valid layer reports zero repairs."""
        store = _make_layer_store({"valid": _layer_with_valid_geoms()})
        result = handle_repair_topology(
            {"layer_name": "valid"},
            layer_store=store,
        )
        assert "error" not in result
        assert result["repaired_count"] == 0
        assert result["already_valid_count"] == 2

    def test_empty_layer(self):
        """Empty layer returns error."""
        store = _make_layer_store({"empty": _empty_layer()})
        result = handle_repair_topology(
            {"layer_name": "empty"},
            layer_store=store,
        )
        assert "error" in result

    def test_custom_output_name(self):
        """Custom output_name is respected."""
        store = _make_layer_store({"valid": _layer_with_valid_geoms()})
        result = handle_repair_topology(
            {"layer_name": "valid", "output_name": "my_clean_layer"},
            layer_store=store,
        )
        assert result["layer_name"] == "my_clean_layer"

    def test_dispatch_repair_topology(self):
        """repair_topology is accessible via dispatch_tool."""
        store = _make_layer_store({"mixed": _layer_with_invalid_geoms()})
        result = dispatch_tool(
            "repair_topology",
            {"layer_name": "mixed"},
            layer_store=store,
        )
        assert "error" not in result
        assert "geojson" in result


# ============================================================
# Service area tests
# ============================================================


class TestServiceArea:
    """Tests for handle_service_area."""

    def _mock_isochrone_response(self, lon, lat, **kwargs):
        """Return a simple isochrone polygon around the given point."""
        offset = 0.01
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [lon - offset, lat - offset],
                                [lon + offset, lat - offset],
                                [lon + offset, lat + offset],
                                [lon - offset, lat + offset],
                                [lon - offset, lat - offset],
                            ]
                        ],
                    },
                    "properties": {},
                }
            ],
        }

    @patch("services.valhalla_client.get_isochrone")
    def test_single_facility(self, mock_iso):
        """Single facility produces a coverage polygon."""
        mock_iso.side_effect = lambda lon, lat, **kw: self._mock_isochrone_response(lon, lat)
        result = handle_service_area(
            {
                "facilities": [{"lat": 40.7, "lon": -74.0}],
                "time_minutes": 15,
            },
        )
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "geojson" in result
        assert result["facility_count"] == 1
        assert result["coverage_area_sq_km"] > 0
        # Check coverage feature exists
        coverage_feats = [
            f for f in result["geojson"]["features"]
            if f["properties"].get("type") == "coverage"
        ]
        assert len(coverage_feats) == 1

    @patch("services.valhalla_client.get_isochrone")
    def test_multiple_facilities(self, mock_iso):
        """Multiple facilities produce a unioned coverage polygon."""
        mock_iso.side_effect = lambda lon, lat, **kw: self._mock_isochrone_response(lon, lat)
        result = handle_service_area(
            {
                "facilities": [
                    {"lat": 40.7, "lon": -74.0},
                    {"lat": 40.8, "lon": -73.9},
                ],
                "time_minutes": 10,
            },
        )
        assert "error" not in result
        assert result["facility_count"] == 2

    @patch("services.valhalla_client.get_isochrone")
    def test_show_gaps(self, mock_iso):
        """show_gaps=True includes gap polygons in the result."""
        mock_iso.side_effect = lambda lon, lat, **kw: self._mock_isochrone_response(lon, lat)
        result = handle_service_area(
            {
                "facilities": [{"lat": 40.7, "lon": -74.0}],
                "time_minutes": 15,
                "show_gaps": True,
            },
        )
        assert "error" not in result
        gap_feats = [
            f for f in result["geojson"]["features"]
            if f["properties"].get("type") == "gap"
        ]
        assert len(gap_feats) == 1
        assert "gap_area_sq_km" in result

    def test_missing_time_and_distance(self):
        """Service area fails without time_minutes or distance_m."""
        result = handle_service_area(
            {"facilities": [{"lat": 40.7, "lon": -74.0}]},
        )
        assert "error" in result
        assert "time_minutes" in result["error"] or "distance_m" in result["error"]

    def test_no_facilities(self):
        """Service area fails with no facilities."""
        result = handle_service_area(
            {"time_minutes": 15},
        )
        assert "error" in result
        assert "facility" in result["error"].lower()

    @patch("services.valhalla_client.get_isochrone")
    def test_facility_layer(self, mock_iso):
        """Service area accepts a facility_layer."""
        mock_iso.side_effect = lambda lon, lat, **kw: self._mock_isochrone_response(lon, lat)
        facility_layer = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-74.0, 40.7]},
                    "properties": {"name": "Station 1"},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-73.9, 40.8]},
                    "properties": {"name": "Station 2"},
                },
            ],
        }
        store = _make_layer_store({"stations": facility_layer})
        result = handle_service_area(
            {"facility_layer": "stations", "time_minutes": 10},
            layer_store=store,
        )
        assert "error" not in result
        assert result["facility_count"] == 2

    def test_dispatch_service_area(self):
        """service_area is accessible via dispatch_tool."""
        with patch("services.valhalla_client.get_isochrone") as mock_iso:
            mock_iso.side_effect = lambda lon, lat, **kw: self._mock_isochrone_response(lon, lat)
            result = dispatch_tool(
                "service_area",
                {
                    "facilities": [{"lat": 40.7, "lon": -74.0}],
                    "time_minutes": 15,
                },
                layer_store={},
            )
            assert "error" not in result


# ============================================================
# Schema registration tests
# ============================================================


class TestSchemaRegistration:
    """Verify tool schemas are properly registered."""

    def test_new_tool_schemas_exist(self):
        """All new tools have schema definitions in get_tool_definitions."""
        from nl_gis.tools import get_tool_definitions
        tools = get_tool_definitions()
        tool_names = {t["name"] for t in tools}
        for name in ("interpolate", "validate_topology", "repair_topology", "service_area"):
            assert name in tool_names, f"Tool '{name}' not found in tool definitions"

    def test_new_tools_in_dispatch(self):
        """All new tools are registered in dispatch_tool."""
        for name in ("interpolate", "validate_topology", "repair_topology", "service_area"):
            # Should not raise ValueError
            try:
                dispatch_tool(name, {}, layer_store={})
            except ValueError:
                pytest.fail(f"Tool '{name}' not registered in dispatch_tool")
            except Exception:
                pass  # Other errors are fine (missing params etc.)
