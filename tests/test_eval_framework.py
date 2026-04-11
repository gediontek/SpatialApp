"""Tests for the tool selection evaluation framework."""

import pytest

from tests.eval.reference_queries import (
    REFERENCE_QUERIES,
    ALL_QUERIES,
    ALL_TOOLS,
    get_tool_coverage,
)
from tests.eval.evaluator import ToolSelectionEvaluator
from tests.eval.mock_responses import MOCK_RESPONSES, get_mock_tools, get_mock_params
from tests.eval.run_eval import run_mock_evaluation


class TestEvaluatorScoring:
    """Test the evaluator's match classification logic."""

    def setup_method(self):
        self.evaluator = ToolSelectionEvaluator()

    def test_full_match_single_tool(self):
        result = self.evaluator.evaluate_single("Q006", ["measure_distance"])
        assert result["match"] == "full"
        assert result["missing_tools"] == []
        assert result["extra_tools"] == []

    def test_full_match_multi_tool(self):
        result = self.evaluator.evaluate_single("Q005", ["geocode", "map_command"])
        assert result["match"] == "full"

    def test_full_match_order_independent(self):
        result = self.evaluator.evaluate_single("Q005", ["map_command", "geocode"])
        assert result["match"] == "full"

    def test_partial_match_missing_tool(self):
        result = self.evaluator.evaluate_single("Q005", ["geocode"])
        assert result["match"] == "partial"
        assert "map_command" in result["missing_tools"]
        assert result["extra_tools"] == []

    def test_partial_match_extra_tool(self):
        result = self.evaluator.evaluate_single("Q006", ["measure_distance", "map_command"])
        assert result["match"] == "partial"
        assert result["missing_tools"] == []
        assert "map_command" in result["extra_tools"]

    def test_no_match_completely_wrong(self):
        result = self.evaluator.evaluate_single("Q006", ["fetch_osm"])
        assert result["match"] == "none"
        assert "measure_distance" in result["missing_tools"]

    def test_no_match_empty_actual(self):
        result = self.evaluator.evaluate_single("Q006", [])
        assert result["match"] == "none"

    def test_duplicate_expected_tools(self):
        """Q020 expects fetch_osm twice (parks + commercial)."""
        result = self.evaluator.evaluate_single(
            "Q020", ["fetch_osm", "fetch_osm", "intersection"]
        )
        assert result["match"] == "full"

    def test_duplicate_expected_missing_one(self):
        result = self.evaluator.evaluate_single(
            "Q020", ["fetch_osm", "intersection"]
        )
        assert result["match"] == "partial"
        assert result["missing_tools"] == ["fetch_osm"]

    def test_unknown_query_id_raises(self):
        with pytest.raises(ValueError, match="Unknown query_id"):
            self.evaluator.evaluate_single("INVALID", ["geocode"])


class TestParamChecking:
    """Test parameter matching logic."""

    def setup_method(self):
        self.evaluator = ToolSelectionEvaluator()

    def test_param_match_true(self):
        result = self.evaluator.evaluate_single(
            "Q007",
            ["calculate_area"],
            actual_params={"calculate_area": {"layer_name": "parks"}},
        )
        assert result["param_match"] is True

    def test_param_match_false(self):
        result = self.evaluator.evaluate_single(
            "Q007",
            ["calculate_area"],
            actual_params={"calculate_area": {"layer_name": "wrong_layer"}},
        )
        assert result["param_match"] is False

    def test_param_match_extra_params_ok(self):
        """Extra params in actual should not cause failure."""
        result = self.evaluator.evaluate_single(
            "Q007",
            ["calculate_area"],
            actual_params={"calculate_area": {"layer_name": "parks", "extra": True}},
        )
        assert result["param_match"] is True

    def test_param_match_none_when_no_expected(self):
        """Queries without expected_params should return None."""
        result = self.evaluator.evaluate_single(
            "Q014",
            ["convex_hull"],
            actual_params={"convex_hull": {"layer_name": "crime"}},
        )
        assert result["param_match"] is None

    def test_param_match_false_when_no_actual(self):
        """If expected_params exist but actual_params not provided, should be False."""
        result = self.evaluator.evaluate_single("Q007", ["calculate_area"])
        assert result["param_match"] is False


