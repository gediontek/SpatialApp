# SpatialApp Design Document: Natural Language to GIS

**Date**: 2026-03-22
**Status**: Draft
**Author**: Research-assisted design

---

## 1. Problem Statement

SpatialApp is a functional geospatial annotation tool with manual labeling and automated landcover classification. However, it lacks **natural language interaction** — users must navigate menus, dropdowns, and forms for every GIS operation. The goal is to add a **conversational GIS interface** where users can type commands like:

- "Show me all buildings near downtown Chicago"
- "What's the total area of farmland in the current view?"
- "Fetch forests and water bodies for Berlin"
- "Draw a buffer of 500m around this park"
- "Zoom to Seattle and show satellite view"

This transforms SpatialApp from a tool-driven application into an **AI-powered spatial assistant**.

---

## 2. Current Architecture

```
[Browser: jQuery + Leaflet 1.7.1 + Leaflet.draw]
        |  (AJAX / REST)
        v
[Flask Backend (app.py, 753 LOC)]
   |-- 14 routes (GET/POST)
   |-- Global state: geo_coco_annotations[] (in-memory list)
   |-- Persistence: labels/annotations.geojson (JSON file)
   |-- OSM fetch: Overpass API (12 hardcoded feature types)
   |-- Raster: rasterio + pyproj CRS transform
   |-- Classification: OSM_auto_label (GloVe embeddings, 7 categories)
   |-- Export: GeoJSON, Shapefile, GeoPackage via GeoPandas
```

### Current Capabilities
- Raster overlay (GeoTIFF upload + transparency control)
- Manual drawing (polygon, rectangle, circle, polyline via Leaflet.draw)
- OSM feature fetch (12 feature types via Overpass API)
- Auto landcover classification (GloVe word embeddings → 7 categories)
- Annotation CRUD with backups
- Multi-format export (GeoJSON, Shapefile, GeoPackage)
- Basic geocoding (Nominatim)

