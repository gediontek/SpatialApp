# SpatialApp v2 — Improvement Prompts

> Run `/plan-project` on each prompt to generate a `*-plan.md` in `docs/v2/`.
> Every plan MUST use **Milestones → Epics → Tasks** hierarchy.
> Each task: description, acceptance criteria, effort (XS/S/M/L).
> Scope per prompt: ~200-400 lines of code, 1-2 focused days.

## Current State (verified 2026-04-11)

- **64 tools** (geocode, fetch_osm, buffer, spatial_query, aggregate, filter, style, route, isochrone, heatmap, closest_facility, interpolate, topology, service_area, hot_spot, execute_code, and 48 more)
- **438 tests** across 34 test files
- **5 handlers** (analysis.py, annotations.py, layers.py, navigation.py, routing.py)
- **7 blueprints** (chat, layers, osm, annotations, dashboard, auth, websocket)
- **10 services** (database, cache, valhalla_client, code_executor, metrics, rate_limiter, etc.)
- **Eval framework** exists (tests/eval/ with LLM-as-judge evaluator)
- **Multi-provider LLM** (Anthropic + OpenAI)
- **Flask + Leaflet.js + SQLite/PostGIS + Valhalla + Nominatim**
- v1.0-v1.3 complete (80 bugs fixed, 438 tests, blueprints, WebSocket, PostGIS path)
- v2.0 roadmap started (OSM expansion, enrichment plan with 6 milestones)

## Prior Work (already planned/implemented)

| Version | What | Status |
|---|---|---|
| v1.0 | 80 bug fixes + 33 improvements | DONE |
| v1.1 | Blueprint refactor + app factory | DONE |
| v1.2 | Connection pooling, logging, Gunicorn, spatial indexing | DONE |
| v1.3 | Multi-stop routing, dashboard, WebSocket, PostGIS path | DONE |
| v2.0 M1 | Interpolation, topology validation/repair, service areas | DONE |
| v2.0 M2 | KML import, GeoParquet, data quality tools | DONE |
| v2.0 M3 | Prometheus metrics, layer pagination | DONE |
| v2.0 M5 | 8 missing capability tools (CRS, network, geometry, temporal) | DONE |
| v2.0 M6 | Integration tests, documentation, performance benchmarks | DONE |
| **v2.1** | **NL-GIS intelligence + feature depth — this plan** | **PLANNED** |

---

## NL-to-GIS Improvement Track (Prompts 1-7)

### Prompt 1: NL-GIS Accuracy Audit — Measure Before Improving

Depends on: nothing (run first)
Acceptance criteria: Baseline accuracy score across 50+ queries. Per-tool accuracy breakdown. Top 10 failure modes identified.

```
/plan-project Audit the NL-to-GIS pipeline accuracy for SpatialApp. Current: 64 tools, eval framework exists (tests/eval/), LLM-as-judge evaluator, tool descriptions enhanced (commit 34f2013). But we don't have a reliable baseline. Milestones: (M1) Run the eval framework on 50+ reference queries — basic (15), intermediate (15), advanced (10), stress (10). Record: tool selection accuracy %, parameter accuracy %, chain accuracy % (multi-tool queries). (M2) For each failed query: classify the failure — wrong tool chosen, right tool but wrong parameters, missing tool chain, ambiguous query misinterpreted, tool description misleading. (M3) Rank the top 10 failure patterns by frequency. These become the improvement targets for Prompts 2-7. Output: baseline scorecard, failure taxonomy, and prioritized fix list. Target: establish the number we're improving FROM, so we can measure whether changes help.
```

### Prompt 2: Tool Description Engineering — The 90% Accuracy Target

Depends on: Prompt 1 (failure taxonomy tells us which descriptions fail)
Read first: docs/v2/01-accuracy-audit-plan.md
Acceptance criteria: Eval score improves from baseline to ≥85% on same 50 queries. Zero "wrong tool" failures on basic queries.

