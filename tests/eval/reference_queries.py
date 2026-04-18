"""Reference queries for tool selection evaluation.

30 queries covering all 44 tools across 8 categories.
Each query specifies expected tool chain, complexity, and optional param checks.

Tools covered (44):
  geocode, fetch_osm, reverse_geocode, batch_geocode, map_command,
  calculate_area, measure_distance, buffer, spatial_query, aggregate,
  search_nearby, show_layer, hide_layer, remove_layer, highlight_features,
  filter_layer, style_layer, add_annotation, classify_landcover,
  export_annotations, get_annotations, merge_layers, import_layer,
  import_csv, import_wkt, export_layer, find_route, isochrone, heatmap,
  closest_facility, optimize_route, intersection, difference,
  symmetric_difference, convex_hull, centroid, simplify, bounding_box,
  dissolve, clip, voronoi, point_in_polygon, attribute_join,
  spatial_statistics
"""

REFERENCE_QUERIES = [
    # === DATA ACQUISITION (Q001-Q005) ===
    {
        "id": "Q001",
        "query": "Show me all parks in downtown Chicago",
        "complexity": "simple",
        "expected_tools": ["fetch_osm"],
        "expected_params": {
            "fetch_osm": {"feature_type": "park", "location": "downtown Chicago"}
        },
        "category": "data_acquisition",
    },
    {
        "id": "Q002",
        "query": "What place is at coordinates 40.7128, -74.0060?",
        "complexity": "simple",
        "expected_tools": ["reverse_geocode"],
        "expected_params": {
            "reverse_geocode": {"lat": 40.7128, "lon": -74.006}
        },
        "category": "data_acquisition",
    },
    {
        "id": "Q003",
        "query": "Find restaurants near Times Square within 800 meters",
        "complexity": "simple",
        "expected_tools": ["search_nearby"],
        "expected_params": {
            "search_nearby": {"feature_type": "restaurant", "radius_m": 800}
        },
        "category": "data_acquisition",
    },
    {
        "id": "Q004",
        "query": "Geocode these addresses: 1600 Pennsylvania Ave, 350 Fifth Ave, 233 S Wacker Dr",
        "complexity": "simple",
        "expected_tools": ["batch_geocode"],
        "category": "data_acquisition",
    },
    {
        "id": "Q005",
        "query": "Pan to Berlin, Germany and zoom to level 12",
        "complexity": "moderate",
        "expected_tools": ["geocode", "map_command"],
        "expected_params": {
            "geocode": {"query": "Berlin, Germany"},
            "map_command": {"action": "pan_and_zoom"},
        },
        "category": "data_acquisition",
    },

    # === MEASUREMENT (Q006-Q008) ===
    {
        "id": "Q006",
        "query": "How far is it from the White House to the Capitol?",
        "complexity": "simple",
        "expected_tools": ["measure_distance"],
        "category": "measurement",
    },
    {
        "id": "Q007",
        "query": "What is the area of the parks layer?",
        "complexity": "simple",
        "expected_tools": ["calculate_area"],
        "expected_params": {
            "calculate_area": {"layer_name": "parks"}
        },
        "category": "measurement",
    },
    {
        "id": "Q008",
        "query": "How many buildings are in downtown Seattle?",
        "complexity": "moderate",
        "expected_tools": ["fetch_osm", "aggregate"],
        "expected_params": {
            "aggregate": {"operation": "count"}
        },
        "category": "measurement",
    },

    # === SPATIAL ANALYSIS (Q009-Q013) ===
    {
        "id": "Q009",
        "query": "Which restaurants are within 500 meters of Central Park?",
        "complexity": "complex",
        "expected_tools": ["geocode", "buffer", "search_nearby", "spatial_query"],
        "category": "spatial_analysis",
    },
    {
        "id": "Q010",
        "query": "Which district contains the point at 51.5074, -0.1278?",
        "complexity": "simple",
        "expected_tools": ["point_in_polygon"],
        "expected_params": {
            "point_in_polygon": {"lat": 51.5074, "lon": -0.1278}
        },
        "category": "spatial_analysis",
    },
    {
        "id": "Q011",
        "query": "Tag each store with its census tract",
        "complexity": "moderate",
        "expected_tools": ["point_in_polygon"],
        "expected_params": {
            "point_in_polygon": {"point_layer": "stores", "polygon_layer": "census_tracts"}
        },
        "category": "spatial_analysis",
    },
    {
        "id": "Q012",
        "query": "Are the crime points spatially clustered?",
        "complexity": "simple",
        "expected_tools": ["spatial_statistics"],
        "expected_params": {
            "spatial_statistics": {"method": "nearest_neighbor"}
        },
        "category": "spatial_analysis",
    },
    {
        "id": "Q013",
        "query": "Run DBSCAN clustering on the restaurant data with 200m radius and minimum 3 points",
        "complexity": "simple",
        "expected_tools": ["spatial_statistics"],
        "expected_params": {
            "spatial_statistics": {"method": "dbscan", "eps": 200, "min_samples": 3}
        },
        "category": "spatial_analysis",
    },

    # === GEOMETRY (Q014-Q019) ===
    {
        "id": "Q014",
        "query": "Draw a boundary around the crime data points",
        "complexity": "simple",
        "expected_tools": ["convex_hull"],
        "category": "geometry",
    },
    {
        "id": "Q015",
        "query": "Get the center points of all buildings",
        "complexity": "simple",
        "expected_tools": ["centroid"],
        "category": "geometry",
    },
    {
        "id": "Q016",
        "query": "Simplify the coastline layer with tolerance 50 meters",
        "complexity": "simple",
        "expected_tools": ["simplify"],
        "expected_params": {
            "simplify": {"tolerance": 50}
        },
        "category": "geometry",
    },
    {
        "id": "Q017",
        "query": "Show the rectangular extent of the buildings layer",
        "complexity": "simple",
        "expected_tools": ["bounding_box"],
        "category": "geometry",
    },
    {
        "id": "Q018",
        "query": "Merge the zoning polygons by zone_type",
        "complexity": "simple",
        "expected_tools": ["dissolve"],
        "expected_params": {
            "dissolve": {"by": "zone_type"}
        },
        "category": "geometry",
    },
    {
        "id": "Q019",
        "query": "Create a 2km buffer around the hospital",
        "complexity": "moderate",
        "expected_tools": ["geocode", "buffer"],
        "expected_params": {
            "buffer": {"distance_m": 2000}
        },
        "category": "geometry",
    },

    # === OVERLAY (Q020-Q022) ===
    {
        "id": "Q020",
        "query": "Show where parks and commercial zones overlap in downtown Seattle",
        "complexity": "complex",
        "expected_tools": ["fetch_osm", "fetch_osm", "intersection"],
        "category": "overlay",
    },
    {
        "id": "Q021",
        "query": "Remove water areas from the land use layer",
        "complexity": "simple",
        "expected_tools": ["difference"],
        "category": "overlay",
    },
    {
        "id": "Q022",
        "query": "What features are unique to each layer — parks vs green spaces?",
        "complexity": "simple",
        "expected_tools": ["symmetric_difference"],
        "category": "overlay",
    },

    # === ROUTING (Q023-Q025) ===
    {
        "id": "Q023",
        "query": "Plan a driving route from Times Square to Brooklyn Bridge",
        "complexity": "simple",
        "expected_tools": ["find_route"],
        "expected_params": {
            "find_route": {"from_location": "Times Square", "to_location": "Brooklyn Bridge"}
        },
        "category": "routing",
    },
    {
        "id": "Q024",
        "query": "What areas can I reach within 15 minutes driving from downtown Portland?",
        "complexity": "simple",
        "expected_tools": ["isochrone"],
        "expected_params": {
            "isochrone": {"time_minutes": 15, "profile": "driving"}
        },
        "category": "routing",
    },
    {
        "id": "Q025",
        "query": "Find the 3 nearest hospitals to Times Square",
        "complexity": "simple",
        "expected_tools": ["closest_facility"],
        "expected_params": {
            "closest_facility": {"feature_type": "hospital", "count": 3}
        },
        "category": "routing",
    },

    # === LAYER MANAGEMENT & STYLING (Q026-Q028) ===
    {
        "id": "Q026",
        "query": "Find restaurants within 500m of Central Park and color them red",
        "complexity": "multi_step",
        "expected_tools": ["search_nearby", "style_layer"],
        "category": "layer_management",
    },
    {
        "id": "Q027",
        "query": "Show only buildings taller than 20 meters and highlight the commercial ones",
        "complexity": "multi_step",
        "expected_tools": ["filter_layer", "highlight_features"],
        "category": "layer_management",
    },
    {
        "id": "Q028",
        "query": "Hide the roads layer, remove the old buildings layer, and show the parks layer",
        "complexity": "moderate",
        "expected_tools": ["hide_layer", "remove_layer", "show_layer"],
        "category": "layer_management",
    },

    # === IMPORT/EXPORT (Q029-Q030) ===
    {
        "id": "Q029",
        "query": "Import this CSV of addresses as a map layer: name,lat,lon\\nHQ,40.7,-74.0\\nBranch,34.0,-118.2",
        "complexity": "simple",
        "expected_tools": ["import_csv"],
        "category": "import_export",
    },
    {
        "id": "Q030",
        "query": "Import this WKT polygon: POLYGON((-73.98 40.76, -73.97 40.76, -73.97 40.77, -73.98 40.77, -73.98 40.76))",
        "complexity": "simple",
        "expected_tools": ["import_wkt"],
        "category": "import_export",
    },
]

