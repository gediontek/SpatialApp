"""Tool definitions for Claude API tool_use integration."""


def get_tool_definitions() -> list:
    """Return tool definitions for Claude API.

    Each tool has: name, description, input_schema (JSON Schema).
    Claude uses these to decide which tool to call and with what parameters.
    """
    return [
        {
            "name": "geocode",
            "description": "Convert a place name or address into geographic coordinates (latitude, longitude). Use this whenever the user references a location by name. Returns coordinates, display name, and bounding box.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Place name or address to geocode (e.g., 'downtown Chicago', 'Berlin, Germany', '1600 Pennsylvania Ave')"
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "fetch_osm",
            "description": "Fetch OpenStreetMap features within a bounding box or near a location. Returns a GeoJSON FeatureCollection displayed as a named layer. Use fetch_osm for bbox area queries ('all parks in Chicago'); use search_nearby for point-radius queries ('cafes near Times Square'). Built-in types: building, forest, water, park, grass, farmland, residential, commercial, industrial, road, river, lake, restaurant, school, hospital, pharmacy, supermarket, hotel, church, mosque, bank, atm, cafe, bar, cinema, library, university, police, fire_station, post_office, bus_stop, rail, parking, fuel, playground, stadium, swimming_pool, cemetery, wetland, beach, cliff. For unlisted types, use osm_key and osm_value for custom Overpass queries.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "feature_type": {
                        "type": "string",
                        "description": "Type of OSM feature to fetch. Example: 'park', 'hospital', 'building'. Use osm_key/osm_value for unlisted types."
                    },
                    "category_name": {
                        "type": "string",
                        "description": "Label to assign to fetched features. Example: 'chicago_buildings', 'berlin_parks'"
                    },
                    "bbox": {
                        "type": "string",
                        "description": "Bounding box as 'south,west,north,east' in decimal degrees. Example: '41.8,-87.7,41.9,-87.6'. If not provided, you must provide location instead."
                    },
                    "location": {
                        "type": "string",
                        "description": "Place name to use as the search area. Example: 'downtown Chicago', 'Berlin, Germany'. Will be geocoded to get a bounding box."
                    },
                    "osm_key": {
                        "type": "string",
                        "description": "OSM tag key for custom queries (e.g., 'amenity', 'shop', 'tourism')"
                    },
                    "osm_value": {
                        "type": "string",
                        "description": "OSM tag value for custom queries (e.g., 'restaurant', 'supermarket')"
                    }
                },
                "required": ["feature_type", "category_name"]
            }
        },
        {
            "name": "reverse_geocode",
            "description": "Convert geographic coordinates (latitude, longitude) into a human-readable address or place name. Use when the user asks 'What's at these coordinates?' or 'What place is at lat/lon?'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "lat": {
                        "type": "number",
                        "description": "Latitude (north-south, -90 to 90). Example: 40.7128"
                    },
                    "lon": {
                        "type": "number",
                        "description": "Longitude (east-west, -180 to 180). Example: -74.0060"
                    }
                },
                "required": ["lat", "lon"]
            }
        },
        {
            "name": "batch_geocode",
            "description": "Geocode a list of addresses into a point layer on the map. Use when the user provides multiple addresses to plot. Returns a GeoJSON FeatureCollection with a point for each successfully geocoded address. Maximum 50 addresses per batch.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "addresses": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of addresses or place names to geocode (max 50). Example: ['350 5th Ave, New York', 'Golden Gate Bridge, SF', 'Big Ben, London']"
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Name for the output point layer (default: 'geocoded_points'). Example: 'office_locations'"
                    }
                },
                "required": ["addresses"]
            }
        },
        {
            "name": "map_command",
            "description": "Control the map view: pan to coordinates, set zoom level, fit to bounding box, or change basemap. Use this to navigate the map based on user requests. Always follow a data fetch with fit_bounds so the user sees results.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Map action to perform. Example: 'pan_and_zoom' to center on a location at a specific zoom",
                        "enum": ["pan", "zoom", "pan_and_zoom", "fit_bounds", "change_basemap"]
                    },
                    "lat": {
                        "type": "number",
                        "description": "Latitude for pan action (north-south, -90 to 90). Example: 41.88"
                    },
                    "lon": {
                        "type": "number",
                        "description": "Longitude for pan action (east-west, -180 to 180). Example: -87.63"
                    },
                    "zoom": {
                        "type": "integer",
                        "description": "Zoom level (1-20). Higher = more zoomed in. Example: 13 for city-level, 16 for street-level",
                        "minimum": 1,
                        "maximum": 20
                    },
                    "bbox": {
                        "type": "array",
                        "description": "Bounding box [south, west, north, east] in decimal degrees for fit_bounds action. Example: [41.8, -87.7, 41.9, -87.6]",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4
                    },
                    "basemap": {
                        "type": "string",
                        "description": "Basemap style. Example: 'satellite' for aerial imagery",
                        "enum": ["osm", "satellite"]
                    }
                },
                "required": ["action"]
            }
        },
        {
            "name": "calculate_area",
            "description": "Calculate the geodesic area of polygons. Accepts either a layer name (to calculate area of all features in that layer) or a GeoJSON geometry. Returns area in square meters, square kilometers, and acres.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of an existing map layer to calculate area for. Example: 'parks_chicago'"
                    },
                    "geometry": {
                        "type": "object",
                        "description": "GeoJSON geometry object (Polygon or MultiPolygon). Example: {\"type\": \"Polygon\", \"coordinates\": [[[lon,lat], [lon,lat], ...]]}"
                    }
                }
            }
        },
        {
            "name": "measure_distance",
            "description": "Calculate the geodesic distance between two points. Points can be specified as coordinates or place names. Returns distance in meters, kilometers, and miles.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "from_point": {
                        "type": "object",
                        "description": "Start point as {\"lat\": number, \"lon\": number}. Example: {\"lat\": 40.71, \"lon\": -74.01}",
                        "properties": {
                            "lat": {"type": "number"},
                            "lon": {"type": "number"}
                        },
                        "required": ["lat", "lon"]
                    },
                    "to_point": {
                        "type": "object",
                        "description": "End point as {\"lat\": number, \"lon\": number}. Example: {\"lat\": 38.90, \"lon\": -77.04}",
                        "properties": {
                            "lat": {"type": "number"},
                            "lon": {"type": "number"}
                        },
                        "required": ["lat", "lon"]
                    },
                    "from_location": {
                        "type": "string",
                        "description": "Start location name (geocoded automatically). Example: 'Times Square, NYC'"
                    },
                    "to_location": {
                        "type": "string",
                        "description": "End location name (geocoded automatically). Example: 'Brooklyn Bridge'"
                    }
                }
            }
        },
        # ---- Phase 2: Spatial Analysis Tools ----
        {
            "name": "buffer",
            "description": "Create a buffer polygon around a geometry or all features in a named layer. Returns a visible GeoJSON polygon added as a new layer on the map. Use buffer to create a visible polygon; use spatial_query(within_distance) to find features near something without creating a polygon.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of an existing layer to buffer. Example: 'hospitals_nyc'"
                    },
                    "geometry": {
                        "type": "object",
                        "description": "GeoJSON geometry to buffer (alternative to layer_name). Example: {\"type\": \"Point\", \"coordinates\": [-73.97, 40.78]}"
                    },
                    "distance_m": {
                        "type": "number",
                        "description": "Buffer distance in meters (max 100,000 = 100km). Example: 500 for a 500m buffer",
                        "minimum": 1,
                        "maximum": 100000
                    }
                },
                "required": ["distance_m"]
            }
        },
        {
            "name": "spatial_query",
            "description": "Find features in one layer that match a spatial relationship with another layer or geometry. Use spatial_query(intersects) to filter features that touch/overlap a target; use the intersection tool instead for geometric overlay that produces new cut geometries. Use spatial_query(within_distance) to find features near something; use buffer instead to create a visible polygon. Predicates: intersects (any overlap), contains (source fully encloses target), within (source fully inside target), within_distance (source within N meters of target).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_layer": {
                        "type": "string",
                        "description": "Layer to query features FROM. Example: 'restaurants_downtown'"
                    },
                    "predicate": {
                        "type": "string",
                        "description": "Spatial relationship to test. Example: 'within' to find features inside a polygon",
                        "enum": ["intersects", "contains", "within", "within_distance"]
                    },
                    "target_layer": {
                        "type": "string",
                        "description": "Layer to compare AGAINST. Example: 'buffer_central_park'"
                    },
                    "target_geometry": {
                        "type": "object",
                        "description": "GeoJSON geometry to compare against (alternative to target_layer). Example: {\"type\": \"Polygon\", \"coordinates\": [[[lon,lat], ...]]}"
                    },
                    "distance_m": {
                        "type": "number",
                        "description": "Distance in meters for within_distance predicate. Example: 1000 for 1km"
                    }
                },
                "required": ["source_layer", "predicate"]
            }
        },
        {
            "name": "aggregate",
            "description": "Summarize features in a layer: count features, calculate total area, or group by an attribute. Useful for questions like 'how many buildings?' or 'what's the total area of farmland?'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to aggregate. Example: 'buildings_seattle'"
                    },
                    "operation": {
                        "type": "string",
                        "description": "Operation to perform: count (number of features), area (total geodesic area in sq meters), group_by (count per category). Example: 'count'",
                        "enum": ["count", "area", "group_by"]
                    },
                    "group_by": {
                        "type": "string",
                        "description": "Property name to group by (required for group_by operation). Example: 'feature_type'"
                    }
                },
                "required": ["layer_name", "operation"]
            }
        },
        {
            "name": "search_nearby",
            "description": "Search for OSM features near a point within a given radius. Uses Overpass API 'around' filter. Returns a GeoJSON FeatureCollection added as a map layer. Use search_nearby for point-radius queries ('cafes near Times Square'); use fetch_osm for bbox area queries ('all parks in Chicago').",
            "input_schema": {
                "type": "object",
                "properties": {
                    "lat": {
                        "type": "number",
                        "description": "Center latitude (north-south, -90 to 90). Example: 40.758"
                    },
                    "lon": {
                        "type": "number",
                        "description": "Center longitude (east-west, -180 to 180). Example: -73.985"
                    },
                    "location": {
                        "type": "string",
                        "description": "Place name (geocoded to get lat/lon if not provided). Example: 'Times Square, NYC'"
                    },
                    "radius_m": {
                        "type": "number",
                        "description": "Search radius in meters (max 50,000 = 50km). Example: 500 for a 500m radius",
                        "default": 500,
                        "minimum": 1,
                        "maximum": 50000
                    },
                    "feature_type": {
                        "type": "string",
                        "description": "OSM feature type to search for. Example: 'restaurant', 'hospital', 'cafe'. Use osm_key/osm_value for unlisted types."
                    },
                    "osm_key": {
                        "type": "string",
                        "description": "OSM tag key for custom queries. Example: 'amenity', 'shop', 'tourism'"
                    },
                    "osm_value": {
                        "type": "string",
                        "description": "OSM tag value for custom queries. Example: 'restaurant', 'supermarket', 'museum'"
                    }
                },
                "required": ["feature_type"]
            }
        },
        {
            "name": "show_layer",
            "description": "Make a hidden layer visible on the map. Use when the user says 'show the parks layer' or 'turn on buildings'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to show. Example: 'parks_chicago'"
                    }
                },
                "required": ["layer_name"]
            }
        },
        {
            "name": "hide_layer",
            "description": "Hide a layer from the map without deleting it. The layer can be shown again later with show_layer.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to hide. Example: 'buildings_seattle'"
                    }
                },
                "required": ["layer_name"]
            }
        },
        {
            "name": "remove_layer",
            "description": "Remove a layer from the map permanently. Cannot be undone. Use hide_layer if the user may want it back later.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to remove. Example: 'old_buffer_layer'"
                    }
                },
                "required": ["layer_name"]
            }
        },
        {
            "name": "highlight_features",
            "description": "Highlight features in a layer that match a specific attribute value. Changes the style of matching features to draw attention to them. Useful for 'highlight all residential buildings' or 'show me the forests in green'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer containing features to highlight. Example: 'buildings_downtown'"
                    },
                    "attribute": {
                        "type": "string",
                        "description": "Property name to match on. Example: 'feature_type', 'category_name', 'name'"
                    },
                    "value": {
                        "type": "string",
                        "description": "Value to match. Example: 'residential', 'forest', 'Central Park'"
                    },
                    "color": {
                        "type": "string",
                        "description": "Hex color for highlighted features (e.g., '#ff0000')",
                        "default": "#ff0000"
                    }
                },
                "required": ["layer_name", "attribute", "value"]
            }
        },
        {
            "name": "filter_layer",
            "description": "Filter features in an existing layer by attribute value. Creates a new layer with only the matching features. Use for queries like 'show only residential buildings', 'parks named Central Park', or filtering by any property.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to filter. Example: 'buildings_downtown'"
                    },
                    "attribute": {
                        "type": "string",
                        "description": "Property name to filter on. Example: 'feature_type', 'building:levels', 'name'"
                    },
                    "operator": {
                        "type": "string",
                        "description": "Comparison operator. Example: 'greater_than' for numeric filters. Use 'between' with value as 'min,max'.",
                        "enum": ["equals", "not_equals", "contains", "starts_with", "greater_than", "less_than", "greater_equal", "less_equal", "between"]
                    },
                    "value": {
                        "type": "string",
                        "description": "Value to compare against. Example: 'residential', '5', '10,50' (for between)"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the filtered output layer. Example: 'tall_buildings'"
                    }
                },
                "required": ["layer_name", "attribute", "operator", "value", "output_name"]
            }
        },
        {
            "name": "style_layer",
            "description": "Change the visual style of an existing layer. Set color, weight (line thickness), fill opacity, or fill color. Use for 'color the parks green', 'make the roads thicker', 'set building fill to 50% opacity'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to style. Example: 'parks_chicago'"
                    },
                    "color": {
                        "type": "string",
                        "description": "Outline/stroke color as hex. Example: '#ff0000' for red, '#00ff00' for green, '#0000ff' for blue"
                    },
                    "fill_color": {
                        "type": "string",
                        "description": "Fill color as hex (defaults to same as color). Example: '#228B22' for forest green"
                    },
                    "weight": {
                        "type": "number",
                        "description": "Line/border thickness in pixels (1-10). Example: 2 for normal, 5 for thick",
                        "minimum": 1,
                        "maximum": 10
                    },
                    "fill_opacity": {
                        "type": "number",
                        "description": "Fill opacity (0.0 = transparent, 1.0 = opaque). Example: 0.3 for semi-transparent, 0.8 for mostly opaque",
                        "minimum": 0,
                        "maximum": 1
                    },
                    "opacity": {
                        "type": "number",
                        "description": "Stroke opacity (0.0 = transparent, 1.0 = opaque). Example: 1.0 for solid borders",
                        "minimum": 0,
                        "maximum": 1
                    }
                },
                "required": ["layer_name"]
            }
        },
        # ---- Phase 3: Annotation & Classification Tools ----
        {
            "name": "add_annotation",
            "description": "Save a geometry as an annotation with a category name and color. Use this to label features on the map for later retrieval or export.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "geometry": {
                        "type": "object",
                        "description": "GeoJSON geometry to annotate. Example: {\"type\": \"Point\", \"coordinates\": [-73.97, 40.78]}"
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Name of an existing layer whose features to annotate (alternative to geometry). Example: 'parks_chicago'"
                    },
                    "category_name": {
                        "type": "string",
                        "description": "Category label for the annotation. Example: 'farmland', 'residential', 'flood_risk'"
                    },
                    "color": {
                        "type": "string",
                        "description": "Hex color for the annotation (e.g., '#ff0000')",
                        "default": "#3388ff"
                    }
                },
                "required": ["category_name"]
            }
        },
        {
            "name": "classify_landcover",
            "description": "Automatically classify landcover for an area using OSM data and word embeddings. Returns classified features with categories: builtup_area, water, forest, grassland, farmland, bare_earth, aquaculture.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "Place name to classify. Example: 'Portland, Oregon', 'central Amsterdam'"
                    },
                    "bbox": {
                        "type": "object",
                        "description": "Bounding box with north/south/east/west in decimal degrees. Example: {\"north\": 45.55, \"south\": 45.50, \"east\": -122.60, \"west\": -122.70}",
                        "properties": {
                            "north": {"type": "number"},
                            "south": {"type": "number"},
                            "east": {"type": "number"},
                            "west": {"type": "number"}
                        },
                        "required": ["north", "south", "east", "west"]
                    },
                    "classes": {
                        "type": "array",
                        "description": "Filter to specific classes (default: all). Example: ['forest', 'water', 'builtup_area']",
                        "items": {"type": "string"}
                    }
                }
            }
        },
        {
            "name": "export_annotations",
            "description": "Export all current annotations to a file. Supported formats: geojson, shapefile, geopackage. Returns a download link. Use get_annotations to view without exporting.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "description": "Export format. Example: 'geojson' for web use, 'shapefile' for desktop GIS",
                        "enum": ["geojson", "shapefile", "geopackage"]
                    }
                },
                "required": ["format"]
            }
        },
        {
            "name": "get_annotations",
            "description": "Get all current annotations. Returns a GeoJSON FeatureCollection with count and category breakdown.",
            "input_schema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "merge_layers",
            "description": "Merge two named layers into a single new layer. Optionally perform a spatial join to transfer attributes from one layer to another based on spatial relationship. Useful for combining datasets or enriching features with attributes from another layer.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_a": {
                        "type": "string",
                        "description": "First layer name. Example: 'parks_north'"
                    },
                    "layer_b": {
                        "type": "string",
                        "description": "Second layer name. Example: 'parks_south'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the merged output layer. Example: 'all_parks'"
                    },
                    "operation": {
                        "type": "string",
                        "description": "Merge operation: 'union' combines all features into one layer, 'spatial_join' transfers attributes from layer_b to layer_a based on spatial overlap. Example: 'union'",
                        "enum": ["union", "spatial_join"],
                        "default": "union"
                    }
                },
                "required": ["layer_a", "layer_b", "output_name"]
            }
        },
        {
            "name": "import_layer",
            "description": "Import a vector file (GeoJSON, Shapefile, GeoPackage) as a named layer on the map. The user must upload the file via the /api/import endpoint. Use this tool to tell the user how to import and to process inline GeoJSON data.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "geojson": {
                        "type": "object",
                        "description": "GeoJSON FeatureCollection to import directly as a layer. Example: {\"type\": \"FeatureCollection\", \"features\": [{\"type\": \"Feature\", \"geometry\": {\"type\": \"Point\", \"coordinates\": [-73.97, 40.78]}, \"properties\": {\"name\": \"Central Park\"}}]}"
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Name for the imported layer. Example: 'custom_points'"
                    }
                },
                "required": ["layer_name"]
            }
        },
        # ---- Data Import/Export Tools ----
        {
            "name": "import_csv",
            "description": "Import CSV data with latitude/longitude columns as a point layer on the map. Use when the user pastes CSV content or wants to plot tabular data with coordinates. Skips rows with missing or invalid lat/lon values.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "csv_data": {
                        "type": "string",
                        "description": "CSV content as a string (header row + data rows). Example: 'name,lat,lon\\nCentral Park,40.78,-73.97\\nBryant Park,40.75,-73.98'"
                    },
                    "lat_column": {
                        "type": "string",
                        "description": "Name of the latitude column (default: 'lat'). Example: 'latitude', 'y', 'lat'",
                        "default": "lat"
                    },
                    "lon_column": {
                        "type": "string",
                        "description": "Name of the longitude column (default: 'lon'). Example: 'longitude', 'x', 'lng'",
                        "default": "lon"
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Name for the imported layer (default: 'csv_import'). Example: 'sensor_locations'"
                    }
                },
                "required": ["csv_data"]
            }
        },
        {
            "name": "import_wkt",
            "description": "Import a Well-Known Text (WKT) geometry string as a layer on the map. Supports all WKT geometry types: POINT, LINESTRING, POLYGON, MULTIPOINT, MULTILINESTRING, MULTIPOLYGON, GEOMETRYCOLLECTION.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "wkt": {
                        "type": "string",
                        "description": "WKT geometry string. Example: 'POINT(-73.97 40.78)', 'POLYGON((-87.7 41.8, -87.6 41.8, -87.6 41.9, -87.7 41.9, -87.7 41.8))'. Note: WKT uses lon lat order."
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Name for the imported layer (default: 'wkt_import'). Example: 'study_area'"
                    }
                },
                "required": ["wkt"]
            }
        },
        {
            "name": "export_layer",
            "description": "Export an existing map layer to a file format. Returns GeoJSON as a string, or a file path for Shapefile/GeoPackage. Use when the user asks to download, export, or save layer data.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to export. Example: 'parks_chicago'"
                    },
                    "format": {
                        "type": "string",
                        "description": "Export format. Example: 'geojson' for web, 'shapefile' for ArcGIS/QGIS",
                        "enum": ["geojson", "shapefile", "geopackage"],
                        "default": "geojson"
                    }
                },
                "required": ["layer_name"]
            }
        },
        # ---- Phase 4: Routing Tools ----
        {
            "name": "find_route",
            "description": "Find a route between two or more locations. Returns a GeoJSON LineString with distance and duration. Supports driving, walking, and cycling profiles. Supports optional intermediate waypoints for multi-stop routes. Uses Valhalla routing engine.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "from_location": {
                        "type": "string",
                        "description": "Origin place name (will be geocoded). Example: 'Times Square, NYC'"
                    },
                    "to_location": {
                        "type": "string",
                        "description": "Destination place name (will be geocoded). Example: 'Brooklyn Bridge'"
                    },
                    "from_point": {
                        "type": "object",
                        "description": "Origin as {lat, lon}. Example: {\"lat\": 40.758, \"lon\": -73.985}",
                        "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
                        "required": ["lat", "lon"]
                    },
                    "to_point": {
                        "type": "object",
                        "description": "Destination as {lat, lon}. Example: {\"lat\": 40.706, \"lon\": -73.997}",
                        "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
                        "required": ["lat", "lon"]
                    },
                    "waypoints": {
                        "type": "array",
                        "description": "Optional intermediate stops between origin and destination. Each item has lat/lon coordinates or a location name. Example: [{\"location\": \"Empire State Building\"}]",
                        "items": {
                            "type": "object",
                            "properties": {
                                "lat": {"type": "number"},
                                "lon": {"type": "number"},
                                "location": {"type": "string"}
                            }
                        }
                    },
                    "profile": {
                        "type": "string",
                        "description": "Routing profile. Example: 'walking' for pedestrian, 'cycling' for bike routes",
                        "enum": ["driving", "walking", "cycling"],
                        "default": "driving"
                    }
                }
            }
        },
        {
            "name": "isochrone",
            "description": "Calculate the area reachable from a point within a given time or distance. Returns a true network-based isochrone polygon using the Valhalla routing engine. The result follows actual roads, not a simple circle.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "Center location name (will be geocoded). Example: 'downtown Portland', 'Union Station, Chicago'"
                    },
                    "lat": {
                        "type": "number",
                        "description": "Center latitude (north-south, -90 to 90). Example: 45.52"
                    },
                    "lon": {
                        "type": "number",
                        "description": "Center longitude (east-west, -180 to 180). Example: -122.68"
                    },
                    "time_minutes": {
                        "type": "number",
                        "description": "Travel time in minutes. Example: 15 for a 15-minute isochrone"
                    },
                    "distance_m": {
                        "type": "number",
                        "description": "Travel distance in meters (alternative to time). Example: 5000 for 5km radius"
                    },
                    "profile": {
                        "type": "string",
                        "description": "Travel profile. Example: 'walking' for pedestrian reachability",
                        "enum": ["driving", "walking", "cycling"],
                        "default": "driving"
                    }
                }
            }
        },
        {
            "name": "heatmap",
            "description": "Generate a density heatmap visualization from point features in a layer. Returns an instruction for the frontend to render a Leaflet.heat layer.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Layer containing point features to visualize as heatmap. Example: 'crime_reports', 'restaurants_nyc'"
                    },
                    "radius": {
                        "type": "integer",
                        "description": "Heatmap point radius in pixels. Example: 25 for standard density, 40 for broad spread",
                        "default": 25
                    },
                    "max_zoom": {
                        "type": "integer",
                        "description": "Zoom level at which heatmap reaches full intensity. Example: 15 for city-level, 18 for block-level",
                        "default": 15
                    }
                },
                "required": ["layer_name"]
            }
        },
        # ---- Network Analysis Tools ----
        {
            "name": "closest_facility",
            "description": "Find the nearest N features of a given type from a point. Searches using Overpass API, calculates geodesic distance from the center point to each result, and returns the closest ones sorted by distance. Each feature includes distance_m in its properties. Use for 'find the 3 nearest hospitals', 'closest pharmacies to my location'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "lat": {
                        "type": "number",
                        "description": "Center latitude (north-south, -90 to 90). Example: 40.758"
                    },
                    "lon": {
                        "type": "number",
                        "description": "Center longitude (east-west, -180 to 180). Example: -73.985"
                    },
                    "location": {
                        "type": "string",
                        "description": "Center location name (geocoded to get lat/lon if not provided). Example: 'Times Square, NYC'"
                    },
                    "feature_type": {
                        "type": "string",
                        "description": "OSM feature type to search for. Example: 'hospital', 'pharmacy', 'restaurant', 'school'"
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of nearest features to return (default 5, max 20). Example: 3",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20
                    },
                    "max_radius_m": {
                        "type": "integer",
                        "description": "Maximum search radius in meters (default 5000, max 50000). Example: 10000 for 10km",
                        "default": 5000,
                        "minimum": 1,
                        "maximum": 50000
                    },
                    "osm_key": {
                        "type": "string",
                        "description": "OSM tag key for custom queries. Example: 'amenity', 'shop'"
                    },
                    "osm_value": {
                        "type": "string",
                        "description": "OSM tag value for custom queries. Example: 'dentist', 'veterinary'"
                    }
                },
                "required": ["feature_type"]
            }
        },
        {
            "name": "optimize_route",
            "description": "Optimize the visiting order of multiple locations (traveling salesman). Takes 3-20 locations and returns the most efficient route order. Returns a GeoJSON layer with the optimized route line and ordered markers, plus distance/time savings compared to the original order. Use for 'what's the best order to visit these places', 'optimize my delivery route'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "locations": {
                        "type": "array",
                        "description": "List of locations to visit (3-20). Each item has lat/lon coordinates or a location name to geocode. Example: [{\"location\": \"Times Square\"}, {\"location\": \"Central Park\"}, {\"lat\": 40.706, \"lon\": -73.997}]",
                        "items": {
                            "type": "object",
                            "properties": {
                                "lat": {"type": "number"},
                                "lon": {"type": "number"},
                                "location": {"type": "string"}
                            }
                        },
                        "minItems": 3,
                        "maxItems": 20
                    },
                    "profile": {
                        "type": "string",
                        "description": "Routing profile. Example: 'auto' for driving, 'pedestrian' for walking",
                        "enum": ["auto", "pedestrian", "bicycle"],
                        "default": "auto"
                    }
                },
                "required": ["locations"]
            }
        },
        # ---- Overlay Operations ----
        {
            "name": "intersection",
            "description": "Compute the geometric intersection (overlay) of two layers. Returns a new layer containing only the area where both layers overlap, with new cut geometries. Use intersection for geometric overlay that produces new shapes; use spatial_query(intersects) to merely filter features that touch a target without cutting geometry.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_a": {
                        "type": "string",
                        "description": "Name of the first layer. Example: 'parks_downtown'"
                    },
                    "layer_b": {
                        "type": "string",
                        "description": "Name of the second layer. Example: 'flood_zones'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: intersection_<layer_a>_<layer_b>). Example: 'parks_in_flood_zones'"
                    }
                },
                "required": ["layer_a", "layer_b"]
            }
        },
        {
            "name": "difference",
            "description": "Subtract layer B from layer A. Returns a new layer containing the area of layer A that does NOT overlap with layer B. Useful for removing one region from another (e.g., land minus water).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_a": {
                        "type": "string",
                        "description": "Name of the layer to subtract FROM (keeps this area minus overlap). Example: 'land_use'"
                    },
                    "layer_b": {
                        "type": "string",
                        "description": "Name of the layer to subtract (area to remove). Example: 'water_bodies'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: difference_<layer_a>_<layer_b>). Example: 'land_minus_water'"
                    }
                },
                "required": ["layer_a", "layer_b"]
            }
        },
        {
            "name": "symmetric_difference",
            "description": "Compute the symmetric difference of two layers. Returns a new layer containing areas that are in EITHER layer but NOT in both. Useful for finding areas unique to each layer.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_a": {
                        "type": "string",
                        "description": "Name of the first layer. Example: 'zoning_2020'"
                    },
                    "layer_b": {
                        "type": "string",
                        "description": "Name of the second layer. Example: 'zoning_2023'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: symmetric_difference_<layer_a>_<layer_b>). Example: 'changed_zones'"
                    }
                },
                "required": ["layer_a", "layer_b"]
            }
        },
        # ---- Geometry Tools ----
        {
            "name": "convex_hull",
            "description": "Compute the convex hull (smallest enclosing convex polygon) of all features in a layer. Useful for 'draw boundary around data', 'create an envelope around crime locations', or 'show the extent of these points'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to compute convex hull for. Example: 'crime_incidents'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: convex_hull_<layer_name>). Example: 'crime_boundary'"
                    }
                },
                "required": ["layer_name"]
            }
        },
        {
            "name": "centroid",
            "description": "Extract the centroid (center point) of each feature in a layer. Returns a new point layer preserving original properties. Useful for 'get building centers', 'find center of each polygon', or converting polygons to representative points.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to extract centroids from. Example: 'buildings_downtown'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output point layer (default: centroids_<layer_name>). Example: 'building_centers'"
                    }
                },
                "required": ["layer_name"]
            }
        },
        {
            "name": "simplify",
            "description": "Simplify geometries by reducing vertex count while preserving shape. Useful for 'simplify for export', 'reduce detail level', or preparing data for web display. Higher tolerance = more simplification.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to simplify. Example: 'coastline_detailed'"
                    },
                    "tolerance": {
                        "type": "number",
                        "description": "Simplification tolerance in meters (default: 10). Higher values = more simplification. Example: 50 for moderate simplification, 200 for aggressive",
                        "default": 10,
                        "minimum": 0.1
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: simplified_<layer_name>). Example: 'coastline_simple'"
                    }
                },
                "required": ["layer_name"]
            }
        },
        {
            "name": "bounding_box",
            "description": "Create a bounding box (rectangular envelope) polygon from the extent of all features in a layer. Useful for 'show the extent of this data', 'create a rectangle around these features'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to compute bounding box for. Example: 'scattered_points'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: bbox_<layer_name>). Example: 'data_extent'"
                    }
                },
                "required": ["layer_name"]
            }
        },
        {
            "name": "dissolve",
            "description": "Merge features by a shared attribute value. All features with the same attribute value are combined into a single geometry. Useful for 'merge polygons by district', 'combine zones by type', 'aggregate boundaries by category'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to dissolve. Example: 'zoning_parcels'"
                    },
                    "by": {
                        "type": "string",
                        "description": "Attribute name to dissolve by (features with the same value are merged). Example: 'zone_type', 'district_name'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: dissolved_<layer_name>). Example: 'merged_zones'"
                    }
                },
                "required": ["layer_name", "by"]
            }
        },
        {
            "name": "clip",
            "description": "Clip one layer by another layer's boundary. Features from the clip layer are cut to the extent of the mask layer. Useful for 'cut buildings to city boundary', 'crop features to study area', 'trim data to region'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "clip_layer": {
                        "type": "string",
                        "description": "Name of the layer to clip (features to cut). Example: 'buildings_metro'"
                    },
                    "mask_layer": {
                        "type": "string",
                        "description": "Name of the layer to use as the clipping boundary. Example: 'city_limits'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: clipped_<clip_layer>). Example: 'buildings_in_city'"
                    }
                },
                "required": ["clip_layer", "mask_layer"]
            }
        },
        {
            "name": "voronoi",
            "description": "Generate a Voronoi diagram (Thiessen polygons) from point features. Each polygon contains the area closest to its source point. Useful for 'create service areas', 'nearest-facility zones', 'Thiessen polygons from stations'. Non-point features use their centroids.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the point layer to generate Voronoi diagram from. Example: 'fire_stations'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output polygon layer (default: voronoi_<layer_name>). Example: 'fire_service_areas'"
                    }
                },
                "required": ["layer_name"]
            }
        },
        # ---- Advanced Analysis Tools ----
        {
            "name": "point_in_polygon",
            "description": "Determine which polygon contains a point, or which polygons contain each point in a point layer. Use for 'which district is this point in?', 'tag each store with its census tract', 'is this coordinate inside the boundary?'. Single-point mode returns the containing polygon's properties. Batch mode returns a new point layer with containing polygon info merged into each point's properties.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "polygon_layer": {
                        "type": "string",
                        "description": "Name of the polygon layer to test against. Example: 'districts', 'census_tracts'"
                    },
                    "lat": {
                        "type": "number",
                        "description": "Latitude of a single point to test (north-south, -90 to 90). Example: 40.758"
                    },
                    "lon": {
                        "type": "number",
                        "description": "Longitude of a single point to test (east-west, -180 to 180). Example: -73.985"
                    },
                    "point_layer": {
                        "type": "string",
                        "description": "Name of a point layer to test against the polygon layer (batch mode). Example: 'store_locations'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer in batch mode (default: pip_<polygon_layer>). Example: 'stores_with_districts'"
                    }
                },
                "required": ["polygon_layer"]
            }
        },
        {
            "name": "attribute_join",
            "description": "Join tabular data to a spatial layer by matching a shared attribute. Use for 'add population data to districts', 'attach sales figures to store locations', 'enrich features with external data'. Matched fields are prefixed with 'joined_' in the output.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the spatial layer to join data to. Example: 'districts'"
                    },
                    "join_data": {
                        "type": "array",
                        "description": "Array of objects containing the data to join. Example: [{\"id\": \"A\", \"population\": 5000}, {\"id\": \"B\", \"population\": 12000}]",
                        "items": {
                            "type": "object"
                        }
                    },
                    "layer_key": {
                        "type": "string",
                        "description": "Attribute name in the layer to match on. Example: 'district_id', 'name'"
                    },
                    "data_key": {
                        "type": "string",
                        "description": "Key in join_data objects to match on. Example: 'id', 'district_id'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: joined_<layer_name>). Example: 'districts_with_population'"
                    }
                },
                "required": ["layer_name", "join_data", "layer_key", "data_key"]
            }
        },
        {
            "name": "spatial_statistics",
            "description": "Compute spatial clustering statistics for point features. Methods: nearest_neighbor (Nearest Neighbor Index — values < 1 indicate clustering, = 1 random, > 1 dispersed), dbscan (density-based clustering with eps distance and min_samples). Use for 'are these points clustered?', 'find clusters in crime data', 'identify hotspot groups'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the point layer to analyze. Example: 'crime_reports', 'restaurant_locations'"
                    },
                    "method": {
                        "type": "string",
                        "description": "Statistical method to use. Example: 'nearest_neighbor' for clustering index, 'dbscan' for cluster identification",
                        "enum": ["nearest_neighbor", "dbscan"],
                        "default": "nearest_neighbor"
                    },
                    "eps": {
                        "type": "number",
                        "description": "DBSCAN: maximum distance (meters) between two points to be considered neighbors (default: 100). Example: 200 for a 200m neighborhood",
                        "default": 100
                    },
                    "min_samples": {
                        "type": "integer",
                        "description": "DBSCAN: minimum number of points to form a cluster (default: 5). Example: 3 for small clusters",
                        "default": 5
                    }
                },
                "required": ["layer_name"]
            }
        },
        {
            "name": "hot_spot_analysis",
            "description": "Perform Getis-Ord Gi* hot spot analysis on a spatial layer. Identifies statistically significant spatial clusters of high values (hot spots) and low values (cold spots) for a numeric attribute. Returns a layer with z-scores, p-values, and hotspot classification (hot/cold/not_significant). Use for 'find crime hot spots', 'where are the highest property values clustered?', 'analyze spatial patterns of population density'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to analyze. Example: 'crime_data', 'census_tracts'"
                    },
                    "attribute": {
                        "type": "string",
                        "description": "Numeric attribute to analyze for clustering. Example: 'count', 'population', 'price'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: hotspot_<layer_name>). Example: 'crime_hotspots'"
                    }
                },
                "required": ["layer_name", "attribute"]
            }
        },
        # ---- Code Execution (Fallback) ----
        {
            "name": "execute_code",
            "description": "Execute Python code for spatial analysis operations not covered by other tools. Use as a LAST RESORT when no specific tool matches. Available libraries: shapely, geopandas, pandas, numpy, scipy, pyproj. Set a variable named 'result' (for text/data) or 'geojson' (for map layers) to return output. Input layer data is available via _input_data['layer'].",
            "input_schema": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute"
                    },
                    "input_layer": {
                        "type": "string",
                        "description": "Optional: layer name to pass as input data"
                    },
                    "output_layer": {
                        "type": "string",
                        "description": "Optional: name for output layer if code produces GeoJSON"
                    }
                },
                "required": ["code"]
            }
        }
    ]
