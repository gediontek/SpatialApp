# Prompt 2: Tool Description Engineering Plan (RE-SCOPED 2026-04-18)

> **STATUS — rescoped for Gemini 2.5 Flash after experimental evidence.**
> The original plan's 85% accuracy target and aggressive prompt-enrichment
> approach regressed the baseline by −4.8 percentage points on Gemini 2.5
> Flash (51.6% → 46.8%). The model entered analysis paralysis under the
> heavy COMMON CONFUSIONS / NEVER-DO / CHAIN VALIDATION rule set. Eight
> basic queries that had been firing cleanly started returning no tool.
>
> See lessons-learned entry `llm-tool-selection-plans-must-account-for-model-sensitivity`
> and commit `ec1c899` for the experimental result.

**Re-scoped objective**: Modestly improve NL-GIS accuracy on **Gemini 2.5 Flash**
through **surgical description rewrites only** — targeting the specific tools
that failed with weak activation in the classified baseline. No SYSTEM_PROMPT
enrichment. No NEVER-DO rules. No CHAIN VALIDATION RULES.

**Re-scoped target**: 55-60% tool-selection accuracy on Gemini 2.5 Flash
(vs 51.6% baseline). The plan's original 85% target assumed a Claude-class
model and is deferred to Plan 07 (provider tuning), where the aggressive
prompt enrichment can be A/B-tested against Claude.

**Scope**: `nl_gis/tools.py` description edits only, ~100 lines across ~8
tools identified in `failure-patterns.md`. No `nl_gis/chat.py` changes.
No new test scaffolding (M5 eval already exists).

**Depends on**: Prompt 1 baseline (`docs/v2/baseline-classified.json`) and
failure classification (`docs/v2/failure-patterns.md`).

**Tools to rewrite** (target list from `failure-patterns.md`):
| Tool | Baseline failure | Pattern |
|------|-----------------|---------|
| `point_in_polygon` | Q010, Q011 | ✅ Shipped in commit `ec1c899` |
| `spatial_statistics` | Q012, Q013 | ✅ Shipped in commit `ec1c899` |
| `reverse_geocode` | Q002 | Pending — USE WHEN trigger phrases |
| `convex_hull` | Q014 | Pending — USE WHEN trigger phrases |
| `centroid` | Q015 | Pending — USE WHEN trigger phrases |
| `dissolve` | Q018 | Pending — USE WHEN trigger phrases |
| `difference` | Q021 | Pending — USE WHEN trigger phrases |
| `calculate_area` | Q007 (params) | Pending — add concrete param example |

**Process**: Apply the remaining edits in one batch, re-run Gemini eval,
accept the delta if net non-negative. No iteration if it regresses.

**Key files**:
- `nl_gis/tools.py` — 64 tool schemas (1602 lines), each with `name`, `description`, `input_schema`
- `nl_gis/chat.py` — `SYSTEM_PROMPT` (lines 32-225), tool selection guidance + chaining patterns
- `tests/eval/reference_queries.py` — 30 primary + 12 supplementary reference queries (42 total)
- `tests/eval/evaluator.py` — `ToolSelectionEvaluator` with `evaluate_batch()` and `generate_report()`
- `tests/eval/run_eval.py` — evaluation runner script

---

## Confusable Tool Pairs (Pre-Analysis)

These tool pairs have overlapping semantics that cause "wrong tool chosen" failures. Each pair is addressed in M1.

