# Plan 8: Raster Analysis

**Objective**: Add raster analysis capabilities to SpatialApp so users can query elevation, compute terrain derivatives, and visualize raster data through natural language. The app currently handles vector data only, despite `rasterio>=1.3.5` being in `requirements.txt` and `sample_rasters/` containing 5 test TIFs.

**Scope**: ~300 lines of Python (handler + tool schemas), ~50 lines JS (tile overlay), ~100 lines tests. 2 focused days.

**Key files touched**:
- `nl_gis/handlers/raster.py` -- **new**: 5 raster tool handler functions
- `nl_gis/handlers/__init__.py` -- import raster handlers, register in `dispatch_tool()`, add to `LAYER_PRODUCING_TOOLS`
- `nl_gis/tools.py` -- add 5 raster tool schemas to `get_tool_definitions()`
- `nl_gis/chat.py` -- add raster tool descriptions to `SYSTEM_PROMPT`
- `static/js/layers.js` -- add `addRasterOverlay()` for tile image overlay on Leaflet
- `config.py` -- add `RASTER_DIR`, `MAX_RASTER_SIZE_MB` settings
- `tests/test_raster.py` -- **new**: unit tests for all 5 raster tools

**Prerequisite**: None (independent track). `rasterio>=1.3.5` is already in `requirements.txt`. `sample_rasters/` contains: `chicago_sp27.tif`, `chicago_utm.tif`, `geog_wgs84.tif`, `sentinel_rgb.tif`, `usgs_ortho.tif`.

---

## Milestone 1: Core Raster Tools (5 Handlers)

### Epic 1.1: Raster Infrastructure and Configuration

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.1.1 | Add `RASTER_DIR` and `MAX_RASTER_SIZE_MB` to `config.py` `Config` class. `RASTER_DIR` defaults to `os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sample_rasters')`. `MAX_RASTER_SIZE_MB` defaults to 500. | `Config.RASTER_DIR` resolves to `sample_rasters/` and the directory exists. `Config.MAX_RASTER_SIZE_MB` is configurable via env var. | XS |
| T1.1.2 | Create `nl_gis/handlers/raster.py` with module docstring, imports (`rasterio`, `numpy`, `pyproj`), and a `_open_raster(name_or_path)` helper function. The helper: (1) checks if the file exists under `Config.RASTER_DIR`, (2) checks file size against `MAX_RASTER_SIZE_MB`, (3) opens with `rasterio.open()` and returns the dataset handle. Returns `(dataset, None)` on success, `(None, error_string)` on failure. | `_open_raster("chicago_utm.tif")` opens successfully. `_open_raster("nonexistent.tif")` returns an error string. Files outside `RASTER_DIR` are rejected (path traversal prevention). | S |
| T1.1.3 | Add a `_list_available_rasters()` helper in `raster.py` that returns a list of `{"name": str, "size_mb": float}` dicts for all `.tif`/`.tiff` files in `Config.RASTER_DIR`. Used by `raster_info` to let users discover available rasters. | `_list_available_rasters()` returns 5 entries for the sample_rasters directory. | XS |

### Epic 1.2: raster_info Tool

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.2.1 | Implement `handle_raster_info(params)` in `raster.py`. Params: `{"raster": str (filename)}`. If no raster specified, list available rasters via `_list_available_rasters()`. If specified, open with `_open_raster()` and return: CRS (EPSG code), resolution (pixel size in CRS units), dimensions (width x height), bounds (in WGS84 lat/lon via `pyproj.Transformer`), band count, data type, nodata value. | `handle_raster_info({"raster": "chicago_utm.tif"})` returns dict with `crs`, `resolution`, `bounds`, `width`, `height`, `bands`, `dtype`, `nodata`. `handle_raster_info({})` returns list of available rasters. | M |
| T1.2.2 | Add tool schema for `raster_info` in `get_tool_definitions()` in `nl_gis/tools.py`. Follow existing pattern (name, description, input_schema with JSON Schema). Description: "Get metadata about a raster file (CRS, resolution, bounds, bands). Call with no arguments to list available rasters." Single optional property: `raster` (string). | Schema passes JSON Schema validation. Description matches the pattern of existing tools like `describe_layer`. | S |
| T1.2.3 | Register `handle_raster_info` in `dispatch_tool()` in `nl_gis/handlers/__init__.py`. Add import from `nl_gis.handlers.raster`. Add entry: `"raster_info": handle_raster_info`. | `dispatch_tool("raster_info", {"raster": "chicago_utm.tif"})` returns valid metadata dict. | XS |

