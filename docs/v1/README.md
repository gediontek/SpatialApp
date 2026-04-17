# SpatialApp — v1 (Shipped)

**Status:** Frozen. All content in this folder describes completed work.
**Shipped:** 2026-04-11
**For current status:** see [`.project_plan/STATUS.md`](../../.project_plan/STATUS.md)
**For active work:** see [`docs/v2/`](../v2/)

---

## What v1 Delivered

| Release | Scope | Outcome |
|---------|-------|---------|
| v1.0 | Bug fixes & hardening | 80 bugs fixed (2 critical, 15 high, 32 medium, 31 low), 33 quality/security improvements |
| v1.1 | Architectural refactor | App factory, 7 blueprints, state module, handler package |
| v1.2 | Infrastructure | Connection pooling, structured logging, Gunicorn, STRtree, responsive CSS |
| v1.3 | Features | Multi-stop routing, dashboard, WebSocket, PostGIS migration path |
| v2.0 M1 | Spatial analysis depth | Interpolation, topology validation/repair, service areas |
| v2.0 M2 | Data pipeline | KML import, GeoParquet, data quality tools |
| v2.0 M3 | Infrastructure | Prometheus metrics, layer pagination |
| v2.0 M5 | Capability expansion | 8 tools: CRS, network, geometry, temporal |
| v2.0 M6 | Integration | Tests, documentation, performance benchmarks |
| A1-A4 | LLM accuracy | Code-gen fallback, plan-then-execute, enhanced tool descriptions, LLM-as-judge eval |
| B1-B4 | Spatial ops | Hot-spot analysis, IDW interpolation, topology validation, service areas |
| C3 | Observability | Prometheus metrics endpoint |

## Files in This Folder

| File | Origin | Status |
|------|--------|--------|
| [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) | Research-driven improvement plan (4 tracks, 15 initiatives) | ~80% shipped. Residuals (C1 raster, C2 vector tiles, D1 multi-agent, D2 fine-tuning) rolled forward into v2.1 — see successor links in the file. |
| [ENRICHMENT_PLAN.md](ENRICHMENT_PLAN.md) | Enrichment plan (6 milestones, 18 epics, 70 tasks, 190 tests) | 100% shipped as v2.0 M1-M6. |

## What's Next (v2.1)

All forward-looking work moved to [`docs/v2/`](../v2/). Start there for active plans.
