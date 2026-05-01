"""Tests for v2.1 Plan 12 OSM auto-label handlers.

These tests do NOT require gensim or osmnx — heavy ML deps are mocked
via the `_set_test_factories` test seam in `nl_gis.handlers.autolabel`.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

import nl_gis.handlers.autolabel as autolabel
from nl_gis.handlers import dispatch_tool
from nl_gis.handlers.autolabel import (
    _GeoJSONWrapper,
    _parse_bbox,
    _set_test_factories,
    _reset_test_factories,
    handle_classify_area,
    handle_evaluate_classifier,
    handle_export_training_data,
    handle_predict_labels,
    handle_train_classifier,
)
from nl_gis.tools import get_tool_definitions


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------


class _MockClassifier:
    """Mimics OSMLandcoverClassifier.process_geodataframe()."""

    def __init__(self, label_cycle=("forest", "water", "builtup_area")):
        self.label_cycle = label_cycle
        self.calls = []

    def process_geodataframe(self, gdf, name="x"):
        self.calls.append({"name": name, "size": len(gdf) if hasattr(gdf, "__len__") else None})
        # Pull features out of either a real GDF (via to_json) or our wrapper
        if hasattr(gdf, "__geo_interface__"):
            fc = gdf.__geo_interface__
        else:
            fc = json.loads(gdf.to_json())
        feats = fc.get("features", [])
        for i, f in enumerate(feats):
            props = dict(f.get("properties") or {})
            props["predicted_label"] = self.label_cycle[i % len(self.label_cycle)]
            props["confidence"] = 0.9
            f["properties"] = props
        return _GeoJSONWrapper({"type": "FeatureCollection", "features": feats})


class _MockDownloader:
    def __init__(self, n=3):
        self.n = n
        self.calls = []

    def from_location(self, loc):
        self.calls.append(("location", loc))
        return self._make_fc(self.n)

    def from_bbox(self, bbox):
        self.calls.append(("bbox", bbox))
        return self._make_fc(self.n)

    @staticmethod
    def _make_fc(n):
        feats = [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [0, i], [1, i], [1, i + 1], [0, i + 1], [0, i],
                    ]],
                },
                "properties": {"osm_id": i, "osm_tags": {"landuse": "residential"}},
            }
            for i in range(n)
        ]
        return _GeoJSONWrapper({"type": "FeatureCollection", "features": feats})


class _BoomClassifier:
    def process_geodataframe(self, gdf, name="x"):
        raise RuntimeError("simulated classify failure")


class _BoomDownloader:
    def from_location(self, loc):
        raise RuntimeError("simulated download failure")

    def from_bbox(self, bbox):
        raise RuntimeError("simulated download failure")


@pytest.fixture(autouse=True)
def _reset_factories():
    """Make sure no factory leaks between tests."""
    yield
    _reset_test_factories()


@pytest.fixture
def mock_classifier_factory():
    classifier = _MockClassifier()
    _set_test_factories(classifier_factory=lambda: classifier)
    return classifier


@pytest.fixture
def mock_downloader_factory():
    dl = _MockDownloader(n=3)
    _set_test_factories(downloader_factory=lambda: dl)
    return dl


# ---------------------------------------------------------------------------
# bbox parsing
# ---------------------------------------------------------------------------

class TestBboxParse:
    def test_string_form(self):
        assert _parse_bbox("1,2,3,4") == (1.0, 2.0, 3.0, 4.0)

    def test_list_form(self):
        assert _parse_bbox([1, 2, 3, 4]) == (1.0, 2.0, 3.0, 4.0)

    def test_invalid_returns_none(self):
        assert _parse_bbox("not a bbox") is None
        assert _parse_bbox("1,2,3") is None
        assert _parse_bbox(None) is None
        assert _parse_bbox([1, 2, 3]) is None
        assert _parse_bbox("a,b,c,d") is None


# ---------------------------------------------------------------------------
# classify_area
# ---------------------------------------------------------------------------

class TestClassifyArea:
    def test_happy_path_location(self, mock_classifier_factory, mock_downloader_factory):
        result = handle_classify_area({"location": "Paris", "output_name": "test_paris"})
        assert "error" not in result
        assert result["action"] == "classify"
        assert result["layer_name"] == "test_paris"
        assert result["feature_count"] == 3
        # Each feature got a predicted_label
        for f in result["geojson"]["features"]:
            assert "predicted_label" in f["properties"]
        assert "colorMap" in result["style"]
        assert mock_downloader_factory.calls[0] == ("location", "Paris")

    def test_happy_path_bbox(self, mock_classifier_factory, mock_downloader_factory):
        result = handle_classify_area({"bbox": "40.0,-74.0,41.0,-73.0"})
        assert "error" not in result
        assert mock_downloader_factory.calls[0][0] == "bbox"
        assert mock_downloader_factory.calls[0][1] == (40.0, -74.0, 41.0, -73.0)

    def test_missing_both_args(self):
        result = handle_classify_area({})
        assert "error" in result
        assert "location" in result["error"] or "bbox" in result["error"]

    def test_invalid_bbox(self, mock_classifier_factory, mock_downloader_factory):
        result = handle_classify_area({"bbox": "garbage"})
        assert "error" in result

    def test_download_failure(self):
        _set_test_factories(downloader_factory=lambda: _BoomDownloader(),
                            classifier_factory=lambda: _MockClassifier())
        result = handle_classify_area({"location": "X"})
        assert "error" in result
        assert "download" in result["error"].lower()

    def test_classification_failure(self, mock_downloader_factory):
        _set_test_factories(classifier_factory=lambda: _BoomClassifier())
        result = handle_classify_area({"location": "X"})
        assert "error" in result
        assert "classification" in result["error"].lower()

    def test_classcount_aggregation(self, mock_classifier_factory, mock_downloader_factory):
        result = handle_classify_area({"location": "X"})
        # Mock cycles through 3 labels for 3 features → one each
        assert sum(result["class_counts"].values()) == 3
        assert set(result["class_counts"].keys()).issubset(
            {"forest", "water", "builtup_area"}
        )

    def test_dispatch_classify_area(self, mock_classifier_factory, mock_downloader_factory):
        result = dispatch_tool("classify_area", {"location": "Paris"}, layer_store={})
        assert result["action"] == "classify"


# ---------------------------------------------------------------------------
# predict_labels
# ---------------------------------------------------------------------------

class TestPredictLabels:
    def test_happy_path(self, mock_classifier_factory):
        layer_store = {
            "parks": {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]},
                     "properties": {"name": "p1"}},
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]},
                     "properties": {"name": "p2"}},
                ],
            },
        }
        result = handle_predict_labels({"layer_name": "parks"}, layer_store)
        assert "error" not in result
        assert result["layer_name"] == "parks_classified"
        assert result["feature_count"] == 2

    def test_layer_missing(self):
        result = handle_predict_labels({"layer_name": "nope"}, {})
        assert "error" in result

    def test_required_param(self):
        result = handle_predict_labels({}, {})
        assert "error" in result

    def test_empty_layer(self, mock_classifier_factory):
        store = {"x": {"type": "FeatureCollection", "features": []}}
        result = handle_predict_labels({"layer_name": "x"}, store)
        assert "error" in result

    def test_caps_at_max(self, mock_classifier_factory):
        # MAX_CLASSIFY_FEATURES is 10000 → 10001 should be rejected
        feats = [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]},
             "properties": {}}
            for _ in range(autolabel.MAX_CLASSIFY_FEATURES + 1)
        ]
        store = {"big": {"type": "FeatureCollection", "features": feats}}
        result = handle_predict_labels({"layer_name": "big"}, store)
        assert "error" in result
        assert "cap" in result["error"]


# ---------------------------------------------------------------------------
# train_classifier
# ---------------------------------------------------------------------------

class TestTrainClassifier:
    def test_seed_extraction(self, tmp_path, monkeypatch):
        # Redirect output dir so we don't pollute the real OSM_auto_label/data
        monkeypatch.chdir(tmp_path)
        store = {
            "labels": {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0]]]},
                     "properties": {
                         "category_name": "forest",
                         "osm_tags": {"landuse": "forest"},
                     }},
                    {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[1, 1]]]},
                     "properties": {
                         "category_name": "water",
                         "osm_tags": {"natural": "water"},
                     }},
                    {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[2, 2]]]},
                     "properties": {
                         "category_name": "forest",
                         "feature_type": "wood",
                     }},
                ],
            },
        }
        result = handle_train_classifier(
            {"layer_name": "labels", "output_model_name": "fixture"}, store,
        )
        assert "error" not in result
        assert result["training_samples"] == 3
        assert "forest" in result["seeds"]
        assert "water" in result["seeds"]
        # Forest should have both the OSM tag and feature_type seeds
        assert sorted(result["seeds"]["forest"]) == ["forest", "wood"]

    def test_no_labels(self):
        store = {"labels": {"type": "FeatureCollection",
                            "features": [{"type": "Feature", "geometry": None, "properties": {}}]}}
        result = handle_train_classifier({"layer_name": "labels"}, store)
        assert "error" in result

    def test_required_layer(self):
        result = handle_train_classifier({}, {})
        assert "error" in result


# ---------------------------------------------------------------------------
# export_training_data
# ---------------------------------------------------------------------------

class TestExportTrainingData:
    def test_geojson_export_via_param(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        anns = [
            {"category_name": "forest", "geometry": {"type": "Point", "coordinates": [0, 0]}},
            {"category_name": "water", "geometry_json": json.dumps({"type": "Point", "coordinates": [1, 1]})},
        ]
        result = handle_export_training_data(
            {"format": "geojson", "annotations": anns, "output_name": "u1"}, layer_store={},
        )
        assert "error" not in result
        assert result["sample_count"] == 2
        assert result["geojson"]["type"] == "FeatureCollection"

    def test_csv_export(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        anns = [{"category_name": "forest", "geometry": {"type": "Point", "coordinates": [0, 0]}}]
        result = handle_export_training_data(
            {"format": "csv", "annotations": anns}, layer_store={},
        )
        assert "error" not in result
        # CSV path: geojson key is None because we don't return inline data
        assert result["geojson"] is None
        assert result["format"] == "csv"

    def test_invalid_format(self):
        result = handle_export_training_data({"format": "parquet"}, layer_store={})
        assert "error" in result

    def test_no_annotations(self, monkeypatch):
        # Force state.db to None and clear in-memory annotations list
        import state
        monkeypatch.setattr(state, "db", None)
        monkeypatch.setattr(state, "geo_coco_annotations", [])
        result = handle_export_training_data({}, layer_store={})
        assert "error" in result


# ---------------------------------------------------------------------------
# evaluate_classifier
# ---------------------------------------------------------------------------

class TestEvaluateClassifier:
    def _build_store(self, pairs):
        feats = []
        for truth, pred in pairs:
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {"category_name": truth, "predicted_label": pred},
            })
        return {"e": {"type": "FeatureCollection", "features": feats}}

    def test_perfect_accuracy(self):
        store = self._build_store([("forest", "forest"), ("water", "water")])
        result = handle_evaluate_classifier({"layer_name": "e"}, store)
        assert result["accuracy"] == 1.0
        assert result["total_evaluated"] == 2
        for cls, m in result["per_class"].items():
            assert m["precision"] == 1.0
            assert m["recall"] == 1.0
            assert m["f1"] == 1.0

    def test_partial_accuracy_with_confusion(self):
        # Confusion: 2/3 forest correct; 1 water predicted as forest
        store = self._build_store([
            ("forest", "forest"),
            ("forest", "forest"),
            ("forest", "water"),
            ("water", "forest"),
            ("water", "water"),
        ])
        result = handle_evaluate_classifier({"layer_name": "e"}, store)
        assert result["accuracy"] == round(3 / 5, 4)
        # Forest precision: tp=2, fp=1 (water→forest) → 2/3
        assert result["per_class"]["forest"]["precision"] == round(2 / 3, 4)
        # Forest recall: tp=2, fn=1 (forest→water) → 2/3
        assert result["per_class"]["forest"]["recall"] == round(2 / 3, 4)
        # Confusion matrix counts
        assert result["confusion_matrix"]["forest"]["forest"] == 2
        assert result["confusion_matrix"]["forest"]["water"] == 1
        assert result["confusion_matrix"]["water"]["forest"] == 1
        assert result["confusion_matrix"]["water"]["water"] == 1

    def test_no_pairs(self):
        store = {"e": {"type": "FeatureCollection",
                       "features": [{"type": "Feature", "geometry": None,
                                     "properties": {"category_name": "x"}}]}}  # missing prediction
        result = handle_evaluate_classifier({"layer_name": "e"}, store)
        assert "error" in result

    def test_layer_required(self):
        result = handle_evaluate_classifier({}, {})
        assert "error" in result

    def test_dispatch(self):
        store = self._build_store([("a", "a")])
        result = dispatch_tool("evaluate_classifier", {"layer_name": "e"}, store)
        assert result["accuracy"] == 1.0


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

class TestToolSchemas:
    def test_all_five_tools_registered(self):
        names = {t["name"] for t in get_tool_definitions()}
        for required in [
            "classify_area", "predict_labels", "train_classifier",
            "export_training_data", "evaluate_classifier",
        ]:
            assert required in names

    def test_classify_area_dispatches_with_missing_deps_gracefully(self, monkeypatch):
        # Simulate gensim missing: real factories raise ImportError
        def bad_classifier():
            raise ImportError("gensim not installed")

        def bad_downloader():
            raise ImportError("osmnx not installed")

        _set_test_factories(
            classifier_factory=bad_classifier,
            downloader_factory=bad_downloader,
        )
        result = handle_classify_area({"location": "X"})
        assert "error" in result
        assert "not installed" in result["error"]