```
/plan-project Improve tool descriptions to achieve ≥85% NL-to-GIS accuracy. Current: 64 tools in nl_gis/tools.py with descriptions enhanced in commit 34f2013. But the eval framework reveals failures. Using the failure taxonomy from Prompt 1, fix tool descriptions. Milestones: (M1) For each "wrong tool chosen" failure: analyze which tool WAS chosen vs which SHOULD have been. Identify the description ambiguity that confused the LLM. Rewrite both descriptions to create clear differentiation. Example: "buffer" vs "search_nearby" — when does the user want a geometry buffer vs a proximity search? (M2) For each "wrong parameters" failure: add explicit parameter examples to the description. Not "bbox as south,west,north,east" but "bbox: '41.8,-87.7,41.9,-87.6' (Chicago downtown)". (M3) For "missing chain" failures: add tool chaining hints. "After fetch_osm, typically call map_command(action='fit_bounds') to show results." (M4) Update system prompt in chat.py with improved chaining patterns. (M5) Re-run eval — measure improvement. If <85%, iterate on the worst 5 failures. Target: 85% accuracy, zero "wrong tool" on basic queries.
```

### Prompt 3: Complex Query Decomposition — Multi-Step Spatial Reasoning

Depends on: Prompt 2 (basic accuracy must be solid before handling complex queries)
Read first: docs/v2/02-tool-descriptions-plan.md
Acceptance criteria: 3-step+ queries succeed ≥70% of the time. Plan-then-execute mode handles 5 benchmark complex queries.

```
/plan-project Improve complex multi-step query handling for the NL-GIS pipeline. Current: plan-then-execute mode exists (commit 0f24011) but complex queries still fail. "Find all hospitals within 5km of schools in areas with population density above 1000/km²" requires: fetch_osm(hospitals) → fetch_osm(schools) → buffer(schools, 5km) → spatial_query(hospitals IN buffer) → join with population data → filter. The LLM often gets the chain wrong or stops after 2 steps. Milestones: (M1) Catalog the 10 most common multi-step spatial query patterns (proximity analysis, overlay analysis, site selection, accessibility analysis, demographic analysis, etc.). For each: define the canonical tool chain. (M2) Add pattern recognition to chat.py — detect which pattern a query matches, inject the canonical chain as a hint. Not hardcoded execution — give the LLM the pattern as guidance. (M3) Improve plan-then-execute mode: the LLM should generate the full chain FIRST (as a plan), show it to the user, then execute. Currently it plans loosely. Make plans explicit: "Step 1: fetch_osm(hospitals, Chicago) → Step 2: buffer(schools_layer, 5000m) → Step 3: spatial_query(hospitals IN buffer)". (M4) Add chain validation: after the LLM generates a plan, validate that each step's output type matches the next step's input type. (M5) Benchmark: 10 complex queries, measure chain accuracy before and after.
```

### Prompt 4: Spatial Context Awareness — The Map Knows Things

Depends on: Prompt 1 (need to know which failures are context-related)
Read first: docs/v2/01-accuracy-audit-plan.md
Acceptance criteria: "Show me more like this" works. Layer-aware queries succeed. Map viewport queries work.

```
/plan-project Add spatial context awareness to the NL-GIS pipeline. Current: chat.py builds a dynamic system prompt with map state and recent context. But the LLM doesn't deeply understand what's on the map. "Show me more like this" fails because the LLM doesn't know what "this" refers to. "Filter the buildings I just loaded" fails if the layer name changed. Milestones: (M1) Enhanced map state injection — when building the system prompt, include: all layer names + their feature counts + their bounding boxes + their attribute schemas. Not just "layers: ['chicago_buildings']" but "chicago_buildings: 247 features, bbox [41.8,-87.7,41.9,-87.6], attributes: {name, height, building_type}". (M2) Conversational reference resolution — track what "this", "those", "the results", "that area" refer to. Maintain a reference stack: last layer added, last area queried, last features highlighted. Inject into system prompt. (M3) Viewport awareness — when user says "what's in this area" or "show me nearby", use the current map viewport as the implicit bounding box. Requires frontend → backend communication of viewport bounds. (M4) Attribute-aware queries — "color buildings by height" requires knowing the layer has a "height" attribute. The describe_layer tool exists but the LLM doesn't call it proactively. Add a prompt pattern: before styling/filtering, check layer attributes first. (M5) Test: 10 context-dependent queries, measure success rate.
```

### Prompt 5: Error Recovery and Graceful Degradation

