# SpatialApp Work Plan: NL-to-GIS Implementation

**Date**: 2026-03-22
**Reference**: design.md

---

## Overview

Six phases, each independently testable and deployable. Each phase builds on the previous. Phases 0-2 deliver the core NL-to-GIS capability. Phases 3-5 extend with advanced spatial operations, routing, and production readiness.

---

## Phase 0: Foundation (Fix & Stabilize)

**Goal**: Working development environment, passing tests, clean architecture for new modules.

**Depends on**: Nothing
**Delivers**: Stable baseline for all subsequent work

### Tasks

#### 0.1 Recreate Virtual Environment
- Delete broken `OSM_auto_label/venv/` (broken symlinks to Python 3.12)
- Create new venv with Python 3.13 (`/opt/homebrew/bin/python3.13 -m venv venv`)
- Install all dependencies from `requirements.txt`
- Install OSM_auto_label in editable mode (`pip install -e OSM_auto_label/`)
- Verify: `python -c "import flask; import rasterio; import geopandas; print('OK')"`

#### 0.2 Fix requirements.txt
- Add `pandas>=2.0.0` (used in `display_table` but not listed)
- Add `shapely>=2.0.0` (needed for spatial ops, also a geopandas dep)
- Pin versions to what's installed in new venv
- Verify: `pip install -r requirements.txt` succeeds from clean venv

#### 0.3 Fix Stale Tests
- `test_fetch_osm_invalid_key` (line 161): Sends `key`/`key_value` params but `fetch_osm_data` now expects `feature_type`/`category_name` — update test
- `test_fetch_osm_missing_params` (line 176): Same param mismatch — update test
- `test_fetch_osm_invalid_bbox` (line 185): Update params to match current API
- Add missing test for valid `fetch_osm_data` request (mock Overpass)
- Verify: `pytest tests/ -v` all pass

#### 0.4 Add ValidatedPoint Utility
- Create `nl_gis/__init__.py`
- Create `nl_gis/geo_utils.py` with:
  - `ValidatedPoint(lat, lon)` — immutable, validated, `.as_leaflet()`, `.as_geojson()`
  - `validate_bbox(south, west, north, east)` — returns validated tuple
  - `project_to_utm(geometry, src_crs=4326)` — auto-detect UTM zone
  - `project_to_wgs84(geometry, src_crs)` — back to WGS84
- Write tests: `tests/test_geo_utils.py`
- Verify: pytest passes for all coordinate edge cases (antimeridian, poles, zero)

#### 0.5 Create Unified Config
- Create `config.py` at project root (extract from app.py `Config` class)
- Add Claude API config placeholders: `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`
- Add `.env` file (copy from `.env.example`, add new vars)
- Add `python-dotenv` to requirements if not present
- Verify: `app.py` still works with extracted config

#### 0.6 Initialize Git Repository
- `git init` in SpatialApp/
- Create `.gitignore` (update existing with venv/, .env, __pycache__, *.pyc, logs/, cache/, *.egg-info)
- Initial commit with current state
- Verify: `git status` clean

### Phase 0 Exit Criteria
- [ ] `pytest tests/ -v` — all tests pass
- [ ] `python app.py` — app starts and loads at localhost:5000
- [ ] `ValidatedPoint(47.6, -122.3).as_leaflet()` returns `[47.6, -122.3]`
- [ ] `ValidatedPoint(47.6, -122.3).as_geojson()` returns `[-122.3, 47.6]`
- [ ] Git repo initialized with clean commit

---

## Phase 1: Chat Interface + Core Tools

**Goal**: User can type natural language queries and get results on the map. Five core tools: geocode, fetch_osm, map_command, calculate_area, measure_distance.

**Depends on**: Phase 0
**Delivers**: Working NL-to-GIS chat with navigation and OSM data retrieval

### Tasks

#### 1.1 Claude API Integration
- Create `nl_gis/chat.py`:
  - `ChatSession` class — manages conversation history per session
  - `process_message(message, map_context)` — sends to Claude with tools, handles tool_use loop
  - Tool dispatch: receives tool_use block → calls handler → returns result → continues
  - System prompt with GIS assistant instructions (from design.md section 10)
