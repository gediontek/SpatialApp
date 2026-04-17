"""Mock LLM responses for CI evaluation.

Each entry maps a query_id to the tool_use blocks that a mock LLM would return.
These simulate Claude's tool selection behavior for deterministic CI testing.
"""


def _tool_use(tool_name, params=None):
    """Create a mock tool_use content block."""
    return {
        "type": "tool_use",
        "id": f"toolu_mock_{tool_name}",
        "name": tool_name,
        "input": params or {},
    }


# Mock responses keyed by query_id.
# Each value is a list of tool_use blocks (simulating multi-tool chains).
MOCK_RESPONSES = {
    # === DATA ACQUISITION ===
    "Q001": [
        _tool_use("fetch_osm", {"feature_type": "park", "category_name": "chicago_parks", "location": "downtown Chicago"}),
    ],
    "Q002": [
        _tool_use("reverse_geocode", {"lat": 40.7128, "lon": -74.006}),
    ],
    "Q003": [
        _tool_use("search_nearby", {"lat": 40.758, "lon": -73.9855, "radius_m": 800, "feature_type": "restaurant", "category_name": "times_sq_restaurants"}),
    ],
    "Q004": [
        _tool_use("batch_geocode", {"addresses": ["1600 Pennsylvania Ave", "350 Fifth Ave", "233 S Wacker Dr"]}),
    ],
    "Q005": [
        _tool_use("geocode", {"query": "Berlin, Germany"}),
        _tool_use("map_command", {"action": "pan_and_zoom", "lat": 52.52, "lon": 13.405, "zoom": 12}),
    ],

    # === MEASUREMENT ===
    "Q006": [
        _tool_use("measure_distance", {"from_location": "The White House", "to_location": "US Capitol Building"}),
    ],
    "Q007": [
        _tool_use("calculate_area", {"layer_name": "parks"}),
    ],
    "Q008": [
        _tool_use("fetch_osm", {"feature_type": "building", "category_name": "seattle_buildings", "location": "downtown Seattle"}),
        _tool_use("aggregate", {"layer_name": "seattle_buildings", "operation": "count"}),
    ],

    # === SPATIAL ANALYSIS ===
    "Q009": [
        _tool_use("geocode", {"query": "Central Park, NYC"}),
        _tool_use("buffer", {"distance_m": 500}),
        _tool_use("search_nearby", {"lat": 40.78, "lon": -73.97, "radius_m": 600, "feature_type": "restaurant", "category_name": "cp_restaurants"}),
        _tool_use("spatial_query", {"predicate": "within"}),
    ],
    "Q010": [
        _tool_use("point_in_polygon", {"lat": 51.5074, "lon": -0.1278, "polygon_layer": "districts"}),
    ],
    "Q011": [
        _tool_use("point_in_polygon", {"point_layer": "stores", "polygon_layer": "census_tracts"}),
    ],
    "Q012": [
        _tool_use("spatial_statistics", {"layer_name": "crimes", "method": "nearest_neighbor"}),
    ],
    "Q013": [
        _tool_use("spatial_statistics", {"layer_name": "restaurants", "method": "dbscan", "eps": 200, "min_samples": 3}),
    ],

    # === GEOMETRY ===
    "Q014": [
        _tool_use("convex_hull", {"layer_name": "crime_data"}),
    ],
    "Q015": [
        _tool_use("centroid", {"layer_name": "buildings"}),
    ],
    "Q016": [
        _tool_use("simplify", {"layer_name": "coastline", "tolerance": 50}),
    ],
    "Q017": [
        _tool_use("bounding_box", {"layer_name": "buildings"}),
    ],
    "Q018": [
        _tool_use("dissolve", {"layer_name": "zoning", "by": "zone_type"}),
    ],
    "Q019": [
        _tool_use("geocode", {"query": "hospital"}),
        _tool_use("buffer", {"distance_m": 2000}),
    ],

    # === OVERLAY ===
    "Q020": [
        _tool_use("fetch_osm", {"feature_type": "park", "category_name": "seattle_parks", "location": "downtown Seattle"}),
        _tool_use("fetch_osm", {"feature_type": "commercial", "category_name": "seattle_commercial", "location": "downtown Seattle"}),
        _tool_use("intersection", {"layer_a": "seattle_parks", "layer_b": "seattle_commercial"}),
    ],
    "Q021": [
        _tool_use("difference", {"layer_a": "land_use", "layer_b": "water"}),
    ],
    "Q022": [
        _tool_use("symmetric_difference", {"layer_a": "parks", "layer_b": "green_spaces"}),
    ],

    # === ROUTING ===
    "Q023": [
        _tool_use("find_route", {"from_location": "Times Square", "to_location": "Brooklyn Bridge"}),
    ],
    "Q024": [
        _tool_use("isochrone", {"location": "downtown Portland", "time_minutes": 15, "profile": "driving"}),
    ],
    "Q025": [
        _tool_use("closest_facility", {"location": "Times Square", "feature_type": "hospital", "count": 3}),
    ],

    # === LAYER MANAGEMENT ===
    "Q026": [
        _tool_use("search_nearby", {"lat": 40.78, "lon": -73.97, "radius_m": 500, "feature_type": "restaurant", "category_name": "cp_restaurants"}),
        _tool_use("style_layer", {"layer_name": "cp_restaurants", "color": "#ff0000"}),
    ],
    "Q027": [
        _tool_use("filter_layer", {"layer_name": "buildings", "attribute": "height", "operator": ">", "value": 20}),
        _tool_use("highlight_features", {"layer_name": "buildings_filtered", "attribute": "type", "value": "commercial", "color": "#ff0000"}),
    ],
    "Q028": [
        _tool_use("hide_layer", {"layer_name": "roads"}),
        _tool_use("remove_layer", {"layer_name": "old_buildings"}),
        _tool_use("show_layer", {"layer_name": "parks"}),
    ],

    # === IMPORT/EXPORT ===
    "Q029": [
        _tool_use("import_csv", {"csv_data": "name,lat,lon\nHQ,40.7,-74.0\nBranch,34.0,-118.2", "lat_column": "lat", "lon_column": "lon"}),
    ],
    "Q030": [
        _tool_use("import_wkt", {"wkt": "POLYGON((-73.98 40.76, -73.97 40.76, -73.97 40.77, -73.98 40.77, -73.98 40.76))"}),
    ],

    # === SUPPLEMENTARY ===
    "S001": [
        _tool_use("export_layer", {"layer_name": "buildings", "format": "shapefile"}),
    ],
    "S002": [
        _tool_use("import_layer", {"geojson": {"type": "FeatureCollection", "features": []}, "layer_name": "imported"}),
    ],
    "S003": [
        _tool_use("merge_layers", {"layer_names": ["parks", "green_spaces"]}),
    ],
    "S004": [
        _tool_use("geocode", {"query": "Eiffel Tower"}),
        _tool_use("add_annotation", {"lat": 48.8584, "lon": 2.2945, "text": "Meeting point"}),
    ],
    "S005": [
        _tool_use("get_annotations", {}),
    ],
    "S006": [
        _tool_use("export_annotations", {"format": "geojson"}),
    ],
    "S007": [
        _tool_use("heatmap", {"layer_name": "crime_incidents"}),
    ],
    "S008": [
        _tool_use("classify_landcover", {"layer_name": "land_cover"}),
    ],
    "S009": [
        _tool_use("optimize_route", {"locations": [], "profile": "auto"}),
    ],
    "S010": [
        _tool_use("clip", {"clip_layer": "buildings", "mask_layer": "city_boundary"}),
    ],
    "S011": [
        _tool_use("voronoi", {"layer_name": "fire_stations"}),
    ],
    "S012": [
        _tool_use("attribute_join", {"layer_name": "districts", "join_data": [], "layer_key": "district_id", "data_key": "district_id"}),
    ],

    # === v2.1 Plan 01 — Coverage expansion (S013-S032) ===
    "S013": [
        _tool_use("hot_spot_analysis", {"layer_name": "incidents", "attribute": "count"}),
    ],
    "S014": [
        _tool_use("interpolate", {"layer_name": "weather_stations", "attribute": "temperature", "method": "linear"}),
    ],
    "S015": [
        _tool_use("service_area", {"facility_layer": "fire_stations", "time_minutes": 10, "profile": "auto"}),
    ],
    "S016": [
        _tool_use("describe_layer", {"layer_name": "buildings"}),
    ],
    "S017": [
        _tool_use("detect_duplicates", {"layer_name": "sensor_locations", "threshold_m": 10}),
    ],
    "S018": [
        _tool_use("clean_layer", {"layer_name": "raw_data"}),
    ],
    "S019": [
        _tool_use("import_kml", {"kml_data": "<kml>...</kml>", "layer_name": "waypoints"}),
    ],
    "S020": [
        _tool_use("temporal_filter", {"layer_name": "events", "date_attribute": "event_date", "after": "2025-01-01", "before": "2025-12-31"}),
    ],
    "S021": [
        _tool_use("attribute_statistics", {"layer_name": "buildings", "attribute": "height"}),
    ],
    "S022": [
        _tool_use("od_matrix", {"origins": [], "destinations": []}),
    ],
    "S023": [
        _tool_use("validate_topology", {"layer_name": "imported_parcels"}),
        _tool_use("repair_topology", {"layer_name": "imported_parcels"}),
    ],
    "S024": [
        _tool_use("reproject_layer", {"layer_name": "boundaries", "from_crs": 32632, "to_crs": 4326}),
    ],
    "S025": [
        _tool_use("detect_crs", {"layer_name": "imported_data"}),
    ],
    "S026": [
        _tool_use("split_feature", {
            "layer_name": "parcels",
            "feature_index": 0,
            "split_line": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        }),
    ],
    "S027": [
        _tool_use("merge_features", {"layer_name": "zones", "by": "zone_type"}),
    ],
    "S028": [
        _tool_use("extract_vertices", {"layer_name": "coastline"}),
    ],
    "S029": [
        _tool_use("import_geoparquet", {"parquet_data": "<base64>", "layer_name": "parcels"}),
    ],
    "S030": [
        _tool_use("export_geoparquet", {"layer_name": "buildings"}),
    ],
    "S031": [
        _tool_use("validate_topology", {"layer_name": "boundaries"}),
        _tool_use("repair_topology", {"layer_name": "boundaries", "output_name": "boundaries_clean"}),
    ],
    "S032": [
        _tool_use("execute_code", {
            "code": "import geopandas as gpd\ngdf = gpd.GeoDataFrame.from_features(_input_data['layer']['features'])\nresult = gdf.total_bounds.tolist()",
            "input_layer": "buildings",
        }),
    ],
}


def get_mock_tools(query_id: str) -> list[str]:
    """Extract tool names from mock response for a query."""
    blocks = MOCK_RESPONSES.get(query_id, [])
    return [b["name"] for b in blocks]


def get_mock_params(query_id: str) -> dict:
    """Extract tool params from mock response, keyed by tool name.

    If a tool appears multiple times, only the last occurrence's params are kept.
    """
    blocks = MOCK_RESPONSES.get(query_id, [])
    params = {}
    for b in blocks:
        params[b["name"]] = b["input"]
    return params