Depends on: Prompt 2 (basic accuracy needed before error recovery matters)
Read first: docs/v2/02-tool-descriptions-plan.md
Acceptance criteria: Zero unhandled errors visible to user. Every failure shows helpful message. Retry succeeds for transient failures.

```
/plan-project Build robust error recovery for the NL-GIS pipeline. Current: errors surface as raw tracebacks or silent failures. Nominatim returns 429, user sees "geocoding failed." Valhalla is down, routing fails silently. Overpass returns 50K features, browser freezes. Milestones: (M1) Catalog every error path in the 5 handler modules. For each: what causes it, what the user sees now, what they SHOULD see. Map: handler → error → user message. (M2) Implement graceful degradation: Nominatim 429 → retry with exponential backoff (3 attempts, 1s/2s/4s), then show "Geocoding service is busy, try again in 30 seconds." Valhalla down → show "Routing service unavailable. Showing straight-line distance instead." Overpass returns >10K features → auto-simplify or paginate with warning. (M3) Add result size guards: if fetch_osm returns >5K features, warn user and offer to zoom in. If spatial_query produces >10K results, auto-paginate. If buffer creates a geometry >100MB, refuse with explanation. (M4) Add retry logic for transient failures (network timeouts, rate limits) with circuit breaker pattern. (M5) Test: trigger each error condition, verify user sees helpful message not traceback.
```

### Prompt 6: Evaluation Framework Expansion — Continuous Quality

Depends on: Prompts 1-5 (eval framework validates all improvements)
Read first: All prior plan files
Acceptance criteria: 100-question eval suite. Automated CI runs. Accuracy regression = build failure.

```
/plan-project Expand the evaluation framework from proof-of-concept to production quality gate. Current: tests/eval/ has evaluator.py, mock_responses.py, reference_queries.py, run_eval.py. But it's a POC — small query set, manual runs, no CI integration. Milestones: (M1) Expand reference queries to 100 questions: 25 basic (single tool, clear intent), 25 intermediate (2-3 tool chains), 25 advanced (complex spatial reasoning, ambiguous queries), 25 stress (edge cases, non-English, huge areas, impossible requests). Each query: expected tool chain, expected parameters, acceptable alternatives, what counts as failure. (M2) Add parameter accuracy scoring — not just "did it pick the right tool?" but "did it pass the right coordinates? Right CRS? Right feature type?" Partial credit for close-but-wrong. (M3) Add CI integration — eval runs on every PR that touches nl_gis/ or tools.py. Accuracy below threshold = build failure. Threshold starts at current baseline (from Prompt 1), ratchets up as improvements land. (M4) Add regression detection — if a PR drops accuracy on ANY query category (basic/intermediate/advanced/stress) by >5%, flag it. (M5) Add eval report generation — after each run, produce a markdown report: overall accuracy, per-category breakdown, top 5 regressions, top 5 improvements. Save to tests/eval/reports/.
```

### Prompt 7: LLM Provider Optimization — Model-Specific Tuning

Depends on: Prompt 6 (need eval framework to measure differences)
Read first: docs/v2/06-eval-framework-plan.md
Acceptance criteria: Both Anthropic and OpenAI providers score within 5% of each other. Provider-specific prompt tuning documented.

```
/plan-project Optimize NL-GIS accuracy per LLM provider. Current: llm_provider.py supports Anthropic (Claude) and OpenAI. Same tool descriptions and system prompt for both. But they interpret tool schemas differently — Claude follows "description" more literally, GPT-4 follows "enum" constraints more strictly. Milestones: (M1) Run eval suite on both providers, compare accuracy per query category. Identify where they diverge — which queries does Claude handle better? Which does GPT handle better? Why? (M2) Provider-specific tool description tuning: for parameters where providers disagree, add provider-specific hints. Not forked descriptions — add a "provider_hints" field that appends to the base description per provider. (M3) Provider-specific system prompt sections: if Claude needs more explicit chaining hints but GPT needs more parameter examples, add provider-conditional sections to the system prompt. (M4) Test: both providers score within 5% of each other on the full 100-query eval. (M5) Document findings: which spatial operations each provider handles best, which need the most hand-holding, and the optimal model (opus vs sonnet, gpt-4 vs gpt-4o-mini) per query complexity tier.
```

