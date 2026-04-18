"""Tests for v2.1 Plan 06: granular param scoring, CI flags, regression detection."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.eval.evaluator import (
    ToolSelectionEvaluator,
    _normalize_crs,
    _param_values_match,
    _score_params,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# _score_params — granular parameter scoring
# ---------------------------------------------------------------------------


class TestScoreParams:
    def test_perfect_match_scores_1_0(self):
        expected = {"geocode": {"query": "Berlin"}}
        actual = {"geocode": {"query": "Berlin"}}
        s = _score_params(expected, actual)
        assert s["score"] == 1.0
        assert s["matched"] == 1
        assert s["total_params"] == 1
        assert s["mismatched"] == []
        assert s["missing"] == []

    def test_mismatch_records_expected_and_actual(self):
        expected = {"geocode": {"query": "Berlin"}}
        actual = {"geocode": {"query": "Paris"}}
        s = _score_params(expected, actual)
        assert s["score"] == 0.0
        assert len(s["mismatched"]) == 1
        mm = s["mismatched"][0]
        assert mm["expected"] == "Berlin"
        assert mm["actual"] == "Paris"

    def test_missing_param_recorded(self):
        expected = {"buffer": {"distance_m": 500, "layer_name": "parks"}}
        actual = {"buffer": {"distance_m": 500}}  # layer_name missing
        s = _score_params(expected, actual)
        assert s["matched"] == 1
        assert s["total_params"] == 2
        assert s["score"] == 0.5
        assert s["missing"] == [{"tool": "buffer", "param": "layer_name", "expected": "parks"}]

    def test_extra_actual_params_ignored(self):
        expected = {"fetch_osm": {"feature_type": "park"}}
        actual = {"fetch_osm": {"feature_type": "park", "extra": "ignored"}}
        s = _score_params(expected, actual)
        assert s["score"] == 1.0

    def test_case_insensitive_string_match(self):
        expected = {"fetch_osm": {"location": "Central Park"}}
        actual = {"fetch_osm": {"location": "central park"}}
        s = _score_params(expected, actual)
        assert s["score"] == 1.0

    def test_coordinate_tolerance(self):
        expected = {"geocode": {"lat": 40.7128, "lon": -74.0060}}
        # Within 0.01° tolerance
        actual = {"geocode": {"lat": 40.7100, "lon": -74.0080}}
        s = _score_params(expected, actual)
        assert s["score"] == 1.0

    def test_coordinate_outside_tolerance(self):
        expected = {"geocode": {"lat": 40.7128}}
        # 0.1° off — fails tolerance
        actual = {"geocode": {"lat": 40.8128}}
        s = _score_params(expected, actual)
        assert s["score"] == 0.0

    def test_float_tolerance(self):
        expected = {"buffer": {"distance_m": 500.0}}
        actual = {"buffer": {"distance_m": 500.0005}}
        s = _score_params(expected, actual)
        assert s["score"] == 1.0

    def test_empty_expected_returns_zero_score(self):
        s = _score_params({}, {})
        assert s["score"] == 0.0
        assert s["total_params"] == 0


# ---------------------------------------------------------------------------
# CRS normalization
# ---------------------------------------------------------------------------


class TestCrsNormalization:
    def test_epsg_codes_match(self):
        assert _normalize_crs("EPSG:4326") == _normalize_crs("epsg:4326")
        assert _normalize_crs("EPSG:4326") == _normalize_crs(4326)
        assert _normalize_crs("EPSG:4326") == _normalize_crs("4326")

    def test_wgs84_aliases(self):
        assert _normalize_crs("WGS84") == "EPSG:4326"
        assert _normalize_crs("wgs84") == "EPSG:4326"
        assert _normalize_crs("wgs 84") == "EPSG:4326"

    def test_crs_param_match_uses_normalization(self):
        assert _param_values_match("from_crs", "EPSG:4326", "wgs84")
        assert _param_values_match("from_crs", 4326, "epsg:4326")


# ---------------------------------------------------------------------------
# Evaluator integration — param_score surfaced per-query + granular aggregate
# ---------------------------------------------------------------------------


class TestEvaluatorGranularParam:
    def test_evaluate_single_attaches_param_score(self):
        ev = ToolSelectionEvaluator(queries=[{
            "id": "T001", "query": "go", "complexity": "simple",
            "expected_tools": ["geocode"],
            "expected_params": {"geocode": {"query": "Berlin"}},
            "category": "test",
        }])
        result = ev.evaluate_single("T001", ["geocode"], {"geocode": {"query": "Paris"}})
        assert result["param_score"] is not None
        assert result["param_score"]["score"] == 0.0
        assert result["param_match"] is False

    def test_evaluate_batch_computes_granular_param_accuracy(self):
        queries = [
            {"id": f"T{i:03d}", "query": "x", "complexity": "simple",
             "expected_tools": ["geocode"],
             "expected_params": {"geocode": {"query": "X", "limit": 1}},
             "category": "t"}
            for i in range(2)
        ]
        ev = ToolSelectionEvaluator(queries=queries)
        results = [
            # Query 1: 2/2 params correct
            {"query_id": "T000", "actual_tools": ["geocode"],
             "actual_params": {"geocode": {"query": "X", "limit": 1}}},
            # Query 2: 1/2 params correct
            {"query_id": "T001", "actual_tools": ["geocode"],
             "actual_params": {"geocode": {"query": "X", "limit": 9}}},
        ]
        batch = ev.evaluate_batch(results)
        # granular accuracy = 3/4 matched params across the batch
        assert batch["granular_param_accuracy"] == 0.75
        # Strict param accuracy = 1/2 queries fully matched
        assert batch["param_accuracy"] == 0.5


# ---------------------------------------------------------------------------
# run_eval.py CLI smoke tests (subprocess)
# ---------------------------------------------------------------------------


class TestRunEvalCli:
    def _run(self, *args: str, expect_code: int | None = None) -> tuple[str, str, int]:
        result = subprocess.run(
            [sys.executable, "-m", "tests.eval.run_eval", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if expect_code is not None:
            assert result.returncode == expect_code, (
                f"expected exit {expect_code}, got {result.returncode}\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        return result.stdout, result.stderr, result.returncode

    def test_ci_mode_mock_produces_json_oneliner_and_passes(self):
        stdout, _stderr, code = self._run("--ci")
        # CI mode should exit 0 (mock run is 100%).
        assert code == 0
        # First line of stdout that is JSON should contain our keys.
        json_lines = [l for l in stdout.splitlines() if l.strip().startswith("{")]
        assert json_lines, f"expected a JSON summary; stdout was:\n{stdout}"
        summary = json.loads(json_lines[-1])
        assert "accuracy" in summary
        assert "param_accuracy" in summary
        assert "pass" in summary
        assert summary["pass"] is True

    def test_ci_mode_respects_env_thresholds(self, tmp_path, monkeypatch):
        # Push param threshold above achievable (mock gives 100%) by setting
        # tool threshold absurdly high — should fail.
        env = {
            "EVAL_TOOL_THRESHOLD": "1.01",
            "PATH": __import__("os").environ.get("PATH", ""),
        }
        result = subprocess.run(
            [sys.executable, "-m", "tests.eval.run_eval", "--ci"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        assert result.returncode == 1
        json_lines = [l for l in result.stdout.splitlines() if l.strip().startswith("{")]
        summary = json.loads(json_lines[-1])
        assert summary["pass"] is False


class TestBaselineAndRegression:
    def test_save_baseline_writes_file_with_expected_fields(self, tmp_path, monkeypatch):
        # Point BASELINE_PATH at a temp location so we don't clobber the real one.
        from tests.eval import run_eval as run_eval_mod
        monkeypatch.setattr(run_eval_mod, "BASELINE_PATH", tmp_path / "baseline.json")

        # Run --save-baseline via subprocess using a module-level override
        # isn't trivial; instead call _check_regression directly below and
        # exercise save via an in-process call to main() with argv patched.
        import sys as _sys
        argv_backup = list(_sys.argv)
        _sys.argv = ["run_eval", "--mock", "--all", "--save-baseline"]
        try:
            # Non-CI mock run at 100% passes the sanity floor, so main()
            # returns normally. If the floor triggers, SystemExit is raised —
            # handle either case without failing the test.
            try:
                run_eval_mod.main()
            except SystemExit as exc:
                assert exc.code in (0, None)
        finally:
            _sys.argv = argv_backup

        baseline_path = tmp_path / "baseline.json"
        assert baseline_path.exists()
        data = json.loads(baseline_path.read_text())
        for key in ("timestamp", "accuracy", "param_accuracy",
                    "chain_accuracy", "by_category", "by_complexity"):
            assert key in data

    def test_check_regression_detects_category_drop(self):
        from tests.eval.run_eval import _check_regression
        baseline = {
            "accuracy": 0.95, "param_accuracy": 0.80, "chain_accuracy": 0.70,
            "by_category": {"routing": {"accuracy": 0.90, "total": 10, "full_match": 9}},
        }
        current = {
            "accuracy": 0.94, "param_accuracy": 0.79, "chain_accuracy": 0.68,
            "by_category": {"routing": {"accuracy": 0.70, "total": 10, "full_match": 7}},
        }
        assert _check_regression(current, baseline) is True

    def test_check_regression_tolerates_small_noise(self):
        from tests.eval.run_eval import _check_regression
        baseline = {
            "accuracy": 0.90, "param_accuracy": 0.80, "chain_accuracy": 0.70,
            "by_category": {"routing": {"accuracy": 0.90, "total": 10, "full_match": 9}},
        }
        # Drop of 2pp — within the 5% tolerance.
        current = {
            "accuracy": 0.88, "param_accuracy": 0.79, "chain_accuracy": 0.70,
            "by_category": {"routing": {"accuracy": 0.88, "total": 10, "full_match": 9}},
        }
        assert _check_regression(current, baseline) is False
