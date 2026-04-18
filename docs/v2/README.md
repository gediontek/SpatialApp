# SpatialApp — v2.1 (Active Planning)

**Status:** Active — 13 plans drafted, none started.
**Drafted:** 2026-04-11 (commit `ad1d3f8`)
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
| 07 | [provider-tuning](07-provider-tuning-plan.md) | Prompt + model tuning, fine-tuning (successor to v1 D2) | Planned |
| 08 | [raster-analysis](08-raster-analysis-plan.md) | 5 raster tools + DEM derivatives (rescoped: skip tile serving blueprint) | ✅ **Done** (rescoped). `raster_info`, `raster_value`, `raster_statistics` (incl. zonal + slope/aspect/hillshade), `raster_profile`, `raster_classify`. 24 new tests. 69 tools total. |
| 09 | [collaboration](09-collaboration-plan.md) | Multi-user sessions, shared state | Planned |
| 10 | [data-pipeline](10-data-pipeline-plan.md) | 4 pipeline tools + validation module (rescoped: skip sample_points, batch_spatial_query, pipeline patterns) | ✅ **Done** (rescoped). `clip_to_bbox`, `generalize` (m-based), `export_gpkg`, `import_auto` + `nl_gis/validation.py`. 30 new tests. 73 tools total. |
| 11 | [visualization](11-visualization-plan.md) | Chart/dashboard output, visual rendering | Planned |
| 12 | [osm-autolabel](12-osm-autolabel-plan.md) | OSM auto-labelling enhancements | Planned |
| 13 | [production](13-production-plan.md) | Vector tiles, auto-scaling, deploy hardening (successor to v1 C2) | Planned |

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
