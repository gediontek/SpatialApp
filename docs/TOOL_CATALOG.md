# SpatialApp Tool Catalog

82 tools available to the NL-to-GIS chat engine (verified at HEAD via `python -c "from nl_gis.tools import get_tool_definitions; print(len(get_tool_definitions()))"`). Claude/Gemini/OpenAI select and chain tools automatically based on user queries. The per-section counts below may lag the runtime registry — the registry is the source of truth.

---

## Geocoding & Navigation (6 tools)

### `geocode`
Convert a place name or address into coordinates.
- **Parameters:** `query` (required)
- **Output:** `{lat, lon, display_name, bbox}`
- **Example:** `"geocode downtown Chicago"` -> `{lat: 41.88, lon: -87.63, ...}`

### `reverse_geocode`
Convert coordinates into a human-readable address.
- **Parameters:** `lat` (required), `lon` (required)
- **Output:** `{display_name, address_components}`

### `batch_geocode`
Geocode a list of addresses into a point layer.
- **Parameters:** `addresses` (required, max 50), `layer_name`
- **Output:** GeoJSON FeatureCollection + layer_name, geocoded count, failed list

### `map_command`
Control map view: pan, zoom, fit bounds, change basemap.
- **Parameters:** `action` (required: pan, zoom, pan_and_zoom, fit_bounds, change_basemap), `lat`, `lon`, `zoom`, `bbox`, `basemap`
- **Output:** `{action, center, zoom}`

### `search_nearby`
Search for OSM features near a point within a radius.
- **Parameters:** `feature_type` (required), `lat`, `lon`, `location`, `radius_m` (default 500, max 50000), `osm_key`, `osm_value`
- **Output:** GeoJSON FeatureCollection layer

### `fetch_osm`
Fetch OpenStreetMap features within a bounding box or location.
- **Parameters:** `feature_type` (required), `category_name` (required), `bbox`, `location`, `osm_key`, `osm_value`
- **Output:** GeoJSON FeatureCollection layer

---

## Measurement & Analysis (6 tools)

### `calculate_area`
Calculate geodesic area of polygon features.
- **Parameters:** `layer_name` or `geometry`
- **Output:** `{total_area_sq_m, total_area_sq_km, total_area_acres, feature_count, per_feature}`

### `measure_distance`
Calculate geodesic distance between two points.
- **Parameters:** `from_point`/`from_location`, `to_point`/`to_location`
- **Output:** `{distance_m, distance_km, distance_mi}`

### `buffer`
Create buffer polygon around geometry or layer features.
- **Parameters:** `distance_m` (required, max 100000), `layer_name` or `geometry`
- **Output:** GeoJSON FeatureCollection layer + `area_sq_km`

### `spatial_query`
Find features matching a spatial predicate.
- **Parameters:** `source_layer` (required), `predicate` (required: intersects, contains, within, within_distance), `target_layer` or `target_geometry`, `distance_m`
- **Output:** GeoJSON FeatureCollection with matching features, `match_percentage`

### `aggregate`
Summarize features: count, area, or group by attribute.
- **Parameters:** `layer_name` (required), `operation` (required: count, area, group_by), `group_by`
- **Output:** `{count}` or `{total_area_sq_m}` or `{groups: [{value, count}]}`

### `filter_layer`
Filter features by attribute value.
- **Parameters:** `layer_name` (required), `attribute` (required), `operator` (required: equals, not_equals, contains, starts_with, greater_than, less_than, greater_equal, less_equal, between), `value` (required), `output_name` (required)
- **Output:** GeoJSON FeatureCollection layer with matching features

---

## Layer Management (5 tools)

### `show_layer`
Make a hidden layer visible.
- **Parameters:** `layer_name` (required)

### `hide_layer`
Hide a layer without deleting it.
- **Parameters:** `layer_name` (required)

### `remove_layer`
Permanently remove a layer.
- **Parameters:** `layer_name` (required)

### `highlight_features`
Highlight features matching an attribute value.
- **Parameters:** `layer_name` (required), `attribute` (required), `value` (required), `color`

### `style_layer`
Change visual style of a layer (color, weight, opacity).
- **Parameters:** `layer_name` (required), `color`, `fill_color`, `weight` (1-10), `fill_opacity` (0-1), `opacity` (0-1)

---

## Import & Export (9 tools)

### `import_layer`
Import inline GeoJSON as a named layer.
- **Parameters:** `geojson`, `layer_name` (required)