---

## Main Feature Tracks (Prompts 8-13)

### Prompt 8: Raster Analysis — The Missing Dimension

Depends on: nothing (independent track)
Acceptance criteria: 5 raster tools working. Elevation queries from natural language. DEM-based analysis.

```
/plan-project Add raster analysis capabilities to SpatialApp. Current: the app handles vector data (points, lines, polygons) but has no raster support despite having sample_rasters/ with 5 test files (chicago_sp27.tif, chicago_utm.tif, geog_wgs84.tif, sentinel_rgb.tif, usgs_ortho.tif). rasterio is in requirements.txt but unused by nl_gis. Milestones: (M1) Add 5 raster tools: raster_info (metadata, CRS, resolution, bounds), raster_value (point query — "what's the elevation at X,Y?"), raster_statistics (min/max/mean/std over a polygon), raster_profile (elevation along a line), raster_classify (reclassify values into categories). (M2) Integrate with existing tools: "find the elevation of each hospital" = spatial_query + raster_value. "Which parks are above 500m elevation?" = fetch_osm(parks) + raster_statistics per feature + filter. (M3) Add visualization: render raster as tile overlay on Leaflet. Support single-band (elevation → color ramp) and RGB (satellite imagery). (M4) DEM analysis: slope, aspect, hillshade from elevation rasters. These are derived products, not raw tools — compute on demand, cache results. (M5) NL integration: "Show me the terrain around Chicago", "What's the elevation at the Eiffel Tower?", "Find all flat areas near the airport." 10 raster-specific eval queries.
```

### Prompt 9: Real-Time Collaboration — Multi-User Map Sessions

Depends on: nothing (independent track, WebSocket already exists)
Acceptance criteria: 2 users see same map state. Layer changes propagate in <1s. Session persistence works.

```
/plan-project Add real-time collaboration to SpatialApp. Current: WebSocket transport exists (Flask-SocketIO, commit bdfcab8) but only for single-user SSE chat. No multi-user awareness. Milestones: (M1) Shared map sessions — generate a session URL. Multiple users join the same session. Map state (viewport, layers, annotations) is synchronized via WebSocket. One user adds a layer → all users see it. (M2) User presence — show who's in the session (colored cursors on map, user list in sidebar). Each user has a color. Their map actions are attributed. (M3) Collaborative annotations — users can add annotations simultaneously. Conflict resolution: last-write-wins for geometry, merge for attributes. (M4) Chat history is shared — all users see the NL-GIS conversation. User A asks "show parks in Chicago", User B sees the parks appear and the chat message. (M5) Session persistence — save session state to database. Resume sessions. Export session as reproducible workflow (sequence of NL commands that recreates the map state). (M6) Test: 2 concurrent users, 10 synchronized operations, latency <1s.
```

### Prompt 10: Data Pipeline — Import, Transform, Export

Depends on: nothing (independent track)
Acceptance criteria: Import from 5 formats. Transform pipeline (chain operations). Export to 5 formats.

```
/plan-project Strengthen the data pipeline for SpatialApp. Current: import_csv, import_wkt, import_kml, import_geoparquet, import_layer (GeoJSON/Shapefile) exist. export_layer, export_geoparquet, export_annotations exist. But no transform pipeline — you can import and export but can't chain: import → clean → transform → analyze → export in one NL command. Milestones: (M1) Add transform tools: reproject (change CRS), clip_to_bbox, sample (random/systematic point sampling), dissolve (merge features by attribute), generalize (simplify geometries by tolerance). (M2) Pipeline mode — "Import the CSV, reproject to UTM, clip to Chicago, calculate area per polygon, export as GeoPackage." This is a 5-step pipeline. The LLM should plan the full chain and execute sequentially. (M3) Batch operations — "For each neighborhood polygon, count the number of restaurants inside." This is a spatial join + aggregate applied to every feature. Add a batch_spatial_query tool. (M4) Data validation on import — check for invalid geometries, missing CRS, duplicate features, null attributes. Auto-repair where possible (repair_topology already exists). (M5) Format detection — user uploads a file, system auto-detects format (GeoJSON, Shapefile, CSV with lat/lon, KML, GeoParquet) without user specifying. (M6) Test: 5 end-to-end pipelines (import → transform → analyze → export), each with different input formats.
```

