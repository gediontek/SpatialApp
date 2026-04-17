# SpatialApp Capability Map

**As of:** 2026-04-17 · 64 tools · 5 handlers · 7 blueprints
**Navigation:** [Status](STATUS.md) · [Shipped → `docs/v1/`](../docs/v1/) · [Active → `docs/v2/`](../docs/v2/)

---

## NL-to-GIS Pipeline

```
User message (natural language)
  │
  ▼
blueprints/chat.py: api_chat() — HTTP POST with SSE response
  │
  ▼
nl_gis/chat.py: ChatSession.process_message()
  │ 1. Build dynamic system prompt (static rules + map state + recent context)
  │ 2. Append user message to conversation history
  │ 3. Optional: plan_mode → return structured plan for user approval
  │
  ▼
Claude API call (system + 64 tool schemas + message history)
  │
  ├─ stop_reason="end_turn" → yield SSE message event → done
  │
  └─ stop_reason="tool_use" → for each tool_use block:
       │ 1. yield SSE tool_start event
       │ 2. dispatch_tool(name, params, layer_store)
       │ 3. yield SSE tool_result event
       │ 4. yield type-specific event (layer_add, map_command, etc.)
       │ 5. append tool_result to messages
       │ 6. loop → next Claude API call
```

## Tool Inventory (64 tools)

### Data Acquisition (5)
`geocode`, `reverse_geocode`, `batch_geocode`, `fetch_osm`, `search_nearby`

### Spatial Analysis — Core (5)
`buffer`, `spatial_query`, `aggregate`, `calculate_area`, `measure_distance`

### Spatial Analysis — Overlay (3)
`intersection`, `difference`, `symmetric_difference`

### Spatial Analysis — Geometry (10)
`convex_hull`, `centroid`, `simplify`, `bounding_box`, `dissolve`, `clip`, `voronoi`, `split_feature`, `merge_features`, `extract_vertices`

### Spatial Analysis — Advanced (6)
`point_in_polygon`, `attribute_join`, `spatial_statistics`, `hot_spot_analysis`, `interpolate`, `attribute_statistics`

### Spatial Analysis — Topology (2)
`validate_topology`, `repair_topology`

### Spatial Analysis — CRS (2)
`reproject_layer`, `detect_crs`

### Spatial Analysis — Code Fallback (1)
`execute_code` — sandboxed GeoPandas/Shapely Python execution

### Routing & Network (7)
`find_route`, `isochrone`, `heatmap`, `closest_facility`, `optimize_route`, `service_area`, `od_matrix`

### Layer Management (7)
`show_layer`, `hide_layer`, `remove_layer`, `style_layer`, `highlight_features`, `filter_layer`, `merge_layers`

### Import/Export (7)
`import_layer`, `import_csv`, `import_wkt`, `import_kml`, `import_geoparquet`, `export_layer`, `export_geoparquet`

### Data Quality (3)
`describe_layer`, `detect_duplicates`, `clean_layer`

### Temporal (1)
`temporal_filter`

### Annotations (4)
`add_annotation`, `classify_landcover`, `export_annotations`, `get_annotations`

### Map Control (1)
`map_command` — pan, zoom, pan_and_zoom, fit_bounds, change_basemap

## Handler Layout

| Handler | Responsibility |
|---------|---------------|
| `navigation.py` | geocode, reverse_geocode, batch_geocode, fetch_osm, search_nearby, map_command |
| `analysis.py` | buffer, spatial_query, aggregate, overlays, geometry ops, topology, CRS, stats, execute_code |
| `layers.py` | style, visibility, highlight, filter, merge, import/export (GeoJSON/CSV/KML/WKT/GeoParquet), data quality |
| `annotations.py` | add, export, get, classify_landcover |
| `routing.py` | find_route, isochrone, heatmap, closest_facility, optimize_route, service_area, od_matrix |

`handlers/__init__.py` hosts `dispatch_tool`, STRtree indexing, and shared helpers.