- Add `anthropic>=0.40.0` to requirements.txt
- Add `ANTHROPIC_API_KEY` to `.env`
- Write tests: `tests/test_chat.py` with mocked Claude responses

#### 1.2 Define Tool Schemas
- Create `nl_gis/tools.py`:
  - `get_tool_definitions()` → returns list of tool dicts for Claude API
  - Start with 5 tools: `geocode`, `fetch_osm`, `map_command`, `calculate_area`, `measure_distance`
  - Each tool: name, description, input_schema (JSON Schema)
- Create `nl_gis/schemas.py`:
  - Pydantic models: `GeocodeInput`, `FetchOSMInput`, `MapCommandInput`, `CalculateAreaInput`, `MeasureDistanceInput`
  - Pydantic models for outputs: `GeocodeResult`, `SpatialResult`, `MapCommandResult`
- Write tests: `tests/test_tools.py` — validate schemas parse correctly

#### 1.3 Implement Tool Handlers
- Create `nl_gis/tool_handlers.py`:
  - `handle_geocode(params)` → call Nominatim, return lat/lon/bbox/display_name
  - `handle_fetch_osm(params)` → reuse existing fetch_osm_data logic, return GeoJSON
  - `handle_map_command(params)` → validate and return instruction for frontend
  - `handle_calculate_area(params)` → pyproj.Geod.geometry_area_perimeter()
  - `handle_measure_distance(params)` → pyproj.Geod.inv()
  - `dispatch_tool(tool_name, params)` → route to handler
- Write tests: `tests/test_tool_handlers.py` — test each handler with real spatial ops (mocked HTTP)

#### 1.4 Chat API Endpoint
- Add to `app.py`:
  - `POST /api/chat` — receives message + map_context, returns SSE stream
  - SSE events: `tool_start`, `tool_result`, `layer_add`, `map_command`, `message`
  - Session management (in-memory dict of conversation histories)
  - CSRF exempt for API endpoint (or use token auth)
- Write tests: `tests/test_chat_api.py` — Flask test client with mocked Claude

#### 1.5 Chat Panel UI
- Update `templates/index.html`:
  - Add third tab: "Chat" (alongside Manual Label, Auto Classify)
  - Chat panel HTML structure: message list + input + send button
- Create `static/js/chat.js`:
  - EventSource connection to `/api/chat` (SSE)
  - Handle events: render messages, execute map commands, add layers
  - Message rendering with markdown support (optional)
  - Tool execution indicators (collapsible)
  - Input handling: Enter to send, Shift+Enter for newline
- Update `static/css/styles.css`:
  - Chat panel styles: message bubbles, input area, tool indicators
- Verify: Type "zoom to Seattle" → map pans to Seattle

#### 1.6 Named Layer System (Frontend)
- Create `static/js/layers.js`:
  - `LayerManager` class:
    - `addLayer(name, geojson, style)` → creates Leaflet layer, adds to registry
    - `removeLayer(name)` → removes from map and registry
    - `toggleLayer(name)` → show/hide
    - `getLayerNames()` → list for LLM context
    - `fitToLayer(name)` → fit map bounds
  - Layer list UI panel (collapsible, below tabs)
- Update `main.js` to use LayerManager for existing OSM fetches and classification results
- Verify: Layers appear in panel, can be toggled on/off

### Phase 1 Exit Criteria
- [ ] User types "Show me buildings in downtown Seattle" → buildings appear on map
- [ ] User types "What's the area of this polygon?" (with existing annotation) → area returned
- [ ] User types "How far is it from Seattle to Portland?" → distance returned
- [ ] User types "Zoom to Berlin" → map pans to Berlin
- [ ] User types "Switch to satellite view" → basemap changes
- [ ] Created layers appear in layer manager panel
- [ ] All tests pass: `pytest tests/ -v`
- [ ] Chat conversation history maintained within session

---

## Phase 2: Spatial Analysis Tools

**Goal**: Buffer, intersect, within-distance, aggregate, and spatial query operations via NL.

**Depends on**: Phase 1
**Delivers**: Full spatial analysis capability through chat

### Tasks

#### 2.1 Implement Buffer Tool
- Add to `tool_handlers.py`:
  - `handle_buffer(params)`:
    - Accept geometry (GeoJSON) or layer_name
    - Project to UTM (auto-detect zone) → buffer → project back to WGS84
    - Return GeoJSON polygon
