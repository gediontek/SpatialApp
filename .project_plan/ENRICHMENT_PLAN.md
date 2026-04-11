# SpatialApp Enrichment Plan — Milestones, Epics & Tasks

**Date**: 2026-04-11
**Baseline**: 47 tools, 828 tests, 43 commits
**Scope**: Remaining P2-P3 items + identified gaps

---

## Milestone 1: Spatial Analysis Depth (Weeks 1-2)

*Goal: Close remaining gaps in vector spatial analysis capabilities*

### Epic 1.1: Interpolation & Surface Analysis
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 1.1.1 | `interpolate_idw` tool — IDW interpolation from point values to contour polygons | M | scipy.interpolate.griddata | 5 |
| 1.1.2 | Configurable grid resolution (default 100x100, max 500x500) | S | 1.1.1 | 2 |
| 1.1.3 | Output as contour lines (iso-lines) or filled contours (polygons) | S | 1.1.1 | 3 |
| 1.1.4 | Support multiple interpolation methods (IDW, linear, cubic) via parameter | S | 1.1.1 | 2 |

**Acceptance**: User says "interpolate temperature from these weather stations" → produces color-graded contour map.

### Epic 1.2: Topology Validation & Repair
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 1.2.1 | `validate_topology` tool — check geometry validity per feature | S | Shapely is_valid, explain_validity | 4 |
| 1.2.2 | Report: valid/invalid count, error type breakdown, auto-fix option | S | 1.2.1 | 3 |
| 1.2.3 | `repair_topology` tool — auto-fix invalid geometries (buffer(0), make_valid) | S | 1.2.1 | 3 |
| 1.2.4 | Check for overlaps, gaps, and slivers between features | M | GeoPandas overlay analysis | 3 |

**Acceptance**: User says "check if these polygons are valid" → report with fix option.

### Epic 1.3: Service Area Analysis
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 1.3.1 | `service_area` tool — multi-facility reachability zones | M | Valhalla isochrone | 4 |
| 1.3.2 | Accept list of facility points (or layer + attribute filter) | S | 1.3.1 | 2 |
| 1.3.3 | Merge overlapping isochrones into unified coverage polygon | S | 1.3.1, shapely unary_union | 2 |
| 1.3.4 | Gap analysis: identify areas NOT covered by any facility | S | 1.3.3 | 2 |

**Acceptance**: User says "show 10-minute driving coverage from all fire stations" → unified coverage area with gaps highlighted.

**Milestone 1 Totals**: 3 epics, 12 tasks, ~34 new tests

---

## Milestone 2: Data Pipeline & Formats (Weeks 2-3)

*Goal: Support real-world data ingestion workflows*

### Epic 2.1: KML/KMZ Import
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 2.1.1 | `import_kml` tool — parse KML to GeoJSON | M | fastkml or xml.etree | 5 |
| 2.1.2 | Handle placemarks, paths, polygons, ground overlays | S | 2.1.1 | 4 |
| 2.1.3 | KMZ support (ZIP containing KML) | S | 2.1.1, zipfile | 2 |
| 2.1.4 | Preserve KML styles as feature properties | S | 2.1.1 | 2 |

### Epic 2.2: GeoParquet Support
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 2.2.1 | `import_geoparquet` tool — read GeoParquet files | S | geopandas.read_parquet | 3 |
| 2.2.2 | `export_geoparquet` tool — write layer as GeoParquet | S | geopandas.to_parquet | 3 |
| 2.2.3 | Streaming read for large files (>100MB) | M | pyarrow partitioned read | 2 |

### Epic 2.3: Data Quality Tools
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 2.3.1 | `describe_layer` tool — summary statistics (feature count, extent, CRS, attribute types, null counts) | S | — | 4 |
| 2.3.2 | `detect_duplicates` tool — find duplicate/near-duplicate features | M | STRtree + distance threshold | 4 |
| 2.3.3 | `clean_layer` tool — remove nulls, fix encoding, normalize attributes | M | pandas | 4 |

**Milestone 2 Totals**: 3 epics, 10 tasks, ~33 new tests

---

## Milestone 3: Infrastructure & Observability (Weeks 3-4)

*Goal: Production monitoring, performance, and operational readiness*

### Epic 3.1: Prometheus Metrics
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 3.1.1 | Install prometheus_flask_exporter | XS | pip install | — |
| 3.1.2 | Add `/metrics` endpoint with default Flask metrics | S | 3.1.1 | 2 |
| 3.1.3 | Custom metrics: tool_calls_total (counter by tool name), tool_duration_seconds (histogram), active_sessions (gauge), layer_count (gauge) | M | 3.1.2 | 4 |
| 3.1.4 | LLM metrics: api_calls_total, tokens_used_total, tool_chain_length (histogram) | S | 3.1.3 | 2 |