### Prompt 11: Advanced Visualization — Beyond Markers and Polygons

Depends on: nothing (independent track)
Acceptance criteria: Choropleth maps from NL. Time-series animation. 3D building visualization. Custom legends.

```
/plan-project Add advanced visualization capabilities to SpatialApp. Current: style_layer changes colors/opacity, heatmap creates heat layers, but no choropleth, no time animation, no 3D, no custom legends. Milestones: (M1) Choropleth maps — "Color neighborhoods by population density" = classify attribute into buckets → assign color ramp → render. Add choropleth_map tool with: layer, attribute, classification method (quantile/equal_interval/natural_breaks/manual), color ramp (sequential/diverging/qualitative), num_classes. (M2) Time-series animation — for layers with temporal attributes, add animate_layer tool: play through time steps, show features appearing/disappearing. "Show how construction permits spread across the city from 2020 to 2024." (M3) 3D building visualization — using Leaflet 3D plugins or deck.gl overlay. "Show buildings in downtown with height extrusion." Requires building height attributes from OSM. (M4) Custom legends — auto-generated legends for styled/classified layers. Show in sidebar. (M5) Chart integration — "Show a bar chart of building types in this area" = aggregate by type → render as Chart.js overlay. Add chart tool: layer, attribute, chart_type (bar/pie/histogram/scatter). (M6) NL integration: "Make a choropleth of income by zip code", "Animate the spread of COVID cases by month", "Show a pie chart of land use types." 10 visualization-specific eval queries.
```

### Prompt 12: OSM Auto-Label Integration — Bring the Sibling In

Depends on: nothing (independent track)
Acceptance criteria: OSM_auto_label accessible from NL chat. Classification results display on map. Training data export works.

```
/plan-project Integrate the OSM_auto_label sub-project into SpatialApp's NL-GIS pipeline. Current: OSM_auto_label is a sibling directory with its own classifier.py, downloader.py, visualizer.py — it classifies OSM features using ML. But it's isolated — not accessible from the main SpatialApp NL interface. Milestones: (M1) Expose OSM_auto_label as tools in nl_gis: classify_area (classify all OSM features in a bbox using the ML model), train_classifier (fine-tune on user annotations), predict_labels (run inference on a layer). (M2) Wire classification results into the map: classified features get a "predicted_label" attribute, color-coded by class. User can correct labels via annotations → feedback loop for training. (M3) NL integration: "Classify all buildings in Addis Ababa", "What type of land use is this area?", "Show me misclassified features." (M4) Training data pipeline: export annotations as training data (GeoJSON with labels), import pre-trained models, evaluate model accuracy on held-out set. (M5) Test: classify a 1km² area, verify >80% accuracy against ground truth annotations.
```

### Prompt 13: Production Hardening — Scale, Security, Deploy

Depends on: Prompts 1-5 (core quality must be solid first)
Read first: All prior plan files
Acceptance criteria: Handles 50 concurrent users. All OWASP top-10 addressed. One-command deploy works.

```
/plan-project Harden SpatialApp for production deployment. Current: Prometheus metrics exist (M3), Docker + CI/CD exist, rate limiter exists, PostGIS migration path exists. But not battle-tested at scale. Milestones: (M1) Load testing — simulate 50 concurrent users sending NL queries. Measure: response time (p50, p95, p99), LLM API cost per session, memory usage, DB connection pool exhaustion. Identify the bottleneck. (M2) Security audit — OWASP top-10 check. Overpass QL injection via location parameter? SQL injection via attribute_join? XSS via layer names displayed in HTML? CSRF on API endpoints? Auth bypass on dashboard? Fix every finding. (M3) Cost optimization — LLM calls are the main cost. Add: response caching (same query within 5 min → cached result), model tiering (simple queries → Haiku/mini, complex → Opus/GPT-4), token budgeting (warn user when session exceeds $X). (M4) Deployment automation — one-command deploy to Railway/Fly.io/Render. Docker image optimized (multi-stage build, <500MB). Health check endpoint. Auto-restart on crash. (M5) Monitoring dashboard — Grafana or built-in: LLM accuracy over time, error rates, latency percentiles, active sessions, cost per session. (M6) Test: deploy to staging, run 50-user load test, verify all metrics within budget.
```

