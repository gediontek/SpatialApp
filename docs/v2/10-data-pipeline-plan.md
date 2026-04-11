# Plan 10: Data Pipeline -- Import, Transform, Export

**Objective**: Add a chainable transform pipeline to SpatialApp so users can express multi-step data workflows in natural language ("Import CSV, reproject to UTM, clip to Chicago, calculate area, export as GeoPackage") and have them execute sequentially. Includes 5 new transform tools, batch spatial operations, import validation, and format auto-detection.

**Scope**: ~350 lines of Python (5 transform handlers + pipeline/validation logic), ~50 lines tool schemas, ~100 lines tests. 2 focused days.

**Key files touched**:
- `nl_gis/handlers/analysis.py` -- add `handle_clip_to_bbox`, `handle_sample_points`, `handle_generalize` handlers
- `nl_gis/handlers/layers.py` -- add `handle_import_auto`, `handle_export_gpkg` handlers; add validation to existing import handlers
- `nl_gis/handlers/__init__.py` -- register new tools in `dispatch_tool()`, update `LAYER_PRODUCING_TOOLS`
- `nl_gis/tools.py` -- add 7 tool schemas (5 transform + batch_spatial_query + import_auto)
- `nl_gis/chat.py` -- add pipeline chaining patterns to `SYSTEM_PROMPT`
- `nl_gis/validation.py` -- **new**: import validation module (geometry validity, CRS detection, duplicates, null checks)
- `config.py` -- add `PIPELINE_MAX_STEPS`, `IMPORT_MAX_FEATURES`
- `tests/test_pipeline.py` -- **new**: 5 end-to-end pipeline tests

**Prerequisite**: None (independent track). Existing tools provide the foundation: `import_csv`, `import_wkt`, `import_kml`, `import_geoparquet`, `import_layer` (GeoJSON/Shapefile), `export_layer`, `export_geoparquet`, `reproject_layer`, `dissolve`, `clip`, `clean_layer`, `repair_topology`, `detect_crs`.

---

## Milestone 1: Transform Tools

### Epic 1.1: clip_to_bbox Tool

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.1.1 | Implement `handle_clip_to_bbox(params, layer_store)` in `nl_gis/handlers/analysis.py`. Params: `{"layer_name": str, "bbox": [south, west, north, east]}` or `{"layer_name": str, "location": str}` (geocode to get bbox). Create a Shapely box from the bbox. For each feature in the layer (via `_get_layer_snapshot()`), compute intersection with the bbox polygon using `shapely.intersection()`. Keep features that have non-empty intersection. Return a new GeoJSON FeatureCollection. Follow the pattern of `handle_clip()` which clips layer A to the boundary of layer B. | `handle_clip_to_bbox({"layer_name": "parks", "bbox": [41.8, -87.7, 41.9, -87.6]})` returns only features within the bbox. Features partially inside are clipped to the bbox boundary. Empty result returns `{"error": "No features found within bounding box"}`. | M |
| T1.1.2 | Add tool schema for `clip_to_bbox` in `tools.py`. Properties: `layer_name` (required), `bbox` (array of 4 numbers), `location` (string -- geocoded to bbox). Description: "Clip a layer to a bounding box. Features outside are removed; features crossing the boundary are trimmed. Provide either bbox coordinates or a location name." | Schema validates bbox as 4-number array. Either `bbox` or `location` is sufficient. | S |
| T1.1.3 | Register in `dispatch_tool()`: `"clip_to_bbox": lambda p: handle_clip_to_bbox(p, layer_store)`. Add `"clip_to_bbox"` to `LAYER_PRODUCING_TOOLS`. | Dispatch works. Clipped layer appears on map. | XS |

### Epic 1.2: sample_points Tool

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.2.1 | Implement `handle_sample_points(params, layer_store)` in `analysis.py`. Params: `{"layer_name": str, "method": "random"|"systematic"|"stratified" (default "random"), "count": int (default 100), "attribute": str (optional, for stratified)}`. For polygon/multipolygon layers: `random` -- generate random points within the union of all polygons using rejection sampling (generate in bbox, keep if within polygon). `systematic` -- create a regular grid of points within the layer extent, keep those inside polygons. `stratified` -- sample `count / num_features` points per feature. Return a point layer with properties from the source feature. | `handle_sample_points({"layer_name": "parks", "method": "random", "count": 50})` returns 50 random points inside park polygons. `systematic` returns a grid. Points carry source feature properties. | L |
| T1.2.2 | Add tool schema for `sample_points` in `tools.py`. Properties: `layer_name` (required), `method` (enum: random/systematic/stratified, default random), `count` (integer, default 100), `attribute` (string, for stratified grouping). Description: "Generate sample points within polygon features. Use for spatial sampling, random point generation, or creating test datasets from polygon layers." | Schema with enum for method and default values. | S |
| T1.2.3 | Register in `dispatch_tool()`. Add to `LAYER_PRODUCING_TOOLS`. | Dispatch works. Points appear on map inside source polygons. | XS |