### Epic 1.3: raster_value Tool (Point Query)

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.3.1 | Implement `handle_raster_value(params)` in `raster.py`. Params: `{"raster": str, "lat": float, "lon": float}` or `{"raster": str, "location": str}`. Resolve point using `_resolve_point()` from `nl_gis/handlers/__init__.py`. Transform WGS84 coords to the raster's CRS using `pyproj.Transformer.from_crs("EPSG:4326", dataset.crs)`. Sample pixel value with `dataset.sample([(x, y)])`. Return `{"values": [v1, ...], "bands": n, "lat": lat, "lon": lon, "pixel_row": row, "pixel_col": col}`. Handle out-of-bounds with a clear error. | `handle_raster_value({"raster": "geog_wgs84.tif", "lat": 40.0, "lon": -90.0})` returns numeric values. Out-of-bounds coords return `{"error": "Point is outside raster extent"}`. | M |
| T1.3.2 | Add tool schema for `raster_value` in `tools.py`. Properties: `raster` (string, required), `lat` (number), `lon` (number), `location` (string). Description: "Query the raster value at a specific point. Use for 'What's the elevation at X?' queries. Provide lat/lon coordinates or a location name." | Schema has required `["raster"]` and at least lat/lon or location. | S |
| T1.3.3 | Register in `dispatch_tool()`: `"raster_value": handle_raster_value`. | Dispatch works end-to-end. | XS |

### Epic 1.4: raster_statistics Tool

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.4.1 | Implement `handle_raster_statistics(params, layer_store)` in `raster.py`. Params: `{"raster": str, "band": int (default 1), "layer_name": str (optional)}`. Without `layer_name`: compute global stats (min, max, mean, std, median, nodata_count) using `numpy` on the full band. With `layer_name`: for each polygon feature in the layer, mask raster with the polygon using `rasterio.mask.mask()`, compute per-feature stats, attach as properties. Return either global stats dict or a new GeoJSON layer with stats attributes. | Global stats: `handle_raster_statistics({"raster": "chicago_utm.tif"})` returns `{"min": ..., "max": ..., "mean": ..., "std": ..., "median": ...}`. Per-feature: when `layer_name` is provided, returns a GeoJSON FeatureCollection with `raster_min`, `raster_max`, `raster_mean` properties per feature. | L |
| T1.4.2 | Add tool schema for `raster_statistics` in `tools.py`. Properties: `raster` (required), `band` (integer, default 1), `layer_name` (optional -- layer to compute zonal stats for). Description: "Compute statistics (min/max/mean/std) for a raster. Optionally compute zonal statistics per polygon in a layer." | Schema correctly defines optional vs required. | S |
| T1.4.3 | Register in `dispatch_tool()`: `"raster_statistics": lambda p: handle_raster_statistics(p, layer_store)`. Follow the `lambda p: handler(p, layer_store)` pattern used by `handle_calculate_area` and other layer-aware tools. | Dispatch works with layer_store forwarded. | XS |

### Epic 1.5: raster_profile Tool

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.5.1 | Implement `handle_raster_profile(params)` in `raster.py`. Params: `{"raster": str, "from_point": {lat, lon}, "to_point": {lat, lon}, "num_samples": int (default 100)}` or location names via `from_location`/`to_location`. Resolve points using `_resolve_point_from_object()`. Interpolate `num_samples` evenly spaced points along the line. Sample raster value at each point. Return: `{"profile": [{"distance_m": float, "value": float, "lat": float, "lon": float}, ...], "min_value": float, "max_value": float, "total_distance_m": float}`. Also return a GeoJSON LineString layer for visualization. | Profile of 100 samples between two points returns distance-value pairs. Distances are geodesic (using `geodesic_distance` from `geo_utils`). | M |
| T1.5.2 | Add tool schema for `raster_profile` in `tools.py`. Properties: `raster` (required), `from_point`/`to_point` (objects with lat/lon), `from_location`/`to_location` (strings), `num_samples` (integer, default 100). Description: "Extract an elevation/value profile along a line between two points. Returns sampled values at regular intervals." | Schema follows the `from_point`/`to_point` pattern from `measure_distance` tool. | S |
| T1.5.3 | Register in `dispatch_tool()`: `"raster_profile": handle_raster_profile`. Add `"raster_profile"` to `LAYER_PRODUCING_TOOLS` set (since it returns a LineString layer). | Dispatch works. Layer is produced and visible on map. | XS |