| Confusable Pair | Distinguishing Signal |
|---|---|
| `buffer` vs `search_nearby` | buffer creates a visible polygon geometry; search_nearby fetches OSM features within a radius |
| `buffer` vs `spatial_query(within_distance)` | buffer produces a new polygon layer; spatial_query filters existing features |
| `intersection` vs `spatial_query(intersects)` | intersection produces new cut geometries (overlay); spatial_query filters features that touch a target |
| `filter_layer` vs `highlight_features` | filter_layer creates a new layer with subset; highlight_features styles matching features in place |
| `filter_layer` vs `spatial_query` | filter_layer filters by attribute value; spatial_query filters by spatial relationship |
| `dissolve` vs `merge_features` | dissolve merges geometries + computes aggregate stats; merge_features is simpler union by attribute |
| `dissolve` vs `merge_layers` | dissolve merges features within one layer by attribute; merge_layers combines two separate layers |
| `fetch_osm` vs `search_nearby` | fetch_osm uses bbox for area queries; search_nearby uses point+radius for proximity queries |
| `closest_facility` vs `search_nearby` | closest_facility returns N nearest sorted by distance; search_nearby returns all within radius |
| `style_layer` vs `highlight_features` | style_layer changes entire layer appearance; highlight_features styles only matching features |
| `convex_hull` vs `bounding_box` | convex_hull is tightest convex polygon; bounding_box is axis-aligned rectangle |
| `clip` vs `intersection` | clip cuts features to a boundary (one-sided); intersection computes overlay of two layers (symmetric) |
| `clip` vs `difference` | clip keeps features inside mask; difference removes features inside mask |
| `centroid` vs `extract_vertices` | centroid gets center point per feature; extract_vertices gets all boundary vertices |
| `isochrone` vs `service_area` | isochrone is single-origin reachability; service_area is multi-facility coverage with gap analysis |
| `heatmap` vs `hot_spot_analysis` | heatmap is visualization (density rendering); hot_spot_analysis is statistical (Gi* z-scores) |
| `aggregate(count)` vs `describe_layer` | aggregate computes summary stats; describe_layer gives full schema + attribute breakdown |
| `attribute_statistics` vs `aggregate` | attribute_statistics gives detailed stats (percentiles, histogram); aggregate gives count/area/group_by |
| `find_route` vs `optimize_route` | find_route goes A-to-B (ordered); optimize_route reorders 3+ stops for efficiency |

---

## M1: Fix "Wrong Tool Chosen" Failures

**Goal**: For each confusable tool pair, rewrite both descriptions so the LLM can differentiate them unambiguously. Zero "wrong tool" failures on basic queries.

### Epic 1.1: Disambiguate Data Acquisition Tools

Tools: `fetch_osm`, `search_nearby`, `closest_facility`

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.1.1 | Rewrite `fetch_osm` description (line 27 in `tools.py`) to emphasize **area-based** retrieval: "Fetch all features of a type within a bounding box or named area." Add negative signal: "Do NOT use for point-radius proximity queries — use search_nearby instead." | Description contains "area-based", "bounding box", and explicit "do not use for" guidance. Eval queries Q001, Q003 both select correct tool. | S |
| T1.1.2 | Rewrite `search_nearby` description (line 270 in `tools.py`) to emphasize **point-radius** retrieval: "Search for features within a radius of a specific point." Add negative signal: "Do NOT use for area-wide queries — use fetch_osm instead." Add trigger phrases: "near", "around", "close to", "within X meters of a point". | Description contains "point-radius", trigger phrases list, and negative guidance. Q003 selects search_nearby, not fetch_osm. | S |
| T1.1.3 | Rewrite `closest_facility` description (line 857 in `tools.py`) to emphasize **ranked nearest-N** retrieval: "Find the N closest features sorted by distance from a point." Add: "Use closest_facility when the user asks for 'nearest', 'closest N'; use search_nearby when the user asks for 'all within radius'." | Description differentiates from search_nearby. Q025 selects closest_facility. | S |

### Epic 1.2: Disambiguate Spatial Analysis Tools

Tools: `buffer`, `spatial_query`, `intersection`, `filter_layer`, `highlight_features`

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.2.1 | Rewrite `buffer` description (line 192 in `tools.py`) to emphasize **geometry creation**: "Create a new polygon layer representing the area within a given distance of a geometry. Output: a visible polygon on the map." Add: "Use buffer to create a visible zone; use search_nearby to find features near a point; use spatial_query(within_distance) to filter an existing layer by proximity." | Description says "creates a new polygon layer". Differentiated from search_nearby and spatial_query. | S |
| T1.2.2 | Rewrite `spatial_query` description (line 216 in `tools.py`) to emphasize **filtering existing features**: "Filter features from an existing layer based on a spatial relationship with another layer or geometry. Does NOT create new geometries — it selects features." Add: "Use intersection instead if you need new cut geometries from the overlap." | Description says "filter", "select", "does not create new geometries". | S |
| T1.2.3 | Rewrite `intersection` description (line 936 in `tools.py`) to emphasize **geometric overlay**: "Compute the geometric overlap of two polygon layers, producing NEW cut geometries representing only the shared area." Add: "Use spatial_query(intersects) instead if you only need to filter features that touch a target without cutting geometry." | Description says "new cut geometries", "overlay", "shared area". | S |
| T1.2.4 | Rewrite `filter_layer` description (line 380 in `tools.py`) to emphasize **attribute-based filtering**: "Create a new layer containing only features that match an attribute condition. Filters by property values (text or numeric), NOT by spatial relationship." Add: "Use spatial_query for spatial filtering; use highlight_features to style features without creating a new layer." | Description says "attribute condition", "property values", "not spatial". | S |
| T1.2.5 | Rewrite `highlight_features` description (line 353 in `tools.py`) to emphasize **in-place styling**: "Change the visual style of matching features within an existing layer WITHOUT creating a new layer. The original layer is modified in place." Add: "Use filter_layer instead to extract matching features into a separate new layer." | Description says "in-place", "without creating a new layer". Q027 uses filter_layer then highlight_features correctly. | S |