# Additional queries to ensure remaining tools are covered.
# These are supplementary — the 30 above are the primary evaluation set.
SUPPLEMENTARY_QUERIES = [
    {
        "id": "S001",
        "query": "Export the buildings layer as a shapefile",
        "complexity": "simple",
        "expected_tools": ["export_layer"],
        "expected_params": {
            "export_layer": {"format": "shapefile"}
        },
        "category": "import_export",
    },
    {
        "id": "S002",
        "query": "Import this GeoJSON as a new layer: {\"type\":\"FeatureCollection\",\"features\":[]}",
        "complexity": "simple",
        "expected_tools": ["import_layer"],
        "category": "import_export",
    },
    {
        "id": "S003",
        "query": "Merge the parks layer and the green_spaces layer into one",
        "complexity": "simple",
        "expected_tools": ["merge_layers"],
        "category": "layer_management",
    },
    {
        "id": "S004",
        "query": "Add an annotation marker at the Eiffel Tower saying 'Meeting point'",
        "complexity": "moderate",
        "expected_tools": ["geocode", "add_annotation"],
        "category": "annotation",
    },
    {
        "id": "S005",
        "query": "Show me all saved annotations",
        "complexity": "simple",
        "expected_tools": ["get_annotations"],
        "category": "annotation",
    },
    {
        "id": "S006",
        "query": "Export all annotations as GeoJSON",
        "complexity": "simple",
        "expected_tools": ["export_annotations"],
        "category": "annotation",
    },
    {
        "id": "S007",
        "query": "Create a heatmap of the crime incident points",
        "complexity": "simple",
        "expected_tools": ["heatmap"],
        "category": "visualization",
    },
    {
        "id": "S008",
        "query": "Classify the land cover types in the area",
        "complexity": "simple",
        "expected_tools": ["classify_landcover"],
        "category": "visualization",
    },
    {
        "id": "S009",
        "query": "Optimize the delivery route visiting these 5 warehouse locations",
        "complexity": "simple",
        "expected_tools": ["optimize_route"],
        "category": "routing",
    },
    {
        "id": "S010",
        "query": "Cut the buildings to the city boundary",
        "complexity": "simple",
        "expected_tools": ["clip"],
        "expected_params": {
            "clip": {"clip_layer": "buildings", "mask_layer": "city_boundary"}
        },
        "category": "overlay",
    },
    {
        "id": "S011",
        "query": "Create Voronoi service areas from the fire station locations",
        "complexity": "simple",
        "expected_tools": ["voronoi"],
        "category": "geometry",
    },
    {
        "id": "S012",
        "query": "Add population data to the district polygons by matching district_id",
        "complexity": "simple",
        "expected_tools": ["attribute_join"],
        "expected_params": {
            "attribute_join": {"layer_key": "district_id"}
        },
        "category": "spatial_analysis",
    },

    # === v2.1 Plan 01 — Coverage expansion (S013-S032) ===
    # S013-S022 target high-priority uncovered tools (Task 1.1.2)
    {
        "id": "S013",
        "query": "Find crime hot spots in the incidents layer using the count attribute",
        "complexity": "simple",
        "expected_tools": ["hot_spot_analysis"],
        "expected_params": {
            "hot_spot_analysis": {"layer_name": "incidents", "attribute": "count"}
        },
        "category": "spatial_analysis",
    },
    {
        "id": "S014",
        "query": "Interpolate temperature readings from the weather_stations layer",
        "complexity": "simple",
        "expected_tools": ["interpolate"],
        "expected_params": {
            "interpolate": {"layer_name": "weather_stations", "attribute": "temperature"}
        },
        "category": "spatial_analysis",
    },
    {
        "id": "S015",
        "query": "Show the 10-minute driving coverage from all fire stations",
        "complexity": "simple",
        "expected_tools": ["service_area"],
        "expected_params": {
            "service_area": {"facility_layer": "fire_stations", "time_minutes": 10}
        },
        "category": "routing",
    },
    {
        "id": "S016",
        "query": "Describe the buildings layer — what's in it?",
        "complexity": "simple",
        "expected_tools": ["describe_layer"],
        "expected_params": {
            "describe_layer": {"layer_name": "buildings"}
        },
        "category": "data_quality",
    },
    {
        "id": "S017",
        "query": "Find duplicate features in the sensor_locations layer within 10 meters",
        "complexity": "simple",
        "expected_tools": ["detect_duplicates"],
        "expected_params": {
            "detect_duplicates": {"layer_name": "sensor_locations", "threshold_m": 10}
        },
        "category": "data_quality",
    },
    {
        "id": "S018",
        "query": "Clean the raw_data layer: remove nulls and fix attributes",
        "complexity": "simple",
        "expected_tools": ["clean_layer"],
        "expected_params": {
            "clean_layer": {"layer_name": "raw_data"}
        },
        "category": "data_quality",
    },
    {
        "id": "S019",
        "query": "Import this KML content as a waypoints layer: <kml>...</kml>",
        "complexity": "simple",
        "expected_tools": ["import_kml"],
        "category": "import_export",
    },
    {
        "id": "S020",
        "query": "Show only the events between 2025-01-01 and 2025-12-31 from the events layer",
        "complexity": "simple",
        "expected_tools": ["temporal_filter"],
        "expected_params": {
            "temporal_filter": {"layer_name": "events", "after": "2025-01-01", "before": "2025-12-31"}
        },
        "category": "spatial_analysis",
    },
    {
        "id": "S021",
        "query": "Give me summary statistics for the height attribute in the buildings layer",
        "complexity": "simple",
        "expected_tools": ["attribute_statistics"],
        "expected_params": {
            "attribute_statistics": {"layer_name": "buildings", "attribute": "height"}
        },
        "category": "spatial_analysis",
    },
    {
        "id": "S022",
        "query": "Compute the origin-destination matrix between the warehouses and customers layers",
        "complexity": "simple",
        "expected_tools": ["od_matrix"],
        "category": "routing",
    },

    # S023-S032 target remaining uncovered tools, multi-step where natural (Task 1.1.3)
    {
        "id": "S023",
        "query": "Check if the imported_parcels polygons are valid and fix any topology errors",
        "complexity": "moderate",
        "expected_tools": ["validate_topology", "repair_topology"],
        "expected_params": {
            "validate_topology": {"layer_name": "imported_parcels"},
            "repair_topology": {"layer_name": "imported_parcels"}
        },
        "category": "data_quality",
    },
    {
        "id": "S024",
        "query": "Tag the boundaries layer as being in EPSG:32632",
        "complexity": "simple",
        "expected_tools": ["reproject_layer"],
        "expected_params": {
            "reproject_layer": {"layer_name": "boundaries", "from_crs": 32632}
        },
        "category": "spatial_analysis",
    },
    {
        "id": "S025",
        "query": "What coordinate system is the imported_data layer in?",
        "complexity": "simple",
        "expected_tools": ["detect_crs"],
        "expected_params": {
            "detect_crs": {"layer_name": "imported_data"}
        },
        "category": "spatial_analysis",
    },
    {
        "id": "S026",
        "query": "Split the first parcel in the parcels layer along this line: [[0,0],[1,1]]",
        "complexity": "simple",
        "expected_tools": ["split_feature"],
        "expected_params": {
            "split_feature": {"layer_name": "parcels", "feature_index": 0}
        },
        "category": "geometry",
    },
    {
        "id": "S027",
        "query": "Merge features in the zones layer that share the same zone_type value",
        "complexity": "simple",
        "expected_tools": ["merge_features"],
        "expected_params": {
            "merge_features": {"layer_name": "zones", "by": "zone_type"}
        },
        "category": "geometry",
    },
    {
        "id": "S028",
        "query": "Extract the vertex points from the coastline layer",
        "complexity": "simple",
        "expected_tools": ["extract_vertices"],
        "expected_params": {
            "extract_vertices": {"layer_name": "coastline"}
        },
        "category": "geometry",
    },
    {
        "id": "S029",
        "query": "Import this GeoParquet file as a parcels layer",
        "complexity": "simple",
        "expected_tools": ["import_geoparquet"],
        "category": "import_export",
    },
    {
        "id": "S030",
        "query": "Export the buildings layer as GeoParquet",
        "complexity": "simple",
        "expected_tools": ["export_geoparquet"],
        "expected_params": {
            "export_geoparquet": {"layer_name": "buildings"}
        },
        "category": "import_export",
    },
    {
        "id": "S031",
        "query": "Validate topology on the boundaries layer, and if there are issues, repair them into a clean version",
        "complexity": "moderate",
        "expected_tools": ["validate_topology", "repair_topology"],
        "expected_params": {
            "validate_topology": {"layer_name": "boundaries"},
            "repair_topology": {"layer_name": "boundaries", "output_name": "boundaries_clean"}
        },
        "category": "data_quality",
    },
    {
        "id": "S032",
        "query": "Compute the minimum bounding rectangle for all features in the buildings layer",
        "complexity": "simple",
        "expected_tools": ["execute_code"],
        "category": "advanced",
    },

    # === v2.1 Plan 08 — Raster analysis (S033-S037) ===
    {
        "id": "S033",
        "query": "What raster files are available?",
        "complexity": "simple",
        "expected_tools": ["raster_info"],
        "category": "raster",
    },
    {
        "id": "S034",
        "query": "What is the elevation at lat 40.758, lon -73.985?",
        "complexity": "simple",
        "expected_tools": ["raster_value"],
        "expected_params": {"raster_value": {"lat": 40.758, "lon": -73.985}},
        "category": "raster",
    },
    {
        "id": "S035",
        "query": "Compute elevation statistics for the chicago_utm.tif raster",
        "complexity": "simple",
        "expected_tools": ["raster_statistics"],
        "expected_params": {"raster_statistics": {"raster": "chicago_utm.tif"}},
        "category": "raster",
    },
    {
        "id": "S036",
        "query": "Draw an elevation profile from downtown Chicago to O'Hare airport using chicago_utm.tif",
        "complexity": "simple",
        "expected_tools": ["raster_profile"],
        "category": "raster",
    },
    {
        "id": "S037",
        "query": "Classify the chicago_utm.tif raster into low, medium, high at breaks 100 and 500",
        "complexity": "simple",
        "expected_tools": ["raster_classify"],
        "expected_params": {"raster_classify": {"raster": "chicago_utm.tif", "breaks": [100, 500]}},
        "category": "raster",
    },

    # === v2.1 Plan 10 — Data pipeline (S038-S041) ===
    {
        "id": "S038",
        "query": "Clip the buildings layer to Chicago's bounding box",
        "complexity": "simple",
        "expected_tools": ["clip_to_bbox"],
        "expected_params": {"clip_to_bbox": {"layer_name": "buildings", "location": "Chicago"}},
        "category": "data_pipeline",
    },
    {
        "id": "S039",
        "query": "Simplify the coastline layer to 50 meter tolerance",
        "complexity": "simple",
        "expected_tools": ["generalize"],
        "expected_params": {"generalize": {"layer_name": "coastline", "tolerance": 50}},
        "category": "data_pipeline",
    },
    {
        "id": "S040",
        "query": "Export the parks layer as GeoPackage",
        "complexity": "simple",
        "expected_tools": ["export_gpkg"],
        "expected_params": {"export_gpkg": {"layer_name": "parks"}},
        "category": "data_pipeline",
    },
    {
        "id": "S041",
        "query": "Import this data and figure out the format automatically",
        "complexity": "simple",
        "expected_tools": ["import_auto"],
        "category": "data_pipeline",
    },
]

