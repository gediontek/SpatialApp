"""Canonical multi-step spatial query patterns and plan-mode validation.

This module serves TWO purposes:

1. **Pattern catalog** — a data-structured version of the multi-step chains
   documented in `chat.py` SYSTEM_PROMPT. Used by plan-mode to seed the LLM
   with canonical chain examples, and by tests to verify the set of patterns
   the system claims to handle. Not injected into the default chat SYSTEM_PROMPT
   at runtime — v2.1 Plan 02 showed that Gemini 2.5 Flash regresses under that
   kind of enrichment (see lessons-learned entry on prompt bloat).

2. **Plan validation + parameter threading** — helpers used by
   `ChatSession._execute_plan_inner` to: (a) resolve `$stepN.field` references
   between plan steps, (b) type-check output-input compatibility before
   execution and emit warnings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# QueryPattern catalog
# ---------------------------------------------------------------------------


@dataclass
class QueryPattern:
    """One canonical multi-step spatial query pattern.

    Fields:
        name: Stable identifier used in plan hints (e.g., "proximity-search").
        description: Human-readable summary of the intent this pattern serves.
        trigger_keywords: List of sets. Each set represents one alternative
            vocabulary — match is counted if ANY keyword in the set appears.
            A pattern matches when a non-trivial fraction of its sets fire.
        tool_chain: Ordered list of `{tool, param_template, output_key}`.
            `param_template` can use placeholders like `{feature_type}` for
            downstream templating. `output_key` is the symbolic name the
            pattern uses when threading results (not required at runtime).
        example_query: A single canonical example that triggers this pattern.
    """

    name: str
    description: str
    trigger_keywords: list[set[str]]
    tool_chain: list[dict[str, Any]]
    example_query: str


def _step(tool: str, output_key: str, **param_template: Any) -> dict[str, Any]:
    """Build a tool_chain step entry concisely."""
    return {
        "tool": tool,
        "param_template": param_template,
        "output_key": output_key,
    }


# The ten canonical patterns. Mirrors the chaining examples in chat.py
# SYSTEM_PROMPT — if you edit one, edit the other.
_PATTERNS: list[QueryPattern] = [
    QueryPattern(
        name="proximity-search",
        description="Find features within a buffer distance of a located place.",
        trigger_keywords=[
            {"within", "near", "around", "close to"},
            {"km of", "meters of", "metres of", "miles of", "mi of", "m of"},
        ],
        tool_chain=[
            _step("geocode", "origin", query="{location}"),
            _step("buffer", "buffer_layer", geometry="$step1.result", distance_m="{distance_m}"),
            _step("fetch_osm", "target_layer", feature_type="{feature_type}", location="{location}"),
            _step("spatial_query", "filtered_layer",
                  source_layer="$step3.layer_name",
                  predicate="within",
                  target_layer="$step2.layer_name"),
            _step("aggregate", "count", layer_name="$step4.layer_name", operation="count"),
        ],
        example_query="How many restaurants are within 2km of Central Park?",
    ),
    QueryPattern(
        name="overlay-analysis",
        description="Find the geometric overlap between two fetched layers as new polygons.",
        trigger_keywords=[
            {"overlap", "intersect", "where do", "common area", "in both"},
        ],
        tool_chain=[
            _step("fetch_osm", "layer_a", feature_type="{feature_a}", location="{location}"),
            _step("fetch_osm", "layer_b", feature_type="{feature_b}", location="{location}"),
            _step("intersection", "overlay",
                  layer_a="$step1.layer_name",
                  layer_b="$step2.layer_name"),
            _step("calculate_area", "area_stats", layer_name="$step3.layer_name"),
        ],
        example_query="Where do parks and flood zones overlap in Portland?",
    ),
    QueryPattern(
        name="compare-layers",
        description="Subtract one layer from another to find the unique remainder.",
        trigger_keywords=[
            {"subtract", "remove", "difference", "exclude", "minus"},
        ],
        tool_chain=[
            _step("fetch_osm", "layer_a", feature_type="{feature_a}", location="{location}"),
            _step("fetch_osm", "layer_b", feature_type="{feature_b}", location="{location}"),
            _step("difference", "remainder",
                  layer_a="$step1.layer_name",
                  layer_b="$step2.layer_name"),
            _step("calculate_area", "area_stats", layer_name="$step3.layer_name"),
        ],
        example_query="Remove water from the land area in Seattle.",
    ),
    QueryPattern(
        name="buffer-and-count",
        description="Count features within a buffer of a located place.",
        trigger_keywords=[
            {"how many", "count", "number of"},
            {"within", "near", "around"},
        ],
        tool_chain=[
            _step("geocode", "origin", query="{location}"),
            _step("buffer", "buffer_layer", geometry="$step1.result", distance_m="{distance_m}"),
            _step("search_nearby", "candidates",
                  lat="$step1.lat", lon="$step1.lon",
                  radius_m="{distance_m}",
                  feature_type="{feature_type}"),
            _step("spatial_query", "filtered",
                  source_layer="$step3.layer_name",
                  predicate="within",
                  target_layer="$step2.layer_name"),
            _step("aggregate", "count",
                  layer_name="$step4.layer_name",
                  operation="count"),
        ],
        example_query="How many cafes are within 500m of Times Square?",
    ),
    QueryPattern(
        name="route-with-nearby",
        description="Find features near a computed route geometry.",
        trigger_keywords=[
            {"along", "near route", "near my route", "on the way", "on my route"},
        ],
        tool_chain=[
            _step("find_route", "route",
                  from_location="{from_location}",
                  to_location="{to_location}"),
            _step("buffer", "route_buffer",
                  geometry="$step1.geometry",
                  distance_m="{corridor_m}"),
            _step("fetch_osm", "candidates",
                  feature_type="{feature_type}",
                  location="{location}"),
            _step("spatial_query", "result",
                  source_layer="$step3.layer_name",
                  predicate="within",
                  target_layer="$step2.layer_name"),
        ],
        example_query="Find restaurants along my route from Times Square to Brooklyn Bridge.",
    ),
    QueryPattern(
        name="coverage-analysis",
        description="Compute multi-facility reachability and coverage area.",
        trigger_keywords=[
            {"coverage", "reachable", "service area", "can reach", "reach within"},
        ],
        tool_chain=[
            _step("fetch_osm", "facilities",
                  feature_type="{facility_type}",
                  location="{location}"),
            _step("service_area", "coverage",
                  facility_layer="$step1.layer_name",
                  time_minutes="{time_minutes}"),
            _step("calculate_area", "area_stats", layer_name="$step2.layer_name"),
        ],
        example_query="What is the 15-minute driving coverage of hospitals in Chicago?",
    ),
    QueryPattern(
        name="cluster-and-hotspot",
        description="Identify clusters and statistically significant hot spots.",
        trigger_keywords=[
            {"cluster", "hot spot", "hotspot", "concentration", "hotspots"},
        ],
        tool_chain=[
            _step("fetch_osm", "points",
                  feature_type="{feature_type}",
                  location="{location}"),
            _step("spatial_statistics", "clusters",
                  layer_name="$step1.layer_name",
                  method="dbscan",
                  eps="{eps_m}",
                  min_samples="{min_samples}"),
            _step("hot_spot_analysis", "hot_spots",
                  layer_name="$step1.layer_name",
                  attribute="{attribute}"),
        ],
        example_query="Find clusters of crime points and show hot spots in Chicago.",
    ),
    QueryPattern(
        name="multi-criteria-filter",
        description="Filter features by attribute after fetching, then summarize.",
        trigger_keywords=[
            {"above", "below", "greater than", "less than", "taller", "larger", "smaller"},
        ],
        tool_chain=[
            _step("fetch_osm", "layer",
                  feature_type="{feature_type}",
                  location="{location}"),
            _step("filter_layer", "filtered",
                  layer_name="$step1.layer_name",
                  attribute="{attribute}",
                  operator="{operator}",
                  value="{value}"),
            _step("aggregate", "count",
                  layer_name="$step2.layer_name",
                  operation="count"),
        ],
        example_query="How many buildings taller than 50 meters are in downtown Seattle?",
    ),
    QueryPattern(
        name="import-and-analyze",
        description="Import tabular point data and run an analysis on it.",
        trigger_keywords=[
            {"import", "upload", "csv"},
            {"nearest", "heatmap", "cluster", "closest"},
        ],
        tool_chain=[
            _step("import_csv", "imported",
                  csv_data="{csv_data}",
                  lat_column="{lat_column}",
                  lon_column="{lon_column}"),
            _step("closest_facility", "nearest",
                  location="$step1.layer_name",
                  feature_type="{feature_type}",
                  count="{count}"),
            _step("heatmap", "density",
                  layer_name="$step1.layer_name"),
        ],
        example_query="Import this CSV and show a heatmap of the points.",
    ),
    QueryPattern(
        name="spatial-join",
        description="Tag each point with the polygon that contains it.",
        trigger_keywords=[
            {"which district", "tag each", "assign to", "belongs to", "containing"},
        ],
        tool_chain=[
            _step("fetch_osm", "points",
                  feature_type="{point_type}",
                  location="{location}"),
            _step("fetch_osm", "polygons",
                  feature_type="{polygon_type}",
                  location="{location}"),
            _step("point_in_polygon", "tagged",
                  point_layer="$step1.layer_name",
                  polygon_layer="$step2.layer_name"),
        ],
        example_query="Tag each store with its census tract.",
    ),
]


def get_all_patterns() -> list[QueryPattern]:
    """Return the full catalog of canonical patterns."""
    return list(_PATTERNS)


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------


_TOKEN_SPLIT_RE = re.compile(r"[^\w']+")


def _query_tokens(query: str) -> set[str]:
    """Lowercased bag of tokens + common 2-grams so 'km of' can match."""
    lowered = query.lower()
    words = [w for w in _TOKEN_SPLIT_RE.split(lowered) if w]
    bigrams = {f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)}
    return set(words) | bigrams


def _keyword_set_matches(keyword_set: set[str], tokens: set[str], query_lower: str) -> bool:
    """A keyword set matches if any of its members appears as a token OR
    substring of the lowered query. Substring matching handles multi-word
    phrases like 'near route' without building full n-gram indices."""
    for kw in keyword_set:
        if " " in kw:
            if kw in query_lower:
                return True
        elif kw in tokens:
            return True
    return False


def match_patterns(query: str, min_score: float = 0.3) -> list[tuple[QueryPattern, float]]:
    """Match a user query against the catalog, returning scored hits.

    Score is the fraction of a pattern's trigger_keywords sets that fired.
    Only patterns scoring >= min_score are returned, sorted descending.
    """
    if not query:
        return []
    tokens = _query_tokens(query)
    query_lower = query.lower()

    hits: list[tuple[QueryPattern, float]] = []
    for pattern in _PATTERNS:
        sets = pattern.trigger_keywords
        if not sets:
            continue
        matched = sum(
            1 for s in sets if _keyword_set_matches(s, tokens, query_lower)
        )
        score = matched / len(sets)
        if score >= min_score:
            hits.append((pattern, round(score, 3)))
    hits.sort(key=lambda t: t[1], reverse=True)
    return hits


# ---------------------------------------------------------------------------
# Plan-mode parameter threading + chain validation
# ---------------------------------------------------------------------------


_STEP_REF_RE = re.compile(r"\$step(\d+)\.([A-Za-z_][A-Za-z0-9_]*)")


def resolve_step_references(
    params: Any,
    step_outputs: dict[int, dict],
) -> Any:
    """Recursively resolve `$stepN.field` references against prior step outputs.

    Supports nested dicts, lists, and string values. A string that is
    ONLY a reference (e.g., `"$step2.layer_name"`) is replaced with the
    full typed value. A string that CONTAINS a reference (e.g.,
    `"prefix_$step1.id"`) performs string interpolation using str().

    Raises:
        ValueError: if a reference cannot be resolved. Message names the
        step number and field so the user can fix the plan.
    """

    def resolve_value(v: Any) -> Any:
        if isinstance(v, str):
            return _resolve_string(v, step_outputs)
        if isinstance(v, list):
            return [resolve_value(x) for x in v]
        if isinstance(v, dict):
            return {k: resolve_value(val) for k, val in v.items()}
        return v

    return resolve_value(params)


def _resolve_string(s: str, step_outputs: dict[int, dict]) -> Any:
    """Resolve references in a single string value."""
    refs = list(_STEP_REF_RE.finditer(s))
    if not refs:
        return s

    # If the string is ONLY the reference, return the raw value (preserves type).
    if len(refs) == 1 and refs[0].group(0) == s.strip():
        step_num = int(refs[0].group(1))
        field_name = refs[0].group(2)
        return _lookup_ref(step_num, field_name, step_outputs)

    # Otherwise, interpolate as a string.
    def sub(match: re.Match) -> str:
        step_num = int(match.group(1))
        field_name = match.group(2)
        return str(_lookup_ref(step_num, field_name, step_outputs))

    return _STEP_REF_RE.sub(sub, s)


def _lookup_ref(step_num: int, field_name: str, step_outputs: dict[int, dict]) -> Any:
    if step_num not in step_outputs:
        raise ValueError(
            f"Cannot resolve $step{step_num}.{field_name}: "
            f"step {step_num} has not executed yet."
        )
    output = step_outputs[step_num]
    if not isinstance(output, dict) or field_name not in output:
        raise ValueError(
            f"Step {step_num} has no output field '{field_name}' "
            f"(available: {sorted(output.keys()) if isinstance(output, dict) else '<non-dict>'})."
        )
    return output[field_name]


# ---------------------------------------------------------------------------
# Tool I/O type registry + chain validation
# ---------------------------------------------------------------------------

# Simplified type system for chain validation. Type labels:
#   "layer_name"   — a named layer in the layer_store
#   "geojson"      — raw GeoJSON geometry or FeatureCollection
#   "coordinates"  — lat/lon values
#   "number"       — scalar numeric
#   "string"       — scalar string
#
# Covers the most-chained tools. Omitted tools are conservatively treated as
# accepting/producing unknown types — validate_plan_chain skips them.
TOOL_IO_TYPES: dict[str, dict[str, dict[str, str]]] = {
    "geocode": {
        "inputs": {"query": "string"},
        "outputs": {"lat": "number", "lon": "number", "bbox": "geojson", "display_name": "string"},
    },
    "reverse_geocode": {
        "inputs": {"lat": "number", "lon": "number"},
        "outputs": {"display_name": "string"},
    },
    "batch_geocode": {
        "inputs": {"addresses": "string"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "fetch_osm": {
        "inputs": {"feature_type": "string", "location": "string", "bbox": "string"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "search_nearby": {
        "inputs": {"lat": "number", "lon": "number", "radius_m": "number", "feature_type": "string"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "closest_facility": {
        "inputs": {"location": "string", "feature_type": "string", "count": "number"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "buffer": {
        "inputs": {"layer_name": "layer_name", "geometry": "geojson", "distance_m": "number"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "spatial_query": {
        "inputs": {"source_layer": "layer_name", "target_layer": "layer_name", "predicate": "string"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "aggregate": {
        "inputs": {"layer_name": "layer_name", "operation": "string"},
        "outputs": {"count": "number", "total_area_m2": "number"},
    },
    "calculate_area": {
        "inputs": {"layer_name": "layer_name", "geometry": "geojson"},
        "outputs": {"area_m2": "number", "area_km2": "number"},
    },
    "measure_distance": {
        "inputs": {"from_location": "string", "to_location": "string"},
        "outputs": {"distance_m": "number", "distance_km": "number"},
    },
    "filter_layer": {
        "inputs": {"layer_name": "layer_name", "attribute": "string", "operator": "string", "value": "string"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "style_layer": {
        "inputs": {"layer_name": "layer_name", "color": "string"},
        "outputs": {"layer_name": "layer_name"},
    },
    "highlight_features": {
        "inputs": {"layer_name": "layer_name", "attribute": "string", "value": "string"},
        "outputs": {"layer_name": "layer_name"},
    },
    "merge_layers": {
        "inputs": {"layer_a": "layer_name", "layer_b": "layer_name"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "intersection": {
        "inputs": {"layer_a": "layer_name", "layer_b": "layer_name"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "difference": {
        "inputs": {"layer_a": "layer_name", "layer_b": "layer_name"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "symmetric_difference": {
        "inputs": {"layer_a": "layer_name", "layer_b": "layer_name"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "clip": {
        "inputs": {"clip_layer": "layer_name", "mask_layer": "layer_name"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "centroid": {
        "inputs": {"layer_name": "layer_name"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "convex_hull": {
        "inputs": {"layer_name": "layer_name"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "bounding_box": {
        "inputs": {"layer_name": "layer_name"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "simplify": {
        "inputs": {"layer_name": "layer_name", "tolerance": "number"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "dissolve": {
        "inputs": {"layer_name": "layer_name", "by": "string"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "voronoi": {
        "inputs": {"layer_name": "layer_name"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "point_in_polygon": {
        "inputs": {"polygon_layer": "layer_name", "point_layer": "layer_name", "lat": "number", "lon": "number"},
        "outputs": {"layer_name": "layer_name", "containing_polygon": "geojson"},
    },
    "attribute_join": {
        "inputs": {"layer_name": "layer_name", "join_data": "string", "layer_key": "string", "data_key": "string"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "spatial_statistics": {
        "inputs": {"layer_name": "layer_name", "method": "string"},
        "outputs": {"layer_name": "layer_name", "nni": "number"},
    },
    "hot_spot_analysis": {
        "inputs": {"layer_name": "layer_name", "attribute": "string"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "find_route": {
        "inputs": {"from_location": "string", "to_location": "string"},
        "outputs": {"layer_name": "layer_name", "geometry": "geojson", "distance_km": "number"},
    },
    "isochrone": {
        "inputs": {"lat": "number", "lon": "number", "time_minutes": "number"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "heatmap": {
        "inputs": {"layer_name": "layer_name"},
        "outputs": {"layer_name": "layer_name", "points": "geojson"},
    },
    "optimize_route": {
        "inputs": {"locations": "string"},
        "outputs": {"layer_name": "layer_name", "order": "string"},
    },
    "service_area": {
        "inputs": {"facility_layer": "layer_name", "time_minutes": "number"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "od_matrix": {
        "inputs": {"origins": "string", "destinations": "string"},
        "outputs": {"matrix": "string"},
    },
    "validate_topology": {
        "inputs": {"layer_name": "layer_name"},
        "outputs": {"invalid_count": "number", "valid_count": "number"},
    },
    "repair_topology": {
        "inputs": {"layer_name": "layer_name"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "import_csv": {
        "inputs": {"csv_data": "string", "lat_column": "string", "lon_column": "string"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "import_layer": {
        "inputs": {"geojson": "geojson"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "import_wkt": {
        "inputs": {"wkt": "string"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "import_kml": {
        "inputs": {"kml_data": "string"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "import_geoparquet": {
        "inputs": {"parquet_data": "string"},
        "outputs": {"layer_name": "layer_name", "geojson": "geojson"},
    },
    "export_layer": {
        "inputs": {"layer_name": "layer_name", "format": "string"},
        "outputs": {"download_url": "string"},
    },
}


def validate_plan_chain(steps: list[dict]) -> list[str]:
    """Check each `$stepN.field` reference in a plan against TOOL_IO_TYPES.

    Returns a list of human-readable warning strings. An empty list means
    the chain's type references are all consistent.

    This is a soft check — it warns rather than rejecting, so callers can
    decide whether to proceed. Unknown tools (not in TOOL_IO_TYPES) are
    skipped, not flagged as errors.
    """
    warnings: list[str] = []
    step_by_num: dict[int, dict] = {}

    for i, step in enumerate(steps, start=1):
        step_num = step.get("step") or i
        step_by_num[step_num] = step
        tool = step.get("tool")
        params = step.get("params") or {}
        if not tool:
            warnings.append(f"Step {step_num}: missing tool name.")
            continue
        tool_io = TOOL_IO_TYPES.get(tool)
        if tool_io is None:
            continue  # unknown tool — don't flag; Plan 05 M1 covers unknowns
        for param_name, value in params.items():
            expected_type = tool_io["inputs"].get(param_name)
            if expected_type is None:
                continue  # extra param; dispatch will validate at runtime
            refs = _refs_in(value)
            for ref_step, ref_field in refs:
                ref_io = _ref_output_type(ref_step, ref_field, step_by_num)
                if ref_io is None:
                    continue  # unknown — skip
                if ref_io != expected_type:
                    warnings.append(
                        f"Step {step_num} ({tool}) expects {expected_type} for "
                        f"'{param_name}' but step {ref_step} (referenced field "
                        f"'{ref_field}') produces {ref_io}."
                    )
    return warnings


def _refs_in(value: Any) -> list[tuple[int, str]]:
    """Collect all (step_num, field) references inside a value."""
    if isinstance(value, str):
        return [(int(m.group(1)), m.group(2)) for m in _STEP_REF_RE.finditer(value)]
    if isinstance(value, list):
        out: list[tuple[int, str]] = []
        for x in value:
            out.extend(_refs_in(x))
        return out
    if isinstance(value, dict):
        out = []
        for v in value.values():
            out.extend(_refs_in(v))
        return out
    return []


def _ref_output_type(
    ref_step: int,
    ref_field: str,
    step_by_num: dict[int, dict],
) -> str | None:
    """Return the declared output type for a given step's field, or None."""
    step = step_by_num.get(ref_step)
    if not step:
        return None
    tool = step.get("tool")
    tool_io = TOOL_IO_TYPES.get(tool or "")
    if not tool_io:
        return None
    return tool_io["outputs"].get(ref_field)