### Current Limitations
- No natural language interface
- No spatial operations (buffer, intersect, within-distance)
- No routing / network analysis
- No spatial statistics (area, distance, density)
- No named layer management
- No address parsing pipeline
- Global mutable state (not thread-safe)
- Broken virtual environment (Python 3.12 → gone, system has 3.13)
- Stale tests (OSM test params don't match current API)
- `pandas` used but not in requirements.txt

---

## 3. Target Architecture

```
[Browser: Leaflet Map + Chat Panel + Layer Manager]
        |  (REST + SSE for streaming)
        v
[Flask Backend]
   |
   |-- /api/chat              NL input → Claude API (tool_use)
   |-- /api/spatial/*          Direct spatial operation endpoints
   |-- /api/layers/*           Named layer CRUD
   |-- Existing routes         Upload, annotations, OSM, export, classify
   |
   |-- Tool Registry           12+ tool definitions for Claude
   |      |
   |      |-- Navigation Tools
   |      |     geocode, pan_to, zoom_to, fit_bounds, change_basemap
   |      |
   |      |-- Data Retrieval Tools
   |      |     fetch_osm, classify_landcover, search_nearby
   |      |
   |      |-- Spatial Analysis Tools
   |      |     buffer, intersect, within_distance, calculate_area,
   |      |     measure_distance, aggregate
   |      |
   |      |-- Map Control Tools
   |      |     show_layer, hide_layer, highlight_features,
   |      |     add_annotation, clear_layer
   |      |
   |      |-- (Future) Routing Tools
   |            find_route, isochrone
   |
   |-- Claude API              Anthropic SDK (tool_use mode)
   |-- GeoPandas / Shapely     Spatial operations engine
   |-- Overpass API             OSM data
   |-- Nominatim               Geocoding
   |-- (Future) OSRM           Routing
```

---

## 4. Design Decisions

### 4.1 LLM Integration: Claude API with tool_use

**Chosen**: Claude API with `tool_use` (function calling)

**Alternatives considered**:

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| **Text-to-SQL (PostGIS)** | Powerful spatial queries | Security risk (SQL injection), requires PostGIS, 56% accuracy (Monkuu benchmark) | Reject |
| **Code generation (Python)** | 97% accuracy, maximum flexibility | Security risk (arbitrary code exec), sandboxing complex | Reject for now |
| **Tool-based function calling** | 86% accuracy, secure (parameterized), predictable, debuggable | Limited to predefined tools | **Chosen** |
| **Rule-based NL parsing** | No API key needed, deterministic | Brittle, can't handle novel phrasing | Fallback only |

**Rationale**: AWS Strands Agents (2025) explicitly chose tool-based over text-to-SQL for security. GeoJSON Agents (2026) showed 85.71% accuracy for function calling — sufficient for interactive use where users can rephrase. The USPS route-optimization project validates this pattern in production with 24 GIS operations.

### 4.2 Frontend Chat: Integrated Panel (not separate page)

**Chosen**: Chat panel embedded in sidebar, alongside existing tabs.

**Rationale**: Users need to see the map while conversing. A modal or separate page breaks spatial context. The USPS repo uses an integrated command bar; Ed in Space's Claude Agent SDK demo uses a side panel. Both confirm this pattern.

### 4.3 Response Streaming: Server-Sent Events (SSE)

**Chosen**: SSE for streaming Claude responses + tool execution status.

**Alternatives**:
- WebSocket: Bidirectional, but overkill — client only sends, server streams.
- Polling: Simple but laggy for multi-tool chains that take 5-30s.
- SSE: Server pushes events, native browser support, works with Flask.

### 4.4 Coordinate Convention: Explicit ValidatedPoint

**Borrowed from USPS repo**: Every coordinate passes through a `ValidatedPoint` class with explicit `.as_leaflet()` (lat, lng) and `.as_geojson()` (lng, lat) methods.

```python
@dataclass(frozen=True)
class ValidatedPoint:
    lat: float
    lon: float

    def __post_init__(self):
        if not (-90 <= self.lat <= 90):
            raise ValueError(f"Latitude {self.lat} out of range [-90, 90]")
        if not (-180 <= self.lon <= 180):
            raise ValueError(f"Longitude {self.lon} out of range [-180, 180]")

    def as_leaflet(self) -> list:
        """[lat, lng] for Leaflet."""
        return [self.lat, self.lon]

    def as_geojson(self) -> list:
        """[lng, lat] for GeoJSON/OSRM."""
        return [self.lon, self.lat]
```

### 4.5 GeoJSON as Universal Exchange Format

All tools return GeoJSON FeatureCollections. This is Leaflet's native format — zero serialization friction. Every tool result can be directly rendered on the map.

### 4.6 Layer Management: Named Layers

Currently, all annotations go into one undifferentiated `drawnItems` FeatureGroup. The new design introduces **named layers**:

```javascript
// Layer registry on frontend
layers = {
    "osm_buildings_chicago": { leafletLayer, visible, metadata },
    "buffer_500m_park":      { leafletLayer, visible, metadata },
    "classified_berlin":     { leafletLayer, visible, metadata }
}
```

Each tool result creates a named layer. The LLM can reference layers by name in subsequent operations ("hide the buildings layer", "intersect forests with the buffer").

### 4.7 State Management: Keep JSON File (for now)

**Decision**: Don't add a database in Phase 0-1. The current JSON file persistence is sufficient for single-user annotation workflows. Database migration (SQLite+SpatiaLite or PostGIS) is deferred to Phase 4+ when multi-user or complex spatial indexing becomes necessary.

**Rationale**: Adding a database now would triple the scope of Phase 0 without enabling any NL-to-GIS capability. The core value is the chat interface and spatial tools, not data persistence.

---

## 5. Tool Definitions

Each tool is defined with a name, description, parameters (JSON Schema), and return type. These are passed to Claude API as `tools` in the request.

### 5.1 Navigation Tools

#### `geocode`
```
Purpose: Convert place name to coordinates
Input:   { query: string }
Output:  { lat, lon, display_name, bbox }
Backend: Nominatim API (existing)
```

#### `map_command`
```
Purpose: Control map view (pan, zoom, change basemap)
Input:   { action: "pan"|"zoom"|"fit_bounds"|"change_basemap",
           lat?: float, lon?: float, zoom?: int,
           bbox?: [south, west, north, east],
           basemap?: "osm"|"satellite" }
Output:  { success: true, action_taken: string }
Backend: Returns instruction; frontend executes
```

### 5.2 Data Retrieval Tools

#### `fetch_osm`
```
Purpose: Fetch OSM features by type within bounds
Input:   { feature_type: string, bbox?: string,
           location?: string, category_name: string }
Output:  GeoJSON FeatureCollection
Backend: Existing /fetch_osm_data (extended with geocoding)
```

#### `classify_landcover`
```
Purpose: Auto-classify landcover for an area
Input:   { location?: string, bbox?: {n,s,e,w},
           classes?: string[] }
Output:  { features: int, geojson: FeatureCollection, colors: dict }
Backend: Existing /api/auto-classify
```

#### `search_nearby`
```
Purpose: Find features near a point
Input:   { lat: float, lon: float, radius_m: float,
           feature_type: string }
Output:  GeoJSON FeatureCollection
Backend: Overpass API with around: filter
```

### 5.3 Spatial Analysis Tools

#### `buffer`
```
Purpose: Create buffer polygon around geometry
Input:   { geometry: GeoJSON, distance_m: float }
Output:  GeoJSON FeatureCollection (buffered polygon)
Backend: Shapely buffer (project to UTM → buffer → back to WGS84)
```

#### `calculate_area`
```
Purpose: Calculate area of polygon(s)
Input:   { layer_name?: string, geometry?: GeoJSON }
Output:  { total_area_sq_m: float, total_area_sq_km: float,
           total_area_acres: float, features: [{id, area_sq_m}] }
Backend: pyproj.Geod.geometry_area_perimeter()
```

#### `measure_distance`
```
Purpose: Geodesic distance between two points
Input:   { from: {lat, lon} | string, to: {lat, lon} | string }
Output:  { distance_m: float, distance_km: float, distance_mi: float }
Backend: pyproj.Geod.inv()
```

#### `spatial_query`
```
Purpose: Find features matching a spatial predicate
Input:   { source_layer: string, predicate: "contains"|"intersects"|
           "within"|"within_distance", target_layer?: string,
           target_geometry?: GeoJSON, distance_m?: float }
Output:  GeoJSON FeatureCollection (matching features)
Backend: GeoPandas sjoin / Shapely predicates
```

#### `aggregate`
```
Purpose: Summarize features by attribute
Input:   { layer_name: string, group_by?: string,
           operation: "count"|"sum"|"mean"|"area" }
Output:  { results: [{group, value}], total: float }
Backend: GeoPandas groupby + agg
```

### 5.4 Map Control Tools

#### `show_layer` / `hide_layer`
```
Purpose: Toggle layer visibility
Input:   { layer_name: string }
Output:  { success: true }
Backend: Frontend-executed instruction
```

#### `highlight_features`
```
Purpose: Highlight features matching criteria
Input:   { layer_name: string, attribute: string,
           value: string, color?: string }
Output:  { highlighted: int }
Backend: Frontend-executed instruction
```

#### `add_annotation`
```
Purpose: Create annotation from NL description
Input:   { geometry: GeoJSON, category_name: string,
           color?: string }
Output:  { success: true, id: int }
Backend: Existing /save_annotation
```

---

## 6. Data Flow: NL Query → Map Result

### 6.1 Single-Tool Flow

```
User types: "Show me all buildings in downtown Chicago"
    |
    v
POST /api/chat { message: "Show me all buildings in downtown Chicago" }
    |
    v
Flask: Build Claude API request
    messages: [{ role: "user", content: "..." }]
    tools: [geocode, fetch_osm, map_command, ...]
    system: "You are a GIS assistant. You have access to spatial tools..."
    |
    v
Claude API response (tool_use):
    tool: "geocode", input: { query: "downtown Chicago" }
    |
    v
Flask: Execute geocode → { lat: 41.88, lon: -87.63, bbox: [...] }
    |
    v
Claude API (continue with tool result):
    tool: "fetch_osm", input: { feature_type: "building",
           bbox: "41.87,-87.64,41.89,-87.62", category_name: "building" }
    |
    v
Flask: Execute fetch_osm → GeoJSON FeatureCollection (247 features)
    |
    v
Claude API (continue with tool result):
    tool: "map_command", input: { action: "fit_bounds",
           bbox: [41.87, -87.64, 41.89, -87.62] }
    |
    v
Claude API (final text response):
    "I found 247 buildings in downtown Chicago. They're displayed
     on the map in blue. The map has been zoomed to fit the area."
    |
    v
Flask: Stream to browser via SSE:
    event: tool_start  { tool: "geocode" }
    event: tool_result { tool: "geocode", data: {...} }
    event: tool_start  { tool: "fetch_osm" }
    event: tool_result { tool: "fetch_osm", geojson: {...}, layer: "buildings_chicago" }
    event: map_command { action: "fit_bounds", bbox: [...] }
    event: message     { text: "I found 247 buildings..." }
    |
    v
Browser:
    1. Render GeoJSON as named layer "buildings_chicago"
    2. Execute map_command (fit bounds)
    3. Display text response in chat panel
```

### 6.2 Multi-Step Analysis Flow

```
User: "What's the total farmland area within 5km of the Chicago River?"
    |
    v
Claude chains:
    1. geocode("Chicago River") → coords
    2. fetch_osm("river", bbox, "chicago_river") → river geometry
    3. buffer(river_geometry, 5000) → buffer polygon
    4. fetch_osm("farmland", buffer_bbox, "farmland") → farmland features
    5. spatial_query(farmland, "intersects", buffer) → filtered farmland
    6. calculate_area(filtered_farmland) → { total_area_sq_km: 12.4 }
    7. map_command(fit_bounds) → zoom to results
    |
    v
Response: "There are 12.4 sq km of farmland within 5km of the
           Chicago River. I've highlighted the matching areas on the map."
```

---

## 7. Frontend Changes

### 7.1 New UI Elements

```
Sidebar (existing 300px):
  ├── Tab: Manual Label (existing)
  ├── Tab: Auto Classify (existing)
  ├── Tab: Chat (NEW)
  │     ├── Chat history panel (scrollable)
  │     ├── Input field + send button
  │     ├── Tool execution indicators
  │     └── Quick action buttons (optional)
  └── Layer Manager panel (NEW, collapsible)
        ├── Layer list with visibility toggles
        ├── Layer color/style controls
        └── Layer delete button
```

### 7.2 Chat Panel Behavior
- Input field at bottom, messages scroll up
- User messages right-aligned, assistant messages left-aligned
- Tool execution shown as collapsible steps (like the USPS repo's activity log)
- GeoJSON results auto-rendered on map as named layers
- Map commands auto-executed (pan, zoom, basemap changes)
- References to layers/features are clickable (zoom-to-feature)

### 7.3 Layer Manager
- Lists all named layers (manual drawings, OSM fetches, classification results, chat-created layers)
- Toggle visibility per layer
- Click layer name to fit bounds
- Color indicator per layer
- Delete layer button

---

## 8. Backend Module Structure

```
SpatialApp/
├── app.py                    # Flask app + existing routes (modified)
├── config.py                 # Unified configuration (NEW)
├── design.md                 # This document
├── work_plan.md              # Implementation plan
├── requirements.txt          # Updated dependencies
│
├── nl_gis/                   # NL-to-GIS module (NEW)
│   ├── __init__.py
│   ├── chat.py               # Claude API integration, tool dispatch
│   ├── tools.py              # Tool definitions (JSON schemas for Claude)
│   ├── tool_handlers.py      # Tool execution logic
│   ├── schemas.py            # Pydantic models for tool I/O
│   └── geo_utils.py          # ValidatedPoint, CRS helpers, spatial ops
│
├── OSM_auto_label/           # Existing classification module
├── static/
│   ├── js/
│   │   ├── main.js           # Existing (modified for layers + chat)
│   │   ├── chat.js           # Chat panel logic (NEW)
│   │   └── layers.js         # Layer manager logic (NEW)
│   └── css/
│       └── styles.css        # Updated styles
├── templates/
│   └── index.html            # Updated with chat panel + layer manager
├── tests/
│   ├── test_app.py           # Existing (fixed)
│   ├── test_tools.py         # Tool handler tests (NEW)
│   ├── test_chat.py          # Chat integration tests (NEW)
│   └── test_geo_utils.py     # Spatial utility tests (NEW)
└── labels/                   # Existing annotation storage
```

---

## 9. API Contracts

### POST /api/chat

**Request**:
```json
{
    "message": "Show me all buildings near downtown Chicago",
    "conversation_id": "optional-session-id",
    "context": {
        "map_bounds": { "south": 41.8, "west": -87.7, "north": 41.9, "east": -87.6 },
        "zoom": 14,
        "active_layers": ["osm_buildings"]
    }
}
```

**Response** (SSE stream):
```
event: tool_start
data: {"tool": "geocode", "input": {"query": "downtown Chicago"}}

event: tool_result
data: {"tool": "geocode", "result": {"lat": 41.88, "lon": -87.63}}

event: tool_start
data: {"tool": "fetch_osm", "input": {"feature_type": "building", ...}}

event: layer_add
data: {"name": "buildings_chicago", "geojson": {...}, "style": {"color": "#3388ff"}}

event: map_command
data: {"action": "fit_bounds", "bbox": [41.87, -87.64, 41.89, -87.62]}

event: message
data: {"text": "I found 247 buildings in downtown Chicago.", "done": true}
```

### POST /api/spatial/buffer

**Request**:
```json
{
    "geometry": { "type": "Polygon", "coordinates": [...] },
    "distance_m": 500
}
```

**Response**:
```json
{
    "type": "FeatureCollection",
    "features": [{ "type": "Feature", "geometry": {...}, "properties": {"buffer_distance_m": 500} }]
}
```

### GET /api/layers

**Response**:
```json
{
    "layers": [
        { "name": "buildings_chicago", "feature_count": 247, "visible": true, "created_at": "..." },
        { "name": "classified_berlin", "feature_count": 1432, "visible": true, "created_at": "..." }
    ]
}
```

---

## 10. Claude System Prompt (Draft)

```
You are a GIS assistant integrated into SpatialApp, a web-based geospatial
labeling and analysis tool. You help users interact with maps and spatial
data through natural language.

You have access to spatial tools that operate on a Leaflet.js map. When a
user asks a spatial question, use the appropriate tool(s) to answer it.

GUIDELINES:
- Always use the geocode tool when the user references a place by name
- When fetching OSM data, check the current map zoom level — warn if too
  zoomed out (large area queries can be slow)
- Return specific numbers: "247 buildings" not "many buildings"
- When creating layers, use descriptive names: "buildings_downtown_chicago"
  not "result_1"
- Chain tools when needed: geocode → fetch → analyze → display
- Always fit the map bounds to show results unless the user specifies otherwise
- Reference created layers by name in your response so the user can manage them
- For area/distance calculations, provide multiple units (sq m, sq km, acres)

CURRENT MAP STATE (provided per request):
- Map bounds, zoom level, active layers

COORDINATE CONVENTION:
- Leaflet uses [lat, lng]
- GeoJSON uses [lng, lat]
- Always validate coordinates before passing to tools
```

---

## 11. Dependencies (New)

```
# Existing
Flask>=2.3.2
Flask-WTF>=1.2.0
rasterio>=1.3.5
pyproj>=3.6.0
geopandas>=0.14.0
requests>=2.31.0
Werkzeug>=2.3.4
pandas>=2.0.0          # Was implicit, now explicit

# New for NL-to-GIS
anthropic>=0.40.0      # Claude API SDK
pydantic>=2.0.0        # Schema validation for tools
shapely>=2.0.0         # Spatial operations (buffer, intersect)

# Testing
pytest>=7.0.0
pytest-cov>=4.0.0
```

---

## 12. Security Considerations

1. **No arbitrary code execution** — Tool-based approach only. Each tool has validated parameters via Pydantic schemas.
2. **API key management** — Claude API key stored in `.env`, never committed. Loaded via `os.environ`.
3. **Rate limiting** — Claude API calls per-session. Overpass API queries throttled (existing validation + new 1-req-per-2s limit).
4. **Input sanitization** — All NL input passes through Claude (no direct eval/exec). Tool parameters validated before execution.
5. **CSRF** — Existing protection extended to new endpoints.
6. **Geometry validation** — All user-supplied geometries validated via Shapely `is_valid` before spatial operations.

---

## 13. Testing Strategy

| Layer | What | Framework |
|-------|------|-----------|
| **Unit** | Tool handlers (geocode, buffer, area calc), ValidatedPoint, schema validation | pytest |
| **Integration** | Tool chaining (geocode → fetch → analyze), Claude API mock responses | pytest + unittest.mock |
| **E2E** | Full NL query → map result flow with mocked Claude API | pytest + Flask test client |
| **Contract** | Tool schemas match Claude API expectations, GeoJSON output valid | pytest + jsonschema |

### Mock Strategy
- Claude API: Mock `anthropic.Anthropic.messages.create()` to return predetermined tool_use responses
- Overpass API: Mock `requests.get` with cached OSM responses
- Nominatim: Mock with known geocoding results
- No mocking of Shapely/GeoPandas — test against real spatial operations

---

## 14. Alternatives Not Chosen

### Multi-Agent Architecture
**What**: Planner agent decomposes → Worker agents execute → Integrator assembles
**Why rejected**: Adds latency and complexity. Claude's built-in multi-tool chaining handles sequential operations well. Revisit if we need parallel spatial operations or complex workflows.

### PostGIS Database
**Why deferred**: The current use case is single-user annotation + NL analysis. PostGIS adds operational complexity (PostgreSQL server, migrations, connection pooling). If multi-user or spatial indexing at scale becomes necessary, migrate then.

### WebSocket for Chat
**Why rejected**: SSE is simpler, sufficient (server→client streaming only), and doesn't require additional Flask extensions. The chat is request-response with streaming, not bidirectional.

### React/Vue Frontend Rewrite
**Why rejected**: The existing jQuery + Leaflet stack works. Adding a framework for a chat panel is over-engineering. The new JS modules (chat.js, layers.js) can be vanilla ES6.
