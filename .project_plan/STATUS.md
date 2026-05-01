# SpatialApp Project Status

**Last updated**: 2026-05-01
**Current version**: v2.0 + v2.1 complete (all 13 plans rescoped + shipped)
**Tests**: 1,406 passing across 45 test files (30 e2e skipped — Playwright browser not installed)
**Commits**: 75 on main
**Health**: All systems operational

**Navigation:** [Shipped history → `docs/v1/`](../docs/v1/) · [Active plans → `docs/v2/`](../docs/v2/) · [Roadmap](ROADMAP.md) · [Architecture](ARCHITECTURE.md) · [Capability map](CAPABILITY_MAP.md)

---

## Current State: v2.1 Complete

### Core Metrics

| Metric | 2026-04-02 | 2026-04-11 (v1.3) | 2026-04-17 (v2.0) | 2026-05-01 (v2.1) | Delta (total) |
|--------|------------|-------------------|-------------------|-------------------|---------------|
| Tools (LLM API) | 24 | 26 | 64 | 82 | +242% |
| Tests collected | 236 | 438 | 1002 | 1,406 | +496% |
| Test files | ~10 | 15 | 35 | 45 | +350% |
| Handlers | monolith | 6 | 5 | 7 (visualization, autolabel) | — |
| Blueprints | — | 5 | 7 | 8 (collab) | +3 |
| Services | 4 | 7 | 9 | 13 (llm_cache, model_router, ...) | +9 |
| Commits | — | 22 | 51 | 75 | +53 |

### What Shipped (Chronological)

**v1.0-v1.3** (2026-04-10 → 2026-04-11)
- 80 bugs fixed (2 critical, 15 high, 32 medium, 31 low)
- 33 quality/security/performance improvements
- Blueprint refactor + app factory + handler package
- Connection pooling, structured logging, Gunicorn, STRtree, responsive CSS
- Multi-stop routing, dashboard, WebSocket, PostGIS migration path

**v2.0** (2026-04-11)
- **M1** — Spatial analysis depth: interpolation, topology validation/repair, service areas (commit `90f19fa`)
- **M2** — Data pipeline: KML import, GeoParquet, data quality tools (commit `4576912`)
- **M3** — Infrastructure: Prometheus metrics, layer pagination (commit `fd9c050`)
- **M5** — Capability tools: 8 tools — CRS, network, geometry, temporal (commit `91799c9`)
- **M6** — Integration: tests, documentation, performance benchmarks (commit `0b2b6a4`)
- **A1-A4** — LLM accuracy: code-gen fallback, plan-then-execute, enhanced tool descriptions, LLM-as-judge eval
- **B1-B4** — Spatial ops: hot-spot analysis, IDW interpolation, topology validation, service areas
- **C3** — Prometheus metrics endpoint

Full v1 history + frozen plans: [`docs/v1/`](../docs/v1/).

### Architecture (Current)

```
app.py                           — create_app() factory
state.py                         — shared mutable state

blueprints/                      (7 blueprints)
  auth.py         — /api/register, /api/me, /api/health
  annotations.py  — 8 annotation CRUD routes
  chat.py         — /api/chat (SSE), /api/usage, /api/metrics
  layers.py       — /api/layers, /api/import, pagination
  osm.py          — /, /upload, /fetch_osm_data, /api/geocode, /api/auto-classify
  dashboard.py    — /dashboard, /api/dashboard, session management
  websocket.py    — Socket.IO events

nl_gis/
  chat.py         — ChatSession: LLM tool dispatch loop + SSE streaming + plan mode
  tools.py        — 64 tool schemas for Claude API
  geo_utils.py    — ValidatedPoint, projections, geodesic ops
  handlers/       (5 modules)
    __init__.py   — dispatch_tool, shared helpers, STRtree indexing
    navigation.py — geocode, fetch_osm, map_command, search_nearby, reverse_geocode, batch_geocode
    analysis.py   — buffer, spatial_query, aggregate, overlays, geometry tools, stats, code_executor
    layers.py     — style, visibility, highlight, merge, import/export (CSV/KML/WKT/GeoParquet)
    annotations.py — add_annotation, classify_landcover, export, get
    routing.py    — find_route, isochrone, heatmap, closest_facility, optimize_route, service_area

services/                        (9 services)
  database.py, db_interface.py, postgres_db.py — SQLite + Postgres migration path
  valhalla_client.py — routing + isochrone + retry
  cache.py, rate_limiter.py, logging_config.py
  code_executor.py — sandboxed Python execution (execute_code tool)
  metrics.py      — Prometheus /metrics endpoint
```