### Epic 1.3: generalize Tool

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.3.1 | Implement `handle_generalize(params, layer_store)` in `analysis.py`. Params: `{"layer_name": str, "tolerance": float (meters), "method": "douglas_peucker"|"visvalingam" (default "douglas_peucker"), "preserve_topology": bool (default true)}`. This extends the existing `handle_simplify()` (which already uses `shapely.simplify()`). Key difference: `generalize` converts tolerance from meters to degrees using the layer's centroid latitude (`tolerance_deg = tolerance_m / (111320 * cos(lat))`), supports Visvalingam via `shapely.simplify()` with `preserve_topology`, and reports vertex reduction statistics. Return the simplified layer + `{"original_vertices": int, "simplified_vertices": int, "reduction_pct": float}`. | `handle_generalize({"layer_name": "roads", "tolerance": 50})` simplifies geometries by ~50m. Reports "Reduced vertices from 12,345 to 3,456 (72% reduction)". Topology preserved by default. | M |
| T1.3.2 | Add tool schema for `generalize` in `tools.py`. Properties: `layer_name` (required), `tolerance` (number in meters, required), `method` (enum, default douglas_peucker), `preserve_topology` (boolean, default true). Description: "Generalize (simplify) geometries by a tolerance in meters. More user-friendly than 'simplify' -- specify tolerance in meters, get vertex reduction statistics. Use for reducing file size or improving rendering performance." | Schema distinguishes from existing `simplify` tool by accepting meters. | S |
| T1.3.3 | Register in `dispatch_tool()`. Add to `LAYER_PRODUCING_TOOLS`. | Dispatch works. Simplified layer displays correctly. | XS |

### Epic 1.4: GeoPackage Export

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.4.1 | Implement `handle_export_gpkg(params, layer_store)` in `nl_gis/handlers/layers.py`. Params: `{"layer_name": str, "filename": str (optional)}`. Use `geopandas.GeoDataFrame.to_file(path, driver="GPKG")` to write the layer as GeoPackage. Convert GeoJSON features to a GeoDataFrame (already a pattern used by `handle_export_layer` for shapefiles). Return base64-encoded file content for download, following the pattern of `handle_export_layer()`. | `handle_export_gpkg({"layer_name": "parks"})` returns `{"download": {"filename": "parks.gpkg", "data": "base64...", "mime_type": "application/geopackage+sqlite3"}}`. | M |
| T1.4.2 | Add tool schema for `export_gpkg` in `tools.py`. Properties: `layer_name` (required), `filename` (optional string). Description: "Export a layer as GeoPackage (.gpkg) format. GeoPackage supports multiple geometry types, CRS metadata, and large datasets better than Shapefile." | Schema follows `export_layer` pattern. | S |
| T1.4.3 | Register in `dispatch_tool()`: `"export_gpkg": lambda p: handle_export_gpkg(p, layer_store)`. | Dispatch works. Export produces valid .gpkg file. | XS |

---

## Milestone 2: Pipeline Mode (Multi-Step Chaining)

### Epic 2.1: System Prompt Pipeline Patterns

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.1.1 | Add `PIPELINE_MAX_STEPS` (default 10) to `config.py`. This limits how many tools the LLM can chain in a single user request to prevent runaway tool loops. | Config value accessible. Used as documentation for the system prompt (the actual enforcement is already in `ChatSession._tool_loop()` via `MAX_TOOL_ROUNDS`). | XS |
| T2.1.2 | Add a "Pipeline patterns:" section to `SYSTEM_PROMPT` in `nl_gis/chat.py`. Document 5 multi-step pipeline examples that combine import + transform + analyze + export. Examples: (1) "Import CSV, reproject to UTM, clip to Chicago, calculate area, export as GeoPackage" -> `import_csv` -> `reproject_layer` -> `clip_to_bbox(location="Chicago")` -> `calculate_area` -> `export_gpkg`. (2) "Clean and simplify the buildings layer for export" -> `clean_layer` -> `generalize(tolerance=20)` -> `export_layer`. (3) "Sample 100 random points from parks and find nearest restaurants" -> `sample_points(layer="parks", count=100)` -> `closest_facility` per point. (4) "Import GeoJSON, validate, repair, dissolve by type" -> `import_layer` -> `validate_topology` -> `repair_topology` -> `dissolve(by="type")`. (5) "Import KML, clip to study area, calculate statistics" -> `import_kml` -> `clip_to_bbox` -> `attribute_statistics`. | System prompt includes 5 pipeline patterns. Claude chains tools correctly for multi-step NL queries in testing. | M |
| T2.1.3 | Add tool descriptions for `clip_to_bbox`, `sample_points`, `generalize`, `export_gpkg` to the appropriate sections of `SYSTEM_PROMPT`. Integrate under existing "Data import/export:" and "Geometry operations:" headings. | New tools listed in system prompt. No section duplication. | S |

