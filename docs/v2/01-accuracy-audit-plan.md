# Plan 01: NL-GIS Accuracy Audit

## Overview

Audit the NL-to-GIS pipeline's tool selection accuracy by expanding the reference query set to 50+ queries, running both mock and live evaluations, classifying every failure, and producing a ranked list of improvement targets. The eval framework (`tests/eval/`) already has an evaluator, mock responses, and a runner -- but the query set covers only 42 queries across 44 of 64 tools, the failure taxonomy is absent, and no live baseline has been recorded. This plan closes those gaps without modifying any production code.

## Dependencies

- Existing eval framework: `tests/eval/evaluator.py`, `tests/eval/reference_queries.py`, `tests/eval/mock_responses.py`, `tests/eval/run_eval.py`
- `ANTHROPIC_API_KEY` in `.env` for live evaluation (Milestone 1, Epic 1.3)
- All 236 existing tests passing (`pytest tests/ -v`)

## Success Criteria

- Reference query set contains 50+ queries covering all 64 tools (currently 42 queries, 44 tools)
- Live evaluation produces a baseline scorecard with three metrics: tool selection accuracy %, parameter accuracy %, chain accuracy %
- Every failed query is classified into exactly one failure category from a defined taxonomy
- Top 10 failure patterns ranked by frequency, documented with specific tool names and example queries
- All changes are in `tests/eval/` and `docs/v2/` -- zero production code modifications

---

## Milestone 1: Establish Reliable Baseline (50+ queries, 3 metrics)

### Epic 1.1: Expand Reference Query Set to 50+ Queries Covering All 64 Tools

Currently `reference_queries.py` defines `ALL_TOOLS` with 44 tools but `nl_gis/tools.py` defines 64 tools. Twenty tools have no reference queries: `hot_spot_analysis`, `interpolate`, `validate_topology`, `repair_topology`, `service_area`, `reproject_layer`, `detect_crs`, `od_matrix`, `split_feature`, `merge_features`, `extract_vertices`, `temporal_filter`, `attribute_statistics`, `import_kml`, `import_geoparquet`, `export_geoparquet`, `describe_layer`, `detect_duplicates`, `clean_layer`, `execute_code`.

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 1.1.1 | Update `ALL_TOOLS` list in `tests/eval/reference_queries.py` to include all 64 tool names from `nl_gis/tools.py` (lines 398-409). Add the 20 missing tool names alphabetically. | `len(ALL_TOOLS) == 64`. Running `get_tool_coverage(ALL_QUERIES)` returns 0 uncovered tools after task 1.1.3. | XS |
| 1.1.2 | Add 10 new reference queries to `SUPPLEMENTARY_QUERIES` in `tests/eval/reference_queries.py` for the 10 highest-priority uncovered tools: `hot_spot_analysis`, `interpolate`, `service_area`, `describe_layer`, `detect_duplicates`, `clean_layer`, `import_kml`, `temporal_filter`, `attribute_statistics`, `od_matrix`. Each query must include `id` (S013-S022), `query`, `complexity`, `expected_tools`, `expected_params` (where applicable), and `category`. | 10 new entries in `SUPPLEMENTARY_QUERIES`. Each has all required keys. `len(ALL_QUERIES) >= 52`. | S |
| 1.1.3 | Add 10 more reference queries to `SUPPLEMENTARY_QUERIES` for the remaining uncovered tools: `validate_topology`, `repair_topology`, `reproject_layer`, `detect_crs`, `split_feature`, `merge_features`, `extract_vertices`, `import_geoparquet`, `export_geoparquet`, `execute_code`. Include multi-step chains where natural (e.g., `validate_topology` then `repair_topology`). | 10 new entries (S023-S032). `get_tool_coverage(ALL_QUERIES)` returns `(set_of_64, set())`. | S |
| 1.1.4 | Add corresponding mock responses to `MOCK_RESPONSES` dict in `tests/eval/mock_responses.py` for all 20 new queries (S013-S032). Each mock must use `_tool_use()` with realistic parameters matching what Claude would produce. | `get_mock_tools(qid)` returns non-empty list for every new query ID. `run_eval.py --mock --all` runs without KeyError. | S |

### Epic 1.2: Add Parameter Accuracy and Chain Accuracy Metrics