### `import_csv`
Import CSV data with lat/lon columns as a point layer.
- **Parameters:** `csv_data` (required), `lat_column` (default: "lat"), `lon_column` (default: "lon"), `layer_name`

### `import_wkt`
Import a WKT geometry string as a layer.
- **Parameters:** `wkt` (required), `layer_name`

### `import_kml`
Import KML data as a GeoJSON layer.
- **Parameters:** `kml_data` (required), `layer_name`

### `import_geoparquet`
Import GeoParquet (base64-encoded) as a layer.
- **Parameters:** `parquet_data` (required), `layer_name`

### `export_layer`
Export a layer as GeoJSON, Shapefile, or GeoPackage.
- **Parameters:** `layer_name` (required), `format` (default: geojson)

### `export_geoparquet`
Export a layer as GeoParquet (base64).
- **Parameters:** `layer_name` (required)

### `merge_layers`
Merge two layers into one (union or spatial join).
- **Parameters:** `layer_a` (required), `layer_b` (required), `output_name` (required), `operation` (union or spatial_join)

### `describe_layer`
Get summary statistics for a layer.
- **Parameters:** `layer_name` (required)
- **Output:** `{feature_count, geometry_types, bbox, attributes, sample_properties}`

---

## Overlay Operations (3 tools)

### `intersection`
Compute geometric intersection of two layers.
- **Parameters:** `layer_a` (required), `layer_b` (required), `output_name`
- **Output:** GeoJSON layer of overlapping area + `area_sq_km`

### `difference`
Subtract layer B from layer A.
- **Parameters:** `layer_a` (required), `layer_b` (required), `output_name`

### `symmetric_difference`
Compute areas in either layer but not both.
- **Parameters:** `layer_a` (required), `layer_b` (required), `output_name`

---

## Geometry Tools (10 tools)

### `convex_hull`
Smallest enclosing convex polygon of all features.
- **Parameters:** `layer_name` (required), `output_name`

### `centroid`
Extract center point of each feature.
- **Parameters:** `layer_name` (required), `output_name`

### `simplify`
Reduce vertex count while preserving shape.
- **Parameters:** `layer_name` (required), `tolerance`, `output_name`

### `bounding_box`
Create rectangular envelope from feature extent.
- **Parameters:** `layer_name` (required), `output_name`

### `dissolve`
Merge features by shared attribute value.
- **Parameters:** `layer_name` (required), `by` (required), `output_name`

### `clip`
Cut features to a mask layer boundary.
- **Parameters:** `clip_layer` (required), `mask_layer` (required), `output_name`

### `voronoi`
Generate Voronoi/Thiessen polygons from points.
- **Parameters:** `layer_name` (required), `output_name`

### `split_feature`
Split a polygon by a line.
- **Parameters:** `layer_name` (required), `feature_index` (required), `split_line` (required), `output_name`

### `merge_features`
Merge features by attribute value.
- **Parameters:** `layer_name` (required), `by` (required), `output_name`

### `extract_vertices`
Convert boundaries to a point layer of vertices.
- **Parameters:** `layer_name` (required), `output_name`

---

## Spatial Analysis (5 tools)

### `point_in_polygon`
Determine which polygon contains a point or point layer.
- **Parameters:** `polygon_layer` (required), `lat`/`lon` or `point_layer`, `output_name`

### `attribute_join`
Join tabular data to a spatial layer by shared key.
- **Parameters:** `layer_name` (required), `join_data` (required), `layer_key` (required), `data_key` (required), `output_name`

### `spatial_statistics`
Compute spatial clustering statistics (nearest neighbor, DBSCAN).
- **Parameters:** `layer_name` (required), `method`, `eps`, `min_samples`

### `hot_spot_analysis`
Getis-Ord Gi* hot/cold spot analysis.
- **Parameters:** `layer_name` (required), `attribute` (required), `output_name`
- **Output:** GeoJSON with `gi_z_score`, `gi_p_value`, `hotspot_class` per feature

### `interpolate`
Interpolate point values to contour surface.
- **Parameters:** `layer_name` (required), `attribute` (required), `method`, `resolution`, `contour_levels`, `output_name`

---

## Data Quality (5 tools)

### `detect_duplicates`
Find duplicate or near-duplicate features.
- **Parameters:** `layer_name` (required), `threshold_m`, `output_name`

### `clean_layer`
Remove null geometries, normalize properties.
- **Parameters:** `layer_name` (required), `output_name`

### `validate_topology`
Check geometry validity for all features.
- **Parameters:** `layer_name` (required)
- **Output:** `{valid_count, invalid_count, issues: [{index, reason}]}`