### Epic 2.2: Pipeline Execution Verification

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.2.1 | Verify that the existing `ChatSession._tool_loop()` in `nl_gis/chat.py` correctly handles sequential multi-tool execution where each tool's output (especially `layer_name`) feeds into the next tool's input. Test with a 4-step pipeline: `import_csv` -> `reproject_layer` -> `clip_to_bbox` -> `export_gpkg`. Confirm the LLM passes the correct `layer_name` from each step's output to the next step's input. If the loop has issues, fix them. | 4-step pipeline executes: import produces layer "csv_import_xxx", reproject uses that name, clip uses the reprojected name, export uses the clipped name. All intermediate layers are in `layer_store`. | M |
| T2.2.2 | Add a `pipeline_summary` field to the final message event when 3+ tools are chained in a single user request. In `ChatSession.process_message()`, after the tool loop completes, if `tool_count >= 3`, append a summary: `{"pipeline_summary": {"steps": int, "tools_used": [str], "input_layer": str, "output_layer": str}}`. | Pipeline of 4 steps includes `pipeline_summary` in the final SSE message event. Frontend can display "Pipeline completed: 4 steps (import_csv -> reproject_layer -> clip_to_bbox -> export_gpkg)". | S |

---

## Milestone 3: Batch Operations

### Epic 3.1: batch_spatial_query Tool

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T3.1.1 | Implement `handle_batch_spatial_query(params, layer_store)` in `analysis.py`. Params: `{"source_layer": str, "target_layer": str, "predicate": "contains"|"intersects"|"within", "aggregate": "count"|"sum"|"mean" (optional), "aggregate_attribute": str (optional)}`. For each feature in `source_layer`, run a spatial query against `target_layer` using the specified predicate. Attach results as properties: `_matched_count`, and if `aggregate` is specified, `_aggregate_value`. Use `_build_spatial_index()` on target features for O(n log n) performance instead of O(n^2). Return the source layer enriched with spatial join results. | `handle_batch_spatial_query({"source_layer": "neighborhoods", "target_layer": "restaurants", "predicate": "contains", "aggregate": "count"})` returns neighborhoods with `_matched_count` = number of restaurants inside each. | L |
| T3.1.2 | Add tool schema for `batch_spatial_query` in `tools.py`. Properties: `source_layer` (required), `target_layer` (required), `predicate` (enum, required), `aggregate` (enum, optional), `aggregate_attribute` (string, optional). Description: "For each feature in the source layer, find matching features in the target layer. Use for 'count restaurants per neighborhood', 'total population per district', 'which zones contain schools'." | Schema clearly distinguishes from single `spatial_query` tool. | S |
| T3.1.3 | Register in `dispatch_tool()`. Add to `LAYER_PRODUCING_TOOLS`. | Dispatch works. Enriched source layer displays on map with new properties. | XS |

---

## Milestone 4: Data Validation on Import

### Epic 4.1: Validation Module

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.1.1 | Create `nl_gis/validation.py` with a `validate_geojson(geojson, auto_repair=True)` function. Checks: (1) valid GeoJSON structure (type, features array), (2) each feature has geometry and properties, (3) geometry validity via `shapely.validation.explain_validity()`, (4) null/empty geometry detection, (5) duplicate feature detection (by geometry hash), (6) CRS detection via `detect_crs` logic from `handle_detect_crs()` in `analysis.py`. Returns `{"valid": bool, "warnings": [str], "errors": [str], "stats": {"total": int, "valid_geom": int, "invalid_geom": int, "null_geom": int, "duplicates": int}, "repaired_geojson": geojson_or_None}`. If `auto_repair=True`, apply `make_valid()` to invalid geometries and remove null geometries. | `validate_geojson(geojson_with_invalid_polygon, auto_repair=True)` returns `valid=True` with warnings about repaired geometries and a `repaired_geojson` with fixed data. `validate_geojson(totally_broken)` returns `valid=False` with errors. | L |
| T4.1.2 | Wire `validate_geojson()` into existing import handlers. In `handle_import_layer()` in `layers.py`, after parsing the GeoJSON, call `validate_geojson(geojson)`. If invalid and unrepairable, return `{"error": "..."}`. If repaired, use `repaired_geojson` and include warnings in the response. Apply the same pattern to `handle_import_csv()`, `handle_import_wkt()`, `handle_import_kml()`. | All import handlers validate on ingest. Invalid but repairable data is auto-fixed with warnings. Truly invalid data is rejected with specific error messages. | M |
| T4.1.3 | Add `IMPORT_MAX_FEATURES` (default 10000) to `config.py`. In `validate_geojson()`, if feature count exceeds this limit, truncate and add a warning. This prevents memory issues from huge imports. | Importing a 50,000-feature file truncates to 10,000 with warning "Truncated from 50,000 to 10,000 features (limit: IMPORT_MAX_FEATURES)". | S |

