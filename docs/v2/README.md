# SpatialApp — v2.1 (Active Planning)

**Status:** All 13 plans landed (rescoped surgically per project pattern). 82 tools, 1,406 backend tests passing.
**Drafted:** 2026-04-11 (commit `ad1d3f8`)
**Last shipped:** 2026-05-01 — Plans 07/09/11/12/13 in a single working session.
**For current code status:** see [`.project_plan/STATUS.md`](../../.project_plan/STATUS.md)
**For shipped history:** see [`docs/v1/`](../v1/)

---

## Scope

v2.1 raises the NL-GIS pipeline from ~85% tool-selection accuracy (v2.0 baseline) toward ~97% research SOTA, deepens feature coverage (raster, collaboration, visualization), and hardens for production.

## Plans

| # | Plan | Theme | Status |
|---|------|-------|--------|
| 01 | [accuracy-audit](01-accuracy-audit-plan.md) | Measure before improving — baseline eval, failure taxonomy, ranked fix list | ✅ **Done** (M1–M3 complete). See [`baseline-scorecard.md`](baseline-scorecard.md), [`baseline-classified.json`](baseline-classified.json), [`failure-patterns.md`](failure-patterns.md) |
| 02 | [tool-descriptions](02-tool-descriptions-plan.md) | Tool description engineering (rescoped: Gemini-safe, surgical-only) | ✅ **Done** (rescoped). Tool: 51.6%→53.2%, Param: 60%→74.3%. Full-scope enrichment rejected (regressed on Flash). See [`post-02-rescoped-results.json`](post-02-rescoped-results.json). |
| 03 | [complex-queries](03-complex-queries-plan.md) | Pattern catalog + parameter threading + chain validation (rescoped: skip runtime SYSTEM_PROMPT injection) | ✅ **Done** (rescoped). 10-pattern catalog, `$stepN.field` threading in plan mode, pre-flight chain validation, 28 new tests. |
| 04 | [context-awareness](04-context-awareness-plan.md) | Context library + handler attribute validation (rescoped: skip unconditional prompt injection) | ✅ **Done** (rescoped). `nl_gis/context.py` library, ReferenceTracker, attribute validation in filter_layer + highlight_features, 26 new tests. |
| 05 | [error-recovery](05-error-recovery-plan.md) | Retry, graceful degradation, circuit breaker, result-size guards | ✅ **Done** (M1–M5 complete, 24 new tests) |
| 06 | [eval-framework](06-eval-framework-plan.md) | Granular param scoring + CI mode + regression detection + baseline persistence (rescoped: skip 58-query expansion) | ✅ **Done** (rescoped). `--ci`, `--save-baseline`, `--check-regression`, `--save-report` flags; coord/CRS tolerance; 19 new tests. |
| 07 | [provider-tuning](07-provider-tuning-plan.md) | Prompt + model tuning, fine-tuning (successor to v1 D2) | ✅ **Done** (rescoped: mechanism only, no live bake-off). `provider_hints` field, per-provider `description_suffix` application in all 3 providers, `get_system_prompt(provider_name)` with ANTHROPIC/OPENAI/GEMINI addenda, `--provider {anthropic\|openai\|gemini\|all}` and `--parity-threshold` flags in `tests/eval/run_eval.py`, `compare_providers()` + `check_parity()`, `PROVIDER_NOTES` reference. 23 new tests. |
| 08 | [raster-analysis](08-raster-analysis-plan.md) | 5 raster tools + DEM derivatives (rescoped: skip tile serving blueprint) | ✅ **Done** (rescoped). `raster_info`, `raster_value`, `raster_statistics` (incl. zonal + slope/aspect/hillshade), `raster_profile`, `raster_classify`. 24 new tests. 69 tools total. |
| 09 | [collaboration](09-collaboration-plan.md) | Multi-user sessions, shared state | ✅ **Done** (rescoped: backend only, frontend deferred). `blueprints/collab.py` (create/info/resume/export REST), 5 new WS events (join_collab/leave_collab/cursor_move/layer_remove/layer_style), `collab_sessions` SQLite table + persistence, throttled cursor broadcast, FIFO-capped layer history, 10-color palette. 30 new tests. |
| 10 | [data-pipeline](10-data-pipeline-plan.md) | 4 pipeline tools + validation module (rescoped: skip sample_points, batch_spatial_query, pipeline patterns) | ✅ **Done** (rescoped). `clip_to_bbox`, `generalize` (m-based), `export_gpkg`, `import_auto` + `nl_gis/validation.py`. 30 new tests. 73 tools total. |
| 11 | [visualization](11-visualization-plan.md) | Chart/dashboard output, visual rendering | ✅ **Done** (rescoped: backend tools, JS deferred). `choropleth_map` (quantile/equal_interval/natural_breaks/manual + sequential/diverging/qualitative ramps), `chart` (bar/pie/histogram/scatter), `animate_layer` (auto-binned at >100 unique values), `visualize_3d` (height fallback chain). Also fixed matplotlib ≥3.10 contour API regression. 43 new tests. 77 tools total. |
| 12 | [osm-autolabel](12-osm-autolabel-plan.md) | OSM auto-labelling enhancements | ✅ **Done** (rescoped: handler bridge with mock-friendly seam). `classify_area`, `predict_labels`, `train_classifier` (annotation-based seed update), `export_training_data` (geojson/csv), `evaluate_classifier` (pure-numpy accuracy + per-class precision/recall/F1 + confusion matrix). Heavy deps (gensim/osmnx) optional — handlers return clear error if missing. 30 new tests. 82 tools total. |
| 13 | [production](13-production-plan.md) | Vector tiles, auto-scaling, deploy hardening (successor to v1 C2) | ✅ **Done** (rescoped: security + caching + Docker; load test deferred). Security headers (CSNP/X-Frame-Options/Referrer-Policy/HSTS conditional on X-Forwarded-Proto), `services/model_router.py` (heuristic simple/complex tiering), `services/llm_cache.py` (LRU+TTL + key stability + bypass phrases), `/api/health/ready` (503 when DB or LLM key missing), uptime+version on `/api/health`, multi-stage Dockerfile (non-root user, runtime libs only). 30 new tests. |

## How to Work These Plans

Each plan is structured as **Milestones → Epics → Tasks** with acceptance criteria and effort estimates. See [PROMPTS.md](PROMPTS.md) for the generation prompts.

**Before starting execution:** read [`DEPENDENCIES.md`](DEPENDENCIES.md) — it maps hidden dependencies between plans, identifies touchpoint hotspots, and recommends execution order.

**Recommended order (from DEPENDENCIES.md):**
```
Phase 0 (parallel):  01 Accuracy Audit + 05 Error Recovery
Phase 1:             02+03 paired → 06 → 07
Phase 2 (parallel):  04 · 08 · 10 · 11 · 12
Phase 3:             09 (needs stable chat.py) → 13
```

## Status Updates

When a plan lands, update its row to `In progress` or `Done` and note the commit hash. Keep this README the single source of truth for v2.1 progress.