Currently `ToolSelectionEvaluator.evaluate_batch()` returns only tool-level match rates. The prompt requires three distinct metrics: tool selection accuracy, parameter accuracy, and chain accuracy (multi-tool ordering).

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 1.2.1 | Add `param_accuracy` computation to `ToolSelectionEvaluator.evaluate_batch()` in `tests/eval/evaluator.py` (after line 157). Count queries where `param_match is True` vs. queries where `param_match is not None`. Report as `param_accuracy` float in the returned dict. | `evaluate_batch()` return dict includes `"param_accuracy"` key with float 0.0-1.0. Queries without `expected_params` are excluded from the denominator. | S |
| 1.2.2 | Add `chain_accuracy` computation to `ToolSelectionEvaluator.evaluate_batch()`. For queries with `len(expected_tools) >= 2`, check whether `actual_tools` contains the expected tools in the correct relative order (not necessarily contiguous). Report as `chain_accuracy` float. | `evaluate_batch()` return dict includes `"chain_accuracy"` key. Computed only over multi-tool queries (complexity `moderate`, `complex`, or `multi_step`). Single-tool queries excluded from denominator. | M |
| 1.2.3 | Add `chain_order_correct` field to the per-query result dict returned by `evaluate_single()` (line 76-97 in `evaluator.py`). For single-tool queries, set to `None`. For multi-tool queries, compute by checking subsequence ordering of expected tools within actual tools. | `evaluate_single()` result includes `"chain_order_correct"`: `True`, `False`, or `None`. | S |
| 1.2.4 | Update `generate_report()` in `evaluator.py` (line 159) to include the two new metrics in the Summary section and add a "Chain Accuracy by Complexity" table. | Markdown report includes `param_accuracy` and `chain_accuracy` in Summary. Chain table shows accuracy for `moderate`, `complex`, `multi_step` rows. | S |

### Epic 1.3: Run Live Evaluation and Record Baseline

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 1.3.1 | Add `--output` flag to `run_eval.py` `main()` (line 107) that writes raw evaluation results to a JSON file. Include timestamp, query count, provider, model, and the full `evaluate_batch()` output dict. | `python -m tests.eval.run_eval --mock --all --output results.json` produces a valid JSON file with all fields. | S |
| 1.3.2 | Fix `run_live_evaluation()` in `run_eval.py` (line 47) to handle the event stream correctly. Currently it tries `json.loads(event)` but `process_message()` yields dicts, not strings. Add type checking: if `event` is already a dict, use it directly. | `run_live_evaluation()` does not crash on dict events. Tool names are correctly extracted from `tool_start` events. | XS |
| 1.3.3 | Run live evaluation with `--all` flag against all 50+ queries. Save output to `docs/v2/baseline-results.json`. This is a manual execution step, not a code change. | `docs/v2/baseline-results.json` exists with `total >= 50`, `accuracy` field populated, all three metrics present. | M |
| 1.3.4 | Generate the markdown baseline report from live results and save to `docs/v2/baseline-scorecard.md` using `generate_report()`. This is a manual execution step. | `docs/v2/baseline-scorecard.md` contains Summary with tool_accuracy, param_accuracy, chain_accuracy, plus breakdown tables. | XS |

---

## Milestone 2: Failure Classification

### Epic 2.1: Define Failure Taxonomy

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 2.1.1 | Create `tests/eval/failure_taxonomy.py` defining a `FailureCategory` enum with these categories: `WRONG_TOOL` (selected a different tool entirely), `RIGHT_TOOL_WRONG_PARAMS` (correct tool, incorrect parameters), `MISSING_CHAIN_STEP` (multi-tool query, omitted a required tool), `EXTRA_CHAIN_STEP` (added unnecessary tools), `AMBIGUOUS_QUERY` (query was genuinely ambiguous, multiple valid interpretations), `TOOL_DESCRIPTION_MISLEADING` (tool description led LLM astray), `WRONG_CHAIN_ORDER` (correct tools but wrong execution order). | Enum importable. 7 categories defined. Each has a `label` and `description` property. | S |
| 2.1.2 | Add `classify_failure()` function to `tests/eval/failure_taxonomy.py`. Takes an evaluation result dict (from `evaluate_single()`) and returns the most specific `FailureCategory`. Classification logic: if `match == "full"` return `None`; if `missing_tools` non-empty and `extra_tools` non-empty, check if extra tools are semantically related (heuristic: same category in `reference_queries.py`) to classify as `WRONG_TOOL` vs `MISSING_CHAIN_STEP`; if `param_match is False` and `match == "full"`, return `RIGHT_TOOL_WRONG_PARAMS`; if `chain_order_correct is False`, return `WRONG_CHAIN_ORDER`. | Function returns `None` for passing queries. Returns a `FailureCategory` for every failing query. Unit tests cover all 7 categories. | M |

### Epic 2.2: Integrate Classification into Evaluator

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 2.2.1 | Add `failure_category` field to the per-query result dict in `evaluate_single()` by calling `classify_failure()` after building the result dict. Import from `tests.eval.failure_taxonomy`. | Each evaluation result dict includes `"failure_category"`: string label or `None`. | XS |
| 2.2.2 | Add `failure_breakdown` to `evaluate_batch()` output: a dict mapping each `FailureCategory` label to its count and list of affected query IDs. | `evaluate_batch()` return dict includes `"failure_breakdown"` with category counts. Sum of all category counts equals `partial_match + no_match`. | S |
| 2.2.3 | Add "Failure Classification" section to `generate_report()` output. Table with columns: Category, Count, Percentage, Example Query IDs (up to 3). | Markdown report includes failure classification table. Categories sorted by count descending. | S |

