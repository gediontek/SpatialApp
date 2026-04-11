# Plan 3: Complex Query Decomposition

**Objective**: Improve multi-step spatial query handling so complex queries (5+ tool calls) succeed reliably by adding pattern recognition, structured plan generation, and chain validation.

**Scope**: ~300 lines of code | 1.5 days | Files: `nl_gis/chat.py`, `nl_gis/query_patterns.py` (new), `tests/test_query_patterns.py` (new)

**Current State**: `ChatSession.process_message()` in `nl_gis/chat.py` relies entirely on the LLM to chain tools correctly. The `SYSTEM_PROMPT` contains 30+ chaining examples (lines 134-171), but complex queries like "Find all hospitals within 5km of schools in areas with population density above 1000/km2" require 5+ tool calls with correct parameter threading between steps. The LLM frequently picks wrong layer names, omits intermediate steps, or loses context mid-chain. The plan-then-execute mode (`_generate_plan` / `execute_plan`) exists but has no validation that step outputs match next-step inputs.

---

## M1: Catalog Canonical Multi-Step Query Patterns

**Goal**: Define the 10 most common spatial query patterns as structured data with tool chains, so pattern matching can inject them as hints.

### Epic 1.1: Define Pattern Schema and Catalog

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.1.1 | Create `nl_gis/query_patterns.py` with a `QueryPattern` dataclass: `name`, `description`, `trigger_keywords` (list of keyword sets), `tool_chain` (ordered list of `{tool, param_template, output_key}`), `example_query` | File exists, dataclass is importable, includes docstrings explaining each field | S |
| T1.1.2 | Define pattern: **proximity-search** ("within X of Y") -- `geocode -> buffer -> fetch_osm -> spatial_query -> aggregate`. Trigger keywords: `{"within", "near", "around", "km of", "miles of"}`. `param_template` maps buffer distance from user query to `distance_m`, output `layer_name` threads to next step's `source_layer` | Pattern defined with all fields populated; `tool_chain` has 5 steps; `param_template` uses `{distance_m}` and `{feature_type}` placeholders | XS |
| T1.1.3 | Define pattern: **overlay-analysis** ("where do X and Y overlap") -- `fetch_osm(A) -> fetch_osm(B) -> intersection -> calculate_area`. Trigger: `{"overlap", "intersect", "where do", "common area"}` | Pattern defined; `tool_chain` correctly threads `layer_a`/`layer_b` from fetch_osm output `layer_name` | XS |
| T1.1.4 | Define pattern: **compare-layers** ("difference between X and Y") -- `fetch_osm(A) -> fetch_osm(B) -> difference -> calculate_area`. Trigger: `{"subtract", "remove", "difference", "exclude"}` | Pattern defined; distinct from overlay-analysis by trigger keywords | XS |
| T1.1.5 | Define pattern: **buffer-and-count** ("how many X within Y distance of Z") -- `geocode -> buffer -> search_nearby -> spatial_query -> aggregate(count)`. Trigger: `{"how many", "count", "number of"}` combined with `{"within", "near", "around"}` | Pattern defined; aggregate step uses `operation="count"` | XS |
| T1.1.6 | Define pattern: **route-with-nearby** ("find restaurants near my route from A to B") -- `find_route -> buffer(route_geometry) -> fetch_osm -> spatial_query`. Trigger: `{"along", "near route", "near my route", "on the way"}` | Pattern defined; buffer input is route geometry, not a point | XS |
| T1.1.7 | Define pattern: **coverage-analysis** ("which areas are within X min of hospitals") -- `fetch_osm -> service_area -> calculate_area`. Trigger: `{"coverage", "reachable", "service area", "can reach"}` | Pattern defined; uses service_area tool, not simple buffer | XS |
| T1.1.8 | Define pattern: **cluster-and-hotspot** ("find clusters of X, show hot spots") -- `fetch_osm -> spatial_statistics(dbscan) -> hot_spot_analysis`. Trigger: `{"cluster", "hot spot", "hotspot", "concentration"}` | Pattern defined; chains spatial_statistics into hot_spot_analysis | XS |
| T1.1.9 | Define pattern: **multi-criteria-filter** ("X with attribute A above N in area Y") -- `fetch_osm -> filter_layer -> aggregate`. Trigger: `{"above", "below", "greater than", "less than", "taller", "larger"}` combined with area references | Pattern defined; filter_layer step uses attribute/operator/value from user query | XS |
| T1.1.10 | Define pattern: **import-and-analyze** ("import CSV, find nearest X, show heatmap") -- `import_csv -> closest_facility -> heatmap`. Trigger: `{"import", "upload", "csv"}` combined with analysis keywords | Pattern defined; handles import-then-analyze chains | XS |
| T1.1.11 | Define pattern: **spatial-join** ("tag each X with its containing Y") -- `fetch_osm(X) -> fetch_osm(Y) -> point_in_polygon(batch)`. Trigger: `{"which district", "tag each", "assign to", "belongs to"}` | Pattern defined; point_in_polygon uses batch mode with two layers | XS |
| T1.1.12 | Add `get_all_patterns() -> list[QueryPattern]` function and `match_patterns(query: str) -> list[tuple[QueryPattern, float]]` stub that returns empty list (implemented in M2) | Function exists and is importable; returns empty list for any input | XS |

