# Plan 6: Evaluation Framework Expansion

**Objective**: Expand the eval framework from POC (42 queries, tool-selection-only) to a production quality gate with 100 queries, parameter accuracy scoring, CI integration, regression detection, and per-run reporting.

**Scope**: ~300 lines of code, 1-2 focused days.

**Key files touched**:
- `tests/eval/reference_queries.py` -- expand from 42 to 100 queries
- `tests/eval/mock_responses.py` -- add mock responses for new queries
- `tests/eval/evaluator.py` -- add parameter scoring in `ToolSelectionEvaluator`
- `tests/eval/run_eval.py` -- add `--ci` mode, `--save-report`, regression detection
- `.github/workflows/ci.yml` -- add eval job triggered on `nl_gis/` and `tools.py` changes

---

## Milestone 1: Expand Reference Queries to 100

### Epic 1.1: Define Query Tiers and Fill Gaps

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.1.1 | Audit tool coverage gaps in current 42 queries using `get_tool_coverage()` in `reference_queries.py`. Identify which of the 44 tools in `ALL_TOOLS` lack queries at each complexity tier. | Written list of uncovered tool x tier combinations. | XS |
| T1.1.2 | Add 25 **basic** queries (single-tool, direct mapping) to `REFERENCE_QUERIES` in `reference_queries.py`. Each must cover a distinct tool or tool variant not already tested at basic level. Include `expected_params` for every query. IDs: `Q031`-`Q055`. | 25 new entries with `complexity: "simple"`, each has `expected_tools` (length 1) and `expected_params`. All pass schema validation. | M |
| T1.1.3 | Add 25 **intermediate** queries (2-3 tool chains, parameter inference) to `REFERENCE_QUERIES`. IDs: `Q056`-`Q080`. Cover chaining patterns from `SYSTEM_PROMPT` in `chat.py` (e.g., geocode -> buffer -> spatial_query, fetch_osm -> aggregate -> style_layer). | 25 new entries with `complexity: "moderate"` or `"multi_step"`, each with 2-3 expected tools and `expected_params` for at least the primary tool. | M |
| T1.1.4 | Add 25 **advanced** queries (4+ tool chains, ambiguous phrasing, implicit parameters) to `REFERENCE_QUERIES`. IDs: `Q081`-`Q105`. Include queries that require the LLM to infer context (e.g., "color the results red" implies style_layer on the most recent layer). | 25 new entries with `complexity: "complex"`, 4+ expected tools, `expected_params` for key tools. | M |
| T1.1.5 | Add 25 **stress** queries (adversarial phrasing, near-miss tool names, ambiguous spatial language) as a new `STRESS_QUERIES` list in `reference_queries.py`. IDs: `X001`-`X025`. Examples: "zoom into that thing we just looked at", "make a donut around the park" (buffer + difference), "show me everything nearby" (ambiguous radius). | 25 entries with `complexity: "stress"`. Each has a `notes` field explaining what makes it adversarial. | M |

### Epic 1.2: Add Mock Responses for New Queries

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.2.1 | Add mock responses in `mock_responses.py` for Q031-Q055 (basic tier). Each entry in `MOCK_RESPONSES` dict must return the correct tool chain via `_tool_use()`. | `get_mock_tools(q_id)` returns expected tools for all 25 new basic queries. `run_mock_evaluation` passes at 100% for these queries. | S |
| T1.2.2 | Add mock responses for Q056-Q080 (intermediate tier). | Same as T1.2.1 for intermediate queries. | S |
| T1.2.3 | Add mock responses for Q081-Q105 (advanced tier). | Same as T1.2.1 for advanced queries. | S |
| T1.2.4 | Add mock responses for X001-X025 (stress tier). | Same as T1.2.1 for stress queries. | S |

### Epic 1.3: Validate Expanded Query Set

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.3.1 | Update `get_tool_coverage()` to accept a `tier` filter parameter. Add a `QUERY_TIERS` dict mapping tier name to query list. Update `ALL_QUERIES` to include `STRESS_QUERIES`. | `get_tool_coverage(tier="basic")` returns coverage for that tier only. `ALL_QUERIES` has 100 entries. | S |
| T1.3.2 | Run `python -m tests.eval.run_eval --mock --all` and verify 100% mock accuracy across all 100 queries. Fix any mock response mismatches. | Exit code 0, accuracy 100% on mock run. | XS |

---

## Milestone 2: Parameter Accuracy Scoring

### Epic 2.1: Granular Parameter Scoring in `evaluator.py`

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.1.1 | Replace the boolean `_check_params()` function in `evaluator.py` with a new `_score_params()` that returns a dict: `{"score": float, "total_params": int, "matched": int, "mismatched": list[str], "missing": list[str]}`. Score = matched / total_params. A param matches if: exact match for strings/ints, within 0.001 for floats, case-insensitive for CRS strings. | `_score_params({"geocode": {"query": "Berlin"}}, {"geocode": {"query": "Berlin"}})` returns `{"score": 1.0, ...}`. Mismatched values appear in `mismatched` list with expected vs actual. | M |
| T2.1.2 | Update `evaluate_single()` to replace the boolean `param_match` with the granular `param_score` dict from `_score_params()`. Keep backward compat: if `expected_params` is None, `param_score` is None. | `evaluate_single()` result includes `"param_score": {"score": 0.75, "matched": 3, "total_params": 4, ...}`. | S |
| T2.1.3 | Update `evaluate_batch()` to compute aggregate parameter accuracy: `param_accuracy = mean(param_score["score"])` across all queries that have `expected_params`. Add `param_accuracy` to the batch result dict. Add `by_category` and `by_complexity` breakdowns for param accuracy. | Batch result includes `"param_accuracy": 0.85` and per-category/per-complexity param accuracy. | S |
| T2.1.4 | Update `generate_report()` in `evaluator.py` to include a "Parameter Accuracy" section in the markdown output. Show overall param accuracy, per-category breakdown, and list the top 5 worst param mismatches with expected vs actual values. | Report includes `## Parameter Accuracy` section with table and mismatch details. | S |