### Epic 3.2: Elevation/DEM Integration
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 3.2.1 | Research & select DEM service (OpenTopography vs self-hosted SRTM) | S | Research | — |
| 3.2.2 | `services/dem_client.py` — DEM tile fetching with caching | M | 3.2.1 | 4 |
| 3.2.3 | `elevation_at_point` tool — elevation for a lat/lon | S | 3.2.2 | 3 |
| 3.2.4 | `elevation_profile` tool — elevation along a route or line geometry | M | 3.2.2 | 4 |
| 3.2.5 | `slope_aspect` tool — compute slope/aspect for a bounding box | L | 3.2.2, numpy gradient | 4 |

### Epic 3.3: Vector Tile Generation
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 3.3.1 | Add geojson-vt or tippecanoe integration for MVT generation | M | — | 3 |
| 3.3.2 | Auto-generate vector tiles for layers >5000 features | S | 3.3.1 | 2 |
| 3.3.3 | Leaflet.VectorGrid integration for tile-based rendering | M | 3.3.2 | 2 |
| 3.3.4 | Cache generated tiles with invalidation on layer update | S | 3.3.1 | 2 |

**Milestone 3 Totals**: 3 epics, 13 tasks, ~32 new tests

---

## Milestone 4: Architecture Evolution (Weeks 5-8)

*Goal: Multi-agent architecture and model optimization*

### Epic 4.1: Multi-Agent Architecture (Planner + Workers)
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 4.1.1 | Design doc: Planner agent prompt, Worker agent prompts, orchestration protocol | M | A2 (plan mode exists) | — |
| 4.1.2 | `PlannerAgent` class — decomposes complex queries into sub-tasks with dependency graph | L | 4.1.1 | 6 |
| 4.1.3 | `WorkerAgent` class — executes individual sub-tasks (tool call or code gen) | M | 4.1.2 | 4 |
| 4.1.4 | `Orchestrator` — manages worker lifecycle, collects results, handles failures | L | 4.1.3 | 6 |
| 4.1.5 | Integration with ChatSession (multi-agent mode behind feature flag) | M | 4.1.4 | 4 |
| 4.1.6 | Parallel worker execution for independent sub-tasks | M | 4.1.4 | 3 |
| 4.1.7 | A/B accuracy comparison: single-agent vs multi-agent (using A4 eval framework) | M | 4.1.5, A4 | 2 |

**Acceptance**: Complex query "Find all restaurants within 500m of parks in Chicago, color hot spots red" → Planner creates 5-step plan → Workers execute in parallel where possible → Results assembled and streamed.

### Epic 4.2: Fine-Tuning Pipeline
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 4.2.1 | Data export: extract successful tool chains from query_metrics | M | Tool instrumentation (done) | 3 |
| 4.2.2 | Training data formatter: convert to Claude fine-tuning JSONL format | M | 4.2.1 | 3 |
| 4.2.3 | Fine-tuning job submission script (Anthropic API) | S | 4.2.2 | 2 |
| 4.2.4 | Model evaluation: run A4 benchmark on fine-tuned vs base model | M | 4.2.3, A4 | 2 |
| 4.2.5 | A/B routing: serve fine-tuned model to X% of traffic, compare accuracy | M | 4.2.4 | 3 |
| 4.2.6 | Automated re-training pipeline (quarterly with new data) | L | 4.2.5 | 2 |

**Milestone 4 Totals**: 2 epics, 13 tasks, ~39 new tests

---

## Milestone 5: Missing Capabilities Identified by Gap Analysis (Weeks 4-6)

*Goal: Operations identified as missing but not yet planned*

### Epic 5.1: Coordinate & Projection Tools
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 5.1.1 | `reproject_layer` tool — transform layer CRS (display remains WGS84, metadata updated) | S | pyproj | 3 |
| 5.1.2 | `detect_crs` tool — attempt to identify CRS from geometry ranges | S | heuristic | 3 |
| 5.1.3 | Auto-reproject on import for non-WGS84 data | S | 5.1.1 | 2 |

### Epic 5.2: Advanced Network Analysis
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 5.2.1 | `od_matrix` tool — origin-destination cost matrix via Valhalla sources_to_targets | M | Valhalla API | 4 |
| 5.2.2 | `accessibility_score` tool — weighted sum of reachable amenities from a point | M | 5.2.1 + closest_facility | 3 |

### Epic 5.3: Geometry Editing (User-Facing)
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 5.3.1 | `split_feature` tool — split a polygon by a line | M | Shapely split | 4 |
| 5.3.2 | `merge_features` tool — merge selected features within a layer (by IDs or attribute) | M | Shapely unary_union | 4 |
| 5.3.3 | `extract_vertices` tool — convert polygon/line boundaries to point layer | S | Shapely coords | 3 |

### Epic 5.4: Temporal & Attribute Analysis
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 5.4.1 | `temporal_filter` tool — filter features by date attribute (before/after/between) | S | datetime parsing | 4 |
| 5.4.2 | `attribute_statistics` tool — min/max/mean/median/std/histogram for numeric attribute | S | numpy | 4 |
| 5.4.3 | `classify_attribute` tool — equal interval / quantile / natural breaks classification | M | numpy/jenkspy | 4 |

