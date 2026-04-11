# SpatialApp Roadmap

## Completed Work (2026-04-11)

### v1.0 — Bug Fixes & Hardening
- [x] 80 bugs fixed (2 critical, 15 high, 32 medium, 31 low)
- [x] 33 quality/security/performance improvements
- [x] 438 tests (from 236)

### v1.1 — Architectural Refactor
- [x] App factory pattern with create_app()
- [x] 5 Flask blueprints (auth, annotations, chat, layers, osm)
- [x] Shared state module (state.py)
- [x] Handler package (6 domain modules)
- [x] DB-first data flow
- [x] Stale import cleanup (zero backward-compat shims)

### v1.2 — Infrastructure
- [x] SQLite thread-local connection pooling
- [x] Structured JSON logging with request IDs
- [x] Gunicorn production config
- [x] STRtree spatial indexing
- [x] Responsive CSS (tablet + phone)

### v1.3 — Features
- [x] Multi-stop routing (Valhalla waypoints)
- [x] User dashboard (sessions, layers, stats)
- [x] WebSocket transport (Flask-SocketIO)
- [x] PostGIS migration path (database abstraction)

---

## Next: v2.0 — Spatial Operations Expansion

### Phase 1: Overlay & Geometry Tools (7 tools, ~2 days)
New tools that fill the most-requested gaps:

| Tool | Description | Implementation |
|------|-------------|---------------|
| `intersection` | Overlay intersection of two layers | Shapely `intersection()` |
| `difference` | Subtract one layer from another | Shapely `difference()` |
| `symmetric_difference` | Non-overlapping areas | Shapely `symmetric_difference()` |
| `convex_hull` | Boundary around point set | Shapely `convex_hull` |
| `centroid` | Extract center points | Shapely `centroid` |
| `simplify` | Reduce geometry complexity | Shapely `simplify(tolerance)` |
| `bounding_box` | Create rectangle geometry | Shapely `envelope` |

**Acceptance criteria**: Each tool has schema in tools.py, handler in handlers/analysis.py, 3+ tests, and the LLM can chain them with existing tools.

### Phase 2: Geocoding Enhancements (3 tools, ~1 day)

| Tool | Description | Implementation |
|------|-------------|---------------|
| `reverse_geocode` | Coordinates → address | Nominatim reverse |
| `batch_geocode` | List of addresses → point layer | Nominatim with rate limiting |
| `autocomplete` | Progressive search suggestions | Nominatim (or Photon) |

### Phase 3: Data Import Expansion (3 tools, ~1 day)

| Tool | Description | Implementation |
|------|-------------|---------------|
| `import_csv` | CSV with lat/lon columns → point layer | pandas + ValidatedPoint |
| `import_kml` | KML/KMZ → GeoJSON layer | fastkml or xml.etree |
| `import_wkt` | WKT string → geometry | Shapely `wkt.loads()` |

### Phase 4: Network Analysis (3 tools, ~2 days)

| Tool | Description | Implementation |
|------|-------------|---------------|
| `closest_facility` | Nearest N features of type X | Overpass + geodesic sort |
| `optimize_route` | Traveling salesman for waypoint ordering | Valhalla optimized_route |
| `od_matrix` | Origin-destination cost matrix | Valhalla sources_to_targets |

### Phase 5: Advanced Analysis (2-3 tools, ~2 days)

| Tool | Description | Implementation |
|------|-------------|---------------|
| `point_in_polygon` | Which polygon contains this point | STRtree + contains |
| `attribute_join` | Join CSV/JSON data to layer by key | pandas merge |
| `spatial_statistics` | Clustering analysis (DBSCAN, etc.) | scikit-learn |

---

## v3.0 — Scale & Production (Future)

### PostGIS Implementation
- [ ] Implement PostgresDatabase class (stub exists)
- [ ] Server-side spatial queries (ST_Intersects, ST_Within, etc.)
- [ ] Spatial indexing at DB level (GIST indexes)
- [ ] Connection pooling (psycopg2 pool)
- [ ] Data migration script (SQLite → PostgreSQL)

### Performance
- [ ] Streaming large GeoJSON (chunked SSE)
- [ ] Layer data virtualization (viewport-based rendering)
- [ ] Vector tiles for large layers (MVT format)
- [ ] Query result caching (spatial query memoization)

### Raster Support
- [ ] Elevation queries (DEM service integration)
- [ ] Slope/aspect calculation
- [ ] Viewshed analysis
- [ ] Zonal statistics (raster + vector overlay)

### Deployment
- [ ] Docker containerization
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Health monitoring (Prometheus metrics)
- [ ] Auto-scaling configuration

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-10 | Fix bugs before refactoring | Correct behavior first, then restructure |
| 2026-04-10 | DB-first over in-memory-first | Process restart = silent data loss was unacceptable |
| 2026-04-11 | Blueprints over microservices | Same-process communication is simpler for SQLite; blueprints provide separation without IPC |
| 2026-04-11 | State module over Flask g/extensions | Mutable containers (list, dict) need module-level identity, not per-request g |
| 2026-04-11 | WebSocket alongside SSE (not replacing) | SSE is simpler, works everywhere; WebSocket is enhancement for bidirectional |
| 2026-04-11 | PostGIS stub over full implementation | App works fine with SQLite at current scale; PostGIS path is ready when needed |
| 2026-04-11 | STRtree over R-tree library | Built into Shapely 2.0, no additional dependency |
| 2026-04-11 | Thread-local connections over pool library | SQLite doesn't benefit from connection pools; thread-local avoids churn |