### Known Limitations

| Limitation | Condition | Tracked In |
|------------|-----------|------------|
| UTM zone distortion | Geometry spans > 6° longitude | Known (0.2-31% area error) |
| No spatial indexing at DB level | > 10K features | `docs/v2/13-production-plan.md` |
| SQLite single-writer | High write concurrency | PostGIS path ready |
| No raster analysis | Elevation/terrain queries | `docs/v2/08-raster-analysis-plan.md` |
| Chat layers not persisted to DB | Server restart | Open |
| Accuracy baseline unmeasured | — | `docs/v2/01-accuracy-audit-plan.md` |

### Next: v2.1

All 13 v2.1 plans landed (rescoped surgically per the project's established pattern). See [`docs/v2/README.md`](../docs/v2/README.md) for the per-plan rescoping notes and shipped-vs-deferred details.

**v2.1 highlights (2026-04-17 → 2026-05-01)**

- **Plan 07** — Multi-provider tuning mechanism: `provider_hints` field (deep-copied + suffix-applied per provider), `get_system_prompt(provider_name)` with addenda for Anthropic / OpenAI / Gemini, `--provider {a|b|c|all}` + `--parity-threshold` flags in `tests/eval/run_eval.py`, `compare_providers()` + `check_parity()`.
- **Plan 09** — Real-time collaboration backend: `blueprints/collab.py` (create/info/resume/export REST), 5 new WebSocket events (join_collab, leave_collab, cursor_move, layer_remove, layer_style), `collab_sessions` SQLite table + persistence with transient-field scrubbing, throttled cursor broadcast, FIFO-capped layer history, 10-color presence palette. Frontend JS module deferred (no headless browser to validate).
- **Plan 11** — Visualization tools: `choropleth_map` (quantile / equal_interval / natural_breaks via jenkspy with quantile fallback / manual + sequential / diverging / qualitative ramps + custom hex array), `chart` (bar / pie / histogram / scatter, count / sum / mean reductions), `animate_layer` (auto-bins above 100 unique time values), `visualize_3d` (height attribute → building:levels × multiplier → default_height fallback chain). Also fixed a real matplotlib ≥3.10 contour API regression in `handle_interpolate`.
- **Plan 12** — OSM auto-label bridge: `classify_area`, `predict_labels`, `train_classifier` (annotation-based seed update), `export_training_data` (geojson / csv), `evaluate_classifier` (pure-numpy accuracy + per-class precision / recall / F1 + confusion matrix). Mock-friendly factory seam keeps tests dep-free; gensim / osmnx remain optional.
- **Plan 13** — Production hardening: full security header set (CSP / X-Frame-Options / Referrer-Policy / X-XSS-Protection / conditional HSTS), `/api/health/ready` (503 when DB or LLM key missing), uptime+version on `/api/health`, `services/model_router.py` (heuristic simple/complex classification), `services/llm_cache.py` (LRU+TTL + stable order-independent keys + bypass phrases), multi-stage Dockerfile with non-root user.

**Deferred from v2.1 (require infrastructure not available in this session)**

- Frontend JS for visualization (CollabManager, ChartManager, AnimationPlayer) — wire protocol fully specced; backend tests cover the data shape.
- Live multi-provider parity bake-off (Plan 07 M4) — requires both Anthropic + OpenAI keys + ~$10 API budget. Mechanism is in place; rerun whenever both keys are configured.
- Locust 50-user load test runs (Plan 13 M1, M6) — needs deployed staging instance.
- Fly.io / Railway deploy automation (Plan 13 M4.2) — needs platform credentials.
- gensim / osmnx integration test (Plan 12 M4.1.5) — handlers ship; integration test deferred until those deps are added to a CI image.