### Epic 2.3: Classify All Failures from Baseline

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 2.3.1 | Run the updated evaluator against the live baseline results (`docs/v2/baseline-results.json`). For any failures where `classify_failure()` returns `AMBIGUOUS_QUERY` or `TOOL_DESCRIPTION_MISLEADING`, manually review and annotate. Save annotated results to `docs/v2/baseline-classified.json`. | Every failed query has a `failure_category` field. Manual annotations added as `"manual_notes"` field where automatic classification was insufficient. | M |

---

## Milestone 3: Ranked Failure Patterns and Fix List

### Epic 3.1: Pattern Extraction and Ranking

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 3.1.1 | Add `rank_failure_patterns()` function to `tests/eval/failure_taxonomy.py`. Takes the `failure_breakdown` dict from `evaluate_batch()` and returns a sorted list of `(category, count, percentage, affected_tool_names, example_queries)` tuples. Group by failure category, then within each category identify the specific tools most frequently involved. | Function returns list sorted by count descending. Each entry includes the specific tool names involved (e.g., "fetch_osm confused with search_nearby" not just "WRONG_TOOL"). | S |
| 3.1.2 | Add `--rank` flag to `run_eval.py` that prints the top N failure patterns (default 10). Format as a numbered list with category, count, affected tools, and recommended fix area (system prompt in `chat.py`, tool description in `tools.py`, or query reformulation). | `python -m tests.eval.run_eval --live --all --rank` prints ranked list. Each entry references a specific file and section to fix. | S |

### Epic 3.2: Produce Prioritized Fix List

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 3.2.1 | Generate `docs/v2/failure-patterns.md` from the ranked output. For each of the top 10 patterns, document: rank, failure category, frequency (count and %), affected tools, example failing queries (ID and text), root cause hypothesis, and recommended fix target (one of: `nl_gis/chat.py` SYSTEM_PROMPT section, `nl_gis/tools.py` tool description, `tests/eval/reference_queries.py` query reformulation). | File contains 10 entries (or fewer if <10 distinct patterns). Each entry has all 7 fields populated. Fix targets reference specific line ranges. | M |
| 3.2.2 | Add a summary table at the top of `docs/v2/failure-patterns.md` mapping each pattern to the downstream prompt (Prompts 2-7 from `docs/v2/PROMPTS.md`) that will address it. This creates the explicit link between audit findings and improvement work. | Summary table has columns: Rank, Pattern, Fix Target, Downstream Prompt. Every pattern maps to at least one prompt. | XS |

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Live eval costs: 50+ API calls to Claude | ~$2-5 depending on model | Use `CLAUDE_MODEL` env var to select a cheaper model for baseline. Run `--mock` first to verify framework works. |
| Non-deterministic LLM responses | Baseline varies between runs | Record exact model version and timestamp in output JSON. Run 2-3 times and report variance. |
| `classify_failure()` heuristic misclassifies edge cases | Wrong priorities in fix list | Include `AMBIGUOUS_QUERY` as a catch-all. Manual review step (Epic 2.3) catches misclassifications. |
| `run_live_evaluation()` crashes mid-run | Partial results lost | Task 1.3.1 adds `--output` flag that writes incrementally. Existing error handling in `run_live_evaluation()` (line 88-89) catches per-query exceptions. |
| New queries may have wrong expected_tools | False failures inflate error rate | Validate new queries against mock responses first (`--mock --all`). Mock eval should be 100% before running live. |

## Output Artifacts

| Artifact | Path | Content |
|----------|------|---------|
| Expanded reference queries | `tests/eval/reference_queries.py` | 62+ queries, 64 tools in `ALL_TOOLS` |
| Expanded mock responses | `tests/eval/mock_responses.py` | Mock entries for all 62+ queries |
| Failure taxonomy | `tests/eval/failure_taxonomy.py` | `FailureCategory` enum, `classify_failure()`, `rank_failure_patterns()` |
| Enhanced evaluator | `tests/eval/evaluator.py` | `param_accuracy`, `chain_accuracy`, `failure_category`, `failure_breakdown` |
| Enhanced runner | `tests/eval/run_eval.py` | `--output`, `--rank` flags, incremental JSON output |
| Baseline results | `docs/v2/baseline-results.json` | Raw JSON from live eval run |
| Baseline scorecard | `docs/v2/baseline-scorecard.md` | Formatted report with 3 metrics + breakdowns |
| Classified failures | `docs/v2/baseline-classified.json` | Every failure annotated with category |
| Prioritized fix list | `docs/v2/failure-patterns.md` | Top 10 patterns ranked, mapped to downstream prompts |