### Epic 1.3: Disambiguate Geometry Merge/Combine Tools

Tools: `dissolve`, `merge_features`, `merge_layers`

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.3.1 | Rewrite `dissolve` description (line 1081 in `tools.py`) to emphasize **attribute-based geometry union within one layer**: "Merge features within a single layer that share the same attribute value into combined geometries. Use for 'merge zones by type' within one dataset." Add: "Use merge_layers to combine two separate layers. Use merge_features for simple union without stats." | Description differentiates from merge_layers and merge_features. Q018 selects dissolve. | S |
| T1.3.2 | Rewrite `merge_features` description (line 1490 in `tools.py`) to add: "Simpler than dissolve — only unions geometries. Use dissolve instead when you also need aggregate statistics or when the user says 'dissolve'." | Description explicitly positions relative to dissolve. | XS |
| T1.3.3 | Rewrite `merge_layers` description (line 531 in `tools.py`) to emphasize **combining two separate layers**: "Combine two separate named layers into a single layer. Use when the user has two different datasets to merge. Use dissolve to merge features within one layer by attribute." | Description says "two separate layers". S003 selects merge_layers. | XS |

### Epic 1.4: Disambiguate Geometry Analysis Tools

Tools: `convex_hull`, `bounding_box`, `clip`, `difference`

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.4.1 | Rewrite `convex_hull` description (line 1002 in `tools.py`) to add: "Returns the tightest convex polygon (like wrapping a rubber band). Use bounding_box for a rectangular extent instead." | Q014 selects convex_hull. | XS |
| T1.4.2 | Rewrite `bounding_box` description (line 1062 in `tools.py`) to add: "Returns an axis-aligned rectangle. Use convex_hull for a tighter boundary that follows the shape of the data." | Q017 selects bounding_box. | XS |
| T1.4.3 | Rewrite `clip` description (line 1102 in `tools.py`) to add: "One-sided operation: keeps features from clip_layer that fall inside mask_layer. Use difference to keep features OUTSIDE the mask. Use intersection for symmetric geometric overlay." | S010 selects clip. | XS |

### Epic 1.5: Disambiguate Visualization vs Analysis Tools

Tools: `heatmap`, `hot_spot_analysis`, `spatial_statistics`

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.5.1 | Rewrite `heatmap` description (line 832 in `tools.py`) to add: "Produces a visual density rendering (no statistics). Use hot_spot_analysis for statistically significant clusters with z-scores. Use spatial_statistics(dbscan) to identify discrete cluster groups." | S007 selects heatmap, not hot_spot_analysis. | XS |
| T1.5.2 | Rewrite `hot_spot_analysis` description (line 1237 in `tools.py`) to add: "Returns statistical results (z-scores, p-values), not just visualization. Use heatmap for visual-only density display." | Description differentiates from heatmap. | XS |
| T1.5.3 | Rewrite `spatial_statistics` description (line 1207 in `tools.py`) to add: "Use nearest_neighbor to answer 'is it clustered?' (returns NNI index). Use dbscan to answer 'where are the clusters?' (returns cluster assignments). Use hot_spot_analysis for attribute-weighted clustering (Gi* statistic)." | Q012 selects spatial_statistics with nearest_neighbor. Q013 selects spatial_statistics with dbscan. | S |

### Epic 1.6: Disambiguate Routing Tools

