# SpatialApp Roadmap

## Completed Work (2026-04-11)

### v1.0 — Bug Fixes & Hardening
- [x] 80 bugs fixed (2 critical, 15 high, 32 medium, 31 low)
- [x] 33 quality/security/performance improvements
- [x] 438 tests (from 236)

### v1.1 — Architectural Refactor
- [x] App factory pattern, 5 blueprints, state module, handler package
- [x] DB-first data flow, stale import cleanup

### v1.2 — Infrastructure
- [x] Connection pooling, structured logging, Gunicorn, STRtree, responsive CSS

### v1.3 — Features
- [x] Multi-stop routing, user dashboard, WebSocket, PostGIS migration path

---

## v2.0 — Spatial Operations Expansion

### Phase 0: Blocking Gap Fixes (from gap analysis — do FIRST)

These are blocking items from the gap analysis that affect correctness and usability of existing tools.

#### 0a. Expand OSM Feature Types (BLOCKING)
**Problem**: Only 12 hardcoded feature types. Users asking for "restaurant", "school", "hospital" get "invalid feature type".

**Solution**: Replace the fixed enum with flexible key=value Overpass queries.

| Change | File | Description |
|--------|------|-------------|
| Expand `OSM_FEATURE_MAPPINGS` | `handlers/__init__.py` | Add 20+ types: restaurant, school, hospital, pharmacy, supermarket, hotel, rail, bus_stop, parking, church, cemetery, playground, stadium, university, library, police, fire_station, post_office, bank, cinema |
| Allow custom key=value | `handlers/navigation.py` | If `feature_type` not in mapping, accept `osm_key` + `osm_value` params for arbitrary Overpass queries |
| Update tool schema | `tools.py` | Add `osm_key`/`osm_value` optional params to `fetch_osm` and `search_nearby` |
| Update system prompt | `chat.py` | Add expanded feature type list |
| Tests | `tests/` | Test new feature types + custom key=value queries |

#### 0b. Add Overlay Operations (BLOCKING)
**Problem**: No intersection/difference — can't answer "where do parks and flood zones overlap?"

| Tool | Handler | Implementation |
|------|---------|---------------|
| `intersection` | `handlers/analysis.py` | `unary_union(A).intersection(unary_union(B))` → GeoJSON layer |
| `difference` | `handlers/analysis.py` | `unary_union(A).difference(unary_union(B))` → GeoJSON layer |
| `symmetric_difference` | `handlers/analysis.py` | `unary_union(A).symmetric_difference(unary_union(B))` → GeoJSON layer |

Each needs: schema in tools.py, handler, add to `dispatch_tool`, add to `LAYER_PRODUCING_TOOLS`, 3+ tests.

#### 0c. Fix Schema & Prompt Issues (SIGNIFICANT)

| Fix | File | Description |
|-----|------|-------------|
| Clarify spatial_query predicates | `tools.py` | "contains: source features that fully contain the target geometry" vs "within: source features fully inside the target" |
| Fix aggregate schema | `tools.py` | Separate `operation` (count/sum/area/min/max/avg) from `group_by` (attribute name) |
| Update system prompt tool count | `chat.py` | Change "24 tools" to actual count |
| Add system prompt chain patterns | `chat.py` | Add patterns for intersection/difference, expanded feature types |

#### 0d. Add Tool Selection Instrumentation (SIGNIFICANT)

| Change | File | Description |
|--------|------|-------------|
| Log tool call accuracy signals | `chat.py` | Track: tool name, params, success/failure, retry count, chain depth |
| Add metrics endpoint | `blueprints/dashboard.py` | Tool usage breakdown: most used, failure rates, avg chain length |
| Store in query_metrics | `services/database.py` | Extend `log_query_metrics` with tool-level detail |

---

### Phase 1: Geometry Tools (7 tools)

| Tool | Description | Implementation | Effort |
|------|-------------|---------------|--------|
| `convex_hull` | Boundary polygon around points/features | Shapely `convex_hull` | S |
| `centroid` | Extract center points as new layer | Shapely `centroid` | S |
| `simplify` | Reduce geometry complexity | Shapely `simplify(tolerance)` | S |
| `bounding_box` | Create rectangle from layer extent | Shapely `envelope` | XS |
| `dissolve` | Merge features by attribute value | GeoPandas `dissolve(by=attr)` | S |
| `clip` | Clip one layer by another's boundary | Shapely/GeoPandas `clip` | S |
| `reproject` | Transform layer to different CRS | pyproj Transformer | S |