# Full query set = primary + supplementary
ALL_QUERIES = REFERENCE_QUERIES + SUPPLEMENTARY_QUERIES

# All 64 tool names for coverage validation (source of truth: nl_gis/tools.py)
ALL_TOOLS = [
    # Data acquisition + nav
    "geocode", "fetch_osm", "reverse_geocode", "batch_geocode", "map_command",
    "search_nearby",
    # Measurement + core analysis
    "calculate_area", "measure_distance", "buffer", "spatial_query", "aggregate",
    "filter_layer",
    # Layer management
    "show_layer", "hide_layer", "remove_layer", "highlight_features", "style_layer",
    "merge_layers",
    # Annotations
    "add_annotation", "classify_landcover", "export_annotations", "get_annotations",
    # Import/export
    "import_layer", "import_csv", "import_wkt", "import_kml",
    "import_geoparquet", "export_geoparquet", "export_layer",
    # Data quality
    "describe_layer", "detect_duplicates", "clean_layer",
    # Routing
    "find_route", "isochrone", "heatmap", "closest_facility", "optimize_route",
    "service_area", "od_matrix",
    # Overlays
    "intersection", "difference", "symmetric_difference",
    # Geometry
    "convex_hull", "centroid", "simplify", "bounding_box", "dissolve", "clip",
    "voronoi", "split_feature", "merge_features", "extract_vertices",
    # Advanced spatial analysis
    "point_in_polygon", "attribute_join", "spatial_statistics",
    "hot_spot_analysis", "interpolate",
    # Topology
    "validate_topology", "repair_topology",
    # CRS
    "reproject_layer", "detect_crs",
    # Temporal + attribute stats
    "temporal_filter", "attribute_statistics",
    # Code fallback
    "execute_code",
    # Raster analysis (v2.1 Plan 08)
    "raster_info", "raster_value", "raster_statistics", "raster_profile",
    "raster_classify",
    # Data pipeline (v2.1 Plan 10)
    "clip_to_bbox", "generalize", "export_gpkg", "import_auto",
]


def get_tool_coverage(queries=None):
    """Return set of tools covered by given queries and set of uncovered tools."""
    if queries is None:
        queries = ALL_QUERIES
    covered = set()
    for q in queries:
        for tool in q["expected_tools"]:
            covered.add(tool)
    uncovered = set(ALL_TOOLS) - covered
    return covered, uncovered