Tools: `find_route`, `optimize_route`, `isochrone`, `service_area`

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.6.1 | Rewrite `find_route` description (line 750 in `tools.py`) to add: "Follows a fixed order: origin → waypoints → destination. Use optimize_route when the user wants to find the BEST order to visit 3+ stops." | Q023 selects find_route. S009 selects optimize_route. | XS |
| T1.6.2 | Rewrite `isochrone` description (line 797 in `tools.py`) to add: "Single-origin reachability polygon. Use service_area for multi-facility coverage (unions multiple isochrones + optional gap analysis)." | Q024 selects isochrone. | XS |

---

## M2: Fix "Wrong Parameters" Failures

**Goal**: Add concrete parameter examples with real-world values to every tool that has parameter accuracy failures.

### Epic 2.1: Add Concrete Bbox and Coordinate Examples

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.1.1 | Update `fetch_osm.bbox` parameter description (line 41 in `tools.py`): Change from generic example to concrete city examples: "bbox: '41.8781,-87.6298,41.8842,-87.6235' (Millennium Park, Chicago) or '40.7484,-74.0060,40.7580,-73.9855' (Midtown Manhattan). Format: 'south,west,north,east' in decimal degrees." | Parameter description includes 2 real-world bbox examples with city labels. | XS |
| T2.1.2 | Update `map_command.bbox` parameter description (line 122 in `tools.py`): Add concrete example: "bbox: [41.87, -87.65, 41.90, -87.62] (Chicago Loop). Format: [south, west, north, east]." Note: this bbox is an array, not a string like fetch_osm. | Parameter includes concrete example. Q005 produces correct map_command params. | XS |
| T2.1.3 | Update `search_nearby.radius_m` parameter description (line 289 in `tools.py`): Add scale reference: "radius_m: 500 (5-minute walk), 1000 (10-minute walk), 5000 (typical neighborhood), 10000 (city-wide search)." | Parameter includes human-scale references. Q003 passes radius_m=800. | XS |

### Epic 2.2: Add Feature Type and Attribute Examples

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.2.1 | Update `filter_layer.attribute` parameter description (line 390 in `tools.py`): Add common attribute names from OSM: "Common attributes from fetch_osm: 'feature_type' (building, park, ...), 'name', 'building:levels' (number of floors), 'addr:street'. Use describe_layer first if unsure which attributes exist." | Parameter lists common attribute names. Q027 passes correct attribute. | S |
| T2.2.2 | Update `filter_layer.value` parameter description (line 398 in `tools.py`): Add type coercion note: "For numeric comparisons (greater_than, less_than, between), the value is compared numerically. Example: '20' for buildings taller than 20m. For 'between', use 'min,max' format: '10,50'." | Parameter clarifies numeric coercion behavior. | XS |
| T2.2.3 | Update `aggregate.operation` parameter description (line 258 in `tools.py`): Add when-to-use guidance: "count: 'how many features?' area: 'total area of polygons in sq meters.' group_by: 'how many of each type?' (requires group_by parameter)." | Parameter includes when-to-use guidance for each enum value. Q008 produces aggregate with operation='count'. | XS |

### Epic 2.3: Add Spatial Relationship Examples

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.3.1 | Update `spatial_query.predicate` parameter description (line 225 in `tools.py`): Add concrete scenarios for each predicate: "intersects: 'which roads cross the park?' contains: 'which district fully encloses this building?' within: 'which buildings are fully inside the buffer?' within_distance: 'which schools are within 1km of the hospital?'" | Each predicate has a concrete natural-language scenario. Q009 uses correct predicate. | S |
| T2.3.2 | Update `point_in_polygon` lat/lon parameter descriptions (lines 1153-1159 in `tools.py`): Add note: "For single-point mode, provide lat and lon. For batch mode (tagging all points in a layer), provide point_layer instead. Do not mix single-point and batch-mode parameters." | Mode selection is unambiguous. Q010 uses single-point mode. Q011 uses batch mode. | XS |

### Epic 2.4: Add Routing Parameter Examples

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.4.1 | Update `isochrone.time_minutes` and `isochrone.distance_m` parameter descriptions (lines 814-820 in `tools.py`): Add: "Provide time_minutes OR distance_m, not both. time_minutes: 5 (walking errand), 15 (commute), 30 (regional). distance_m: 1000 (1km walk), 5000 (5km drive)." | Parameter clarifies mutual exclusivity and includes scale references. Q024 passes time_minutes=15. | XS |
| T2.4.2 | Update `buffer.distance_m` parameter description (line 205 in `tools.py`): Add human-scale references: "distance_m: 100 (1-minute walk), 500 (5-minute walk), 1000 (1km), 5000 (urban neighborhood), 50000 (metro area). Max: 100000 (100km)." | Parameter includes human-scale references. Q019 passes distance_m=2000. | XS |

