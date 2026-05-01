"""Tests for v2.1 Plan 11 visualization handlers."""

from __future__ import annotations

import math

import pytest

from nl_gis.handlers import dispatch_tool
from nl_gis.handlers.visualization import (
    _classify_values,
    _class_breaks,
    _generate_color_ramp,
    handle_animate_layer,
    handle_chart,
    handle_choropleth_map,
    handle_visualize_3d,
)
from nl_gis.tools import get_tool_definitions


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------

def _point_feature(props):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [0, 0]},
        "properties": props,
    }


def _square_polygon(cx, cy, side=0.001):
    h = side / 2
    return {
        "type": "Polygon",
        "coordinates": [[
            [cx - h, cy - h],
            [cx + h, cy - h],
            [cx + h, cy + h],
            [cx - h, cy + h],
            [cx - h, cy - h],
        ]],
    }


@pytest.fixture
def numeric_layer_store():
    """20 features with `pop` 100..2000 and `cat` cycling A/B/C."""
    feats = []
    for i in range(20):
        feats.append(_point_feature({
            "pop": 100 * (i + 1),
            "cat": "ABC"[i % 3],
            "year": 2020 + (i % 4),
        }))
    return {"cities": {"type": "FeatureCollection", "features": feats}}


@pytest.fixture
def building_layer_store():
    feats = [
        {"type": "Feature", "geometry": _square_polygon(0, 0),
         "properties": {"height": 12, "name": "A"}},
        {"type": "Feature", "geometry": _square_polygon(0.01, 0.01),
         "properties": {"building:levels": 5, "name": "B"}},
        {"type": "Feature", "geometry": _square_polygon(0.02, 0.02),
         "properties": {"name": "C"}},  # missing → default
        {"type": "Feature", "geometry": _square_polygon(0.03, 0.03),
         "properties": {"height": "tall", "name": "D"}},  # bad value → default
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]},
         "properties": {"height": 99, "name": "E"}},  # non-polygon → skipped
    ]
    return {"buildings": {"type": "FeatureCollection", "features": feats}}


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

class TestColorRamps:
    def test_sequential_5(self):
        ramp = _generate_color_ramp("sequential", 5)
        assert len(ramp) == 5
        assert all(c.startswith("#") and len(c) == 7 for c in ramp)

    def test_diverging_3(self):
        ramp = _generate_color_ramp("diverging", 3)
        assert len(ramp) == 3

    def test_qualitative_cycles(self):
        ramp = _generate_color_ramp("qualitative", 12)
        # First and 11th differ; 11th == 1st (cycle of 10)
        assert ramp[0] == ramp[10]
        assert ramp[0] != ramp[1]

    def test_custom_array(self):
        custom = ["#000000", "#ffffff"]
        ramp = _generate_color_ramp(custom, 5)
        assert len(ramp) == 5
        # First & last anchor the custom ramp
        assert ramp[0] == "#000000"
        assert ramp[-1] == "#ffffff"

    def test_unknown_name_falls_back(self):
        # Anything not recognized -> sequential
        ramp = _generate_color_ramp("nonsense", 4)
        assert len(ramp) == 4

    def test_single_class(self):
        ramp = _generate_color_ramp("sequential", 1)
        assert len(ramp) == 1