class TestBatchEvaluation:
    """Test batch evaluation and aggregation."""

    def setup_method(self):
        self.evaluator = ToolSelectionEvaluator()

    def test_batch_all_full_match(self):
        results = [
            {"query_id": "Q006", "actual_tools": ["measure_distance"]},
            {"query_id": "Q014", "actual_tools": ["convex_hull"]},
        ]
        batch = self.evaluator.evaluate_batch(results)
        assert batch["total"] == 2
        assert batch["full_match"] == 2
        assert batch["accuracy"] == 1.0

    def test_batch_mixed_results(self):
        results = [
            {"query_id": "Q006", "actual_tools": ["measure_distance"]},  # full
            {"query_id": "Q005", "actual_tools": ["geocode"]},            # partial
            {"query_id": "Q014", "actual_tools": ["fetch_osm"]},          # none
        ]
        batch = self.evaluator.evaluate_batch(results)
        assert batch["total"] == 3
        assert batch["full_match"] == 1
        assert batch["partial_match"] == 1
        assert batch["no_match"] == 1
        assert batch["accuracy"] == pytest.approx(0.333, abs=0.001)

    def test_batch_by_complexity(self):
        results = [
            {"query_id": "Q006", "actual_tools": ["measure_distance"]},  # simple, full
            {"query_id": "Q007", "actual_tools": ["calculate_area"]},    # simple, full
            {"query_id": "Q005", "actual_tools": ["geocode"]},            # moderate, partial
        ]
        batch = self.evaluator.evaluate_batch(results)
        assert batch["by_complexity"]["simple"]["accuracy"] == 1.0
        assert batch["by_complexity"]["moderate"]["accuracy"] == 0.0

    def test_batch_by_category(self):
        results = [
            {"query_id": "Q006", "actual_tools": ["measure_distance"]},  # measurement, full
            {"query_id": "Q014", "actual_tools": ["convex_hull"]},       # geometry, full
        ]
        batch = self.evaluator.evaluate_batch(results)
        assert batch["by_category"]["measurement"]["accuracy"] == 1.0
        assert batch["by_category"]["geometry"]["accuracy"] == 1.0

    def test_batch_worst_queries(self):
        results = [
            {"query_id": "Q006", "actual_tools": ["measure_distance"]},  # full
            {"query_id": "Q014", "actual_tools": ["fetch_osm"]},          # none
            {"query_id": "Q005", "actual_tools": ["geocode"]},            # partial
        ]
        batch = self.evaluator.evaluate_batch(results)
        assert len(batch["worst_queries"]) == 2
        # "none" should come before "partial" in sorting
        assert batch["worst_queries"][0]["match"] == "none"
        assert batch["worst_queries"][1]["match"] == "partial"

    def test_batch_empty_results(self):
        batch = self.evaluator.evaluate_batch([])
        assert batch["total"] == 0
        assert batch["accuracy"] == 0.0


class TestReportGeneration:
    """Test markdown report generation."""

    def setup_method(self):
        self.evaluator = ToolSelectionEvaluator()

    def test_report_contains_summary(self):
        results = [
            {"query_id": "Q006", "actual_tools": ["measure_distance"]},
        ]
        report = self.evaluator.generate_report(results)
        assert "# Tool Selection Accuracy Report" in report
        assert "## Summary" in report
        assert "100.0%" in report

    def test_report_contains_complexity_table(self):
        results = [
            {"query_id": "Q006", "actual_tools": ["measure_distance"]},
        ]
        report = self.evaluator.generate_report(results)
        assert "## Accuracy by Complexity" in report
        assert "simple" in report

    def test_report_contains_mismatches(self):
        results = [
            {"query_id": "Q006", "actual_tools": ["fetch_osm"]},
        ]
        report = self.evaluator.generate_report(results)
        assert "## Mismatched Queries" in report
        assert "Q006" in report

    def test_report_no_mismatch_section_on_perfect(self):
        results = [
            {"query_id": "Q006", "actual_tools": ["measure_distance"]},
        ]
        report = self.evaluator.generate_report(results)
        assert "## Mismatched Queries" not in report


