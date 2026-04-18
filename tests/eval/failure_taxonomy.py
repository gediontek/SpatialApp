"""Failure taxonomy for NL-GIS accuracy audits.

Classifies each failed evaluation into exactly one of seven categories so that
failure patterns can be ranked and routed to the correct fix target (tool
description edit, system prompt change, query reformulation).
"""

from __future__ import annotations

from collections import defaultdict
from enum import Enum
from typing import Optional


class FailureCategory(Enum):
    """Seven canonical ways a tool-selection evaluation can fail.

    Used by classify_failure() to route each mismatch to a fix target.
    """

    WRONG_TOOL = "wrong_tool"
    RIGHT_TOOL_WRONG_PARAMS = "right_tool_wrong_params"
    MISSING_CHAIN_STEP = "missing_chain_step"
    EXTRA_CHAIN_STEP = "extra_chain_step"
    AMBIGUOUS_QUERY = "ambiguous_query"
    TOOL_DESCRIPTION_MISLEADING = "tool_description_misleading"
    WRONG_CHAIN_ORDER = "wrong_chain_order"

    @property
    def label(self) -> str:
        return self.value

    @property
    def description(self) -> str:
        return _DESCRIPTIONS[self]


_DESCRIPTIONS: dict[FailureCategory, str] = {
    FailureCategory.WRONG_TOOL: (
        "Selected a different tool entirely. No expected tool present in the "
        "actual chain. Fix target: tool description (disambiguate confusable "
        "pairs) or system prompt chain pattern."
    ),
    FailureCategory.RIGHT_TOOL_WRONG_PARAMS: (
        "Correct tool selected but parameter values are wrong or missing. Fix "
        "target: tool parameter descriptions (add examples, units, enums)."
    ),
    FailureCategory.MISSING_CHAIN_STEP: (
        "Multi-tool query where at least one expected tool is absent from the "
        "actual chain. Fix target: system prompt chain pattern that teaches "
        "the LLM to compose this sequence."
    ),
    FailureCategory.EXTRA_CHAIN_STEP: (
        "All expected tools present, but the actual chain includes additional "
        "unnecessary tools. Fix target: tool description (add 'NEVER DO' "
        "guidance) or system prompt (concise decision rules)."
    ),
    FailureCategory.AMBIGUOUS_QUERY: (
        "Query is genuinely ambiguous — multiple valid tool selections exist. "
        "Fix target: reformulate the reference query, or mark as accepted "
        "ambiguity."
    ),
    FailureCategory.TOOL_DESCRIPTION_MISLEADING: (
        "LLM selected a tool whose description suggested it handles this use "
        "case, but it does not. Fix target: rewrite the misleading description."
    ),
    FailureCategory.WRONG_CHAIN_ORDER: (
        "All expected tools present but in the wrong relative order. Fix "
        "target: system prompt chain pattern with explicit step numbering."
    ),
}


# Layer name vocabularies used to distinguish WRONG_TOOL from related-tool
# confusion. When a tool selection error involves two tools from the same
# semantic family, treat it as potentially description-driven rather than
# a pure wrong-tool error.
_SEMANTIC_FAMILIES: list[set[str]] = [
    # OSM fetch family
    {"fetch_osm", "search_nearby"},
    # Overlay family
    {"intersection", "difference", "symmetric_difference"},
    # Buffer/proximity
    {"buffer", "spatial_query"},
    # Import family
    {"import_layer", "import_csv", "import_kml", "import_wkt",
     "import_geoparquet"},
    # Export family
    {"export_layer", "export_annotations", "export_geoparquet"},
    # Point-in-polygon vs spatial_query(within)
    {"point_in_polygon", "spatial_query"},
    # Clip vs intersection (both cut geometry)
    {"clip", "intersection"},
    # Geocode vs reverse_geocode vs batch_geocode
    {"geocode", "reverse_geocode", "batch_geocode"},
    # Aggregate vs attribute_statistics vs describe_layer
    {"aggregate", "attribute_statistics", "describe_layer"},
    # CRS family
    {"reproject_layer", "detect_crs"},
    # Topology pair
    {"validate_topology", "repair_topology"},
    # Routing family
    {"find_route", "optimize_route", "closest_facility"},
    # Service / coverage
    {"isochrone", "service_area"},
    # Dissolve vs merge_features vs merge_layers
    {"dissolve", "merge_features", "merge_layers"},
]


def _are_semantically_related(tool_a: str, tool_b: str) -> bool:
    """Return True if two tools belong to the same semantic family.

    Semantic-family overlap suggests the LLM confused similar tools —
    the failure is likely description-driven rather than a random wrong pick.
    """
    if tool_a == tool_b:
        return True
    for family in _SEMANTIC_FAMILIES:
        if tool_a in family and tool_b in family:
            return True
    return False