class TestClassBreaks:
    def test_quantile_5(self):
        import numpy as np
        vals = np.arange(100, dtype=float)
        breaks = _class_breaks(vals, "quantile", 5)
        assert len(breaks) == 6
        assert breaks[0] == 0
        assert breaks[-1] == 99

    def test_equal_interval(self):
        import numpy as np
        breaks = _class_breaks(np.array([0.0, 100.0]), "equal_interval", 4)
        assert breaks == [0.0, 25.0, 50.0, 75.0, 100.0]

    def test_manual(self):
        import numpy as np
        breaks = _class_breaks(np.array([1.0, 2.0]), "manual", 3, manual=[10, 0, 5])
        # Sorted ascending
        assert breaks == [0.0, 5.0, 10.0]

    def test_manual_requires_two(self):
        import numpy as np
        with pytest.raises(ValueError):
            _class_breaks(np.array([1.0]), "manual", 3, manual=[1])

    def test_all_nan_raises(self):
        import numpy as np
        with pytest.raises(ValueError):
            _class_breaks(np.array([float("nan"), float("nan")]), "quantile", 3)

    def test_natural_breaks_falls_back_when_jenkspy_missing(self, monkeypatch):
        import builtins
        import numpy as np

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "jenkspy":
                raise ImportError("simulate missing jenkspy")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        vals = np.arange(20, dtype=float)
        breaks = _class_breaks(vals, "natural_breaks", 4)
        # Quantile-equivalent: 5 breakpoints
        assert len(breaks) == 5

    def test_classify_assigns_correct_bucket(self):
        import numpy as np
        breaks = [0.0, 10.0, 20.0, 30.0]
        result = _classify_values(np.array([5.0, 15.0, 25.0, 30.0]), breaks)
        assert result == [0, 1, 2, 2]

    def test_classify_handles_nan(self):
        import numpy as np
        breaks = [0.0, 10.0]
        out = _classify_values(np.array([float("nan"), 5.0]), breaks)
        assert out == [None, 0]


# ----------------------------------------------------------------------------
# choropleth_map
# ----------------------------------------------------------------------------

class TestChoropleth:
    def test_happy_path_quantile(self, numeric_layer_store):
        result = handle_choropleth_map(
            {"layer_name": "cities", "attribute": "pop", "num_classes": 5},
            numeric_layer_store,
        )
        assert "error" not in result
        assert result["action"] == "choropleth"
        assert len(result["breaks"]) == 6
        assert len(result["colors"]) == 5
        # Every feature index gets a color
        assert len(result["styleMap"]) == 20
        assert all(c.startswith("#") for c in result["styleMap"].values())
        assert result["legendData"]["type"] == "choropleth"
        assert len(result["legendData"]["entries"]) == 5

    def test_equal_interval(self, numeric_layer_store):
        result = handle_choropleth_map(
            {"layer_name": "cities", "attribute": "pop", "method": "equal_interval", "num_classes": 4},
            numeric_layer_store,
        )
        assert "error" not in result
        # Equal-interval breaks evenly span min..max
        spans = [result["breaks"][i+1] - result["breaks"][i] for i in range(4)]
        assert all(math.isclose(s, spans[0], rel_tol=1e-9) for s in spans)

    def test_manual_breaks(self, numeric_layer_store):
        result = handle_choropleth_map(
            {
                "layer_name": "cities", "attribute": "pop",
                "method": "manual", "num_classes": 3,
                "breaks": [0, 500, 1500, 3000],
            },
            numeric_layer_store,
        )
        assert "error" not in result
        assert result["breaks"][0] == 0.0
        assert result["breaks"][-1] == 3000.0

    def test_diverging_ramp(self, numeric_layer_store):
        result = handle_choropleth_map(
            {"layer_name": "cities", "attribute": "pop", "color_ramp": "diverging"},
            numeric_layer_store,
        )
        assert "error" not in result
        # Diverging palettes don't repeat first→last colors
        assert result["colors"][0] != result["colors"][-1]

    def test_missing_layer(self):
        result = handle_choropleth_map({"layer_name": "nope", "attribute": "x"}, {})
        assert "error" in result

    def test_missing_attribute(self, numeric_layer_store):
        result = handle_choropleth_map({"layer_name": "cities", "attribute": "ghost"}, numeric_layer_store)
        assert "error" in result

    def test_non_numeric_handled(self, numeric_layer_store):
        # Some features get non-numeric value
        layer = numeric_layer_store["cities"]
        layer["features"][0]["properties"]["pop"] = "n/a"
        layer["features"][1]["properties"]["pop"] = None
        result = handle_choropleth_map(
            {"layer_name": "cities", "attribute": "pop"}, numeric_layer_store,
        )
        assert "error" not in result
        # Two missing → not in styleMap
        assert result["missing_count"] >= 2
        assert 0 not in result["styleMap"]
        assert 1 not in result["styleMap"]

    def test_num_classes_bounds(self, numeric_layer_store):
        bad_low = handle_choropleth_map(
            {"layer_name": "cities", "attribute": "pop", "num_classes": 1},
            numeric_layer_store,
        )
        assert "error" in bad_low
        bad_high = handle_choropleth_map(
            {"layer_name": "cities", "attribute": "pop", "num_classes": 99},
            numeric_layer_store,
        )
        assert "error" in bad_high

    def test_dispatch(self, numeric_layer_store):
        result = dispatch_tool(
            "choropleth_map",
            {"layer_name": "cities", "attribute": "pop"},
            numeric_layer_store,
        )
        assert result["action"] == "choropleth"