- Add tool schema to `tools.py`
- Write tests with known geometries and expected buffer areas

#### 2.2 Implement Spatial Query Tool
- Add to `tool_handlers.py`:
  - `handle_spatial_query(params)`:
    - Predicates: contains, intersects, within, within_distance
    - Source: layer_name or geometry
    - Target: layer_name or geometry
    - For within_distance: project to UTM, apply distance, project back
    - Return matching features as GeoJSON
- Add tool schema
- Write tests: point-in-polygon, polygon intersection, within-distance

#### 2.3 Implement Aggregate Tool
- Add to `tool_handlers.py`:
  - `handle_aggregate(params)`:
    - Load layer by name
    - Group by attribute (if specified)
    - Operations: count, sum, mean, area
    - Return structured result
- Add tool schema
- Write tests: count buildings by category, total farmland area

#### 2.4 Implement Search Nearby Tool
- Add to `tool_handlers.py`:
  - `handle_search_nearby(params)`:
    - Build Overpass `around:` query
    - Fetch features within radius of point
    - Return GeoJSON
- Add tool schema
- Write tests with mocked Overpass response

#### 2.5 Layer-Aware Tool Context
- Update `chat.py`:
  - Include active layer names + feature counts in system prompt
  - When user says "the buildings layer", resolve to actual layer name
  - Pass layer GeoJSON to tools when referenced
- Update `chat.js`:
  - Send layer state with each chat message
- Write integration tests: multi-tool queries referencing layers

#### 2.6 Highlight & Style Tools
- Add to `tool_handlers.py`:
  - `handle_highlight_features(params)`:
    - Return instruction for frontend to re-style matching features
  - `handle_clear_layer(params)`:
    - Remove named layer
- Update `layers.js` to handle highlight/clear instructions
- Write tests

### Phase 2 Exit Criteria
- [ ] "Create a 1km buffer around Central Park" → buffer polygon on map
- [ ] "Find all buildings within 500m of the river" → filtered results displayed
- [ ] "How many features are in the buildings layer?" → count returned
- [ ] "Show me restaurants near Times Square" → POIs displayed
- [ ] "Highlight all forests in green" → forests re-styled
- [ ] All tests pass

---

## Phase 3: NL Annotation & Classification

**Goal**: Create and manage annotations through natural language. Integrate classification as a chat-accessible tool.

**Depends on**: Phase 2
**Delivers**: Full annotation workflow through chat

### Tasks

#### 3.1 NL Annotation Tool
- Add `handle_annotate(params)`:
  - Accept geometry (from prior tool results) + category + color
  - Save to annotation store (existing mechanism)
  - Return success + annotation ID
- NL examples: "Label this as farmland", "Add these buildings to my annotations"

#### 3.2 Classify Landcover Tool
- Wrap existing `api_auto_classify` as a chat tool:
  - `handle_classify_landcover(params)`
  - Accept location or bbox + class filter
  - Return GeoJSON + colors + feature count
  - Create named layer on map
- NL examples: "Classify landcover for Berlin", "Show me the land use around Mumbai"

#### 3.3 Export Tool
- Add `handle_export(params)`:
  - Export annotations or named layer to file
  - Formats: geojson, shapefile, geopackage
  - Return download link
- NL examples: "Export my annotations as shapefile", "Download the buildings layer"

#### 3.4 Annotation Query Tool
- Add `handle_query_annotations(params)`:
  - Filter annotations by category, source, date range
  - Return matching features
- NL examples: "Show me all manual annotations", "How many OSM features did I add?"

### Phase 3 Exit Criteria
- [ ] "Classify landcover for Portland, Oregon" → classified layer on map
- [ ] "Label the selected features as residential" → annotations saved
- [ ] "Export everything as GeoJSON" → file download initiated
- [ ] "Show me all annotations from OSM" → filtered display

---

## Phase 4: Routing & Advanced Analysis (Future)

**Goal**: Add routing, isochrone, and advanced spatial statistics.

**Depends on**: Phase 2
**Delivers**: Routing capability and spatial statistics

### Tasks