---

## M2: Pattern Recognition in Chat Session

**Goal**: Detect which pattern matches a user query and inject the canonical chain as a hint into the system prompt, improving LLM tool selection accuracy.

### Epic 2.1: Keyword-Based Pattern Matching

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.1.1 | Implement `match_patterns(query: str) -> list[tuple[QueryPattern, float]]` in `nl_gis/query_patterns.py`. Scoring: each `trigger_keywords` set matched adds 1.0 to score; normalize by total keyword sets. Return patterns with score > 0.3, sorted descending. Case-insensitive matching | Function returns scored matches; "how many restaurants within 2km of Central Park" matches `buffer-and-count` with score >= 0.6 | M |
| T2.1.2 | Add `_build_pattern_hint(patterns: list[tuple[QueryPattern, float]]) -> str` that formats the top 2 matched patterns as a structured hint string: "SUGGESTED APPROACH: {pattern.name} -- Steps: 1. {tool}({param_template}) 2. ..." | Returns formatted string; includes step numbers, tool names, and parameter placeholders | S |
| T2.1.3 | In `ChatSession._process_message_inner()` (line ~689 of `nl_gis/chat.py`), after building the system prompt and before the first LLM call, call `match_patterns(message)`. If matches found, append `_build_pattern_hint()` output to the system prompt under a new `\n\nSUGGESTED APPROACH FOR THIS QUERY:` section | Pattern hint appears in system prompt when query matches; no hint section when no match; verified by unit test mocking `_call_llm_with_retry` | M |

### Epic 2.2: Pattern Hint for Plan Mode

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.2.1 | In `ChatSession._generate_plan()` (line ~451), add the same pattern matching logic before the LLM call. Append matched pattern's `tool_chain` as a structured JSON example in the plan prompt, so the LLM generates plans that follow canonical chains | Plan mode generates plans that follow the matched pattern's tool chain order; verified by inspecting the prompt sent to the LLM | S |

---

## M3: Structured Plan Generation with Parameter Threading

**Goal**: Improve `_generate_plan` and `_execute_plan_inner` so plans explicitly specify how outputs thread into subsequent step inputs.

### Epic 3.1: Enhanced Plan Step Schema

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T3.1.1 | Extend `PLAN_PROMPT_SUFFIX` in `nl_gis/chat.py` (line 17) to include `"output_key"` and `"input_from"` fields in each step. Update the example to show: `{"step": 2, "tool": "buffer", "params": {...}, "output_key": "buffer_layer", "input_from": {"geometry": "$step1.layer_name"}, "reason": "..."}`. The `$stepN.field` syntax references prior step outputs | `PLAN_PROMPT_SUFFIX` includes the extended schema; example shows parameter threading with `$step` references | S |
| T3.1.2 | In `_execute_plan_inner()` (line ~591), add a `step_outputs` dict that stores each step's result keyed by step number. Before calling `dispatch_tool`, resolve `$stepN.field` references in `params` by looking up `step_outputs[N][field]`. Handle missing references with a clear error message | Parameter threading works: step 2 can reference `$step1.layer_name` and get the actual layer name from step 1's result; missing reference yields descriptive error | M |
| T3.1.3 | Add `_resolve_step_references(params: dict, step_outputs: dict) -> dict` helper function in `nl_gis/chat.py`. Recursively walks param values, replaces `$stepN.field` strings with actual values from `step_outputs`. Returns new dict (does not mutate input) | Function handles nested dicts, lists, and string values; raises `ValueError` for unresolvable references with message "Step N has no output field 'X'" | S |

---

## M4: Chain Validation (Output-Input Type Compatibility)

**Goal**: Before executing a plan, validate that each step's expected output types match the next step's expected input types, catching errors before execution.