### Epic 1.6: raster_classify Tool

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.6.1 | Implement `handle_raster_classify(params, layer_store)` in `raster.py`. Params: `{"raster": str, "breaks": [float] (required), "labels": [str] (optional), "band": int (default 1)}`. Reclassify raster values into categories based on breakpoints. Example: `breaks=[0, 100, 500, 1000]` creates classes `<0, 0-100, 100-500, 500-1000, >1000`. Return a GeoJSON FeatureCollection of polygons (one per contiguous classified region) using `rasterio.features.shapes()` to vectorize the classified raster. Each feature has a `class` and optional `label` property. | `handle_raster_classify({"raster": "geog_wgs84.tif", "breaks": [0, 100, 500]})` returns a FeatureCollection with polygon features, each tagged with its class index and label. | L |
| T1.6.2 | Add tool schema for `raster_classify` in `tools.py`. Properties: `raster` (required), `breaks` (array of numbers, required), `labels` (array of strings, optional), `band` (integer, default 1). Description: "Reclassify raster values into categories using breakpoints. Returns a polygon layer with classified regions." | Schema validates that `breaks` is a numeric array. | S |
| T1.6.3 | Register in `dispatch_tool()`: `"raster_classify": lambda p: handle_raster_classify(p, layer_store)`. Add `"raster_classify"` to `LAYER_PRODUCING_TOOLS`. | Dispatch works. Classified polygons appear on map. | XS |

---

## Milestone 2: Cross-Tool Integration

### Epic 2.1: Raster + Vector Tool Chaining

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.1.1 | Add raster tool descriptions to `SYSTEM_PROMPT` in `nl_gis/chat.py`. Add a "Raster analysis:" section after the existing "Spatial analysis:" section. Include: `raster_info`, `raster_value`, `raster_statistics`, `raster_profile`, `raster_classify`. Add 5 tool-chaining patterns for raster+vector combinations to the `TOOL CHAINING PATTERNS` section. Examples: "What's the elevation at the Eiffel Tower?" -> `geocode("Eiffel Tower")` -> `raster_value(raster, lat, lon)`; "Which parks are above 500m?" -> `fetch_osm(parks)` -> `raster_statistics(raster, layer_name=parks)` -> `filter_layer(raster_mean > 500)`. | System prompt includes raster tool descriptions. 5 chaining patterns documented. Claude can select raster tools from NL queries in testing. | M |
| T2.1.2 | Ensure `handle_raster_statistics` with `layer_name` works with layers in `layer_store` that were created by other tools (e.g., `fetch_osm`, `import_csv`). The handler must use `_get_layer_snapshot(layer_store, layer_name)` to read features thread-safely, transform each polygon geometry to the raster's CRS before masking, and handle both Polygon and MultiPolygon geometries. | Integration test: create a layer via `handle_fetch_osm`, then pass its name to `handle_raster_statistics`. Stats are computed per-feature. | M |

### Epic 2.2: DEM Analysis (Slope, Aspect, Hillshade)

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.2.1 | Add a `_compute_dem_derivative(dataset, derivative_type)` helper in `raster.py`. Accepts a rasterio dataset and one of `"slope"`, `"aspect"`, `"hillshade"`. Uses `numpy.gradient()` on the elevation band to compute partial derivatives (dx, dy). Slope = `arctan(sqrt(dx^2 + dy^2))` in degrees. Aspect = `arctan2(-dy, dx)` converted to 0-360 compass bearing. Hillshade = standard algorithm with azimuth=315, altitude=45. Returns a 2D numpy array. | `_compute_dem_derivative(ds, "slope")` returns array of slope values in degrees (0-90). Hillshade returns 0-255 shading values. | M |
| T2.2.2 | Extend `handle_raster_statistics` to accept a `derivative` parameter: `{"raster": str, "derivative": "slope"|"aspect"|"hillshade", ...}`. When set, compute the derivative first using `_compute_dem_derivative()`, then run statistics on the derived array instead of the raw band. | `handle_raster_statistics({"raster": "chicago_utm.tif", "derivative": "slope"})` returns slope statistics (mean slope, max slope, etc.). | S |

---

## Milestone 3: Raster Visualization

