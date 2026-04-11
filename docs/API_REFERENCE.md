# SpatialApp API Reference

All endpoints require authentication via Bearer token unless noted otherwise. Set `CHAT_API_TOKEN` in `.env` or register a per-user token via `/api/register`.

**Base URL**: `http://localhost:5000`

---

## Auth Endpoints

### POST `/api/register`

Register a new user. Returns `user_id` and API token. **No auth required.**

**Request body:**
```json
{"username": "alice"}
```

**Response (201):**
```json
{"success": true, "user_id": "uuid", "token": "generated-token", "username": "alice"}
```

### GET `/api/me`

Get current authenticated user info.

**Response:**
```json
{"user_id": "uuid", "username": "alice", "created_at": "2025-01-01T00:00:00Z"}
```

### GET `/api/health`

Health check. **No auth required** (returns minimal info). With valid token, returns subsystem details.

**Response (unauthenticated):**
```json
{"status": "ok", "timestamp": "2025-01-01T00:00:00Z"}
```

**Response (authenticated):**
```json
{"status": "ok", "timestamp": "...", "database": "ok", "layers_in_memory": 5, "active_sessions": 2}
```

---

## Chat Endpoints

### POST `/api/chat`

Process a natural language message. Returns an SSE event stream.

**Request body:**
```json
{
  "message": "Show parks in downtown Chicago",
  "session_id": "default",
  "context": {"center": [41.88, -87.63], "zoom": 12},
  "plan_mode": false
}
```

**SSE events:**
| Event type | Description |
|---|---|
| `thinking` | Claude is processing |
| `tool_call` | Tool invocation with name and parameters |
| `tool_result` | Tool output (GeoJSON, text, etc.) |
| `layer_add` | New layer to display on map |
| `message` | Text response (final when `done: true`) |
| `error` | Error message |

**Example SSE:**
```
data: {"type": "tool_call", "tool": "geocode", "params": {"query": "Chicago"}}

data: {"type": "layer_add", "name": "parks_chicago", "geojson": {...}}

data: {"type": "message", "text": "I found 42 parks in downtown Chicago.", "done": true}
```

### POST `/api/chat/execute-plan`

Execute a previously generated plan (from plan_mode). Returns SSE stream.

**Request body:**
```json
{
  "session_id": "default",
  "plan_id": "plan_abc123"
}
```

### GET `/api/usage`

Get token usage statistics for the current session.

**Response:**
```json
{"session_id": "default", "input_tokens": 5000, "output_tokens": 1200, "total_tokens": 6200}
```

### GET `/api/metrics`

Get tool call metrics (counts, timing) for the current session.

**Response:**
```json
{
  "total_tool_calls": 15,
  "tools": {"geocode": {"count": 3, "avg_ms": 120}, "fetch_osm": {"count": 2, "avg_ms": 450}}
}
```

---

## Layer Endpoints

### GET `/api/layers`

List all named layers in memory. Supports optional pagination.

**Query parameters:**
| Param | Type | Default | Description |
|---|---|---|---|
| `page` | int | - | 1-based page number (omit for full list) |
| `per_page` | int | 100 | Items per page (1-500) |

**Response (unpaginated):**
```json
{"layers": [{"name": "parks_chicago", "feature_count": 42}]}
```

**Response (paginated):**
```json
{"layers": [...], "total": 150, "page": 1, "per_page": 100, "total_pages": 2}
```

### DELETE `/api/layers/<layer_name>`

Delete a named layer permanently.

**Response:**
```json
{"success": true}
```

### POST `/api/import`

Import a vector file as a named layer. Accepts `multipart/form-data`.

**Form fields:**
| Field | Type | Description |
|---|---|---|
| `file` | file | GeoJSON, Shapefile (.zip), or GeoPackage (.gpkg) |
| `layer_name` | string | Name for the imported layer |

**Response:**
```json
{"success": true, "layer_name": "my_layer", "feature_count": 25}
```

---

## Annotation Endpoints

### GET `/saved_annotations`