---

## M3: Fix "Missing Chain" Failures

**Goal**: Add tool chaining hints to descriptions so the LLM knows what to call next.

### Epic 3.1: Add Post-Action Chaining Hints to Data Acquisition Tools

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T3.1.1 | Add chaining hint to `fetch_osm` description (line 27 in `tools.py`): Append: "CHAIN: After fetch_osm, call map_command(action='fit_bounds') to show results. To count results, follow with aggregate(operation='count'). To filter results, follow with filter_layer." | Description includes 3 common follow-up tools. | XS |
| T3.1.2 | Add chaining hint to `search_nearby` description (line 270 in `tools.py`): Append: "CHAIN: After search_nearby, call map_command(action='fit_bounds') to show results. To style results, call style_layer. To count, call aggregate(operation='count')." | Description includes follow-up hints. | XS |
| T3.1.3 | Add chaining hint to `geocode` description (line 12 in `tools.py`): Append: "CHAIN: After geocode, use the returned lat/lon for map_command(action='pan_and_zoom') to navigate the map, or pass coordinates to buffer/search_nearby/isochrone." | Description includes follow-up hints. Q005 chains geocode then map_command. | XS |
| T3.1.4 | Add chaining hint to `batch_geocode` description (line 79 in `tools.py`): Append: "CHAIN: After batch_geocode, call map_command(action='fit_bounds') to show all points. To visualize density, follow with heatmap." | Description includes follow-up hints. | XS |

### Epic 3.2: Add Pre-Condition Chaining Hints to Analysis Tools

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T3.2.1 | Add chaining hint to `spatial_query` description (line 216 in `tools.py`): Append: "CHAIN: Typically preceded by fetch_osm (to get the source layer) and buffer (to create the target geometry). Example chain: fetch_osm → buffer → spatial_query." | Description includes common predecessor chain. Q009 produces correct multi-step chain. | XS |
| T3.2.2 | Add chaining hint to `aggregate` description (line 247 in `tools.py`): Append: "CHAIN: Typically preceded by fetch_osm to acquire the data. Example: 'How many buildings in Seattle?' → fetch_osm(building, Seattle) → aggregate(count)." | Description includes predecessor hint. Q008 chains fetch_osm then aggregate. | XS |
| T3.2.3 | Add chaining hint to `intersection` description (line 936 in `tools.py`): Append: "CHAIN: Requires two existing layers. Typically preceded by two fetch_osm calls. Follow with calculate_area to measure the overlap. Example: fetch_osm(parks) → fetch_osm(flood_zones) → intersection → calculate_area." | Q020 chains fetch_osm, fetch_osm, intersection. | XS |
| T3.2.4 | Add chaining hint to `buffer` description (line 192 in `tools.py`): Append: "CHAIN: Often preceded by geocode (to get a center point). Often followed by spatial_query (to find features within the buffer). Example: geocode → buffer → spatial_query." | Q019 chains geocode then buffer. | XS |

### Epic 3.3: Add Chaining Hints to Styling and Visualization Tools

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T3.3.1 | Add chaining hint to `style_layer` description (line 411 in `tools.py`): Append: "CHAIN: Requires an existing layer. Typically preceded by fetch_osm, search_nearby, or filter_layer. Example: 'Find restaurants near Central Park and color them red' → search_nearby → style_layer(color='#ff0000')." | Q026 chains search_nearby then style_layer. | XS |
| T3.3.2 | Add chaining hint to `heatmap` description (line 832 in `tools.py`): Append: "CHAIN: Requires an existing point layer. Typically preceded by import_csv or fetch_osm. Follow with map_command(action='fit_bounds') to show results." | S007 selects heatmap after data exists. | XS |
| T3.3.3 | Add chaining hint to `highlight_features` description (line 353 in `tools.py`): Append: "CHAIN: Often used after filter_layer. Example: 'Show only tall buildings and highlight the commercial ones' → filter_layer(height > 20) → highlight_features(attribute='type', value='commercial')." | Q027 chains filter_layer then highlight_features. | XS |