# ----------------------------------------------------------------------------
# chart
# ----------------------------------------------------------------------------

class TestChart:
    def test_pie_count(self, numeric_layer_store):
        result = handle_chart(
            {"layer_name": "cities", "attribute": "cat", "chart_type": "pie"},
            numeric_layer_store,
        )
        assert "error" not in result
        assert result["chart_type"] == "pie"
        assert sorted(result["labels"]) == ["A", "B", "C"]
        assert sum(result["datasets"][0]["data"]) == 20

    def test_bar_sum(self, numeric_layer_store):
        result = handle_chart(
            {
                "layer_name": "cities", "attribute": "pop",
                "chart_type": "bar", "group_by": "cat", "aggregation": "sum",
            },
            numeric_layer_store,
        )
        assert "error" not in result
        # Total pop = sum(100..2000 step 100) = 21000
        assert math.isclose(sum(result["datasets"][0]["data"]), 21000.0)

    def test_histogram(self, numeric_layer_store):
        result = handle_chart(
            {"layer_name": "cities", "attribute": "pop", "chart_type": "histogram", "num_bins": 5},
            numeric_layer_store,
        )
        assert "error" not in result
        assert len(result["datasets"][0]["data"]) == 5
        assert sum(result["datasets"][0]["data"]) == 20

    def test_scatter(self, numeric_layer_store):
        result = handle_chart(
            {
                "layer_name": "cities", "attribute": "pop",
                "chart_type": "scatter", "x_attribute": "year",
            },
            numeric_layer_store,
        )
        assert "error" not in result
        assert all("x" in pt and "y" in pt for pt in result["datasets"][0]["data"])

    def test_invalid_type(self, numeric_layer_store):
        result = handle_chart(
            {"layer_name": "cities", "attribute": "pop", "chart_type": "violin"},
            numeric_layer_store,
        )
        assert "error" in result

    def test_empty_layer(self):
        store = {"empty": {"type": "FeatureCollection", "features": []}}
        result = handle_chart(
            {"layer_name": "empty", "attribute": "pop", "chart_type": "pie"},
            store,
        )
        assert "error" in result

    def test_missing_attribute_for_histogram(self, numeric_layer_store):
        result = handle_chart(
            {"layer_name": "cities", "attribute": "ghost", "chart_type": "histogram"},
            numeric_layer_store,
        )
        assert "error" in result

    def test_dispatch(self, numeric_layer_store):
        result = dispatch_tool(
            "chart",
            {"layer_name": "cities", "attribute": "cat", "chart_type": "pie"},
            numeric_layer_store,
        )
        assert result["chart_type"] == "pie"


# ----------------------------------------------------------------------------
# animate_layer
# ----------------------------------------------------------------------------