### Epic 4.2: Format Auto-Detection

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.2.1 | Implement `handle_import_auto(params, layer_store)` in `layers.py`. Params: `{"data": str (raw content or base64), "layer_name": str (optional)}`. Auto-detect format by inspecting content: (1) starts with `{` or `[` -> try JSON parse -> if has `"type": "FeatureCollection"` -> GeoJSON via `handle_import_layer()`. (2) Starts with `<?xml` or `<kml` -> KML via `handle_import_kml()`. (3) Contains comma-separated values with lat/lon-like headers -> CSV via `handle_import_csv()` (scan first line for lat/lon/latitude/longitude column names). (4) Starts with `PAR1` magic bytes (base64 decoded) -> GeoParquet via `handle_import_geoparquet()`. (5) Starts with `PK` (zip magic) -> Shapefile via `handle_import_layer()`. (6) Starts with `POLYGON`, `POINT`, `LINESTRING`, `MULTIPOLYGON`, `GEOMETRYCOLLECTION` -> WKT via `handle_import_wkt()`. Return result from the delegated handler. | `handle_import_auto({"data": '{"type":"FeatureCollection",...}'})` delegates to GeoJSON. `handle_import_auto({"data": "name,lat,lon\nA,40,-74"})` delegates to CSV. Unrecognized format returns `{"error": "Could not auto-detect format. Supported: GeoJSON, CSV, KML, WKT, Shapefile, GeoParquet."}`. | L |
| T4.2.2 | Add tool schema for `import_auto` in `tools.py`. Properties: `data` (string, required), `layer_name` (string, optional). Description: "Import spatial data with automatic format detection. Supports GeoJSON, CSV (with lat/lon columns), KML, WKT, Shapefile (zipped), and GeoParquet (base64). Use when the user provides data without specifying the format." | Schema is minimal -- the tool does the format detection work. | S |
| T4.2.3 | Register in `dispatch_tool()`: `"import_auto": lambda p: handle_import_auto(p, layer_store)`. Add to `LAYER_PRODUCING_TOOLS`. | Dispatch works for all 6 supported formats. | XS |

---

## Milestone 5: End-to-End Pipeline Tests

### Epic 5.1: Pipeline Integration Tests

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T5.1.1 | Create `tests/test_pipeline.py`. Pipeline 1 (CSV -> reproject -> clip -> area -> export): Import CSV with lat/lon columns -> `handle_import_csv()`. Reproject to UTM -> `handle_reproject_layer()`. Clip to bbox -> `handle_clip_to_bbox()`. Calculate area -> `handle_calculate_area()`. Export as GeoPackage -> `handle_export_gpkg()`. Assert each step produces valid output and the final export is a valid .gpkg file. | Pipeline 1 test passes. Each intermediate layer is in `layer_store`. Final export is decodable base64 GeoPackage. | M |
| T5.1.2 | Pipeline 2 (GeoJSON -> validate -> repair -> dissolve -> export): Import GeoJSON with intentionally invalid geometries -> `handle_import_layer()` (with validation). Repair -> `handle_repair_topology()`. Dissolve by attribute -> `handle_dissolve()`. Export as shapefile -> `handle_export_layer()`. Assert invalid geometries are repaired, dissolved output has fewer features. | Pipeline 2 test passes. Validation catches and repairs invalid geoms. Dissolve reduces feature count. | M |
| T5.1.3 | Pipeline 3 (Import -> sample -> spatial join): Import polygon layer. Generate 50 random sample points -> `handle_sample_points()`. Run batch spatial query -> `handle_batch_spatial_query()` to count points per polygon. Assert point count per polygon sums to 50. | Pipeline 3 test passes. Point counts are correct and sum to total. | M |
| T5.1.4 | Pipeline 4 (KML -> clean -> generalize -> export): Import KML data -> `handle_import_kml()`. Clean layer -> `handle_clean_layer()`. Generalize at 100m tolerance -> `handle_generalize()`. Export as GeoJSON -> `handle_export_layer()`. Assert vertex count decreases after generalization. | Pipeline 4 test passes. Vertex reduction is measurable and reported. | M |
| T5.1.5 | Pipeline 5 (Auto-detect -> validate -> analyze): Use `handle_import_auto()` with CSV data. Validate (auto via import). Compute attribute statistics -> `handle_attribute_statistics()`. Assert format was correctly detected as CSV and statistics are computed. | Pipeline 5 test passes. Format auto-detection correct. Stats computed. | S |

