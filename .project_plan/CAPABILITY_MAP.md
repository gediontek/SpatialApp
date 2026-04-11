# SpatialApp Capability Map

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
  │
  ▼
Claude API call (system + 26 tool schemas + message history)
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

## Tool Inventory (26 tools)

### Data Acquisition (4 tools)
| Tool | External API | Output | Caching |
|------|-------------|--------|---------|
| `geocode` | Nominatim | lat/lon/bbox | 24h file cache |
| `fetch_osm` | Overpass | GeoJSON layer | 1h file cache |
| `search_nearby` | Overpass | GeoJSON layer | 1h file cache |
| `classify_landcover` | OSM_auto_label | GeoJSON layer | None |

### Spatial Analysis (6 tools)
| Tool | Spatial Operations | Output |
|------|-------------------|--------|
| `buffer` | UTM project → Shapely buffer → reproject | GeoJSON layer |
| `spatial_query` | STRtree index + intersects/contains/within/within_distance | GeoJSON layer |
| `aggregate` | geodesic_area (for area op) | Stats dict |
| `calculate_area` | geodesic_area (pyproj ellipsoidal) | Stats dict |
| `measure_distance` | geodesic_distance (pyproj inverse) | Stats dict |
| `filter_layer` | 9 operators (equals, gt, lt, between, etc.) | GeoJSON layer |

### Routing & Network (3 tools)
| Tool | External API | Output |
|------|-------------|--------|
| `find_route` | Valhalla (multi-stop) | GeoJSON layer (line + markers) |
| `isochrone` | Valhalla (fallback: buffer) | GeoJSON layer (polygon) |
| `heatmap` | None (centroid extraction) | Point array for Leaflet.heat |

### Layer Management (7 tools)
| Tool | Operation | Output |
|------|-----------|--------|
| `show_layer` | Visibility toggle | Frontend command |
| `hide_layer` | Visibility toggle | Frontend command |
| `remove_layer` | Delete from map | Frontend command |
| `style_layer` | Change color/weight/opacity | Frontend command |
| `highlight_features` | Attribute-based highlight | Frontend command |
| `merge_layers` | Union or spatial_join (GeoPandas) | GeoJSON layer |
| `import_layer` | Direct GeoJSON import | GeoJSON layer |

### Annotations (3 tools)
| Tool | Operation | Output |
|------|-----------|--------|
| `add_annotation` | Save features to annotation store | Success/count |
| `export_annotations` | GeoJSON/Shapefile/GeoPackage | Download URL |
| `get_annotations` | Read annotation store | GeoJSON + summary |

### Map Control (1 tool)
| Tool | Operations |
|------|-----------|
| `map_command` | pan, zoom, pan_and_zoom, fit_bounds, change_basemap |

### System (2 implicit)
| Tool | Notes |
|------|-------|
| Dashboard API | /api/dashboard — sessions, layers, stats |
| WebSocket | Socket.IO alongside SSE |

## Tool Chain Patterns

The system prompt teaches Claude 8 canonical chains:

```
1. LOCATE → FETCH:     geocode → fetch_osm / search_nearby
2. FETCH → ANALYZE:    fetch_osm → aggregate / calculate_area
3. FETCH → FILTER:     fetch_osm → filter_layer → style_layer
4. BUFFER ANALYSIS:    fetch_osm(A) → fetch_osm(B) → buffer(B) → spatial_query(A, within, buffer)
5. ROUTE → BUFFER:     find_route → buffer → spatial_query (what's near my route?)
6. ISOCHRONE ANALYSIS:  isochrone → fetch_osm → spatial_query (what's reachable?)
7. ANNOTATE:           fetch_osm → filter → add_annotation → export_annotations
8. COMPARE:            fetch_osm(A) → fetch_osm(B) → merge_layers(spatial_join)
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
  └── geojson↔shapely       — format conversion wrappers

handlers/__init__.py (shared helpers)
  ├── _build_spatial_index  — STRtree for O(log n) spatial queries
  ├── _get_layer_snapshot   — thread-safe layer read
  ├── _get_layer_geometries — extract valid Shapely geometries from layer
  ├── _safe_geojson_to_shapely — convert with auto-repair (make_valid)
  ├── _osm_to_geojson       — OSM ways + relations → GeoJSON
  └── _resolve_point*       — geocode or coordinate resolution
```

## Missing Capabilities (Roadmap)

### P0 — Critical Gaps (blocks common user requests)

| # | Capability | User Request Example | Effort |
|---|-----------|---------------------|--------|
| 1 | Overlay: intersection | "Show where parks AND flood zones overlap" | M |
| 2 | Overlay: difference | "Subtract water from the park area" | M |
| 3 | Reverse geocode | "What's at this location?" (click on map) | S |
| 4 | Convex hull | "Draw a boundary around these points" | S |
| 5 | Centroid extraction | "Get center points of all buildings" | S |
| 6 | Geometry simplify | "Simplify this layer for better performance" | S |
| 7 | Closest facility | "What's the nearest hospital?" | M |

### P1 — Important Gaps (professional use)

| # | Capability | Description | Effort |
|---|-----------|-------------|--------|
| 8 | Batch geocode | Geocode a list of addresses to point layer | M |
| 9 | CSV import with coordinates | Import tabular data with lat/lon columns | M |
| 10 | KML/KMZ import | Import GPS tracks and placemarks | M |
| 11 | Attribute join | Join tabular data to spatial layer by key | M |
| 12 | Point-in-polygon | "Which district is this address in?" | S |
| 13 | Bounding box as geometry | "Create a rectangle around this area" | XS |
| 14 | Traveling salesman | "Optimize the order of these 10 stops" | M |
| 15 | Spatial statistics | Clustering, hot spot analysis | L |

### P2 — Advanced (specialized use cases)

| # | Capability | Description | Effort |
|---|-----------|-------------|--------|
| 16 | Elevation/terrain | Elevation profiles, slope, viewshed | L |
| 17 | Raster-vector integration | Zonal statistics | L |
| 18 | Voronoi/Thiessen polygons | Spatial partitioning | M |
| 19 | Temporal filtering | Time-series layer support | M |
| 20 | OD cost matrix | Multi-origin to multi-destination | M |
| 21 | Geometry editing | Split, merge features, edit vertices | L |
| 22 | GeoParquet support | Modern columnar spatial format | S |
| 23 | CRS transformation tool | "Reproject to EPSG:4326" | S |

## External API Dependencies

| API | Used By | Rate Limit | Cache TTL | Fallback |
|-----|---------|-----------|-----------|----------|
| Nominatim | geocode, search_nearby, fetch_osm | 1 req/s | 24h | None |
| Overpass | fetch_osm, search_nearby | 2 req/s | 1h | None |
| Valhalla | find_route, isochrone | 5 req/s | 1h | Buffer estimation (isochrone only) |
| Claude API | chat.py | Per-plan | None | Rule-based fallback for simple commands |