---

## M4: Update System Prompt with Improved Patterns

**Goal**: Update `SYSTEM_PROMPT` in `nl_gis/chat.py` (lines 32-225) with clearer tool selection rules and additional chaining patterns.

### Epic 4.1: Rewrite Tool Selection Decision Tree

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.1.1 | Replace the flat TOOL SELECTION list (lines 42-131 in `chat.py`) with a structured decision tree. Group by user intent: **"Show/Find features"** → fetch_osm vs search_nearby vs closest_facility decision. **"Analyze spatial relationships"** → spatial_query vs intersection vs clip decision. **"Merge/Combine"** → merge_layers vs dissolve vs merge_features decision. **"Style/Visualize"** → style_layer vs highlight_features vs heatmap decision. | TOOL SELECTION section is organized by user intent, not alphabetically by tool name. Each intent group has clear differentiating criteria. | M |
| T4.1.2 | Add a "COMMON CONFUSIONS" section to the system prompt (after TOOL SELECTION, before TOOL CHAINING PATTERNS). List the top 10 confusable pairs from the pre-analysis table with one-sentence disambiguation rules. Example: "buffer creates a polygon, search_nearby fetches features. If the user wants to SEE a zone, use buffer. If the user wants to FIND things nearby, use search_nearby." | System prompt contains COMMON CONFUSIONS section with 10 pairs. | S |

### Epic 4.2: Expand Chaining Patterns

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.2.1 | Add 5 new chaining patterns to `TOOL CHAINING PATTERNS` section (lines 134-171 in `chat.py`) covering missing-chain failures identified in Prompt 1. Candidates based on reference queries: (1) "Filter then highlight" → filter_layer → highlight_features. (2) "Fetch then count" → fetch_osm → aggregate(count). (3) "Multi-layer comparison" → fetch_osm → fetch_osm → intersection → calculate_area. (4) "Import then analyze" → import_csv → spatial_statistics. (5) "Proximity analysis" → geocode → buffer → fetch_osm → spatial_query. | 5 new chaining patterns added. Each maps a natural language intent to a tool chain. | S |
| T4.2.2 | Add a "CHAIN VALIDATION RULES" subsection to the system prompt: "Rule 1: Every fetch_osm or search_nearby should be followed by map_command(fit_bounds) unless another tool immediately consumes the layer. Rule 2: Every geocode that provides coordinates for pan/zoom must be followed by map_command. Rule 3: intersection/difference/symmetric_difference require two existing layers — fetch them first." | System prompt contains 3 chain validation rules. | S |

### Epic 4.3: Improve Disambiguation Section

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.3.1 | Expand the DISAMBIGUATION section (line 200-204 in `chat.py`) with attribute-awareness rules: "Before calling filter_layer or highlight_features, check which attributes exist on the target layer. If unsure, call describe_layer first. Common OSM attributes: 'feature_type', 'name', 'building:levels', 'addr:street'." | DISAMBIGUATION section includes attribute-awareness guidance. | S |
| T4.3.2 | Add "NEVER DO" rules to system prompt: "NEVER use execute_code when a dedicated tool exists. NEVER call buffer when the user just wants to find nearby features (use search_nearby). NEVER call intersection when the user just wants to filter features (use spatial_query). NEVER call aggregate when the user asks 'describe this layer' (use describe_layer)." | System prompt contains 4 explicit negative rules. | XS |

---

## M5: Re-Run Eval and Iterate

**Goal**: Measure accuracy improvement. If <85%, iterate on worst 5 failures until target is met.

### Epic 5.1: Run Baseline Comparison

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T5.1.1 | Run `tests/eval/run_eval.py` against all 42 reference queries (30 primary + 12 supplementary from `tests/eval/reference_queries.py`) using the UPDATED tool descriptions and system prompt. Record: overall accuracy, per-category accuracy, per-complexity accuracy. Save report to `tests/eval/reports/02-post-descriptions.md`. | Eval report generated. Overall accuracy recorded. Comparison with Prompt 1 baseline included. | S |
| T5.1.2 | Compare results against Prompt 1 baseline. Compute delta per category: data_acquisition, measurement, spatial_analysis, geometry, overlay, routing, layer_management, import_export. Identify any regressions (categories where accuracy dropped). | Comparison table shows before/after per category. No regressions identified, or regressions are explained and accepted. | S |