Render the saved annotations page.

### POST `/save_annotation`

Save a geometry as an annotation.

**Request body:**
```json
{
  "coordinates": [[lon, lat], ...],
  "geometry_type": "Polygon",
  "category_name": "farmland",
  "color": "#228B22"
}
```

**Response:**
```json
{"success": true, "annotation_id": 1}
```

### POST `/add_osm_annotations`

Fetch OSM features and add them as annotations.

**Request body:**
```json
{
  "osm_key": "leisure",
  "osm_value": "park",
  "bbox": "41.8,-87.7,41.9,-87.6",
  "category_name": "parks"
}
```

### GET `/get_annotations`

Get all annotations as a GeoJSON FeatureCollection.

**Response:**
```json
{"annotations": [...], "count": 50}
```

### POST `/clear_annotations`

Delete all annotations for the current user.

### POST `/finalize_annotations`

Finalize and persist all current annotations.

### GET `/export_annotations/<format_type>`

Export annotations in the specified format.

**Path parameters:**
| Param | Values |
|---|---|
| `format_type` | `geojson`, `shapefile`, `geopackage` |

**Response:** File download.

### POST `/display_table`

Render annotation data as an HTML table.

---

## OSM Endpoints

### GET `/`

Render the main map application page.

### POST `/upload`

Upload an image for annotation overlay.

**Form fields:** `file` (image file).

### GET `/static/uploads/<filename>`

Serve an uploaded file.

### POST `/fetch_osm_data`

Fetch OSM features by key/value within a bounding box.

**Request body:**
```json
{
  "osm_key": "amenity",
  "osm_value": "hospital",
  "bbox": "41.8,-87.7,41.9,-87.6"
}
```

**Response:**
```json
{"features": [...], "count": 12}
```

### GET `/api/geocode`

Geocode a place name to coordinates.

**Query parameters:** `q` (place name).

**Response:**
```json
{"lat": 41.88, "lon": -87.63, "display_name": "Chicago, IL, USA", "bbox": [41.6, -87.9, 42.0, -87.5]}
```

### POST `/api/auto-classify`

Run automatic landcover classification for a bounding box.

**Request body:**
```json
{"bbox": {"north": 45.55, "south": 45.50, "east": -122.60, "west": -122.70}}
```

### GET `/api/category-colors`

Get the color mapping for annotation categories.

**Response:**
```json
{"farmland": "#228B22", "water": "#0000FF", "forest": "#006400"}
```

---

## Dashboard Endpoints

### GET `/dashboard`

Render the admin dashboard page.

### GET `/api/dashboard`

Get dashboard statistics (sessions, usage, layers).

**Response:**
```json
{
  "total_sessions": 10,
  "active_sessions": 3,
  "total_tool_calls": 150,
  "layers_in_memory": 5,
  "sessions": [{"session_id": "...", "message_count": 12, "created_at": "..."}]
}
```

### DELETE `/api/sessions/<session_id>`

Delete a chat session.

### GET `/api/sessions/<session_id>/messages`

Get message history for a session.

**Response:**
```json
{"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
```

---

## Metrics Endpoint

### GET `/metrics`

Prometheus-compatible metrics endpoint. **No auth required.**

**Response:** Prometheus text format with counters for requests, tool calls, errors, and latency histograms.

---

## WebSocket Events

Connect via Socket.IO at the root URL. Pass auth token as query parameter: `?token=<your_token>`.

### Client-to-Server Events

| Event | Payload | Description |
|---|---|---|
| `join_session` | `{"session_id": "..."}` | Join a chat session room |
| `chat_message` | `{"session_id": "...", "message": "...", "context": {...}}` | Send a chat message |

### Server-to-Client Events

| Event | Payload | Description |
|---|---|---|
| `session_joined` | `{"session_id": "..."}` | Confirmation of room join |
| `chat_event` | `{"type": "...", ...}` | Chat event (same types as SSE) |
| `error` | `{"type": "error", "text": "..."}` | Error message |