#### 4.1 OSRM Integration
- Add `services/osrm_client.py`:
  - Auto-detect local OSRM (port 5000/5001) or use public demo
  - `get_route(origin, destination, profile)` → GeoJSON LineString
  - `get_isochrone(center, time_minutes)` → GeoJSON polygon
  - Response caching (diskcache or simple file cache)
- Add Docker Compose file for local OSRM (optional)

#### 4.2 Route Tool
- Add `handle_find_route(params)`:
  - Accept origin/destination as coordinates or place names
  - Call OSRM → return route geometry + distance + duration
  - Create named layer with route
- NL examples: "Show me the route from Seattle to Portland"

#### 4.3 Isochrone Tool
- Add `handle_isochrone(params)`:
  - Accept center point + time (minutes) or distance (meters)
  - Call OSRM/Valhalla isochrone API
  - Return polygon showing reachable area
- NL examples: "Show me what's within 15 minutes drive of downtown"

#### 4.4 Density / Heatmap Tool
- Add `handle_heatmap(params)`:
  - Accept point layer name
  - Return instruction for Leaflet.heat plugin
- NL examples: "Show a heatmap of building density"

### Phase 4 Exit Criteria
- [ ] "Route from A to B" → route displayed with distance/duration
- [ ] "What can I reach in 10 minutes from here?" → isochrone polygon
- [ ] Routing works with local OSRM or graceful fallback

---

## Phase 5: Production Readiness (Future)

**Goal**: Database, auth, async processing, caching.

**Depends on**: Phases 0-3 complete
**Delivers**: Production-grade infrastructure

### Tasks

#### 5.1 Database Migration
- Replace JSON file with SQLite + SpatiaLite (or PostGIS)
- Migrate annotations to spatial table
- Add layer metadata table
- Add conversation history table

#### 5.2 Async Classification
- Move classification to background task (Celery or threading)
- WebSocket/SSE progress updates during classification
- Job queue for large area requests

#### 5.3 Caching Layer
- Cache Overpass API responses (TTL: 1 hour)
- Cache Nominatim geocoding results (TTL: 24 hours)
- Cache OSRM routing results (TTL: 1 hour)
- Use `diskcache` or `cachetools`

#### 5.4 Rate Limiting
- Overpass API: 1 request per 2 seconds
- Nominatim: 1 request per second (their policy)
- Claude API: configurable per-session limit

#### 5.5 Authentication (Optional)
- API key auth for /api/* endpoints
- Session-based auth for web UI
- Per-user annotation stores

### Phase 5 Exit Criteria
- [ ] Annotations persisted in database
- [ ] Classification runs in background with progress updates
- [ ] API responses cached appropriately
- [ ] Rate limits enforced

---

## Dependency Graph

```
Phase 0 ─────────────────────────────────────┐
  (Foundation)                                │
       │                                      │
       v                                      │
Phase 1 ──────────────────────┐               │
  (Chat + Core Tools)        │               │
       │                      │               │
       v                      v               │
Phase 2              Phase 3                  │
  (Spatial Analysis)   (NL Annotation)        │
       │                      │               │
       v                      v               │
Phase 4              Phase 5 ◄────────────────┘
  (Routing)            (Production)
```

---

## Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| Claude API latency (2-5s per call, multi-tool = 10-20s) | Medium | SSE streaming shows progress; cache common geocoding results |
| Overpass API rate limiting / downtime | Medium | Response caching; graceful error messages; local OSM extract fallback |
| Large area OSM queries timeout | High | Enforce zoom level check; warn user; cap bbox area |
| Claude hallucinating coordinates | Medium | ValidatedPoint validates all coords; tool results are authoritative |
| Cost of Claude API for spatial queries | Low | Track token usage; Claude Haiku for simple commands, Sonnet for complex |
| Leaflet performance with 10K+ features | Medium | Cluster rendering; simplify geometries; limit feature count per layer |
| Global state race conditions | Low (single-user) | Deferred to Phase 5; document as known limitation |

---

## Metrics

Track after Phase 1 launch:
- **Query success rate**: % of NL queries that produce a map result
- **Tool chain length**: Average tools per query (expect 1-4)
- **Response time**: End-to-end from user input to map render
- **Token usage**: Claude API tokens per query (cost tracking)
- **Error rate**: % of queries that fail (tool error, timeout, bad coords)