def classify_failure(result: dict) -> Optional[FailureCategory]:
    """Return the most specific failure category for an evaluation result.

    Args:
        result: dict from ToolSelectionEvaluator.evaluate_single(). Must
            include 'match', 'missing_tools', 'extra_tools', 'param_match',
            'chain_order_correct', 'expected_tools', 'actual_tools'.

    Returns:
        FailureCategory, or None if the query passed (match == "full" and
        param_match is not False).
    """
    match = result.get("match")
    missing = result.get("missing_tools") or []
    extra = result.get("extra_tools") or []
    param_match = result.get("param_match")
    chain_order = result.get("chain_order_correct")
    expected = result.get("expected_tools") or []
    actual = result.get("actual_tools") or []

    # Passing query: full tool match AND param check didn't fail.
    if match == "full" and param_match is not False:
        return None

    # RIGHT_TOOL_WRONG_PARAMS: all tools correct, but params wrong.
    if match == "full" and param_match is False:
        return FailureCategory.RIGHT_TOOL_WRONG_PARAMS

    # WRONG_CHAIN_ORDER: tools match (no missing, no extra) but order wrong.
    # This can only arise when multiset comparison passes but subsequence fails.
    if not missing and not extra and chain_order is False:
        return FailureCategory.WRONG_CHAIN_ORDER

    # EXTRA_CHAIN_STEP: all expected tools present, actual has extras.
    if not missing and extra:
        return FailureCategory.EXTRA_CHAIN_STEP

    # No tool was selected at all — treat as missing chain step for multi-tool
    # queries, wrong tool for single-tool queries.
    if missing and not actual:
        if len(expected) >= 2:
            return FailureCategory.MISSING_CHAIN_STEP
        return FailureCategory.WRONG_TOOL

    # MISSING_CHAIN_STEP: multi-tool query with some tools missing.
    if len(expected) >= 2 and missing:
        # If the extras are semantically related to the missing tools, the LLM
        # swapped one tool for a neighbor — description-driven confusion.
        if extra and all(
            any(_are_semantically_related(e, m) for m in missing) for e in extra
        ):
            return FailureCategory.TOOL_DESCRIPTION_MISLEADING
        return FailureCategory.MISSING_CHAIN_STEP

    # Single-tool query with wrong tool: is the extra semantically related?
    if missing and extra:
        if any(
            _are_semantically_related(e, m) for e in extra for m in missing
        ):
            return FailureCategory.TOOL_DESCRIPTION_MISLEADING
        return FailureCategory.WRONG_TOOL

    # Fallback: no clear signal — treat as ambiguous.
    return FailureCategory.AMBIGUOUS_QUERY


def rank_failure_patterns(
    evaluations: list[dict],
    top_n: int = 10,
) -> list[dict]:
    """Rank failure patterns by frequency.

    Groups failures by (category, confused tool pair) and returns the top N
    patterns with supporting data for docs/v2/failure-patterns.md.

    Args:
        evaluations: List of per-query result dicts from evaluate_batch().
                     Each must include 'failure_category' (str or None).
        top_n: Number of patterns to return (default 10).

    Returns:
        List of dicts:
            {
                "rank": int,
                "category": FailureCategory label,
                "category_description": str,
                "count": int,
                "percentage": float,  # of total failures
                "affected_tools": list[str],   # tools involved
                "confusion_pairs": list[tuple[str, str]],  # (expected, extra)
                "example_query_ids": list[str],  # up to 3
                "example_queries": list[str],    # up to 3
                "fix_target": str,  # one of: tool_description | system_prompt | query_reformulation
            }
    """
    failures = [e for e in evaluations if e.get("failure_category")]
    total_failures = len(failures)
    if total_failures == 0:
        return []

    # Group by (category, sorted expected-extra pair signature)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for ev in failures:
        cat = ev["failure_category"]
        expected = tuple(sorted(ev.get("expected_tools") or []))
        extra = tuple(sorted(ev.get("extra_tools") or []))
        missing = tuple(sorted(ev.get("missing_tools") or []))
        # Confusion signature: which expected ended up replaced by which extra
        signature = (cat, expected, extra, missing)
        groups[signature].append(ev)

    # Sort groups by size descending
    ranked = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)

    patterns = []
    for rank, ((cat_label, expected, extra, missing), group) in enumerate(
        ranked[:top_n], start=1
    ):
        cat_enum = _category_from_label(cat_label)
        fix_target = _fix_target_for(cat_enum)
        affected_tools = sorted(set(list(expected) + list(extra) + list(missing)))
        confusion_pairs = []
        if extra and missing:
            for m in missing:
                for e in extra:
                    confusion_pairs.append((m, e))
        patterns.append({
            "rank": rank,
            "category": cat_label,
            "category_description": (
                cat_enum.description if cat_enum else "Unknown category"
            ),
            "count": len(group),
            "percentage": round(100.0 * len(group) / total_failures, 1),
            "affected_tools": affected_tools,
            "confusion_pairs": confusion_pairs,
            "example_query_ids": [ev["query_id"] for ev in group[:3]],
            "example_queries": [ev["query"] for ev in group[:3]],
            "fix_target": fix_target,
        })

    return patterns


def _category_from_label(label: str) -> Optional[FailureCategory]:
    for cat in FailureCategory:
        if cat.value == label:
            return cat
    return None


_FIX_TARGETS: dict[FailureCategory, str] = {
    FailureCategory.WRONG_TOOL: "tool_description",
    FailureCategory.RIGHT_TOOL_WRONG_PARAMS: "tool_description",  # param examples
    FailureCategory.MISSING_CHAIN_STEP: "system_prompt",
    FailureCategory.EXTRA_CHAIN_STEP: "tool_description",
    FailureCategory.AMBIGUOUS_QUERY: "query_reformulation",
    FailureCategory.TOOL_DESCRIPTION_MISLEADING: "tool_description",
    FailureCategory.WRONG_CHAIN_ORDER: "system_prompt",
}


def _fix_target_for(category: Optional[FailureCategory]) -> str:
    if category is None:
        return "unknown"
    return _FIX_TARGETS.get(category, "unknown")