### Phase 2: Geocoding & Address (3 tools)

| Tool | Description | Implementation | Effort |
|------|-------------|---------------|--------|
| `reverse_geocode` | Coordinates → address/place name | Nominatim `/reverse` | S |
| `batch_geocode` | List of addresses → point layer | Nominatim with rate limiter, returns GeoJSON | M |
| `autocomplete` | Progressive search suggestions | Photon API or Nominatim | S |

### Phase 3: Data Import/Export (4 tools)

| Tool | Description | Implementation | Effort |
|------|-------------|---------------|--------|
| `import_csv` | CSV with lat/lon columns → point layer | pandas + ValidatedPoint | M |
| `import_kml` | KML/KMZ → GeoJSON layer | fastkml or xml.etree | M |
| `import_wkt` | WKT string → geometry | Shapely `wkt.loads()` | S |
| `export_layer` | Export any layer as GeoJSON/Shapefile/GeoPackage | GeoPandas `to_file()` | S |

### Phase 4: Network Analysis (3 tools)

| Tool | Description | Implementation | Effort |
|------|-------------|---------------|--------|
| `closest_facility` | Find nearest N features of type X from a point | Overpass `around` + geodesic sort | M |
| `optimize_route` | Traveling salesman for waypoint ordering | Valhalla `optimized_route` | M |
| `service_area` | Multi-facility reachability | Multiple isochrones + union | M |

### Phase 5: Advanced Analysis (3 tools)

| Tool | Description | Implementation | Effort |
|------|-------------|---------------|--------|
| `point_in_polygon` | Which polygon contains this point/these points | STRtree + contains | S |
| `attribute_join` | Join tabular data to spatial layer by key | pandas merge | M |
| `spatial_statistics` | Clustering analysis (nearest neighbor, DBSCAN) | scipy/scikit-learn | L |

### Phase 6: LLM Accuracy Improvements

| Change | Description | Effort |
|--------|-------------|--------|
| Few-shot examples in system prompt | 2-3 full multi-turn conversations with real tool results | M |
| Tool selection validation | Pre-dispatch check: does the tool match the user's verb (show→fetch, color→style, how many→aggregate)? | M |
| Progressive layer context | Only include layers referenced in last 3 turns, not all 10 | S |
| Chain optimization | If LLM generates suboptimal chain, suggest correction before executing | L |

---

## v3.0 — Scale & Production (Future)

### PostGIS Implementation
- [ ] Implement PostgresDatabase class (stub exists)
- [ ] Server-side spatial queries (ST_Intersects, ST_Within, etc.)
- [ ] Spatial indexing at DB level (GIST indexes)
- [ ] Connection pooling (psycopg2 pool)
- [ ] Data migration script (SQLite → PostgreSQL)

### Performance
- [ ] Streaming large GeoJSON (chunked SSE or WebSocket frames)
- [ ] Layer data virtualization (viewport-based rendering)
- [ ] Vector tiles for large layers (MVT format via tippecanoe)
- [ ] Query result caching (spatial query memoization with geometry hash)

### Raster Support
- [ ] Elevation queries (Mapzen Terrain Tiles / SRTM)
- [ ] Slope/aspect calculation
- [ ] Viewshed analysis
- [ ] Zonal statistics (raster + vector overlay)

### Deployment
- [ ] Docker containerization (Dockerfile + docker-compose.yml)
- [ ] CI/CD pipeline (GitHub Actions: lint → test → build → deploy)
- [ ] Health monitoring (Prometheus metrics export)
- [ ] Auto-scaling configuration

---

## Implementation Order (Priority)

```
Phase 0a (feature types)  ─┐
Phase 0b (overlays)       ─┤── BLOCKING: do first, in parallel
Phase 0c (schema fixes)   ─┤
Phase 0d (instrumentation)─┘
         │
Phase 1 (geometry tools) ──── then this (foundational tools)
         │
Phase 2 + Phase 3 ─────────── parallel (geocoding + import are independent)
         │
Phase 4 (network analysis) ── depends on Phase 2 (geocoding)
         │
Phase 5 (advanced) ────────── depends on Phases 1-3
         │
Phase 6 (LLM accuracy) ────── continuous, informed by Phase 0d instrumentation
```

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
