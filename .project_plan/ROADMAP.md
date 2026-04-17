# SpatialApp Roadmap

**Navigation:** [Status](STATUS.md) · [Shipped history → `docs/v1/`](../docs/v1/) · [Active plans → `docs/v2/`](../docs/v2/)

---

## Shipped — v1.0 through v2.0 (2026-04-11)

All items below are complete. Full details in [`docs/v1/`](../docs/v1/).

### v1.0 — Bug Fixes & Hardening
- 80 bugs fixed (2 critical, 15 high, 32 medium, 31 low)
- 33 quality/security/performance improvements
- Tests: 236 → 438

### v1.1 — Architectural Refactor
- App factory pattern, 7 blueprints, state module, handler package
- DB-first data flow, stale import cleanup

### v1.2 — Infrastructure
- Connection pooling, structured logging, Gunicorn, STRtree, responsive CSS

### v1.3 — Features
- Multi-stop routing, user dashboard, WebSocket, PostGIS migration path

### v2.0 — Spatial Operations Expansion
- **M1** Interpolation, topology validation/repair, service areas
- **M2** KML import, GeoParquet, data quality tools
- **M3** Prometheus metrics, layer pagination
- **M5** 8 capability tools (CRS, network, geometry, temporal)
- **M6** Integration tests, documentation, performance benchmarks
- **A1-A4** Code-gen fallback, plan-then-execute, enhanced tool descriptions, LLM-as-judge eval
- **B1-B4** Hot-spot analysis, IDW interpolation, topology validation, multi-facility service areas
- **C3** Prometheus metrics endpoint

Result: 64 tools, 1002 tests, 51 commits.

Source plans (frozen): [`docs/v1/IMPROVEMENT_PLAN.md`](../docs/v1/IMPROVEMENT_PLAN.md), [`docs/v1/ENRICHMENT_PLAN.md`](../docs/v1/ENRICHMENT_PLAN.md).

---

## Active — v2.1 (planned, not started)

All v2.1 planning lives in [`docs/v2/`](../docs/v2/) as 13 milestone/epic/task plans. See [`docs/v2/README.md`](../docs/v2/README.md) for the status dashboard.

**Themes:**
- NL-GIS intelligence: accuracy audit, tool description engineering, complex queries, context awareness, error recovery, eval framework, provider tuning
- Feature depth: raster analysis, collaboration, data pipeline, visualization, OSM auto-label
- Production: deploy hardening, vector tiles, auto-scaling

**Recommended order:** 01 (audit) → 06 (eval gates) → 02 (tool descriptions), then fan out by theme.

---

## Future — v3.0 (not yet planned in detail)

These items are acknowledged but not yet broken down into plans. Some may be absorbed into v2.1 if priorities shift.

### PostGIS Implementation (stub exists)
- Full PostgresDatabase class, server-side spatial queries, GIST indexes, data migration script

### Performance at Scale
- Streaming large GeoJSON, viewport-based rendering, vector tiles via tippecanoe, spatial query memoization

### Deployment
- Docker containerization, CI/CD, auto-scaling

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-10 | Fix bugs before refactoring | Correct behavior first, then restructure |
| 2026-04-10 | DB-first over in-memory-first | Process restart = silent data loss was unacceptable |
| 2026-04-11 | Blueprints over microservices | Same-process for SQLite; blueprints provide separation without IPC |
| 2026-04-11 | WebSocket alongside SSE | SSE is simpler, works everywhere; WebSocket is enhancement |
| 2026-04-11 | PostGIS stub over full implementation | SQLite works at current scale; path ready when needed |
| 2026-04-11 | Flexible OSM queries over fixed enum | Gap analysis showed 12 types blocks real usage (BLOCKING) |
| 2026-04-11 | Overlay ops as P0 over P1 | Gap analysis: can't answer fundamental spatial questions without intersection/difference |
| 2026-04-11 | Tool instrumentation before LLM tuning | Can't improve what you can't measure |
| 2026-04-17 | Separate v1 (shipped) from v2 (active) in docs | Eliminates reader ambiguity about what's done vs. planned |