### Epic 4.1: Tool I/O Type Registry

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.1.1 | Add `TOOL_IO_TYPES` dict to `nl_gis/query_patterns.py`. Maps each tool name to `{"inputs": {"param_name": "type"}, "outputs": {"field": "type"}}`. Types: `"layer_name"`, `"geojson"`, `"coordinates"`, `"number"`, `"string"`. Cover all 50 tools in `dispatch_tool` (line ~419 of `nl_gis/handlers/__init__.py`) | Dict has entries for all tools in `dispatch_tool`; each entry has both `inputs` and `outputs` | M |
| T4.1.2 | Add `validate_plan_chain(steps: list[dict]) -> list[str]` function in `nl_gis/query_patterns.py`. For each consecutive pair of steps, check that referenced output types match input types. Return list of warning strings (empty = valid). Example warning: "Step 3 expects layer_name for 'source_layer' but step 2 (geocode) outputs coordinates, not layer_name" | Function catches type mismatches; returns empty list for valid chains; returns specific warnings for mismatched chains | M |
| T4.1.3 | In `_execute_plan_inner()`, call `validate_plan_chain(plan_steps)` before executing. If warnings exist, yield them as `{"type": "message", "text": "Plan validation warnings: ..."}` events but still proceed with execution (warnings, not blockers) | Warnings are surfaced to the user before execution starts; execution proceeds despite warnings | S |

### Epic 4.2: Runtime Type Checking During Execution

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.2.1 | In `_execute_plan_inner()`, after each step completes, verify the result contains the expected output fields (per `TOOL_IO_TYPES`). If a field is missing, log a warning and update `step_outputs` with `None` for that field so downstream references fail gracefully with a clear message instead of a KeyError | Missing output fields produce warnings in the SSE stream; downstream steps that reference missing fields get descriptive errors instead of crashes | S |

---

## M5: Benchmark Complex Queries

**Goal**: Measure success rate improvement on 10 canonical complex queries before and after the pattern recognition and chain validation changes.

### Epic 5.1: Benchmark Suite

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T5.1.1 | Create `tests/test_query_patterns.py` with unit tests for `match_patterns()`: test each of the 10 patterns with its example query, verify score > 0.5; test a non-matching query ("hello world"), verify empty result; test ambiguous query that matches multiple patterns, verify correct ordering | 12+ test cases; all pass | M |
| T5.1.2 | Add unit tests for `_resolve_step_references()`: test simple reference `$step1.layer_name`, nested dict reference, list containing reference, missing step reference (ValueError), missing field reference (ValueError) | 5+ test cases; all pass | S |
| T5.1.3 | Add unit tests for `validate_plan_chain()`: test valid chain (proximity-search), test invalid chain (geocode output fed to filter_layer's layer_name input), test chain with no threading (independent steps) | 3+ test cases; all pass | S |
| T5.1.4 | Create `tests/benchmark_complex_queries.py` (manual benchmark, not CI). Define 10 complex queries with expected tool chain patterns. For each, call `match_patterns()` and verify the correct pattern is top-ranked. Log success/failure counts | Benchmark script runs; reports pattern match accuracy as percentage; target: 8/10 correct top-rank matches | M |

---

## Dependencies and Risks

| Risk | Mitigation |
|------|-----------|
| Pattern matching too rigid (misses paraphrased queries) | Use keyword sets with synonyms; scoring threshold 0.3 allows partial matches |
| Pattern hints confuse the LLM instead of helping | Hints are "SUGGESTED" not "REQUIRED"; LLM can deviate; A/B test with/without hints |
| `$stepN.field` syntax conflicts with LLM output format | Use distinctive prefix `$step` unlikely in natural text; validate before dispatch |
| `TOOL_IO_TYPES` maintenance burden as new tools are added | Place in same file as patterns; add to contributor checklist |

## Files Modified

| File | Change |
|------|--------|
| `nl_gis/query_patterns.py` | **New file** -- QueryPattern dataclass, 10 patterns, match_patterns(), TOOL_IO_TYPES, validate_plan_chain() |
| `nl_gis/chat.py` | Modify `_process_message_inner()` and `_generate_plan()` to call match_patterns(); modify `PLAN_PROMPT_SUFFIX` for extended schema; modify `_execute_plan_inner()` for parameter threading and chain validation; add `_resolve_step_references()` |
| `tests/test_query_patterns.py` | **New file** -- unit tests for pattern matching, reference resolution, chain validation |
| `tests/benchmark_complex_queries.py` | **New file** -- manual benchmark script for 10 complex queries |
