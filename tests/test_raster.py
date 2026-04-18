"""Tests for v2.1 Plan 08: raster tools."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from config import Config

# Skip the whole file gracefully if rasterio isn't available.
pytest.importorskip("rasterio")
pytest.importorskip("numpy")

from nl_gis.handlers import dispatch_tool  # noqa: E402
from nl_gis.handlers.raster import (  # noqa: E402
    _list_available_rasters,
    _open_raster,
    _safe_raster_path,
    handle_raster_classify,
    handle_raster_info,
    handle_raster_profile,
    handle_raster_statistics,
    handle_raster_value,
)


SAMPLE_RASTER = "geog_wgs84.tif"


def _sample_dir_has_data() -> bool:
    base = Config.RASTER_DIR
    return os.path.isdir(base) and any(
        f.lower().endswith((".tif", ".tiff")) for f in os.listdir(base)
    )


pytestmark = pytest.mark.skipif(
    not _sample_dir_has_data(),
    reason="sample_rasters/ is empty or missing",
)


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


class TestSafeRasterPath:
    def test_valid_filename_resolves(self):
        path, err = _safe_raster_path(SAMPLE_RASTER)
        assert err is None
        assert path and os.path.exists(path)

    def test_missing_file_errors(self):
        path, err = _safe_raster_path("does_not_exist.tif")
        assert path is None
        assert "not found" in err.lower()

    def test_path_traversal_blocked(self):
        path, err = _safe_raster_path("../../etc/passwd")
        assert path is None
        assert err  # any rejection message is fine

    def test_wrong_extension_rejected(self):
        # Create a temp file with .txt extension in RASTER_DIR and verify
        base = Config.RASTER_DIR
        tmp = os.path.join(base, "not_a_raster.txt")
        try:
            Path(tmp).write_text("hello")
            path, err = _safe_raster_path("not_a_raster.txt")
            assert path is None
            assert "extension" in err.lower() or "supported" in err.lower()
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


# ---------------------------------------------------------------------------
# raster_info
# ---------------------------------------------------------------------------


class TestRasterInfo:
    def test_list_mode_returns_available_rasters(self):
        result = handle_raster_info({})
        assert "available_rasters" in result
        assert isinstance(result["available_rasters"], list)
        assert len(result["available_rasters"]) >= 1
        first = result["available_rasters"][0]
        assert "name" in first and "size_mb" in first

    def test_specific_raster_returns_metadata(self):
        result = handle_raster_info({"raster": SAMPLE_RASTER})
        assert "error" not in result
        for key in ("crs", "resolution", "width", "height", "bands", "dtype", "bounds_wgs84"):
            assert key in result
        assert result["width"] > 0
        assert result["height"] > 0
        assert len(result["bounds_wgs84"]) == 4

    def test_missing_raster_returns_error(self):
        result = handle_raster_info({"raster": "nonexistent.tif"})
        assert "error" in result


# ---------------------------------------------------------------------------
# raster_value
# ---------------------------------------------------------------------------


class TestRasterValue:
    def _bounds_center(self) -> tuple[float, float]:
        info = handle_raster_info({"raster": SAMPLE_RASTER})
        s, w, n, e = info["bounds_wgs84"]
        return (s + n) / 2, (w + e) / 2

    def test_in_bounds_returns_numeric_values(self):
        lat, lon = self._bounds_center()
        result = handle_raster_value({
            "raster": SAMPLE_RASTER, "lat": lat, "lon": lon,
        })
        assert "error" not in result
        assert "values" in result
        assert isinstance(result["values"], list)
        assert result["bands"] >= 1

    def test_out_of_bounds_returns_error(self):
        # Nowhere near the raster's footprint
        result = handle_raster_value({
            "raster": SAMPLE_RASTER, "lat": 89.0, "lon": 179.0,
        })
        assert "error" in result
        assert "outside" in result["error"].lower() or "extent" in result["error"].lower()

    def test_missing_coords_returns_error(self):
        result = handle_raster_value({"raster": SAMPLE_RASTER})
        assert "error" in result


# ---------------------------------------------------------------------------
# raster_statistics
# ---------------------------------------------------------------------------


class TestRasterStatistics:
    def test_global_stats(self):
        result = handle_raster_statistics({"raster": SAMPLE_RASTER})
        assert "error" not in result
        for key in ("min", "max", "mean", "std", "median", "count"):
            assert key in result
        assert result["count"] > 0
        assert result["min"] <= result["mean"] <= result["max"]

    def test_slope_derivative(self):
        result = handle_raster_statistics({"raster": SAMPLE_RASTER, "derivative": "slope"})
        assert "error" not in result
        # Slope in degrees — bounded by arctan, roughly 0 to 90 for realistic data
        assert 0 <= result["min"] <= 90
        assert result["max"] <= 90 + 1e-6

    def test_aspect_range(self):
        result = handle_raster_statistics({"raster": SAMPLE_RASTER, "derivative": "aspect"})
        assert "error" not in result
        assert result["min"] >= 0
        assert result["max"] <= 360.0 + 1e-6


# ---------------------------------------------------------------------------
# raster_profile
# ---------------------------------------------------------------------------


class TestRasterProfile:
    def test_profile_samples_along_line(self):
        info = handle_raster_info({"raster": SAMPLE_RASTER})
        s, w, n, e = info["bounds_wgs84"]
        result = handle_raster_profile({
            "raster": SAMPLE_RASTER,
            "from_point": {"lat": s, "lon": w},
            "to_point": {"lat": n, "lon": e},
            "num_samples": 25,
        })
        assert "error" not in result
        assert len(result["profile"]) == 25
        assert result["total_distance_m"] > 0
        # First sample at distance 0, last at total_distance_m
        assert result["profile"][0]["distance_m"] == 0
        assert abs(result["profile"][-1]["distance_m"] - result["total_distance_m"]) < 1.0
        # LineString geojson
        assert "geojson" in result
        assert result["geojson"]["features"][0]["geometry"]["type"] == "LineString"

    def test_profile_num_samples_clamped(self):
        info = handle_raster_info({"raster": SAMPLE_RASTER})
        s, w, n, e = info["bounds_wgs84"]
        # Request absurdly high count — should be clamped
        result = handle_raster_profile({
            "raster": SAMPLE_RASTER,
            "from_point": {"lat": s, "lon": w},
            "to_point": {"lat": n, "lon": e},
            "num_samples": 10_000,
        })
        assert len(result["profile"]) <= 500

    def test_missing_endpoints_errors(self):
        result = handle_raster_profile({"raster": SAMPLE_RASTER})
        assert "error" in result


# ---------------------------------------------------------------------------
# raster_classify
# ---------------------------------------------------------------------------


class TestRasterClassify:
    def test_basic_breaks_produces_features(self):
        stats = handle_raster_statistics({"raster": SAMPLE_RASTER})
        result = handle_raster_classify({
            "raster": SAMPLE_RASTER, "breaks": [stats["mean"]],
        })
        assert "error" not in result
        assert result["class_count"] == 2
        assert result["feature_count"] > 0
        assert "geojson" in result

    def test_labels_attached_to_features(self):
        stats = handle_raster_statistics({"raster": SAMPLE_RASTER})
        result = handle_raster_classify({
            "raster": SAMPLE_RASTER,
            "breaks": [stats["mean"]],
            "labels": ["low", "high"],
        })
        feats = result["geojson"]["features"]
        assert feats  # non-empty
        labels_seen = {f["properties"].get("label") for f in feats}
        assert labels_seen.issubset({"low", "high"})

    def test_empty_breaks_errors(self):
        result = handle_raster_classify({"raster": SAMPLE_RASTER, "breaks": []})
        assert "error" in result

    def test_non_numeric_breaks_errors(self):
        result = handle_raster_classify({"raster": SAMPLE_RASTER, "breaks": ["a", "b"]})
        assert "error" in result


# ---------------------------------------------------------------------------
# Dispatch registration — the 5 tools are reachable through dispatch_tool
# ---------------------------------------------------------------------------


class TestDispatchRegistration:
    def test_raster_info_dispatches(self):
        result = dispatch_tool("raster_info", {})
        assert "available_rasters" in result

    def test_raster_value_dispatches(self):
        info = dispatch_tool("raster_info", {"raster": SAMPLE_RASTER})
        s, w, n, e = info["bounds_wgs84"]
        result = dispatch_tool("raster_value", {
            "raster": SAMPLE_RASTER,
            "lat": (s + n) / 2, "lon": (w + e) / 2,
        })
        assert "values" in result or "error" in result

    def test_raster_statistics_dispatches(self):
        result = dispatch_tool("raster_statistics", {"raster": SAMPLE_RASTER})
        assert "mean" in result

    def test_raster_classify_dispatches(self):
        stats = dispatch_tool("raster_statistics", {"raster": SAMPLE_RASTER})
        result = dispatch_tool("raster_classify", {
            "raster": SAMPLE_RASTER, "breaks": [stats["mean"]],
        })
        assert "layer_name" in result