## Tool Chain Patterns

Baseline patterns taught to Claude via the system prompt. Enhanced descriptions landed in A3 (commit `34f2013`).

```
1. LOCATE → FETCH:      geocode → fetch_osm / search_nearby
2. FETCH → ANALYZE:     fetch_osm → aggregate / calculate_area
3. FETCH → FILTER:      fetch_osm → filter_layer → style_layer
4. BUFFER ANALYSIS:     fetch_osm(A) → fetch_osm(B) → buffer(B) → spatial_query(A, within, buffer)
5. ROUTE → BUFFER:      find_route → buffer → spatial_query
6. ISOCHRONE ANALYSIS:  isochrone → fetch_osm → spatial_query
7. OVERLAY:             fetch_osm(A) → fetch_osm(B) → intersection/difference
8. ANNOTATE:            fetch_osm → filter → add_annotation → export_annotations
9. IMPORT → ANALYZE:    import_csv → buffer → spatial_query
10. HOT-SPOT:           fetch_osm → hot_spot_analysis → style_layer
11. SERVICE COVERAGE:   fetch_osm(facilities) → service_area → difference(bounds)
12. CODE FALLBACK:      execute_code (when no tool chain matches)
```

## Spatial Operations Stack

```
geo_utils.py (core library)
  ├── ValidatedPoint        — coordinate safety (lat/lon validation + explicit accessors)
  ├── validate_bbox         — bbox validation including antimeridian
  ├── estimate_utm_epsg     — auto-select UTM/UPS zone from coordinates
  ├── project_geometry      — reproject between any CRS (cached transformers)
  ├── buffer_geometry       — metric-accurate buffer via UTM round-trip
  ├── geodesic_area         — ellipsoidal area (pyproj Geod, handles holes)
  ├── geodesic_distance     — ellipsoidal point-to-point distance
  └── geojson ↔ shapely     — format conversion wrappers

handlers/__init__.py (shared helpers)
  ├── _build_spatial_index   — STRtree for O(log n) spatial queries
  ├── _get_layer_snapshot    — thread-safe layer read
  ├── _get_layer_geometries  — extract valid Shapely geometries from layer
  ├── _safe_geojson_to_shapely — convert with auto-repair (make_valid)
  ├── _osm_to_geojson        — OSM ways + relations → GeoJSON
  └── _resolve_point*        — geocode or coordinate resolution
```

## Remaining Capability Gaps

All v1 P0-P2 gaps from the original capability map have been closed. Remaining gaps map to v2.1 plans:

| Gap | v2.1 Plan |
|-----|-----------|
| Raster analysis (elevation, slope, viewshed, zonal stats) | [`docs/v2/08-raster-analysis-plan.md`](../docs/v2/08-raster-analysis-plan.md) |
| Multi-agent complex query decomposition | [`docs/v2/03-complex-queries-plan.md`](../docs/v2/03-complex-queries-plan.md) |
| Vector tiles for large layers | [`docs/v2/13-production-plan.md`](../docs/v2/13-production-plan.md) |
| Visualization/dashboard output | [`docs/v2/11-visualization-plan.md`](../docs/v2/11-visualization-plan.md) |
| Collaboration (multi-user sessions) | [`docs/v2/09-collaboration-plan.md`](../docs/v2/09-collaboration-plan.md) |

## External API Dependencies

| API | Used By | Rate Limit | Cache TTL | Fallback |
|-----|---------|-----------|-----------|----------|
| Nominatim | geocode, reverse_geocode, batch_geocode | 1 req/s | 24h | None |
| Overpass | fetch_osm, search_nearby | 2 req/s | 1h | None |
| Valhalla | find_route, isochrone, optimize_route, service_area, od_matrix | 5 req/s | 1h | Buffer estimation (isochrone only) |
| Claude API | nl_gis/chat.py | Per-plan | None | Rule-based fallback for simple commands |
| OpenAI API (multi-provider) | nl_gis/chat.py | Per-plan | None | Claude fallback |