### Epic 5.2: Unit Tests for New Tools

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T5.2.1 | Unit tests for `validate_geojson()` in `tests/test_pipeline.py`: valid FeatureCollection, invalid geometry (self-intersecting polygon), null geometry, duplicate features, empty collection, non-GeoJSON input. Test both `auto_repair=True` and `auto_repair=False`. | 8 test cases covering all validation checks. Auto-repair fixes self-intersections. | M |
| T5.2.2 | Unit tests for `handle_import_auto()`: test each of the 6 format detection paths (GeoJSON, CSV, KML, WKT, Shapefile zip, GeoParquet base64). Test unrecognized format error. | 7 test cases, one per format + error case. | M |
| T5.2.3 | Unit tests for `handle_clip_to_bbox()`: features fully inside, fully outside, partially overlapping bbox. Test with location string (requires geocode mock). | 4 test cases. Partial clip produces trimmed geometry. | S |
| T5.2.4 | Unit tests for `handle_sample_points()`: random sampling produces correct count, systematic produces grid pattern, stratified distributes across features. Test with empty layer (error). | 4 test cases. Point counts match requested `count`. | S |
| T5.2.5 | Unit tests for `handle_batch_spatial_query()`: count restaurants per neighborhood (mock data), verify spatial index is used (not O(n^2)), test with empty target layer. | 3 test cases. Counts are correct. Performance is subquadratic. | S |

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM fails to chain tools correctly in pipeline | User gets partial results or wrong tool order | Explicit pipeline patterns in SYSTEM_PROMPT with exact tool chains. Test with eval queries. The existing `plan_mode` (in `blueprints/chat.py`) can preview the chain before execution. |
| `validate_geojson()` rejects valid but unusual GeoJSON | Users cannot import their data | Be permissive: repair rather than reject. Only truly unparseable structures return errors. Log all rejections for analysis. |
| `handle_sample_points` rejection sampling is slow for thin polygons | Timeout on narrow/elongated polygons | Cap rejection sampling iterations at `count * 100`. If insufficient points generated, fall back to centroid sampling within individual features. Return partial results with warning. |
| `batch_spatial_query` O(n*m) despite spatial index | Slow for large layers | Use `STRtree` from `_build_spatial_index()` (already exists in `__init__.py`). Pre-filter candidates with `tree.query()` before exact predicate check. Cap at `Config.MAX_FEATURES_PER_LAYER` features per layer. |
| GeoPackage export fails (missing fiona/GDAL driver) | Export tool returns error | Wrap in try/except. If `GPKG` driver unavailable, fall back to GeoJSON export with warning: "GeoPackage export requires GDAL. Exporting as GeoJSON instead." Check driver availability in `_list_drivers()` at import time. |
| Format auto-detection misclassifies input | Wrong import handler called, data corrupted | Detection order matters: check structured formats first (JSON, XML), then delimited (CSV), then binary (Parquet, Shapefile), then text (WKT). If detected handler fails, try next candidate before erroring. |

## Output Artifacts

- `nl_gis/handlers/analysis.py` -- 3 new handlers: `handle_clip_to_bbox`, `handle_sample_points`, `handle_generalize` (~120 lines)
- `nl_gis/handlers/layers.py` -- 2 new handlers: `handle_import_auto`, `handle_export_gpkg` (~80 lines)
- `nl_gis/validation.py` -- **new**: `validate_geojson()` + helpers (~100 lines)
- `nl_gis/tools.py` -- 7 new tool schemas (~100 lines)
- `nl_gis/chat.py` -- pipeline patterns in SYSTEM_PROMPT (~30 lines)
- `nl_gis/handlers/__init__.py` -- imports + dispatch entries (~20 lines)
- `config.py` -- 2 new config vars (~5 lines)
- `tests/test_pipeline.py` -- **new**: 5 pipeline tests + 26 unit tests (~250 lines)
