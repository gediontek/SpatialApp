"""Tests for v2.1 Plan 10: data pipeline tools + validation."""

from __future__ import annotations

import base64
import json

import pytest

from nl_gis.handlers import dispatch_tool
from nl_gis.handlers.analysis import handle_clip_to_bbox, handle_generalize
from nl_gis.handlers.layers import (
    _detect_format,
    handle_export_gpkg,
    handle_import_auto,
)
from nl_gis.validation import validate_geojson


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fc(features: list) -> dict:
    return {"type": "FeatureCollection", "features": features}


def _point_feature(lat, lon, **props):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }


def _poly_feature(ring, **props):
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": props,
    }


# ---------------------------------------------------------------------------
# validate_geojson
# ---------------------------------------------------------------------------


class TestValidateGeoJSON:
    def test_valid_collection(self):
        fc = _fc([_point_feature(40.7, -74.0, name="A")])
        rep = validate_geojson(fc)
        assert rep["valid"] is True
        assert rep["stats"]["valid_geom"] == 1
        assert rep["stats"]["invalid_geom"] == 0

    def test_self_intersecting_polygon_repaired(self):
        # Bowtie polygon — classic self-intersection
        ring = [[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]
        fc = _fc([_poly_feature(ring)])
        rep = validate_geojson(fc, auto_repair=True)
        assert rep["valid"] is True
        assert rep["stats"]["repaired"] >= 1
        assert any("repaired" in w.lower() for w in rep["warnings"])

    def test_null_geometry_dropped_when_repairing(self):
        fc = _fc([
            {"type": "Feature", "geometry": None, "properties": {}},
            _point_feature(0, 0),
        ])
        rep = validate_geojson(fc, auto_repair=True)
        assert rep["stats"]["null_geom"] == 1
        assert rep["stats"]["valid_geom"] == 1

    def test_duplicate_features_dropped_when_repairing(self):
        fc = _fc([_point_feature(0, 0), _point_feature(0, 0), _point_feature(1, 1)])
        rep = validate_geojson(fc, auto_repair=True)
        assert rep["stats"]["duplicates"] == 1
        assert rep["stats"]["valid_geom"] == 2

    def test_non_featurecollection_rejected(self):
        rep = validate_geojson({"type": "Other", "features": []})
        assert rep["valid"] is False
        assert rep["errors"]

    def test_non_dict_rejected(self):
        rep = validate_geojson("not a dict")
        assert rep["valid"] is False


# ---------------------------------------------------------------------------
# _detect_format
# ---------------------------------------------------------------------------


class TestDetectFormat:
    def test_geojson_starts_with_brace(self):
        assert _detect_format('{"type": "FeatureCollection", "features": []}') == "geojson"

    def test_kml_detected_from_xml_prolog(self):
        assert _detect_format('<?xml version="1.0"?><kml>...</kml>') == "kml"

    def test_wkt_detected(self):
        assert _detect_format("POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))") == "wkt"
        assert _detect_format("POINT (-73.9 40.7)") == "wkt"

    def test_csv_detected_from_lat_lon_header(self):
        assert _detect_format("name,lat,lon\nA,40.7,-74.0") == "csv"

    def test_geoparquet_detected_from_base64_par1(self):
        raw = b"PAR1" + b"\x00" * 100
        b64 = base64.b64encode(raw).decode()
        assert _detect_format(b64) == "geoparquet"

    def test_shapefile_detected_from_base64_zip(self):
        raw = b"PK\x03\x04" + b"\x00" * 100
        b64 = base64.b64encode(raw).decode()
        assert _detect_format(b64) == "shapefile"

    def test_unknown_returns_none(self):
        assert _detect_format("just some random text") is None
        assert _detect_format("") is None


# ---------------------------------------------------------------------------
# handle_clip_to_bbox
# ---------------------------------------------------------------------------


class TestClipToBbox:
    def _sample_store(self) -> dict:
        return {
            "pts": _fc([
                _point_feature(40.0, -74.0, id=1),   # inside
                _point_feature(41.0, -73.0, id=2),   # inside
                _point_feature(50.0, -70.0, id=3),   # outside
            ]),
        }

    def test_bbox_filters_features(self):
        result = handle_clip_to_bbox(
            {"layer_name": "pts", "bbox": [39.0, -75.0, 42.0, -72.0]},
            layer_store=self._sample_store(),
        )
        assert "error" not in result
        assert result["feature_count"] == 2

    def test_missing_layer_errors(self):
        result = handle_clip_to_bbox(
            {"layer_name": "nonexistent", "bbox": [0, 0, 1, 1]},
            layer_store=self._sample_store(),
        )
        assert "error" in result

    def test_empty_result_returns_error(self):
        # Bbox that excludes all points
        result = handle_clip_to_bbox(
            {"layer_name": "pts", "bbox": [89.0, 179.0, 90.0, 180.0]},
            layer_store=self._sample_store(),
        )
        assert "error" in result

    def test_invalid_bbox_errors(self):
        result = handle_clip_to_bbox(
            {"layer_name": "pts", "bbox": [1, 2]},
            layer_store=self._sample_store(),
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# handle_generalize
# ---------------------------------------------------------------------------


class TestGeneralize:
    def test_reduces_vertex_count(self):
        # Dense polyline with many close-together points — simplification should cut vertices.
        dense_line = [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[x * 0.0001, 40.7] for x in range(100)],
                },
                "properties": {"id": 1},
            }
        ]
        store = {"line": _fc(dense_line)}
        result = handle_generalize(
            {"layer_name": "line", "tolerance": 50},
            layer_store=store,
        )
        assert "error" not in result
        assert result["simplified_vertices"] < result["original_vertices"]
        assert result["reduction_pct"] > 0

    def test_missing_tolerance_errors(self):
        store = {"line": _fc([])}
        result = handle_generalize({"layer_name": "line"}, layer_store=store)
        assert "error" in result

    def test_negative_tolerance_errors(self):
        store = {"line": _fc([_point_feature(0, 0)])}
        result = handle_generalize(
            {"layer_name": "line", "tolerance": -10},
            layer_store=store,
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# handle_export_gpkg
# ---------------------------------------------------------------------------


class TestExportGpkg:
    def test_missing_layer_returns_error(self):
        result = handle_export_gpkg({"layer_name": "x"}, layer_store={})
        assert "error" in result

    def test_empty_layer_returns_error(self):
        result = handle_export_gpkg(
            {"layer_name": "empty"},
            layer_store={"empty": _fc([])},
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# handle_import_auto
# ---------------------------------------------------------------------------


class TestImportAuto:
    def test_geojson_data_delegated(self):
        data = json.dumps({
            "type": "FeatureCollection",
            "features": [_point_feature(40.7, -74.0, name="A")],
        })
        result = handle_import_auto(
            {"data": data, "layer_name": "test_geojson"},
            layer_store={},
        )
        assert "error" not in result
        assert result.get("detected_format") == "geojson"

    def test_wkt_data_delegated(self):
        data = "POINT(-74.0 40.7)"
        result = handle_import_auto(
            {"data": data, "layer_name": "wkt_test"},
            layer_store={},
        )
        assert result.get("detected_format") == "wkt"

    def test_unknown_format_errors(self):
        result = handle_import_auto(
            {"data": "just random prose"},
            layer_store={},
        )
        assert "error" in result
        assert "auto-detect" in result["error"].lower()

    def test_missing_data_errors(self):
        result = handle_import_auto({}, layer_store={})
        assert "error" in result


# ---------------------------------------------------------------------------
# dispatch registration
# ---------------------------------------------------------------------------


class TestDispatchRegistration:
    def test_clip_to_bbox_dispatches(self):
        store = {"pts": _fc([_point_feature(40.7, -74.0)])}
        result = dispatch_tool("clip_to_bbox",
                               {"layer_name": "pts", "bbox": [39, -75, 42, -72]},
                               layer_store=store)
        assert "error" not in result

    def test_generalize_dispatches(self):
        store = {"line": _fc([{"type": "Feature",
                               "geometry": {"type": "LineString",
                                            "coordinates": [[0, 0], [1, 1], [2, 2]]},
                               "properties": {}}])}
        result = dispatch_tool("generalize",
                               {"layer_name": "line", "tolerance": 10},
                               layer_store=store)
        assert "error" not in result

    def test_import_auto_dispatches(self):
        data = '{"type": "FeatureCollection", "features": []}'
        result = dispatch_tool("import_auto", {"data": data}, layer_store={})
        # Empty FC is valid per validator — just confirm we didn't crash
        assert isinstance(result, dict)

    def test_export_gpkg_dispatches(self):
        result = dispatch_tool("export_gpkg", {"layer_name": "nothing"}, layer_store={})
        # Error path exercised — we're just verifying dispatch reaches the handler
        assert "error" in result