### `repair_topology`
Auto-repair invalid geometries.
- **Parameters:** `layer_name` (required), `output_name`

### `temporal_filter`
Filter features by date attribute within a range.
- **Parameters:** `layer_name` (required), `date_attribute` (required), `after`, `before`, `output_name`

---

## CRS & Projection (2 tools)

### `reproject_layer`
Add or change CRS metadata on a layer.
- **Parameters:** `layer_name` (required), `from_crs` (required), `to_crs`, `output_name`

### `detect_crs`
Heuristically detect coordinate reference system.
- **Parameters:** `layer_name` (required)

---

## Routing & Network (6 tools)

### `find_route`
Find route between locations via Valhalla.
- **Parameters:** `from_location`/`from_point`, `to_location`/`to_point`, `waypoints`, `profile` (auto, bicycle, pedestrian)
- **Output:** GeoJSON LineString + distance, time, maneuvers

### `isochrone`
Calculate reachable area within time or distance.
- **Parameters:** `location`/`lat`+`lon`, `time_minutes`, `distance_m`, `profile`

### `closest_facility`
Find nearest N features of a type.
- **Parameters:** `feature_type` (required), `lat`/`lon`/`location`, `count`, `max_radius_m`, `osm_key`, `osm_value`

### `optimize_route`
Optimize visiting order (traveling salesman).
- **Parameters:** `locations` (required, 3-20), `profile`

### `service_area`
Multi-facility reachability zones with gap analysis.
- **Parameters:** `facility_layer`/`facilities`, `time_minutes`/`distance_m`, `profile`, `output_name`, `show_gaps`

### `od_matrix`
Origin-destination cost matrix.
- **Parameters:** `origins` (required), `destinations` (required), `profile`

---

## Visualization (1 tool)

### `heatmap`
Generate density heatmap from point features.
- **Parameters:** `layer_name` (required), `radius`, `max_zoom`

---

## Annotation (4 tools)

### `add_annotation`
Save geometry as a categorized annotation.
- **Parameters:** `category_name` (required), `geometry` or `layer_name`, `color`

### `classify_landcover`
Auto-classify landcover from OSM data.
- **Parameters:** `location` or `bbox`, `classes`

### `export_annotations`
Export annotations to file.
- **Parameters:** `format` (required: geojson, shapefile, geopackage)

### `get_annotations`
Retrieve all current annotations.

---

## Statistics (1 tool)

### `attribute_statistics`
Compute detailed statistics for a numeric attribute.
- **Parameters:** `layer_name` (required), `attribute` (required)
- **Output:** `{min, max, mean, median, std, count, percentiles}`

---

## Code Execution (1 tool)

### `execute_code`
Execute Python code for spatial analysis (last resort).
- **Parameters:** `code` (required), `input_layer`, `output_layer`
- **Available libraries:** shapely, geopandas, numpy, scipy
- **Output:** Set `result` for text or `geojson` for map layer

---

## Tool Chaining Patterns

Common multi-tool workflows that Claude follows automatically:

| User query | Tool chain |
|---|---|
| "Show parks in Chicago" | `fetch_osm` -> `map_command(fit_bounds)` |
| "Pan to DC, zoom 15" | `geocode` -> `map_command(pan_and_zoom)` |
| "How many buildings in Seattle?" | `fetch_osm` -> `aggregate(count)` |
| "Parks within 2km of Central Park" | `geocode` -> `buffer` -> `fetch_osm` -> `spatial_query(intersects)` |
| "Route from A to B" | `find_route` -> `map_command(fit_bounds)` |
| "Where do parks and flood zones overlap?" | `fetch_osm(park)` -> `fetch_osm(flood)` -> `intersection` |
| "Remove water from land area" | `fetch_osm(land)` -> `fetch_osm(water)` -> `difference` |
| "Check and fix geometry errors" | `validate_topology` -> `repair_topology` |
| "Show hospital coverage within 15 min" | `service_area(time_minutes=15)` -> `map_command(fit_bounds)` |
| "Color residential buildings red" | `highlight_features(attribute="feature_type", value="residential")` |
| "Plot this CSV data" | `import_csv` -> `map_command(fit_bounds)` |
| "Export buildings as shapefile" | `export_layer(format="shapefile")` |
| "Merge zones by type" | `dissolve(by="zone_type")` |
| "Cut buildings to city boundary" | `clip(clip_layer, mask_layer)` |
| "Create service areas from stations" | `voronoi(layer_name="stations")` |
