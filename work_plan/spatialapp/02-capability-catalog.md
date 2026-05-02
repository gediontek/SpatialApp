# SpatialApp — Capability Catalog

> Status: **draft v1**. Source of truth for test derivation.
> Last regenerated: 2026-05-02 (manual; auto-extractor not yet built).

This catalog enumerates every capability the application exposes,
grouped by domain area. Tests are derived from these entries via
[`framework/06`](../../../cognitive-skill-agent/eval-framework/docs/06-test-derivation-rules.md), not
authored independently.

Each row links to the specific code path so reviewers can verify the
capability still exists.

---

## Group A — OSM acquisition (P0)

### `fetch_osm`

| Field | Value |
|---|---|
| **verb / object** | fetch / OSM features |
| **description** | Fetch OSM features by `feature_type` within a bbox or named location. Returns a GeoJSON FeatureCollection registered as a layer. |
| **inputs** | `feature_type` (enum, must exist in `OSM_FEATURE_MAPPINGS`); `bbox` *or* `location`; `category_name`. |
| **outputs** | GeoJSON FeatureCollection. **Domain criteria:** GIS-C1 (spec-valid), GIS-C2 (lon,lat order), GIS-C3 (EPSG:4326), GIS-C4 (closed polygons), GIS-C11 (feature_type ↔ tag mapping correct). |
| **dependencies** | Nominatim (geocode), Overpass. |
| **user_surfaces** | Manual tab `#fetchOsmBtn` → `POST /fetch_osm_data`; Chat tool dispatch → `nl_gis/handlers/navigation.py::handle_fetch_osm`. |
| **failure_modes** | Overpass 406 (UA missing) → "Error connecting to OSM service"; Overpass 429 → backoff; bbox out of range → 400; unknown feature_type → 400. |
| **criticality** | **P0**. Every other workflow depends on getting features on the map. |

### `geocode`, `reverse_geocode`, `batch_geocode`, `search_nearby`

(Same template; one row per handler. Bodies omitted in this draft for
brevity — see `nl_gis/handlers/navigation.py` and
`blueprints/osm.py`. Each row must be filled before this catalog is
considered approved.)

### `classify_area`, `predict_labels`, `train_classifier`, `export_training_data`, `evaluate_classifier`

(See `nl_gis/handlers/autolabel.py`. Each is a Q1 capability with the
sub-axes inherited from `fetch_osm` for the OSM-acquisition portion
plus LLM-ML correctness criteria.)

---

## Group B — Vector analysis (P0 / P1)

### `buffer`

| Field | Value |
|---|---|
| **inputs** | `layer_name`, `distance_m` (positive). |
| **outputs** | New layer of buffered geometries. **Domain criteria:** GIS-C5 (buffer non-shrinking), GIS-C6 (metric correctness — buffer at 500m really is ~500m on the ground via UTM projection). |
| **failure_modes** | Empty layer; geodetic-distance error at antimeridian. |
| **criticality** | P0. |

### `spatial_query`, `intersection`, `difference`, `symmetric_difference`, `clip`, `dissolve`, `convex_hull`, `voronoi`, `centroid`, `simplify`, `bounding_box`, `point_in_polygon`, `attribute_join`, `spatial_statistics`, `hot_spot_analysis`, `interpolate`, `validate_topology`, `repair_topology`

(Each is a Q1 capability with `outputs.domain_criteria` covering the
specific topological / metric invariant — e.g. intersection ⊆ both
inputs; reproject preserves area within tolerance.)

### `aggregate`, `filter_layer`, `attribute_statistics`, `temporal_filter`

(Q1 + Q2; tabular operations on attributes.)

---

## Group C — Routing and networks (P0)

### `find_route`, `isochrone`, `closest_facility`, `optimize_route`, `service_area`, `od_matrix`, `heatmap`

| Field (e.g. `find_route`) | Value |
|---|---|
| **inputs** | `from_location` *or* `from_point`, `to_location` *or* `to_point`, `mode` (auto / bicycle / pedestrian). |
| **outputs** | `LineString` route, `distance_km`, `duration_s`. **Domain criteria:** GIS-C8 (route starts at A, ends at B; distance ≥ great-circle). |
| **dependencies** | Valhalla, Nominatim. |
| **failure_modes** | Valhalla unreachable; no route exists. |
| **criticality** | P0. |

---

## Group D — Layer / data ops (P1)

### Imports: `import_csv`, `import_wkt`, `import_kml`, `import_geoparquet`, `import_layer`, `import_auto`