### Epic 2.2: Coordinate and CRS-Specific Matching

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.2.1 | Add coordinate tolerance matching in `_score_params()`: if param name contains `lat`, `lon`, `longitude`, `latitude`, match within 0.01 degrees (~1km). Add `coordinate_tolerance` parameter to `ToolSelectionEvaluator.__init__()` (default 0.01). | `_score_params({"geocode": {"lat": 40.712}}, {"geocode": {"lat": 40.713}})` scores the lat param as matched (within 0.01). | S |
| T2.2.2 | Add CRS string normalization: treat "EPSG:4326", "epsg:4326", "WGS84", "wgs84" as equivalent. Apply before comparison when param name contains `crs`, `srs`, or `projection`. | `_score_params({"reproject": {"crs": "EPSG:4326"}}, {"reproject": {"crs": "epsg:4326"}})` scores as matched. | XS |

---

## Milestone 3: CI Integration

### Epic 3.1: CI Eval Job in `.github/workflows/ci.yml`

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T3.1.1 | Add `--ci` flag to `run_eval.py` `main()`. When set: (1) always use `--mock`, (2) exit code 1 if tool accuracy < 0.80 OR param accuracy < 0.70, (3) print summary to stdout in a format parseable by CI (JSON one-liner). | `python -m tests.eval.run_eval --ci` exits 0 when thresholds met, 1 otherwise. Stdout includes `{"accuracy": 0.95, "param_accuracy": 0.88, "pass": true}`. | S |
| T3.1.2 | Add `eval` job to `.github/workflows/ci.yml` that runs on PRs touching `nl_gis/**` or `nl_gis/tools.py`. Job: checkout, setup Python 3.11, install deps, run `python -m tests.eval.run_eval --ci --all`. | CI job triggers only on relevant file changes (use `paths` filter). Job fails if eval thresholds not met. | S |
| T3.1.3 | Add configurable thresholds via environment variables: `EVAL_TOOL_THRESHOLD` (default 0.80) and `EVAL_PARAM_THRESHOLD` (default 0.70) in `run_eval.py`. CI job passes these as env vars so thresholds can be tightened over time without code changes. | Thresholds read from env vars with defaults. CI yaml sets explicit values. | XS |

---

## Milestone 4: Regression Detection

### Epic 4.1: Baseline Storage and Comparison

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.1.1 | Add `--save-baseline` flag to `run_eval.py` that writes the current eval results to `tests/eval/baseline.json`. Format: `{"timestamp": "...", "accuracy": float, "param_accuracy": float, "by_category": {...}, "by_complexity": {...}}`. | Running `--save-baseline` creates/overwrites `baseline.json` with current scores. File is committed to repo. | S |
| T4.1.2 | Add `--check-regression` flag to `run_eval.py` that loads `tests/eval/baseline.json` and compares current run against it. Flag regression if any category drops >5% from baseline. Print which categories regressed and by how much. | `--check-regression` exits 1 if any category drops >5%. Stdout: `REGRESSION: spatial_analysis dropped from 0.92 to 0.84 (-8.7%)`. | M |
| T4.1.3 | Integrate `--check-regression` into the CI eval job (T3.1.2). The eval job should fail if regression is detected. Commit a baseline file with the initial 100-query results. | CI eval job runs with `--check-regression`. Baseline file exists in repo at `tests/eval/baseline.json`. | S |

---

## Milestone 5: Eval Report Generation

### Epic 5.1: Markdown Report Persistence

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T5.1.1 | Add `--save-report` flag to `run_eval.py` that writes the markdown report (from `generate_report()`) to `tests/eval/reports/eval_YYYYMMDD_HHMMSS.md`. Create the `reports/` directory if it doesn't exist. Add `tests/eval/reports/` to `.gitignore`. | Running `--save-report` creates a timestamped markdown file. Directory auto-created. Reports not committed to git. | S |
| T5.1.2 | Extend `generate_report()` in `evaluator.py` to include: (1) run metadata header (timestamp, provider, model, query count), (2) parameter accuracy section (from M2), (3) regression delta section (if baseline provided), (4) tool coverage summary from `get_tool_coverage()`. | Report includes 4 sections: metadata, accuracy tables, param accuracy, coverage. | M |
| T5.1.3 | Add `--compare` flag to `run_eval.py` that accepts a path to a previous report JSON and appends a "Delta" column to each accuracy table (current vs previous). | `--compare tests/eval/reports/previous.json` produces report with delta columns showing improvement/regression per category. | S |

---

## Dependencies

```
M1 (queries) ──> M2 (param scoring) ──> M3 (CI integration)
                                    └──> M4 (regression detection)
                                    └──> M5 (report generation)
```

M1 must complete first (queries + mocks are inputs to everything else). M2 provides the scoring used by M3-M5. M3, M4, M5 can proceed in parallel after M2.

## Risk Mitigations

- **Mock drift**: Mock responses must exactly match expected tools. T1.3.2 validates this before moving to M2.
- **Threshold tuning**: Starting with 80% tool / 70% param thresholds. These are env-var configurable (T3.1.3) so they can be tightened as the system improves.
- **Flaky CI**: Eval uses `--mock` in CI, so no API calls, no flakiness from LLM nondeterminism.
- **Baseline staleness**: Baseline is committed to repo and updated when new queries are added. The `--save-baseline` flag makes this explicit.
