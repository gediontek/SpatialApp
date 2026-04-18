"""Tool selection evaluation engine.

Compares actual tool selections against reference queries to measure
accuracy of the LLM's tool selection behavior.
"""

from collections import defaultdict
from typing import Optional

from tests.eval.reference_queries import ALL_QUERIES, REFERENCE_QUERIES
from tests.eval.failure_taxonomy import FailureCategory, classify_failure


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
            "actual_params": actual_params or {},
            "missing_tools": missing,
            "extra_tools": extra,
            "complexity": ref.get("complexity", "unknown"),
            "category": ref.get("category", "unknown"),
        }

        # Check params if expected_params is defined and actual_params provided
        expected_params = ref.get("expected_params")
        if expected_params and actual_params is not None:
            ps = _score_params(expected_params, actual_params)
            result["param_score"] = ps
            result["param_match"] = ps["score"] == 1.0
        elif expected_params and actual_params is None:
            result["param_score"] = {
                "score": 0.0, "total_params": 0, "matched": 0,
                "mismatched": [], "missing": [],
            }
            result["param_match"] = False
        else:
            result["param_score"] = None
            result["param_match"] = None  # No param check applicable

        # Chain order check: only meaningful for multi-tool queries
        if len(expected) >= 2:
            result["chain_order_correct"] = _is_subsequence(expected, actual_tools)
        else:
            result["chain_order_correct"] = None

        # Failure classification: None for passing queries, category label otherwise
        category = classify_failure(result)
        result["failure_category"] = category.label if category else None

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

        # Parameter accuracy: count queries that had a param check applicable
        # (param_match is True or False) and compute ratio of True.
        param_checked = [e for e in evaluations if e["param_match"] is not None]
        param_matched = sum(1 for e in param_checked if e["param_match"])
        param_accuracy = (
            param_matched / len(param_checked) if param_checked else 0.0
        )

        # Granular param accuracy: average of per-query param_score["score"].
        # This gives partial credit for queries that got most params right,
        # unlike the strict all-or-nothing param_match metric above.
        scored = [
            e for e in evaluations
            if e.get("param_score") and e["param_score"].get("total_params")
        ]
        granular_total = sum(e["param_score"]["total_params"] for e in scored)
        granular_matched = sum(e["param_score"]["matched"] for e in scored)
        granular_param_accuracy = (
            granular_matched / granular_total if granular_total else 0.0
        )

        # Chain accuracy: only multi-tool queries where ordering is meaningful.
        # Denominator: multi-tool queries at moderate/complex/multi_step complexity.
        chain_eligible = [
            e for e in evaluations
            if e["chain_order_correct"] is not None
            and e["complexity"] in ("moderate", "complex", "multi_step")
        ]
        chain_correct = sum(1 for e in chain_eligible if e["chain_order_correct"])
        chain_accuracy = (
            chain_correct / len(chain_eligible) if chain_eligible else 0.0
        )

        # By complexity
        by_complexity = _group_accuracy(evaluations, "complexity")
        # By category
        by_category = _group_accuracy(evaluations, "category")
        # Chain accuracy by complexity (multi-tool queries only)
        chain_by_complexity = _chain_accuracy_by_complexity(chain_eligible)
        # Failure breakdown by taxonomy category
        failure_breakdown = _failure_breakdown(evaluations)

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
            "param_accuracy": round(param_accuracy, 3),
            "param_checked_total": len(param_checked),
            "param_matched": param_matched,
            "granular_param_accuracy": round(granular_param_accuracy, 3),
            "granular_param_total": granular_total,
            "granular_param_matched": granular_matched,
            "chain_accuracy": round(chain_accuracy, 3),
            "chain_eligible_total": len(chain_eligible),
            "chain_correct": chain_correct,
            "by_complexity": by_complexity,
            "by_category": by_category,
            "chain_by_complexity": chain_by_complexity,
            "failure_breakdown": failure_breakdown,
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
            f"- **Tool selection accuracy** (full matches / total): **{summary['accuracy']:.1%}**",
            (
                f"- **Parameter accuracy**: **{summary['param_accuracy']:.1%}** "
                f"({summary['param_matched']}/{summary['param_checked_total']} queries with param checks)"
            ),
            (
                f"- **Chain accuracy** (multi-tool queries): **{summary['chain_accuracy']:.1%}** "
                f"({summary['chain_correct']}/{summary['chain_eligible_total']} multi-tool queries)"
            ),
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

        if summary["chain_by_complexity"]:
            lines.extend([
                "",
                "## Chain Accuracy by Complexity",
                "",
                "Multi-tool queries only: correct relative order of expected tools within the actual tool list.",
                "",
                "| Complexity | Chain Accuracy | Multi-tool Count |",
                "|------------|----------------|------------------|",
            ])
            for level in ("moderate", "complex", "multi_step"):
                if level in summary["chain_by_complexity"]:
                    data = summary["chain_by_complexity"][level]
                    lines.append(
                        f"| {level} | {data['accuracy']:.1%} | {data['total']} |"
                    )

        if summary["failure_breakdown"]:
            total_failures = sum(
                d["count"] for d in summary["failure_breakdown"].values()
            )
            lines.extend([
                "",
                "## Failure Classification",
                "",
                "| Category | Count | Percentage | Example Query IDs |",
                "|----------|-------|------------|-------------------|",
            ])
            sorted_breakdown = sorted(
                summary["failure_breakdown"].items(),
                key=lambda kv: kv[1]["count"],
                reverse=True,
            )
            for cat, data in sorted_breakdown:
                pct = (
                    100.0 * data["count"] / total_failures
                    if total_failures else 0.0
                )
                examples = ", ".join(data["query_ids"][:3])
                lines.append(
                    f"| {cat} | {data['count']} | {pct:.1f}% | {examples} |"
                )

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
    Preserved for backward compatibility; new code should use _score_params.
    """
    return _score_params(expected_params, actual_params)["score"] == 1.0


# ---------------------------------------------------------------------------
# Plan 06 M2: granular parameter scoring
# ---------------------------------------------------------------------------


# Param names that should be matched with geographic tolerance rather than
# exact equality. Coordinates with 0.01° resolution (~1km) are considered equal.
_COORD_NAMES = {"lat", "lon", "lng", "latitude", "longitude"}
_COORD_TOLERANCE_DEG = 0.01

# Param names that should be matched after CRS normalization
# ("EPSG:4326" == "epsg:4326" == "WGS84" == "wgs84").
_CRS_NAMES = {"crs", "srs", "projection", "from_crs", "to_crs"}
_CRS_ALIASES = {
    "wgs84": "EPSG:4326",
    "wgs 84": "EPSG:4326",
    "nad83": "EPSG:4269",
    "web mercator": "EPSG:3857",
    "pseudo-mercator": "EPSG:3857",
}


def _normalize_crs(value) -> str:
    """Canonicalize a CRS identifier so 'wgs84' and 'EPSG:4326' match."""
    if value is None:
        return ""
    s = str(value).strip().lower()
    if s in _CRS_ALIASES:
        return _CRS_ALIASES[s]
    # Int EPSG codes -> "EPSG:N"
    try:
        return f"EPSG:{int(s)}"
    except (TypeError, ValueError):
        pass
    # "epsg:4326" -> "EPSG:4326"
    if s.startswith("epsg:"):
        return f"EPSG:{s.split(':', 1)[1].strip()}"
    return s.upper()


def _param_values_match(param_name: str, expected, actual) -> bool:
    """Return True if two values are considered equal for eval purposes.

    Applies name-aware tolerance:
    - coordinates: within ±0.01° (~1km)
    - CRS: normalized by _normalize_crs
    - floats: within ±0.001
    - strings: case-insensitive
    """
    if actual is None:
        return False
    lname = param_name.lower()

    # Coordinate tolerance
    if lname in _COORD_NAMES:
        try:
            return abs(float(expected) - float(actual)) <= _COORD_TOLERANCE_DEG
        except (TypeError, ValueError):
            return False

    # CRS normalization
    if lname in _CRS_NAMES:
        return _normalize_crs(expected) == _normalize_crs(actual)

    # Numeric tolerance
    if isinstance(expected, float) or isinstance(actual, float):
        try:
            return abs(float(expected) - float(actual)) <= 0.001
        except (TypeError, ValueError):
            return False

    # Case-insensitive for strings
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().lower() == actual.strip().lower()

    return expected == actual


def _score_params(expected_params: dict, actual_params: dict) -> dict:
    """Granular parameter score across one or more tools.

    Returns:
        {
            "score": float (0.0-1.0),
            "total_params": int,
            "matched": int,
            "mismatched": list[{"tool", "param", "expected", "actual"}],
            "missing":    list[{"tool", "param", "expected"}],
        }
    Extra params in `actual_params` not listed in `expected_params` are
    ignored (consistent with the prior boolean check).
    """
    total = 0
    matched = 0
    mismatched: list[dict] = []
    missing: list[dict] = []

    for tool, expected_tool in (expected_params or {}).items():
        actual_tool = (actual_params or {}).get(tool) or {}
        for param_name, expected_value in (expected_tool or {}).items():
            total += 1
            if param_name not in actual_tool:
                missing.append({
                    "tool": tool,
                    "param": param_name,
                    "expected": expected_value,
                })
                continue
            actual_value = actual_tool[param_name]
            if _param_values_match(param_name, expected_value, actual_value):
                matched += 1
            else:
                mismatched.append({
                    "tool": tool,
                    "param": param_name,
                    "expected": expected_value,
                    "actual": actual_value,
                })

    score = matched / total if total else 0.0
    return {
        "score": round(score, 3),
        "total_params": total,
        "matched": matched,
        "mismatched": mismatched,
        "missing": missing,
    }


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


def _is_subsequence(expected: list, actual: list) -> bool:
    """Return True if expected appears as a subsequence of actual.

    Tools must appear in the same relative order, but may be interleaved with
    other tools. Handles duplicates correctly — each occurrence in expected
    must be matched by a distinct later occurrence in actual.
    """
    it = iter(actual)
    return all(tool in it for tool in expected)


def _failure_breakdown(evaluations: list[dict]) -> dict:
    """Group failed evaluations by taxonomy category.

    Returns {category_label: {"count": int, "query_ids": list[str]}}.
    Passing queries (failure_category is None) are excluded.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for e in evaluations:
        cat = e.get("failure_category")
        if cat:
            groups[cat].append(e["query_id"])
    return {
        cat: {"count": len(qids), "query_ids": qids}
        for cat, qids in groups.items()
    }


def _chain_accuracy_by_complexity(chain_eligible: list[dict]) -> dict:
    """Group multi-tool evaluations by complexity and compute chain accuracy."""
    groups = defaultdict(list)
    for e in chain_eligible:
        groups[e["complexity"]].append(e)

    result = {}
    for complexity, group_evals in groups.items():
        total = len(group_evals)
        correct = sum(1 for e in group_evals if e["chain_order_correct"])
        result[complexity] = {
            "accuracy": round(correct / total, 3) if total > 0 else 0.0,
            "total": total,
            "correct": correct,
        }
    return result