**Milestone 5 Totals**: 4 epics, 11 tasks, ~38 new tests

---

## Milestone 6: Quality & Polish (Weeks 6-8)

*Goal: Hardening, documentation, and operational excellence*

### Epic 6.1: Cross-Tool Integration Tests
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 6.1.1 | Pipeline test: import_csv → buffer → spatial_query → export_layer | M | All tools | 3 |
| 6.1.2 | Pipeline test: fetch_osm → intersection → calculate_area → aggregate | M | All tools | 3 |
| 6.1.3 | Pipeline test: batch_geocode → hot_spot_analysis → style_layer | M | All tools | 3 |
| 6.1.4 | Concurrent access test: 3 sessions with overlapping layer names | M | threading | 2 |

### Epic 6.2: Documentation
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 6.2.1 | API reference: all endpoints with request/response examples | M | — | — |
| 6.2.2 | Tool catalog: all 50+ tools with usage examples | M | — | — |
| 6.2.3 | Deployment guide: Docker, Gunicorn, env vars, DEM setup | S | — | — |
| 6.2.4 | User guide: common NL queries and expected behavior | M | — | — |

### Epic 6.3: Performance Benchmarks
| Task | Description | Effort | Dependencies | Tests |
|------|-------------|--------|-------------|-------|
| 6.3.1 | Benchmark: spatial_query with 1K, 5K, 10K features (with/without STRtree) | S | — | 3 |
| 6.3.2 | Benchmark: concurrent chat sessions (5, 10, 20 simultaneous) | M | locust/wrk | — |
| 6.3.3 | Benchmark: LLM token usage per query complexity (simple/moderate/complex) | S | A4 framework | — |
| 6.3.4 | Memory profiling: layer store with 100 layers x 1000 features each | S | tracemalloc | — |

**Milestone 6 Totals**: 3 epics, 11 tasks, ~14 new tests

---

## Summary

| Milestone | Epics | Tasks | New Tests | Effort |
|-----------|-------|-------|-----------|--------|
| 1: Spatial Analysis Depth | 3 | 12 | 34 | M |
| 2: Data Pipeline & Formats | 3 | 10 | 33 | M |
| 3: Infrastructure & Observability | 3 | 13 | 32 | L |
| 4: Architecture Evolution | 2 | 13 | 39 | XL |
| 5: Missing Capabilities | 4 | 11 | 38 | L |
| 6: Quality & Polish | 3 | 11 | 14 | M |
| **Total** | **18** | **70** | **190** | — |

### Dependency DAG

```
Milestone 1 ─────────────────────────────────┐
  Epic 1.1 (interpolation) ── no deps        │
  Epic 1.2 (topology) ── no deps             │
  Epic 1.3 (service areas) ── Valhalla       │
                                              │
Milestone 2 ─────────────────────────────────┤── can run in parallel
  Epic 2.1 (KML) ── no deps                  │   with M1
  Epic 2.2 (GeoParquet) ── no deps            │
  Epic 2.3 (data quality) ── no deps          │
                                              │
Milestone 3 ─────────────────────────────────┤── can run in parallel
  Epic 3.1 (Prometheus) ── no deps            │   with M1, M2
  Epic 3.2 (DEM) ── research first            │
  Epic 3.3 (vector tiles) ── no deps          │
                                              │
Milestone 5 ─────────────────────────────────┘── can run in parallel
  Epic 5.1-5.4 ── no cross-deps                  with M1-M3

Milestone 4 ─────────────────────────── after M1-M3 proven
  Epic 4.1 (multi-agent) ── needs A2 (done), A4 (done)
  Epic 4.2 (fine-tuning) ── needs A4 (done), 4.1

Milestone 6 ─────────────────────────── after M1-M5 complete
  Epic 6.1-6.3 ── integration tests require all tools
```

### Execution Order (Recommended)

**Sprint 1 (Week 1-2)**: M1 (spatial depth) + M2 (data pipeline) — parallel
**Sprint 2 (Week 3-4)**: M3 (infrastructure) + M5 (missing capabilities) — parallel
**Sprint 3 (Week 5-6)**: M4 (architecture evolution) — sequential, high-risk
**Sprint 4 (Week 7-8)**: M6 (quality & polish) — requires everything else done

### Success Metrics

| Metric | Current | After M1-M3 | After All |
|--------|---------|-------------|-----------|
| Tools | 47 | ~58 | ~65+ |
| Tests | 828 | ~960 | ~1020+ |
| Accuracy (estimated) | ~85% | ~90% (A3 effect) | ~95% (multi-agent + fine-tune) |
| Data formats | GeoJSON, CSV, WKT | + KML, GeoParquet | + streaming |
| Monitoring | Structured logs | + Prometheus metrics | + benchmarks |
| Documentation | Plan docs | + API reference | + User guide |