---

## Performance Budgets

| Metric | Current | v2.1 Target | Hard Limit |
|---|---|---|---|
| Tool selection accuracy (basic) | TBD (Prompt 1) | ≥95% | — |
| Tool selection accuracy (advanced) | TBD (Prompt 1) | ≥75% | — |
| Chain accuracy (multi-step) | TBD (Prompt 1) | ≥70% | — |
| NL query → first result | ~3-5s | <3s | 5s |
| Eval suite run time | TBD | <5 min | 10 min |
| Test count | 438 | ≥500 | never decrease |
| Concurrent users | ~5 | 50 | — |

---

## Dependency Graph

```
Prompt 1 (accuracy audit) ──────────────────────────────────────────────┐
                                                                        │
Prompt 2 (tool descriptions) ← depends on 1 ─────────────────────────┐ │
                                                                      │ │
Prompt 3 (complex queries) ← depends on 2 ──────────────────────────┐│ │
                                                                     ││ │
Prompt 4 (context awareness) ← depends on 1 ───────────────────────┐││ │
                                                                    │││ │
Prompt 5 (error recovery) ← depends on 2 ─────────────────────────┐│││ │
                                                                   ││││ │
Prompt 6 (eval expansion) ← depends on 1-5 ──────────────────────┐││││ │
                                                                  │││││ │
Prompt 7 (provider tuning) ← depends on 6 ──────────────────────┐│││││ │
                                                                 ││││││ │
Prompt 8  (raster) ← independent                                ││││││ │
Prompt 9  (collaboration) ← independent                         ││││││ │
Prompt 10 (data pipeline) ← independent                         ││││││ │
Prompt 11 (visualization) ← independent                         ││││││ │
Prompt 12 (OSM auto-label) ← independent                        ││││││ │
Prompt 13 (production) ← depends on 1-5 ────────────────────────┘│││││ │
                                                                  │││││ │
/gap-analysis (consistency) ← depends on all ─────────────────────┘││││ │
                                                                   ││││ │
/build-me (implement) ← depends on all plans ──────────────────────┘│││ │
                                                                    │││ │
```

## Execution Order

**Phase 1: Measure** (do first, everything else depends on this)
```
/plan-project [Prompt 1]  → docs/v2/01-accuracy-audit-plan.md
```

**Phase 2: NL-GIS Core** (sequential — each builds on prior)
```
/plan-project [Prompt 2]  → docs/v2/02-tool-descriptions-plan.md
/plan-project [Prompt 3]  → docs/v2/03-complex-queries-plan.md
/plan-project [Prompt 4]  → docs/v2/04-context-awareness-plan.md
/plan-project [Prompt 5]  → docs/v2/05-error-recovery-plan.md
```

**Phase 3: Quality Gate**
```
/plan-project [Prompt 6]  → docs/v2/06-eval-framework-plan.md
/plan-project [Prompt 7]  → docs/v2/07-provider-tuning-plan.md
```

**Phase 4: Feature Tracks** (can run in parallel — independent)
```
/plan-project [Prompt 8]  → docs/v2/08-raster-analysis-plan.md
/plan-project [Prompt 9]  → docs/v2/09-collaboration-plan.md
/plan-project [Prompt 10] → docs/v2/10-data-pipeline-plan.md
/plan-project [Prompt 11] → docs/v2/11-visualization-plan.md
/plan-project [Prompt 12] → docs/v2/12-osm-autolabel-plan.md
```

**Phase 5: Harden**
```
/plan-project [Prompt 13] → docs/v2/13-production-plan.md
```

**Phase 6: Validate**
```
/gap-analysis Review all 13 plan files in docs/v2/ for consistency, overlap, contradictions, and missing dependencies. Flag plans without measurable acceptance criteria.
```

**Phase 7: Build**
```
/build-me Implement SpatialApp v2.1 following the plans in docs/v2/. Start with the NL-GIS track (Prompts 1-7) — this is the core intelligence. Then feature tracks. Then production hardening. Run eval suite after every milestone. Do not stop until all phases are complete and accuracy targets are met.
```