class TestToolCoverage:
    """Test that all 44 tools appear in at least one reference query."""

    def test_all_tools_covered_by_all_queries(self):
        """ALL_QUERIES (primary + supplementary) must cover all 44 tools."""
        covered, uncovered = get_tool_coverage(ALL_QUERIES)
        assert uncovered == set(), (
            f"Tools not covered by any query: {sorted(uncovered)}"
        )

    def test_all_tools_list_has_44(self):
        assert len(ALL_TOOLS) == 44

    def test_no_duplicate_query_ids(self):
        ids = [q["id"] for q in ALL_QUERIES]
        assert len(ids) == len(set(ids)), "Duplicate query IDs found"

    def test_all_query_ids_have_mock_responses(self):
        for q in ALL_QUERIES:
            assert q["id"] in MOCK_RESPONSES, (
                f"Query {q['id']} has no mock response"
            )

    def test_mock_tools_match_expected(self):
        """Mock responses should match expected tools for each query."""
        for q in ALL_QUERIES:
            mock_tools = get_mock_tools(q["id"])
            expected = q["expected_tools"]
            assert sorted(mock_tools) == sorted(expected), (
                f"Mock mismatch for {q['id']}: "
                f"expected {expected}, mock returns {mock_tools}"
            )


class TestMockEvaluation:
    """Test the mock evaluation pipeline end-to-end."""

    def test_mock_eval_runs_all_primary(self):
        results = run_mock_evaluation(REFERENCE_QUERIES)
        assert len(results) == 30

    def test_mock_eval_perfect_accuracy(self):
        """Mock responses are designed to match expected tools exactly."""
        results = run_mock_evaluation(REFERENCE_QUERIES)
        evaluator = ToolSelectionEvaluator()
        batch = evaluator.evaluate_batch(results)
        assert batch["accuracy"] == 1.0, (
            f"Mock evaluation should be 100% accurate but got {batch['accuracy']:.1%}. "
            f"Mismatches: {batch['worst_queries']}"
        )

    def test_mock_eval_with_query_filter(self):
        results = run_mock_evaluation(REFERENCE_QUERIES, query_ids=["Q001", "Q006"])
        assert len(results) == 2

    def test_mock_eval_all_queries(self):
        results = run_mock_evaluation(ALL_QUERIES)
        evaluator = ToolSelectionEvaluator(ALL_QUERIES)
        batch = evaluator.evaluate_batch(results)
        assert batch["accuracy"] == 1.0

    def test_full_pipeline_with_report(self):
        """Integration: mock eval -> batch eval -> report generation."""
        results = run_mock_evaluation(REFERENCE_QUERIES)
        evaluator = ToolSelectionEvaluator()
        report = evaluator.generate_report(results)
        assert "100.0%" in report
        assert "## Mismatched Queries" not in report


class TestReferenceQuerySchema:
    """Validate the structure of reference queries."""

    REQUIRED_KEYS = {"id", "query", "complexity", "expected_tools", "category"}

    @pytest.mark.parametrize("query", ALL_QUERIES, ids=lambda q: q["id"])
    def test_query_has_required_keys(self, query):
        missing = self.REQUIRED_KEYS - set(query.keys())
        assert not missing, f"{query['id']} missing keys: {missing}"

    @pytest.mark.parametrize("query", ALL_QUERIES, ids=lambda q: q["id"])
    def test_expected_tools_non_empty(self, query):
        assert len(query["expected_tools"]) > 0, (
            f"{query['id']} has empty expected_tools"
        )

    @pytest.mark.parametrize("query", ALL_QUERIES, ids=lambda q: q["id"])
    def test_expected_tools_are_valid(self, query):
        for tool in query["expected_tools"]:
            assert tool in ALL_TOOLS, (
                f"{query['id']} references unknown tool: {tool}"
            )

    @pytest.mark.parametrize("query", ALL_QUERIES, ids=lambda q: q["id"])
    def test_complexity_is_valid(self, query):
        valid = {"simple", "moderate", "complex", "multi_step"}
        assert query["complexity"] in valid, (
            f"{query['id']} has invalid complexity: {query['complexity']}"
        )
