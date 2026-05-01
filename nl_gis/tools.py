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
            "description": "Convert geographic coordinates (latitude, longitude) into a human-readable address or place name. USE WHEN: the user provides numeric lat/lon pairs and asks 'what is at these coordinates?', 'what place is at X, Y?', 'identify this location', 'what address is this?'. Example: '40.7128, -74.0060' → reverse_geocode.",
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
            "description": "Calculate the geodesic area of polygons. USE WHEN: 'what is the total area of X?', 'how many square meters/km/acres?', 'measure the area of this region', 'size of the park layer'. Pass `layer_name` for a named existing layer (e.g., layer_name='parks'). Do not pass both layer_name and geometry. Returns area in square meters, square kilometers, and acres.",
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
        {
            "name": "import_kml",
            "description": "Import KML data as a GeoJSON layer on the map. Parses KML Placemark elements with Point, LineString, and Polygon geometries. Extracts name and description from each placemark as feature properties. Use when the user provides KML content to display on the map.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "kml_data": {
                        "type": "string",
                        "description": "Raw KML content as a string. Must contain valid KML XML with Placemark elements."
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Name for the imported layer (default: 'kml_import'). Example: 'waypoints'"
                    }
                },
                "required": ["kml_data"]
            }
        },
        {
            "name": "import_geoparquet",
            "description": "Import a GeoParquet file (base64-encoded) as a GeoJSON layer on the map. Requires geopandas and pyarrow. Use when the user provides GeoParquet data.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "parquet_data": {
                        "type": "string",
                        "description": "Base64-encoded GeoParquet file content."
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Name for the imported layer (default: 'geoparquet_import'). Example: 'parcels'"
                    }
                },
                "required": ["parquet_data"]
            }
        },
        {
            "name": "export_geoparquet",
            "description": "Export an existing map layer as GeoParquet format (returned as base64-encoded data). Requires geopandas and pyarrow. Use when the user wants to export layer data as GeoParquet.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to export. Example: 'buildings_nyc'"
                    }
                },
                "required": ["layer_name"]
            }
        },
        {
            "name": "describe_layer",
            "description": "Get summary statistics for a map layer: feature count, geometry types, bounding box, CRS, and per-attribute statistics (type, null count, unique count, min/max/mean for numeric). Use when the user asks 'describe this layer', 'what's in this layer?', or 'layer summary'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to describe. Example: 'buildings_nyc'"
                    }
                },
                "required": ["layer_name"]
            }
        },
        {
            "name": "detect_duplicates",
            "description": "Find duplicate or near-duplicate features in a layer. Detects exact geometry matches and near-duplicates (centroids within a threshold distance). Use when the user asks 'find duplicates', 'are there duplicate features?', or 'check for near-duplicates'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to check. Example: 'sensor_locations'"
                    },
                    "threshold_m": {
                        "type": "number",
                        "description": "Distance threshold in meters for near-duplicate detection (default: 1). Example: 10 for 10-meter tolerance",
                        "default": 1
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer of duplicate groups (optional)"
                    }
                },
                "required": ["layer_name"]
            }
        },
        {
            "name": "clean_layer",
            "description": "Clean a layer by removing null geometries, stripping whitespace from string properties, and removing attributes that are null for all features. Use when the user asks to 'clean data', 'fix layer', or 'remove nulls'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to clean. Example: 'raw_data'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the cleaned output layer (default: '<layer_name>_cleaned'). Example: 'clean_data'"
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
            "description": "Subtract layer B from layer A. Returns a new layer containing the area of layer A that does NOT overlap with layer B. USE WHEN: 'remove water from land', 'subtract one area from another', 'what's in A but not B', 'exclude flood zones from parks'. Keeps features OUTSIDE the mask.",
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
            "description": "Compute the convex hull (smallest enclosing convex polygon) of all features in a layer. USE WHEN: 'draw boundary around these points', 'wrap the data in a shape', 'create an envelope around crime locations', 'outline the cluster', 'show the footprint of scattered points'. Returns the tightest convex polygon — like wrapping a rubber band.",
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
            "description": "Extract the centroid (center point) of each feature in a layer. Returns a new point layer preserving original properties. USE WHEN: 'get building centers', 'find the center of each polygon', 'convert polygons to points', 'place a marker at the middle of each feature', 'representative point for each shape'. One center point per feature.",
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
            "description": "Merge features within a SINGLE layer that share an attribute value into combined geometries. USE WHEN: 'dissolve polygons by X', 'merge zones by type', 'combine districts by region', 'aggregate boundaries by category', 'collapse features with the same value'. Requires a `by` attribute. Works within ONE layer — use merge_layers to combine TWO layers.",
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
            "description": "Determine which polygon contains a point (or each point in a layer). USE WHEN: 'which district is at lat/lon?', 'is this coordinate inside the X boundary?', 'what zone is this address in?', 'tag each store with its census tract', 'assign each point to its parent polygon', 'spatial join points into polygons'. Single-point mode: provide lat + lon. Batch mode: provide point_layer. Do NOT use fetch_osm for this — point_in_polygon is the correct containment test.",
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
            "description": "Compute spatial clustering statistics for point features. USE WHEN: 'are these points clustered?', 'test for clustering', 'find clusters in crime data', 'DBSCAN these points', 'compute nearest neighbor index'. Methods: 'nearest_neighbor' (NNI — <1 clustered, 1 random, >1 dispersed — answers 'IS there clustering?'); 'dbscan' (density-based — returns cluster assignments per point — answers 'WHERE are the clusters?', requires eps and min_samples).",
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
        # ---- Spatial Analysis Depth (Milestone 1) ----
        {
            "name": "interpolate",
            "description": "Interpolate point values to create a contour surface. Takes a point layer with a numeric attribute, builds a regular grid, and generates contour polygons showing value distribution. Use for 'create elevation contours', 'interpolate temperature data', 'show value gradient across area'. Requires scipy and matplotlib.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the point layer containing values to interpolate. Example: 'weather_stations', 'soil_samples'"
                    },
                    "attribute": {
                        "type": "string",
                        "description": "Numeric attribute to interpolate. Example: 'temperature', 'elevation', 'pollution_index'"
                    },
                    "method": {
                        "type": "string",
                        "description": "Interpolation method. 'linear' for smooth gradients, 'cubic' for smoother results, 'nearest' for nearest-neighbor.",
                        "enum": ["linear", "cubic", "nearest"],
                        "default": "linear"
                    },
                    "resolution": {
                        "type": "integer",
                        "description": "Grid cells per axis (default 50, max 200). Higher = finer detail but slower. Example: 100 for detailed output",
                        "default": 50,
                        "minimum": 2,
                        "maximum": 200
                    },
                    "contour_levels": {
                        "type": "integer",
                        "description": "Number of contour levels to generate (default 10). Example: 20 for fine gradations",
                        "default": 10,
                        "minimum": 2
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output contour layer (default: interpolated_<layer_name>). Example: 'temperature_contours'"
                    }
                },
                "required": ["layer_name", "attribute"]
            }
        },
        {
            "name": "validate_topology",
            "description": "Check geometry validity for all features in a layer. Reports which features have invalid geometries (self-intersections, unclosed rings, etc.) with detailed explanations. Use for 'check if geometries are valid', 'find topology errors', 'validate layer quality'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to validate. Example: 'imported_parcels', 'building_footprints'"
                    }
                },
                "required": ["layer_name"]
            }
        },
        {
            "name": "repair_topology",
            "description": "Auto-repair invalid geometries in a layer. Uses Shapely's make_valid to fix self-intersections, unclosed rings, and other topology errors. Returns a new layer with all geometries repaired. Use after validate_topology finds errors, or proactively before analysis.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to repair. Example: 'imported_parcels', 'raw_boundaries'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output repaired layer (default: repaired_<layer_name>). Example: 'parcels_clean'"
                    }
                },
                "required": ["layer_name"]
            }
        },
        {
            "name": "service_area",
            "description": "Compute multi-facility reachability zones. Given one or more facility locations, calculates isochrone polygons for each and unions them into a single coverage area. Optionally shows gap areas (unreachable zones). Use for 'show hospital coverage', 'find areas within 15 minutes of any fire station', 'identify service gaps'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "facility_layer": {
                        "type": "string",
                        "description": "Name of a point layer containing facility locations. Example: 'fire_stations', 'hospitals'"
                    },
                    "facilities": {
                        "type": "array",
                        "description": "List of facility coordinates. Example: [{\"lat\": 40.7, \"lon\": -74.0}, {\"lat\": 40.8, \"lon\": -73.9}]",
                        "items": {
                            "type": "object",
                            "properties": {
                                "lat": {"type": "number"},
                                "lon": {"type": "number"}
                            },
                            "required": ["lat", "lon"]
                        }
                    },
                    "time_minutes": {
                        "type": "number",
                        "description": "Travel time in minutes for reachability. Example: 15 for 15-minute service area"
                    },
                    "distance_m": {
                        "type": "number",
                        "description": "Travel distance in meters (alternative to time). Example: 5000 for 5km service area"
                    },
                    "profile": {
                        "type": "string",
                        "description": "Travel profile for isochrone computation.",
                        "enum": ["auto", "pedestrian", "bicycle"],
                        "default": "auto"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: 'service_area'). Example: 'hospital_coverage_15min'"
                    },
                    "show_gaps": {
                        "type": "boolean",
                        "description": "If true, include gap polygons showing unreachable areas within the facility bounding box. Default: false",
                        "default": False
                    }
                }
            }
        },
        # ---- Coordinate Tools (Milestone 5.1) ----
        {
            "name": "reproject_layer",
            "description": "Add CRS metadata to a layer. Display stays in WGS84, but adds source_crs property to all features indicating the original coordinate reference system. Use when the user says 'this layer is in EPSG:32632' or wants to tag a layer's CRS.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Layer to add CRS metadata to. Example: 'buildings'"
                    },
                    "from_crs": {
                        "type": "integer",
                        "description": "Source EPSG code. Example: 32632 for UTM zone 32N"
                    },
                    "to_crs": {
                        "type": "integer",
                        "description": "Target EPSG code (default 4326 WGS84). Example: 4326",
                        "default": 4326
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer. Example: 'buildings_wgs84'"
                    }
                },
                "required": ["layer_name", "from_crs"]
            }
        },
        {
            "name": "detect_crs",
            "description": "Heuristically detect the coordinate reference system of a layer by examining coordinate ranges. If all coordinates fall within [-180,180] x [-90,90], reports WGS84 (EPSG:4326). If coordinates exceed these ranges, reports likely projected CRS.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Layer to detect CRS for. Example: 'imported_data'"
                    }
                },
                "required": ["layer_name"]
            }
        },
        # ---- Advanced Network (Milestone 5.2) ----
        {
            "name": "od_matrix",
            "description": "Compute an origin-destination cost matrix. Returns distances (in meters) between all origin-destination pairs. Uses geodesic distance calculations. Use for 'distance matrix from warehouses to customers', 'travel costs between locations'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "origins": {
                        "type": "array",
                        "description": "Array of origin points. Each can have {lat, lon} or {location}.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "lat": {"type": "number"},
                                "lon": {"type": "number"},
                                "location": {"type": "string"}
                            }
                        }
                    },
                    "destinations": {
                        "type": "array",
                        "description": "Array of destination points. Each can have {lat, lon} or {location}.",
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
                        "description": "Travel profile (used for labeling; distances are geodesic).",
                        "enum": ["driving", "walking", "cycling"],
                        "default": "driving"
                    }
                },
                "required": ["origins", "destinations"]
            }
        },
        # ---- Geometry Editing (Milestone 5.3) ----
        {
            "name": "split_feature",
            "description": "Split a polygon feature by a line. Uses shapely.ops.split to divide a polygon into two or more parts along the given line. Use for 'cut this parcel in half', 'split along this road'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Layer containing the polygon to split. Example: 'parcels'"
                    },
                    "feature_index": {
                        "type": "integer",
                        "description": "Index of the feature to split (0-based). Example: 0 for the first feature"
                    },
                    "split_line": {
                        "type": "object",
                        "description": "GeoJSON LineString geometry to split by. Example: {\"type\": \"LineString\", \"coordinates\": [[0,0],[1,1]]}"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer. Example: 'split_parcels'"
                    }
                },
                "required": ["layer_name", "feature_index", "split_line"]
            }
        },
        {
            "name": "merge_features",
            "description": "Merge features within a layer by attribute value. Groups features that share the same value for a given attribute and unions their geometries. Simpler than dissolve — just unions geometries with matching attribute values. Use for 'merge polygons by zone type', 'combine features by category'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Layer containing features to merge. Example: 'zones'"
                    },
                    "by": {
                        "type": "string",
                        "description": "Attribute name to group by. Example: 'zone_type'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer. Example: 'merged_zones'"
                    }
                },
                "required": ["layer_name", "by"]
            }
        },
        {
            "name": "extract_vertices",
            "description": "Convert polygon or line boundaries to a point layer. Extracts all vertex coordinates from geometries and creates a point feature for each. Use for 'show polygon corners', 'extract boundary points'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Layer to extract vertices from. Example: 'buildings'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output point layer. Example: 'building_vertices'"
                    }
                },
                "required": ["layer_name"]
            }
        },
        # ---- Temporal & Attribute (Milestone 5.4) ----
        {
            "name": "temporal_filter",
            "description": "Filter features by a date attribute. Keeps features whose date value falls within the specified range. Use for 'show events after 2023-01-01', 'filter records between two dates'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Layer to filter. Example: 'events'"
                    },
                    "date_attribute": {
                        "type": "string",
                        "description": "Name of the date attribute in feature properties. Example: 'event_date'"
                    },
                    "after": {
                        "type": "string",
                        "description": "ISO date string for lower bound (inclusive). Example: '2023-01-01'"
                    },
                    "before": {
                        "type": "string",
                        "description": "ISO date string for upper bound (inclusive). Example: '2023-12-31'"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer. Example: 'events_2023'"
                    }
                },
                "required": ["layer_name", "date_attribute"]
            }
        },
        {
            "name": "attribute_statistics",
            "description": "Compute detailed statistics for a numeric attribute in a layer. Returns min, max, mean, median, standard deviation, percentiles (25th/50th/75th), and a histogram with 10 bins. Use for 'statistics for population', 'distribution of building heights'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Layer to analyze. Example: 'buildings'"
                    },
                    "attribute": {
                        "type": "string",
                        "description": "Numeric attribute to compute statistics for. Example: 'height'"
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
        },
        # --- Raster analysis (v2.1 Plan 08) ---
        {
            "name": "raster_info",
            "description": "Get metadata for a raster file (CRS, resolution, bounds in WGS84, band count, dtype). Call with no arguments to LIST available rasters in the configured raster directory. USE WHEN: 'what rasters are available?', 'show info about chicago_utm.tif', 'what CRS is this DEM in?'",
            "input_schema": {
                "type": "object",
                "properties": {
                    "raster": {
                        "type": "string",
                        "description": "Raster filename (e.g. 'chicago_utm.tif'). Omit to list available rasters.",
                    }
                },
            },
        },
        {
            "name": "raster_value",
            "description": "Sample the raster value at a single point. USE WHEN: 'what's the elevation at X?', 'what pixel value is at lat/lon?', 'elevation of Times Square'. Provide lat + lon OR a location name (which will be geocoded).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "raster": {"type": "string", "description": "Raster filename. Example: 'chicago_utm.tif'"},
                    "lat": {"type": "number", "description": "Latitude (WGS84)."},
                    "lon": {"type": "number", "description": "Longitude (WGS84)."},
                    "location": {"type": "string", "description": "Place name to geocode (alternative to lat/lon)."},
                },
                "required": ["raster"],
            },
        },
        {
            "name": "raster_statistics",
            "description": "Compute statistics (min/max/mean/std/median) for a raster band. Optionally compute zonal statistics per polygon by passing `layer_name`. Also supports DEM derivatives via `derivative` ('slope', 'aspect', 'hillshade') which are computed from elevation before statistics. USE WHEN: 'mean elevation of the parks', 'slope statistics for this area', 'min/max pixel values'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "raster": {"type": "string", "description": "Raster filename. Required."},
                    "band": {"type": "integer", "description": "Band number (default 1).", "default": 1},
                    "layer_name": {"type": "string", "description": "Polygon layer for zonal stats (optional)."},
                    "derivative": {
                        "type": "string",
                        "description": "Optional DEM derivative: 'slope' (degrees), 'aspect' (0-360°), 'hillshade' (0-255).",
                        "enum": ["slope", "aspect", "hillshade"],
                    },
                },
                "required": ["raster"],
            },
        },
        {
            "name": "raster_profile",
            "description": "Extract a value profile along a line between two points. USE WHEN: 'elevation profile from A to B', 'cross-section between X and Y', 'sample values along this transect'. Returns sampled values at `num_samples` evenly-spaced points plus a GeoJSON LineString visualization.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "raster": {"type": "string", "description": "Raster filename. Required."},
                    "from_point": {
                        "type": "object",
                        "description": "Origin as {lat, lon}. Alternative: from_location.",
                        "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
                    },
                    "to_point": {
                        "type": "object",
                        "description": "Destination as {lat, lon}. Alternative: to_location.",
                        "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
                    },
                    "from_location": {"type": "string", "description": "Origin place name."},
                    "to_location": {"type": "string", "description": "Destination place name."},
                    "num_samples": {"type": "integer", "description": "Sample count (2-500, default 100).", "default": 100},
                },
                "required": ["raster"],
            },
        },
        # --- Data pipeline (v2.1 Plan 10) ---
        {
            "name": "clip_to_bbox",
            "description": "Clip a layer to a bounding box. Features outside are removed; features crossing the boundary are trimmed. USE WHEN: 'clip this layer to Chicago', 'keep only features in the bbox'. Provide either an explicit bbox [south, west, north, east] OR a location name (which will be geocoded to its bbox).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {"type": "string", "description": "Layer to clip. Example: 'buildings_all'"},
                    "bbox": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4, "maxItems": 4,
                        "description": "Bounding box [south, west, north, east].",
                    },
                    "location": {"type": "string", "description": "Alternative to bbox — a place name to geocode."},
                    "output_name": {"type": "string", "description": "Output layer name (optional)."},
                },
                "required": ["layer_name"],
            },
        },
        {
            "name": "generalize",
            "description": "Simplify geometries by a tolerance in METERS. Reports vertex reduction statistics. USE WHEN: 'simplify for export', 'reduce file size', 'lighten geometry for rendering'. Differs from 'simplify' by accepting meters directly (converts to CRS degrees using layer centroid latitude).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {"type": "string", "description": "Layer to generalize. Required."},
                    "tolerance": {"type": "number", "description": "Tolerance in meters. Example: 50 for 50m simplification."},
                    "preserve_topology": {"type": "boolean", "description": "Preserve topology (default true).", "default": True},
                    "output_name": {"type": "string", "description": "Output layer name (optional)."},
                },
                "required": ["layer_name", "tolerance"],
            },
        },
        {
            "name": "export_gpkg",
            "description": "Export a layer as GeoPackage (.gpkg) — preferred over shapefile for modern workflows (supports CRS metadata, large datasets, multiple geometry types). USE WHEN: 'export as GeoPackage', 'download as gpkg'. Falls back to GeoJSON if GDAL's GPKG driver isn't available.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {"type": "string", "description": "Layer to export. Required."},
                    "filename": {"type": "string", "description": "Suggested filename (default '<layer>.gpkg')."},
                },
                "required": ["layer_name"],
            },
        },
        {
            "name": "import_auto",
            "description": "Import spatial data with automatic format detection. Detects GeoJSON (from '{'), CSV (lat/lon header), KML (<?xml/<kml), WKT (POINT/POLYGON...), Shapefile (base64 zip), GeoParquet (base64 PAR1). USE WHEN: user provides raw data without specifying the format.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "data": {"type": "string", "description": "Raw content (text for GeoJSON/KML/WKT/CSV, base64 for Shapefile/GeoParquet)."},
                    "layer_name": {"type": "string", "description": "Optional layer name for the import."},
                    "lat_column": {"type": "string", "description": "CSV only: latitude column name (default 'lat')."},
                    "lon_column": {"type": "string", "description": "CSV only: longitude column name (default 'lon')."},
                },
                "required": ["data"],
            },
        },
        {
            "name": "raster_classify",
            "description": "Reclassify a raster into discrete polygon categories using breakpoints. USE WHEN: 'classify elevation into low/medium/high', 'show terrain categories', 'vectorize the DEM into zones'. Returns a polygon layer with one feature per contiguous classified region.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "raster": {"type": "string", "description": "Raster filename. Required."},
                    "breaks": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Sorted breakpoints. Example: [0, 100, 500] creates classes <0, 0-100, 100-500, >500.",
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional human-readable labels per class.",
                    },
                    "band": {"type": "integer", "description": "Band number (default 1).", "default": 1},
                },
                "required": ["raster", "breaks"],
            },
        },
        # v2.1 Plan 11: visualization
        {
            "name": "choropleth_map",
            "description": "Color a layer by a numeric attribute split into class breaks. USE WHEN: 'color neighborhoods by population', 'map by income', 'shade tracts by density'. Returns class breaks, a per-feature color map, and legend metadata. Prefer this over `style_layer` when the user wants graduated/classified colors.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {"type": "string", "description": "Layer to classify. Required."},
                    "attribute": {"type": "string", "description": "Numeric attribute to classify on. Required."},
                    "method": {
                        "type": "string",
                        "enum": ["quantile", "equal_interval", "natural_breaks", "manual"],
                        "description": "Classification method. Default 'quantile'. 'natural_breaks' uses jenkspy if available; falls back to quantile.",
                    },
                    "color_ramp": {
                        "description": "Named ramp ('sequential', 'diverging', 'qualitative') or a custom hex array.",
                    },
                    "num_classes": {"type": "integer", "minimum": 2, "maximum": 9, "description": "Number of classes (2-9). Default 5."},
                    "breaks": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Manual breaks (used only when method='manual'). Must be sorted ascending.",
                    },
                },
                "required": ["layer_name", "attribute"],
            },
        },
        {
            "name": "chart",
            "description": "Aggregate layer attributes into a chart dataset (bar, pie, histogram, scatter) ready for Chart.js rendering. USE WHEN: 'pie chart of building types', 'histogram of road lengths', 'scatter plot of area vs population', 'bar chart by category'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {"type": "string", "description": "Layer with the attributes."},
                    "attribute": {"type": "string", "description": "Primary attribute (Y-axis for bar/pie/scatter; values for histogram)."},
                    "chart_type": {"type": "string", "enum": ["bar", "pie", "histogram", "scatter"]},
                    "group_by": {"type": "string", "description": "bar/pie only: attribute to group rows by (defaults to `attribute`)."},
                    "aggregation": {"type": "string", "enum": ["count", "sum", "mean"], "description": "bar/pie only: how to reduce within a group. Default 'count'."},
                    "x_attribute": {"type": "string", "description": "scatter only: X-axis attribute."},
                    "num_bins": {"type": "integer", "description": "histogram only: bin count. Default 10."},
                },
                "required": ["layer_name", "attribute", "chart_type"],
            },
        },
        {
            "name": "animate_layer",
            "description": "Group features by a temporal attribute into ordered time steps for animation. USE WHEN: 'animate permits 2020-2024', 'show how cases spread over time', 'play through monthly snapshots'. Returns time_steps with feature indices the frontend animates through. Caps at 100 unique steps; bins above that.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {"type": "string"},
                    "time_attribute": {"type": "string", "description": "Property holding a date/time value."},
                    "interval_ms": {"type": "integer", "description": "Animation step duration in ms (default 1000)."},
                    "cumulative": {"type": "boolean", "description": "If true, each step shows all features up to and including that time."},
                },
                "required": ["layer_name", "time_attribute"],
            },
        },
        {
            "name": "visualize_3d",
            "description": "Annotate polygon features with a computed `_height_m` for 3D extrusion (rendered by OSMBuildings or deck.gl on the frontend). USE WHEN: 'show buildings in 3D', 'extrude by height', '3D footprints'. Falls back to building:levels * multiplier, then a default_height.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {"type": "string"},
                    "height_attribute": {"type": "string", "description": "Property name with the height in meters (default 'height')."},
                    "height_multiplier": {"type": "number", "description": "Multiplier when falling back to building:levels (default 3.0)."},
                    "default_height": {"type": "number", "description": "Fallback height in meters (default 10)."},
                },
                "required": ["layer_name"],
            },
        },
    ]
