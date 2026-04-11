"""Tool selection evaluation engine.

Compares actual tool selections against reference queries to measure
accuracy of the LLM's tool selection behavior.
"""

from collections import defaultdict
from typing import Optional

from tests.eval.reference_queries import ALL_QUERIES, REFERENCE_QUERIES


def _build_query_index(queries):
    """Build dict from query_id -> query definition."""
    return {q["id"]: q for q in queries}


class ToolSelectionEvaluator:
    """Evaluate tool selection accuracy against reference queries."""

    def __init__(self, queries=None):
        """Initialize with reference queries.

        Args:
            queries: List of reference query dicts. Defaults to REFERENCE_QUERIES.
        """
        self.queries = queries or REFERENCE_QUERIES
        self._index = _build_query_index(self.queries)

    def evaluate_single(
        self,
        query_id: str,
        actual_tools: list[str],
        actual_params: Optional[dict] = None,
    ) -> dict:
        """Compare actual tool selection against reference for one query.

        Args:
            query_id: Reference query ID (e.g. "Q001").
            actual_tools: List of tool names actually selected.
            actual_params: Optional dict of {tool_name: {param: value}} for param checking.

        Returns:
            Dict with match result, missing/extra tools, param match status.
        """
        if query_id not in self._index:
            raise ValueError(f"Unknown query_id: {query_id}")

        ref = self._index[query_id]
        expected = ref["expected_tools"]

        # Use multiset comparison: order doesn't matter but duplicates do
        expected_counts = _count_items(expected)
        actual_counts = _count_items(actual_tools)

        missing = []
        for tool, count in expected_counts.items():
            actual_count = actual_counts.get(tool, 0)
            missing.extend([tool] * max(0, count - actual_count))

        extra = []
        for tool, count in actual_counts.items():
            expected_count = expected_counts.get(tool, 0)
            extra.extend([tool] * max(0, count - expected_count))

        if not missing and not extra:
            match = "full"
        elif not missing:
            # All expected tools present but extras exist
            match = "partial"
        elif len(missing) < len(expected):
            match = "partial"
        else:
            match = "none"

        result = {
            "query_id": query_id,
            "query": ref["query"],
            "match": match,
            "expected_tools": expected,
            "actual_tools": actual_tools,
            "missing_tools": missing,
            "extra_tools": extra,
            "complexity": ref.get("complexity", "unknown"),
            "category": ref.get("category", "unknown"),
        }

        # Check params if expected_params is defined and actual_params provided
        expected_params = ref.get("expected_params")
        if expected_params and actual_params is not None:
            result["param_match"] = _check_params(expected_params, actual_params)
        elif expected_params and actual_params is None:
            result["param_match"] = False
        else:
            result["param_match"] = None  # No param check applicable

        return result

    def evaluate_batch(self, results: list[dict]) -> dict:
        """Evaluate multiple query results.

        Args:
            results: List of dicts, each with "query_id" and "actual_tools" keys,
                     and optionally "actual_params".

        Returns:
            Aggregate accuracy report with breakdowns.
        """
        evaluations = []
        for r in results:
            ev = self.evaluate_single(
                r["query_id"],
                r["actual_tools"],
                r.get("actual_params"),
            )
            evaluations.append(ev)

        total = len(evaluations)
        full_match = sum(1 for e in evaluations if e["match"] == "full")
        partial_match = sum(1 for e in evaluations if e["match"] == "partial")
        no_match = sum(1 for e in evaluations if e["match"] == "none")

        accuracy = full_match / total if total > 0 else 0.0

        # By complexity
        by_complexity = _group_accuracy(evaluations, "complexity")
        # By category
        by_category = _group_accuracy(evaluations, "category")

        # Worst queries: non-full matches sorted by severity
        worst = [
            {
                "id": e["query_id"],
                "query": e["query"],
                "match": e["match"],
                "expected": e["expected_tools"],
                "actual": e["actual_tools"],
                "missing": e["missing_tools"],
                "extra": e["extra_tools"],
            }
            for e in evaluations
            if e["match"] != "full"
        ]
        # Sort: "none" before "partial"
        worst.sort(key=lambda x: (0 if x["match"] == "none" else 1))

        return {
            "total": total,
            "full_match": full_match,
            "partial_match": partial_match,
            "no_match": no_match,
            "accuracy": round(accuracy, 3),
            "by_complexity": by_complexity,
            "by_category": by_category,
            "worst_queries": worst,
            "evaluations": evaluations,
        }

    def generate_report(self, results: list[dict]) -> str:
        """Generate a markdown accuracy report.

        Args:
            results: List of dicts with "query_id" and "actual_tools".

        Returns:
            Markdown-formatted report string.
        """
        summary = self.evaluate_batch(results)

        lines = [
            "# Tool Selection Accuracy Report",
            "",
            "## Summary",
            "",
            f"- **Total queries**: {summary['total']}",
            f"- **Full match**: {summary['full_match']}",
            f"- **Partial match**: {summary['partial_match']}",
            f"- **No match**: {summary['no_match']}",
            f"- **Accuracy** (full matches / total): **{summary['accuracy']:.1%}**",
            "",
            "## Accuracy by Complexity",
            "",
            "| Complexity | Accuracy | Count |",
            "|------------|----------|-------|",
        ]

        for level, data in sorted(summary["by_complexity"].items()):
            lines.append(
                f"| {level} | {data['accuracy']:.1%} | {data['total']} |"
            )

        lines.extend([
            "",
            "## Accuracy by Category",
            "",
            "| Category | Accuracy | Count |",
            "|----------|----------|-------|",
        ])

        for cat, data in sorted(summary["by_category"].items()):
            lines.append(f"| {cat} | {data['accuracy']:.1%} | {data['total']} |")

        if summary["worst_queries"]:
            lines.extend([
                "",
                "## Mismatched Queries",
                "",
            ])
            for w in summary["worst_queries"]:
                lines.append(f"### {w['id']}: {w['query']}")
                lines.append(f"- **Match**: {w['match']}")
                lines.append(f"- **Expected**: {w['expected']}")
                lines.append(f"- **Actual**: {w['actual']}")
                if w["missing"]:
                    lines.append(f"- **Missing**: {w['missing']}")
                if w["extra"]:
                    lines.append(f"- **Extra**: {w['extra']}")
                lines.append("")

        return "\n".join(lines)


def _count_items(items: list) -> dict:
    """Count occurrences of each item in list."""
    counts = defaultdict(int)
    for item in items:
        counts[item] += 1
    return dict(counts)


def _check_params(expected_params: dict, actual_params: dict) -> bool:
    """Check if actual params match expected params.

    Only checks keys present in expected_params — extra actual params are OK.
    """
    for tool_name, expected_tool_params in expected_params.items():
        actual_tool_params = actual_params.get(tool_name, {})
        for key, expected_value in expected_tool_params.items():
            actual_value = actual_tool_params.get(key)
            if actual_value != expected_value:
                return False
    return True


def _group_accuracy(evaluations: list[dict], key: str) -> dict:
    """Group evaluations by key and compute accuracy per group."""
    groups = defaultdict(list)
    for e in evaluations:
        groups[e[key]].append(e)

    result = {}
    for group_name, group_evals in groups.items():
        total = len(group_evals)
        full = sum(1 for e in group_evals if e["match"] == "full")
        result[group_name] = {
            "accuracy": round(full / total, 3) if total > 0 else 0.0,
            "total": total,
            "full_match": full,
        }
    return result
