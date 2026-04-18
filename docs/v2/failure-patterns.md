# SpatialApp v2.1 — Ranked Failure Patterns

**Source baseline:** [`baseline-classified.json`](baseline-classified.json) — gemini / gemini-2.5-flash, 62 queries, 32 failures, run 2026-04-18T01:43:44Z.

**Method:** `tests/eval/failure_taxonomy.py:classify_failure()` assigns each failure to one of seven categories; `rank_failure_patterns()` groups by (category, expected-tools, extra-tools, missing-tools) signature and ranks by count. The rollup table below covers ALL failures; the detailed section describes the top 10 patterns.

---

## Fix-Target Rollup (all failures)

| Fix target | Failures | % of failures | Downstream plan |
|------------|----------|---------------|-----------------|
| tool_description | 26 | 81.2% | Prompt 2 (tool-descriptions) |
| system_prompt | 6 | 18.8% | Prompt 3 (complex-queries) |

## Failures by Category (all failures)

| Category | Count | % of failures |
|----------|-------|---------------|
| wrong_tool | 20 | 62.5% |
| missing_chain_step | 6 | 18.8% |
| extra_chain_step | 3 | 9.4% |
| right_tool_wrong_params | 2 | 6.2% |
| tool_description_misleading | 1 | 3.1% |

**Read:** Tool-description edits (plan 02) address **~81%** of failures. System-prompt chain patterns (plan 03) address the remaining **~19%**. Plan 02 is the highest-leverage first move.

## Top 10 Patterns (detailed)

Ranked by frequency. Each pattern is a distinct (category, tool-set) signature with a concrete remediation target.

| Rank | Pattern | Count | Fix Target | Downstream Plan |
|------|---------|-------|------------|-----------------|
| 1 | wrong_tool (spatial_statistics) | 2 | tool_description | Prompt 2 (tool-descriptions) |
| 2 | missing_chain_step (repair_topology, validate_topology) | 2 | system_prompt | Prompt 3 (complex-queries) |
| 3 | wrong_tool (reverse_geocode) | 1 | tool_description | Prompt 2 (tool-descriptions) |
| 4 | right_tool_wrong_params (calculate_area) | 1 | tool_description | Prompt 2 (tool-descriptions) |
| 5 | tool_description_misleading (spatial_query→buffer) | 1 | tool_description | Prompt 2 (tool-descriptions) |
| 6 | wrong_tool (point_in_polygon→fetch_osm) | 1 | tool_description | Prompt 2 (tool-descriptions) |
| 7 | wrong_tool (point_in_polygon) | 1 | tool_description | Prompt 2 (tool-descriptions) |
| 8 | wrong_tool (convex_hull) | 1 | tool_description | Prompt 2 (tool-descriptions) |
| 9 | wrong_tool (centroid) | 1 | tool_description | Prompt 2 (tool-descriptions) |
| 10 | wrong_tool (dissolve) | 1 | tool_description | Prompt 2 (tool-descriptions) |

---

## Detailed Patterns

### #1: wrong_tool — spatial_statistics

**Frequency:** 2 occurrence(s) (6.2% of failures)

**Affected tools:** `spatial_statistics`

**Example failing queries:**
- **Q012**: Are the crime points spatially clustered?
- **Q013**: Run DBSCAN clustering on the restaurant data with 200m radius and minimum 3 points

**Root cause hypothesis:** LLM doesn't recognize the expected tool as applicable — often returns no tool at all. Activation signal is weak; description vocabulary doesn't match user phrasing.

**Fix target:** `tool_description` → Prompt 2 (tool-descriptions)

**Specific actions:**
- In `nl_gis/tools.py`, enrich `spatial_statistics` description with concrete example queries and disambiguation against neighboring tools. If Gemini returned no tool at all for this query, the description's activation signal is too weak — add 'Use for ...' examples with user-phrasing keywords.

---

### #2: missing_chain_step — repair_topology, validate_topology

**Frequency:** 2 occurrence(s) (6.2% of failures)

**Affected tools:** `repair_topology`, `validate_topology`

**Example failing queries:**
- **S023**: Check if the imported_parcels polygons are valid and fix any topology errors
- **S031**: Validate topology on the boundaries layer, and if there are issues, repair them into a clean version

**Root cause hypothesis:** LLM executed only part of the required chain. No system-prompt pattern taught the full sequence.

**Fix target:** `system_prompt` → Prompt 3 (complex-queries)

**Specific actions:**
- Add a chain pattern to `nl_gis/chat.py` SYSTEM_PROMPT showing the full `repair_topology → validate_topology` sequence with a worked example.

---

### #3: wrong_tool — reverse_geocode

**Frequency:** 1 occurrence(s) (3.1% of failures)

**Affected tools:** `reverse_geocode`

**Example failing queries:**
- **Q002**: What place is at coordinates 40.7128, -74.0060?

**Root cause hypothesis:** LLM doesn't recognize the expected tool as applicable — often returns no tool at all. Activation signal is weak; description vocabulary doesn't match user phrasing.

**Fix target:** `tool_description` → Prompt 2 (tool-descriptions)

**Specific actions:**
- In `nl_gis/tools.py`, enrich `reverse_geocode` description with concrete example queries and disambiguation against neighboring tools. If Gemini returned no tool at all for this query, the description's activation signal is too weak — add 'Use for ...' examples with user-phrasing keywords.

---

### #4: right_tool_wrong_params — calculate_area

**Frequency:** 1 occurrence(s) (3.1% of failures)

**Affected tools:** `calculate_area`

**Example failing queries:**
- **Q007**: What is the area of the parks layer?

**Root cause hypothesis:** Correct tool; parameter value differs from reference. Param description lacks a concrete example or format spec.

