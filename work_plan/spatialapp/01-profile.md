# SpatialApp — Profile

Filled by running [`framework/05-profiling-procedure.md`](../../../cognitive-skill-agent/eval-framework/docs/05-profiling-procedure.md)
over this repo. Last regenerated: 2026-05-02.

## P1 — Domain

SpatialApp is a natural-language driven web GIS. Users type questions
in English; the system selects spatial tools, fetches data from OSM /
Nominatim / Valhalla / local rasters, runs spatial analysis (buffer,
intersection, routing, classification, raster derivatives), renders
results on a Leaflet map, and persists annotations and chat sessions.

Target users: GIS analysts, city-planning researchers, OSM
contributors. The job is to make GIS operations accessible without
QGIS / ArcGIS / scripting, while remaining geospatially correct.

## P3 — Inputs (system-wide)

| Class | Type | Constraints |
|---|---|---|
| Place name | string | Geocoded via Nominatim. |
| BBox | string `S,W,N,E` | Validated by `validate_bbox`. |
| Lat / Lon pair | floats | `[-90,90]` / `[-180,180]`. |
| Feature type | enum string | Mapped via `OSM_FEATURE_MAPPINGS` in `nl_gis/handlers/__init__.py`. |
| GeoJSON FeatureCollection | dict | RFC 7946; coords `[lon, lat]`. |
| Raster file | `.tif` / `.tiff` | Opened by rasterio. |
| Tabular import | CSV / KML / WKT / GeoPackage / GeoParquet / Shapefile zip | Format auto-detected by `import_auto`. |
| NL query | string | ≤10,000 chars. |
| Bearer token | string | Per-user or shared `CHAT_API_TOKEN`. |
| CSRF token | string | Required on state-mutating endpoints (Flask-WTF). |

## P5 — External dependencies

| System | Direction | Capabilities affected | Failure mode |
|---|---|---|---|
| **Nominatim** | outbound HTTP | geocode, reverse_geocode, batch_geocode, fetch_osm (geocodes location) | Geocoding fails → "X in Y" queries fail; circuit breaker opens. |
| **Overpass** | outbound HTTP | fetch_osm, search_nearby, classify_area | OSM fetches return error toast; circuit breaker opens. |
| **Valhalla** | outbound HTTP | find_route, isochrone, optimize_route, service_area, od_matrix | Routing tools return "routing service unavailable". |
| **Anthropic / Gemini / OpenAI** | outbound HTTPS | All chat-driven workflows | Chat returns generic error; partial results retained. |
| **rasterio / GDAL** | local | raster_info, raster_value, raster_statistics, raster_profile, raster_classify | Raster handlers error out; vector tools unaffected. |
| **SQLite (or Postgres)** | bidirectional | layer persistence, sessions, annotations, query_metrics, collab_sessions | App still serves; layers don't survive restart. |
| **Optional gensim / osmnx** | local | classify_area, predict_labels, train_classifier | Autolabel handlers return "not installed" error. |
| **flask-socketio** | bidirectional | All chat tab + collab WS events | Falls back to SSE; collab unusable. |
| **OSM tile servers / CARTO / ArcGIS** | outbound HTTPS | Map basemap rendering | Tiles fail to load; Leaflet shows gray squares. |

## P6 — User surfaces

Five surfaces:
1. **Web UI** at `/` — Manual tab, Auto tab, Chat tab, Layer panel.
2. **Dashboard** at `/dashboard` — metrics, sessions.
3. **Saved annotations** at `/saved_annotations`.
4. **REST API** — every blueprint route, callable directly.
5. **WebSocket transport** — `/socket.io` endpoint, chat + collab events.

The full enumeration of UI elements with server effect is in
[`05-workflow-inventory.md`](05-workflow-inventory.md).

## Profile drift checks

Run [`framework/05`](../../../cognitive-skill-agent/eval-framework/docs/05-profiling-procedure.md) extractor
greps and diff against this profile:

```
grep -rE '@.*\.route'         blueprints/        # routes
grep -rE '^def handle_'       nl_gis/handlers/   # handler functions
grep -rE 'on\(.*click|addEventListener.*click' static/js/ templates/  # UI handlers
grep -rE 'requests\.|httpx\.|sqlite3\.|psycopg' nl_gis/ blueprints/ services/   # external deps
```

If any of those produce items not represented in
[`02-capability-catalog.md`](02-capability-catalog.md), open an audit
ticket per governance rule G7.
