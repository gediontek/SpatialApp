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
| 01 | [accuracy-audit](01-accuracy-audit-plan.md) | Measure before improving — baseline eval on 50+ queries, failure taxonomy | Planned |
| 02 | [tool-descriptions](02-tool-descriptions-plan.md) | Tool description engineering for 64 tools (finishes A3 from v1) | Planned |
| 03 | [complex-queries](03-complex-queries-plan.md) | Multi-step reasoning, multi-agent decomposition (successor to v1 D1) | Planned |
| 04 | [context-awareness](04-context-awareness-plan.md) | Session/layer context reuse across turns | Planned |
| 05 | [error-recovery](05-error-recovery-plan.md) | Retry, graceful degradation, user-facing recovery | Planned |
| 06 | [eval-framework](06-eval-framework-plan.md) | Deepens v1 A4 — CI-integrated accuracy regression gates | Planned |
| 07 | [provider-tuning](07-provider-tuning-plan.md) | Prompt + model tuning, fine-tuning (successor to v1 D2) | Planned |
| 08 | [raster-analysis](08-raster-analysis-plan.md) | Elevation/DEM, slope/aspect, viewshed (successor to v1 C1) | Planned |
| 09 | [collaboration](09-collaboration-plan.md) | Multi-user sessions, shared state | Planned |
| 10 | [data-pipeline](10-data-pipeline-plan.md) | ETL workflows, data ingestion automation | Planned |
| 11 | [visualization](11-visualization-plan.md) | Chart/dashboard output, visual rendering | Planned |
| 12 | [osm-autolabel](12-osm-autolabel-plan.md) | OSM auto-labelling enhancements | Planned |
| 13 | [production](13-production-plan.md) | Vector tiles, auto-scaling, deploy hardening (successor to v1 C2) | Planned |

## How to Work These Plans

Each plan is structured as **Milestones → Epics → Tasks** with acceptance criteria and effort estimates. See [PROMPTS.md](PROMPTS.md) for the generation prompts and execution order.

**Recommended order:** 01 → 06 → 02 (measure → gate → improve) then fan out by theme.

## Status Updates

When a plan lands, update its row to `In progress` or `Done` and note the commit hash. Keep this README the single source of truth for v2.1 progress.