**Fix target:** `tool_description` → Prompt 2 (tool-descriptions)

**Specific actions:**
- Enrich `calculate_area` parameter descriptions in `nl_gis/tools.py` with concrete example values. Check whether the reference query's expected param is under-specified.

---

### #5: tool_description_misleading — buffer, geocode, search_nearby, spatial_query

**Frequency:** 1 occurrence(s) (3.1% of failures)

**Confusion:** `spatial_query` → `buffer`

**Affected tools:** `buffer`, `geocode`, `search_nearby`, `spatial_query`

**Example failing queries:**
- **Q009**: Which restaurants are within 500 meters of Central Park?

**Root cause hypothesis:** LLM substituted a semantically-related tool. Descriptions overlap in use-case language without explicit disambiguation.

**Fix target:** `tool_description` → Prompt 2 (tool-descriptions)

**Specific actions:**
- Add 'NEVER use for ...' guidance to `buffer` description to exclude this use case, and strengthen `spatial_query` description with the distinguishing phrasing.

---

### #6: wrong_tool — fetch_osm, point_in_polygon

**Frequency:** 1 occurrence(s) (3.1% of failures)

**Confusion:** `point_in_polygon` → `fetch_osm`

**Affected tools:** `fetch_osm`, `point_in_polygon`

**Example failing queries:**
- **Q010**: Which district contains the point at 51.5074, -0.1278?

**Root cause hypothesis:** LLM doesn't recognize the expected tool as applicable — often returns no tool at all. Activation signal is weak; description vocabulary doesn't match user phrasing.

**Fix target:** `tool_description` → Prompt 2 (tool-descriptions)

**Specific actions:**
- In `nl_gis/tools.py`, enrich `fetch_osm` description with concrete example queries and disambiguation against neighboring tools. If Gemini returned no tool at all for this query, the description's activation signal is too weak — add 'Use for ...' examples with user-phrasing keywords.
- In `nl_gis/tools.py`, enrich `point_in_polygon` description with concrete example queries and disambiguation against neighboring tools. If Gemini returned no tool at all for this query, the description's activation signal is too weak — add 'Use for ...' examples with user-phrasing keywords.

---

### #7: wrong_tool — point_in_polygon

**Frequency:** 1 occurrence(s) (3.1% of failures)

**Affected tools:** `point_in_polygon`

**Example failing queries:**
- **Q011**: Tag each store with its census tract

**Root cause hypothesis:** LLM doesn't recognize the expected tool as applicable — often returns no tool at all. Activation signal is weak; description vocabulary doesn't match user phrasing.

**Fix target:** `tool_description` → Prompt 2 (tool-descriptions)

**Specific actions:**
- In `nl_gis/tools.py`, enrich `point_in_polygon` description with concrete example queries and disambiguation against neighboring tools. If Gemini returned no tool at all for this query, the description's activation signal is too weak — add 'Use for ...' examples with user-phrasing keywords.

---

### #8: wrong_tool — convex_hull

**Frequency:** 1 occurrence(s) (3.1% of failures)

**Affected tools:** `convex_hull`

**Example failing queries:**
- **Q014**: Draw a boundary around the crime data points

**Root cause hypothesis:** LLM doesn't recognize the expected tool as applicable — often returns no tool at all. Activation signal is weak; description vocabulary doesn't match user phrasing.

**Fix target:** `tool_description` → Prompt 2 (tool-descriptions)

**Specific actions:**
- In `nl_gis/tools.py`, enrich `convex_hull` description with concrete example queries and disambiguation against neighboring tools. If Gemini returned no tool at all for this query, the description's activation signal is too weak — add 'Use for ...' examples with user-phrasing keywords.

---

### #9: wrong_tool — centroid

**Frequency:** 1 occurrence(s) (3.1% of failures)

**Affected tools:** `centroid`

**Example failing queries:**
- **Q015**: Get the center points of all buildings

**Root cause hypothesis:** LLM doesn't recognize the expected tool as applicable — often returns no tool at all. Activation signal is weak; description vocabulary doesn't match user phrasing.

**Fix target:** `tool_description` → Prompt 2 (tool-descriptions)

**Specific actions:**
- In `nl_gis/tools.py`, enrich `centroid` description with concrete example queries and disambiguation against neighboring tools. If Gemini returned no tool at all for this query, the description's activation signal is too weak — add 'Use for ...' examples with user-phrasing keywords.

---

### #10: wrong_tool — dissolve

**Frequency:** 1 occurrence(s) (3.1% of failures)

**Affected tools:** `dissolve`

**Example failing queries:**
- **Q018**: Merge the zoning polygons by zone_type

**Root cause hypothesis:** LLM doesn't recognize the expected tool as applicable — often returns no tool at all. Activation signal is weak; description vocabulary doesn't match user phrasing.

**Fix target:** `tool_description` → Prompt 2 (tool-descriptions)

**Specific actions:**
- In `nl_gis/tools.py`, enrich `dissolve` description with concrete example queries and disambiguation against neighboring tools. If Gemini returned no tool at all for this query, the description's activation signal is too weak — add 'Use for ...' examples with user-phrasing keywords.

---

## How to Use This Document

1. Plan 02 (`tool-descriptions`) should land every pattern with `fix_target: tool_description` — ordered by rank.
2. Plan 03 (`complex-queries`) should land every `missing_chain_step` pattern as a system-prompt chain example.
3. After each landing, re-run `venv/bin/python -m tests.eval.run_eval --live --all --output docs/v2/<date>-results.json --rank` and compare against the baseline's 51.6% tool / 57.1% param / 36.4% chain numbers.
4. Patterns that persist after their fix lands indicate the fix was insufficient — escalate to manual review.