### Epic 3.1: Tile Overlay for Leaflet

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T3.1.1 | Add a `/api/raster/tile/<raster>/<int:z>/<int:x>/<int:y>.png` route in a new `blueprints/raster.py` blueprint. The route: opens the raster, computes the tile bounds from z/x/y (using standard Web Mercator tile math), reads the windowed data with `rasterio.windows.from_bounds()`, resamples to 256x256, applies a color ramp (single band) or direct RGB (multi-band), returns as PNG using `PIL.Image` or `matplotlib`. Register the blueprint in `app.py` `create_app()`. | `GET /api/raster/tile/geog_wgs84.tif/8/64/95.png` returns a 256x256 PNG image. Invalid tile coords return 404. | L |
| T3.1.2 | Add `addRasterOverlay(name, rasterFile)` to `LayerManager` in `static/js/layers.js`. Creates a `L.tileLayer('/api/raster/tile/{rasterFile}/{z}/{x}/{y}.png')` and adds it to the map. Stores it in the `layers` dict with `type: 'raster'`. | `LayerManager.addRasterOverlay("elevation", "chicago_utm.tif")` renders tiles on the map. Layer appears in the sidebar with toggle/remove controls. | M |
| T3.1.3 | Update the `layer_add` SSE event handling in `static/js/chat.js` to detect raster layers (by checking for a `raster_overlay` key in the event data) and call `LayerManager.addRasterOverlay()` instead of `addLayer()`. | When a raster tool returns `{"raster_overlay": "chicago_utm.tif", "layer_name": "elevation"}`, the frontend renders it as a tile overlay. | S |

---

## Milestone 4: NL Integration and Evaluation

### Epic 4.1: Eval Queries

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.1.1 | Add 10 raster-specific eval queries to the eval suite (in `tests/eval/queries/` or equivalent). Queries cover: (1) "What rasters are available?", (2) "What's the elevation at 41.88, -87.63?", (3) "Show me info about chicago_utm.tif", (4) "What's the average elevation in this area?" (with polygon layer), (5) "Draw an elevation profile from downtown Chicago to O'Hare airport", (6) "Classify the terrain into low/medium/high elevation", (7) "What's the slope around the city center?", (8) "Find flat areas (slope < 5 degrees)", (9) "Show the terrain around Chicago", (10) "Which buildings are at highest elevation?" (cross-tool). | All 10 queries have expected tool chains. At least 8/10 produce correct tool selections when tested live. | M |
| T4.1.2 | Write unit tests in `tests/test_raster.py` covering: `_open_raster` (valid file, missing file, path traversal), `handle_raster_info` (with and without raster param), `handle_raster_value` (valid point, out-of-bounds), `handle_raster_statistics` (global stats, zonal stats mock), `handle_raster_profile` (two points), `handle_raster_classify` (basic breaks). Mock `rasterio.open()` for tests that don't need real files; use `sample_rasters/` files for integration tests. | `pytest tests/test_raster.py -v` passes with >= 15 test cases. Coverage of error paths (missing file, out-of-bounds, invalid params). | L |

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| `rasterio` import fails (missing GDAL) | Blocks all raster features | Wrap rasterio imports in try/except. Degrade gracefully: raster tools return `{"error": "rasterio not installed"}`. Add install check to `app.py` startup log. |
| Large raster files cause memory issues | OOM on tile rendering or stats | `MAX_RASTER_SIZE_MB` config. Use `rasterio.windows` for windowed reads. Never load full raster into memory for tile serving. |
| CRS transformation errors | Wrong point sampling | Always use `pyproj.Transformer.from_crs()` with `always_xy=True`. Validate raster CRS at open time. |
| Tile rendering performance | Slow map interaction | Cache rendered tiles (in-memory LRU or filesystem). Limit max zoom level to raster native resolution. |
| `rasterio.features.shapes()` produces too many polygons | `raster_classify` returns huge GeoJSON | Limit output to `Config.MAX_FEATURES_PER_LAYER`. Simplify geometries with tolerance if count exceeds threshold. |

## Output Artifacts

- `nl_gis/handlers/raster.py` -- 5 handler functions + helpers (~200 lines)
- `nl_gis/tools.py` -- 5 tool schemas added (~100 lines)
- `nl_gis/chat.py` -- raster section in SYSTEM_PROMPT (~20 lines)
- `nl_gis/handlers/__init__.py` -- import + dispatch registration (~15 lines)
- `blueprints/raster.py` -- tile serving route (~60 lines)
- `static/js/layers.js` -- `addRasterOverlay()` (~30 lines)
- `config.py` -- 2 new config vars (~5 lines)
- `tests/test_raster.py` -- 15+ test cases (~150 lines)