### Epic 5.2: Iterate on Remaining Failures

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T5.2.1 | If accuracy <85%: extract the worst 5 failures from `evaluator.generate_report()` output. For each failure: (a) classify failure type (wrong tool / wrong params / missing chain), (b) identify the specific description text that caused confusion, (c) write a targeted fix. Apply fixes to `nl_gis/tools.py` and/or `nl_gis/chat.py`. | Top 5 failures analyzed. Root cause identified for each. Targeted description fix applied. | M |
| T5.2.2 | Re-run eval after iteration fixes. If accuracy still <85%, repeat T5.2.1 for the next worst 5 failures. Maximum 3 iterations (15 fixes total). | Accuracy >=85% achieved, or 3 iterations completed with documented remaining gaps. | M |
| T5.2.3 | Verify zero "wrong tool" failures on basic (single-tool, simple complexity) queries: Q001-Q007, Q010-Q018, Q021-Q025, Q029-Q030, S001-S011. Any remaining basic-query failures must be resolved before closing this milestone. | All basic-complexity reference queries achieve "full" match in evaluator output. | S |

### Epic 5.3: Add Regression Tests

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T5.3.1 | For each confusable pair that was fixed in M1, add a targeted test case to `tests/eval/reference_queries.py` in the `SUPPLEMENTARY_QUERIES` list. Each test should present the ambiguous natural language that previously caused the wrong tool selection, with the correct expected tool. Minimum 5 new test cases covering: buffer vs search_nearby, intersection vs spatial_query, filter_layer vs highlight_features, dissolve vs merge_layers, heatmap vs hot_spot_analysis. | 5+ new supplementary queries added. Each targets a specific confusable pair. All pass with "full" match. | S |
| T5.3.2 | Update `ALL_TOOLS` list in `reference_queries.py` (line 398) to include all 64 tools if not already present. Run `get_tool_coverage()` and document which tools remain uncovered by the eval suite. | ALL_TOOLS list matches all 64 tools in `tools.py`. Coverage report documents uncovered tools. | XS |

---

## Effort Summary

| Milestone | Tasks | XS | S | M | L | Estimated Hours |
|-----------|-------|----|----|---|---|-----------------|
| M1: Wrong Tool Fixes | 16 | 8 | 7 | 0 | 0 | 4-5h |
| M2: Wrong Params Fixes | 9 | 6 | 3 | 0 | 0 | 2-3h |
| M3: Missing Chain Hints | 10 | 10 | 0 | 0 | 0 | 1-2h |
| M4: System Prompt Update | 5 | 1 | 3 | 1 | 0 | 3-4h |
| M5: Eval and Iterate | 5 | 1 | 3 | 2 | 0 | 3-4h |
| **Total** | **45** | **26** | **16** | **3** | **0** | **13-18h** |

XS = <30 min, S = 30-60 min, M = 1-2 hours, L = 2-4 hours

## Execution Order

1. **M1** first — wrong tool selection is the highest-impact failure class
2. **M2** second — wrong parameters are the next highest impact
3. **M3** third — chaining hints build on the corrected descriptions
4. **M4** fourth — system prompt updates consolidate all description improvements
5. **M5** last — measure, iterate, verify

## Success Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| Overall accuracy | >=85% | `evaluator.evaluate_batch()` full_match / total |
| Basic query accuracy | 100% | All simple-complexity queries achieve "full" match |
| No regressions | 0 | No category drops accuracy vs Prompt 1 baseline |
| Confusable pair resolution | 100% | All 19 confusable pairs have differentiated descriptions |
| Chaining hints | 10+ tools | At least 10 tools have explicit CHAIN hints in descriptions |

## Risk Mitigations

| Risk | Mitigation |
|------|------------|
| Description changes help one tool but break another | Run full eval after each milestone, not just at end |
| System prompt grows too long (token cost) | Keep COMMON CONFUSIONS section to 10 pairs max. Use terse rules, not paragraphs |
| Chaining hints make descriptions too verbose | Put chaining hints at END of description so core purpose comes first |
| Parameter examples are location-specific (Chicago-centric) | Use examples from 3+ cities (Chicago, NYC, London) |
| 85% target unreachable with descriptions alone | Document remaining failures for Prompt 3 (complex query decomposition) to address |