| Field | Value |
|---|---|
| **inputs** | Format-specific raw payload + optional layer name. |
| **outputs** | New layer, valid GeoJSON. **Domain criteria:** GIS-C12 (round-trip preserves attributes), GIS-C2 (lon/lat order respected after import). |
| **failure_modes** | Malformed input; oversized payload; CRS mismatch on Shapefile. |

### Exports: `export_layer`, `export_geoparquet`, `export_gpkg`, `export_annotations`

(Symmetric. Round-trip test pairs each import with its export.)

### Layer management: `style_layer`, `highlight_features`, `merge_layers`, `clean_layer`, `detect_duplicates`, `describe_layer`, `clip_to_bbox`, `generalize`, `reproject_layer`, `detect_crs`, `split_feature`, `merge_features`, `extract_vertices`

---

## Group E — Raster (P1)

### `raster_info`, `raster_value`, `raster_statistics`, `raster_profile`, `raster_classify`

| Field (e.g. `raster_value`) | Value |
|---|---|
| **inputs** | `raster` filename, `lat`, `lon`. |
| **outputs** | Numeric value at point. **Domain criteria:** GIS-C9 (value at known coord matches source within rounding). |
| **dependencies** | rasterio, GDAL. |
| **failure_modes** | File missing; coord outside raster extent; nodata at point. |

---

## Group F — Visualization (P1)

### `choropleth_map`, `chart`, `animate_layer`, `visualize_3d`

(Q1 plus Q5/Q6 — output must render in the Leaflet / Chart.js / OSMBuildings frontend.)

---

## Group G — Annotations (P1)

### `add_annotation`, `classify_landcover`, `get_annotations`, `export_annotations`

---

## Group H — Chat / NL routing (P0)

### `ChatSession.process_message`

| Field | Value |
|---|---|
| **verb / object** | route / NL query → tool call(s) |
| **inputs** | NL query, map context (bounds, zoom), session state. |
| **outputs** | SSE stream of `tool_start`, `tool_result`, `layer_add`, `message`, `error` events. **Domain criteria:** LLM-C1 (tool selection accuracy on reference set), LLM-C2 (param grounding), LLM-C3 (chain coherence), LLM-C5 (token budget hygiene). |
| **dependencies** | Anthropic / Gemini / OpenAI; every tool handler. |
| **failure_modes** | Provider quota exceeded; provider unreachable; thinking-budget swallows output (Gemini 2.5 — fixed 2026-05-02); token-budget exhaustion mid-session. |
| **criticality** | P0. |

### `validate_plan_chain`, `resolve_step_references`

(Plan-mode chain validator. Q1 sub-axis: LLM-C3.)

---

## Group I — Collaboration (P2)

### REST: `POST /api/collab/create`, `GET /api/collab/<id>/info`, `/resume`, `/export`

### WebSocket events: `join_collab`, `leave_collab`, `cursor_move`, `layer_remove`, `layer_style`

(Q3 + Q1; real-time invariants — cursor throttle ≤100ms, layer history capped, transient SIDs scrubbed on persistence.)

---

## Group J — Auth + health (P0)

### `POST /api/register`, `GET /api/me`, `GET /api/health`, `GET /api/health/ready`

---

## Group K — Observability + admin (P2)

### `GET /metrics`, `GET /api/usage`, `GET /api/dashboard`

---

## Group L — Security boundaries

Not capabilities themselves but enforcement points the catalog must
record so derivation rule R9 generates the right tests:

- CSRF: enforced via Flask-WTF on every state-mutating endpoint
  except the explicit exemptions in `app.py`.
- CSP: nonce-based script-src; host allowlist; `strict-origin-when-cross-origin` referrer.
- Auth: `require_api_token` decorator gates per-user data.
- Overpass-QL: `validate_bbox` + key/value sanitization at boundary.

---

## Coverage of catalog by current code

This catalog enumerates ~95 capabilities. Every entry must have at
least one source-code reference. The reference column is omitted from
this draft for brevity but **must be filled before approval** —
governance rule G1 requires it.

## Next steps

1. Fill in the omitted-for-brevity rows above (each with inputs / outputs / domain criteria / surfaces / failure modes).
2. Add a code-path reference column to every row.
3. Run derivation rules ([`framework/06`](../../../cognitive-skill-agent/eval-framework/docs/06-test-derivation-rules.md)) → emit `test-inventory.yaml`.
4. Reconcile with current `tests/` tree → identify orphans.
5. Fill the matrix → identify gaps.