class TestAnimate:
    def test_year_grouping(self, numeric_layer_store):
        result = handle_animate_layer(
            {"layer_name": "cities", "time_attribute": "year"},
            numeric_layer_store,
        )
        assert "error" not in result
        # Years 2020..2023 → 4 unique
        assert len(result["time_steps"]) == 4
        # Total feature indices across steps == feature count
        total = sum(len(s["feature_indices"]) for s in result["time_steps"])
        assert total == 20

    def test_missing_time_attribute(self, numeric_layer_store):
        result = handle_animate_layer(
            {"layer_name": "cities", "time_attribute": "ghost"},
            numeric_layer_store,
        )
        assert "error" in result

    def test_required_params(self):
        assert "error" in handle_animate_layer({}, {})
        assert "error" in handle_animate_layer({"layer_name": "x"}, {})

    def test_binning_when_too_many_steps(self):
        # 250 unique years -> binned into <= 100 steps
        feats = [
            _point_feature({"year": 1000 + i})
            for i in range(250)
        ]
        store = {"big": {"type": "FeatureCollection", "features": feats}}
        result = handle_animate_layer(
            {"layer_name": "big", "time_attribute": "year"}, store,
        )
        assert result["binned"] is True
        assert len(result["time_steps"]) <= 100
        # Every feature is included in some bin
        total = sum(len(s["feature_indices"]) for s in result["time_steps"])
        assert total == 250

    def test_dispatch(self, numeric_layer_store):
        result = dispatch_tool(
            "animate_layer",
            {"layer_name": "cities", "time_attribute": "year"},
            numeric_layer_store,
        )
        assert result["action"] == "animate"


# ----------------------------------------------------------------------------
# visualize_3d
# ----------------------------------------------------------------------------

class TestVisualize3D:
    def test_height_extraction(self, building_layer_store):
        result = handle_visualize_3d(
            {"layer_name": "buildings"}, building_layer_store,
        )
        assert "error" not in result
        # 4 polygons accepted, 1 point skipped
        assert result["feature_count"] == 4
        assert result["skipped_non_polygon"] == 1
        # Default applied to two features (missing + non-numeric)
        assert result["used_default_count"] == 2
        # All annotated features have _height_m
        for f in result["geojson"]["features"]:
            assert "_height_m" in f["properties"]

    def test_levels_fallback(self, building_layer_store):
        result = handle_visualize_3d(
            {"layer_name": "buildings", "height_multiplier": 4.0},
            building_layer_store,
        )
        # Building B has levels=5 -> 5 * 4.0 = 20m
        feats = result["geojson"]["features"]
        b = next(f for f in feats if f["properties"].get("name") == "B")
        assert b["properties"]["_height_m"] == 20.0

    def test_default_height_override(self, building_layer_store):
        result = handle_visualize_3d(
            {"layer_name": "buildings", "default_height": 42.0},
            building_layer_store,
        )
        feats = result["geojson"]["features"]
        c = next(f for f in feats if f["properties"].get("name") == "C")
        assert c["properties"]["_height_m"] == 42.0

    def test_no_polygons(self):
        feats = [_point_feature({"height": 5})]
        store = {"pts": {"type": "FeatureCollection", "features": feats}}
        result = handle_visualize_3d({"layer_name": "pts"}, store)
        assert "error" in result

    def test_dispatch(self, building_layer_store):
        result = dispatch_tool(
            "visualize_3d", {"layer_name": "buildings"}, building_layer_store,
        )
        assert result["action"] == "3d_buildings"


# ----------------------------------------------------------------------------
# Tool schemas registered
# ----------------------------------------------------------------------------

class TestToolSchemas:
    def test_all_four_tools_in_definitions(self):
        names = {t["name"] for t in get_tool_definitions()}
        for required in ["choropleth_map", "chart", "animate_layer", "visualize_3d"]:
            assert required in names

    def test_dispatch_unknown_tool_still_raises(self):
        # Verify we didn't break the catch-all
        with pytest.raises(ValueError):
            dispatch_tool("definitely_not_a_tool", {}, {})
