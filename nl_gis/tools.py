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
            "description": "Fetch OpenStreetMap features within a bounding box or near a location. Returns a GeoJSON FeatureCollection displayed as a named layer. Built-in types: building, forest, water, park, grass, farmland, residential, commercial, industrial, road, river, lake, restaurant, school, hospital, pharmacy, supermarket, hotel, church, mosque, bank, atm, cafe, bar, cinema, library, university, police, fire_station, post_office, bus_stop, rail, parking, fuel, playground, stadium, swimming_pool, cemetery, wetland, beach, cliff. For unlisted types, use osm_key and osm_value for custom Overpass queries.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "feature_type": {
                        "type": "string",
                        "description": "Type of OSM feature to fetch (use a built-in name or a custom name with osm_key/osm_value)"
                    },
                    "category_name": {
                        "type": "string",
                        "description": "Label to assign to fetched features (e.g., 'chicago_buildings', 'berlin_parks')"
                    },
                    "bbox": {
                        "type": "string",
                        "description": "Bounding box as 'south,west,north,east'. If not provided, you must provide location instead."
                    },
                    "location": {
                        "type": "string",
                        "description": "Place name to use as the search area. Will be geocoded to get a bounding box. Use if bbox is not available."
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
                        "description": "Latitude of the point to reverse geocode"
                    },
                    "lon": {
                        "type": "number",
                        "description": "Longitude of the point to reverse geocode"
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
                        "description": "List of addresses or place names to geocode (max 50)"
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Name for the output point layer (default: 'geocoded_points')"
                    }
                },
                "required": ["addresses"]
            }
        },
        {
            "name": "map_command",
            "description": "Control the map view: pan to coordinates, set zoom level, fit to bounding box, or change basemap. Use this to navigate the map based on user requests.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Map action to perform",
                        "enum": ["pan", "zoom", "pan_and_zoom", "fit_bounds", "change_basemap"]
                    },
                    "lat": {
                        "type": "number",
                        "description": "Latitude for pan action"
                    },
                    "lon": {
                        "type": "number",
                        "description": "Longitude for pan action"
                    },
                    "zoom": {
                        "type": "integer",
                        "description": "Zoom level (1-20). Higher = more zoomed in.",
                        "minimum": 1,
                        "maximum": 20
                    },
                    "bbox": {
                        "type": "array",
                        "description": "Bounding box [south, west, north, east] for fit_bounds action",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4
                    },
                    "basemap": {
                        "type": "string",
                        "description": "Basemap style",
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
                        "description": "Name of an existing map layer to calculate area for"
                    },
                    "geometry": {
                        "type": "object",
                        "description": "GeoJSON geometry (Polygon or MultiPolygon) to calculate area of"
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
                        "description": "Start point as {\"lat\": number, \"lon\": number}",
                        "properties": {
                            "lat": {"type": "number"},
                            "lon": {"type": "number"}
                        },
                        "required": ["lat", "lon"]
                    },
                    "to_point": {
                        "type": "object",
                        "description": "End point as {\"lat\": number, \"lon\": number}",
                        "properties": {
                            "lat": {"type": "number"},
                            "lon": {"type": "number"}
                        },
                        "required": ["lat", "lon"]
                    },
                    "from_location": {
                        "type": "string",
                        "description": "Start location name (geocoded automatically)"
                    },
                    "to_location": {
                        "type": "string",
                        "description": "End location name (geocoded automatically)"
                    }
                }
            }
        },
        # ---- Phase 2: Spatial Analysis Tools ----
        {
            "name": "buffer",
            "description": "Create a buffer polygon around a geometry or all features in a named layer. The buffer distance is in meters. Returns a GeoJSON polygon that is added as a new layer on the map.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of an existing layer to buffer"
                    },
                    "geometry": {
                        "type": "object",
                        "description": "GeoJSON geometry to buffer (alternative to layer_name)"
                    },
                    "distance_m": {
                        "type": "number",
                        "description": "Buffer distance in meters (max 100,000 = 100km)",
                        "minimum": 1,
                        "maximum": 100000
                    }
                },
                "required": ["distance_m"]
            }
        },
        {
            "name": "spatial_query",
            "description": "Find features in one layer that match a spatial relationship with another layer or geometry. Predicates: intersects (any overlap between source feature and target), contains (source feature fully encloses the target geometry), within (source feature is fully inside the target geometry), within_distance (source feature is within N meters of target).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_layer": {
                        "type": "string",
                        "description": "Layer to query features FROM"
                    },
                    "predicate": {
                        "type": "string",
                        "description": "Spatial relationship to test",
                        "enum": ["intersects", "contains", "within", "within_distance"]
                    },
                    "target_layer": {
                        "type": "string",
                        "description": "Layer to compare AGAINST"
                    },
                    "target_geometry": {
                        "type": "object",
                        "description": "GeoJSON geometry to compare against (alternative to target_layer)"
                    },
                    "distance_m": {
                        "type": "number",
                        "description": "Distance in meters (required for within_distance predicate)"
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
                        "description": "Name of the layer to aggregate"
                    },
                    "operation": {
                        "type": "string",
                        "description": "Operation to perform: count (number of features), area (total geodesic area in sq meters)",
                        "enum": ["count", "area", "group_by"]
                    },
                    "group_by": {
                        "type": "string",
                        "description": "Property name to group by (for group_by operation)"
                    }
                },
                "required": ["layer_name", "operation"]
            }
        },
        {
            "name": "search_nearby",
            "description": "Search for OSM features near a point within a given radius. Uses Overpass API 'around' filter. Returns a GeoJSON FeatureCollection added as a map layer. Supports 35+ built-in feature types plus custom osm_key/osm_value queries.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "lat": {
                        "type": "number",
                        "description": "Center latitude"
                    },
                    "lon": {
                        "type": "number",
                        "description": "Center longitude"
                    },
                    "location": {
                        "type": "string",
                        "description": "Place name (geocoded to get lat/lon if not provided)"
                    },
                    "radius_m": {
                        "type": "number",
                        "description": "Search radius in meters (max 50,000 = 50km)",
                        "default": 500,
                        "minimum": 1,
                        "maximum": 50000
                    },
                    "feature_type": {
                        "type": "string",
                        "description": "OSM feature type to search for (use a built-in name or a custom name with osm_key/osm_value)"
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
                "required": ["feature_type"]
            }
        },
        {
            "name": "show_layer",
            "description": "Make a hidden layer visible on the map.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to show"
                    }
                },
                "required": ["layer_name"]
            }
        },
        {
            "name": "hide_layer",
            "description": "Hide a layer from the map without deleting it.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to hide"
                    }
                },
                "required": ["layer_name"]
            }
        },
        {
            "name": "remove_layer",
            "description": "Remove a layer from the map permanently.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Name of the layer to remove"
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
                        "description": "Name of the layer containing features to highlight"
                    },
                    "attribute": {
                        "type": "string",
                        "description": "Property name to match on (e.g., 'category_name', 'feature_type')"
                    },
                    "value": {
                        "type": "string",
                        "description": "Value to match (e.g., 'residential', 'forest')"
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
                        "description": "Name of the layer to filter"
                    },
                    "attribute": {
                        "type": "string",
                        "description": "Property name to filter on (e.g., 'feature_type', 'category_name', or any OSM tag key)"
                    },
                    "operator": {
                        "type": "string",
                        "description": "Comparison operator. Numeric operators: greater_than, less_than, greater_equal, less_equal, between (value as 'min,max').",
                        "enum": ["equals", "not_equals", "contains", "starts_with", "greater_than", "less_than", "greater_equal", "less_equal", "between"]
                    },
                    "value": {
                        "type": "string",
                        "description": "Value to compare against"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the filtered output layer"
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
                        "description": "Name of the layer to style"
                    },
                    "color": {
                        "type": "string",
                        "description": "Outline/stroke color as hex (e.g., '#ff0000' for red, '#00ff00' for green)"
                    },
                    "fill_color": {
                        "type": "string",
                        "description": "Fill color as hex (defaults to same as color)"
                    },
                    "weight": {
                        "type": "number",
                        "description": "Line/border thickness in pixels (1-10)",
                        "minimum": 1,
                        "maximum": 10
                    },
                    "fill_opacity": {
                        "type": "number",
                        "description": "Fill opacity (0.0 = transparent, 1.0 = opaque)",
                        "minimum": 0,
                        "maximum": 1
                    },
                    "opacity": {
                        "type": "number",
                        "description": "Stroke opacity (0.0 = transparent, 1.0 = opaque)",
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
            "description": "Save a geometry as an annotation with a category name and color. Use this to label features on the map.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "geometry": {
                        "type": "object",
                        "description": "GeoJSON geometry to annotate"
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Name of an existing layer whose features to annotate (alternative to geometry)"
                    },
                    "category_name": {
                        "type": "string",
                        "description": "Category label for the annotation (e.g., 'farmland', 'residential')"
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
                        "description": "Place name to classify (e.g., 'Portland, Oregon')"
                    },
                    "bbox": {
                        "type": "object",
                        "description": "Bounding box {north, south, east, west}",
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
                        "description": "Filter to specific classes (default: all)",
                        "items": {"type": "string"}
                    }
                }
            }
        },
        {
            "name": "export_annotations",
            "description": "Export all current annotations to a file. Supported formats: geojson, shapefile, geopackage. Returns a download link.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "description": "Export format",
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
                        "description": "First layer name"
                    },
                    "layer_b": {
                        "type": "string",
                        "description": "Second layer name"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the merged output layer"
                    },
                    "operation": {
                        "type": "string",
                        "description": "Merge operation: 'union' combines all features, 'spatial_join' transfers attributes from layer_b to layer_a based on spatial overlap",
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
                        "description": "GeoJSON FeatureCollection to import directly as a layer"
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Name for the imported layer"
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
                        "description": "CSV content as a string (header row + data rows)"
                    },
                    "lat_column": {
                        "type": "string",
                        "description": "Name of the latitude column (default: 'lat')",
                        "default": "lat"
                    },
                    "lon_column": {
                        "type": "string",
                        "description": "Name of the longitude column (default: 'lon')",
                        "default": "lon"
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Name for the imported layer (default: 'csv_import')"
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
                        "description": "WKT geometry string (e.g., 'POLYGON((...))', 'POINT(lon lat)')"
                    },
                    "layer_name": {
                        "type": "string",
                        "description": "Name for the imported layer (default: 'wkt_import')"
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
                        "description": "Name of the layer to export"
                    },
                    "format": {
                        "type": "string",
                        "description": "Export format",
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
                        "description": "Origin place name (will be geocoded)"
                    },
                    "to_location": {
                        "type": "string",
                        "description": "Destination place name (will be geocoded)"
                    },
                    "from_point": {
                        "type": "object",
                        "description": "Origin as {lat, lon}",
                        "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
                        "required": ["lat", "lon"]
                    },
                    "to_point": {
                        "type": "object",
                        "description": "Destination as {lat, lon}",
                        "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
                        "required": ["lat", "lon"]
                    },
                    "waypoints": {
                        "type": "array",
                        "description": "Optional intermediate stops between origin and destination. Each item has lat/lon coordinates or a location name to be geocoded.",
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
                        "description": "Routing profile",
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
                        "description": "Center location name (will be geocoded)"
                    },
                    "lat": {
                        "type": "number",
                        "description": "Center latitude"
                    },
                    "lon": {
                        "type": "number",
                        "description": "Center longitude"
                    },
                    "time_minutes": {
                        "type": "number",
                        "description": "Travel time in minutes"
                    },
                    "distance_m": {
                        "type": "number",
                        "description": "Travel distance in meters (alternative to time)"
                    },
                    "profile": {
                        "type": "string",
                        "description": "Travel profile",
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
                        "description": "Layer containing features to visualize as heatmap"
                    },
                    "radius": {
                        "type": "integer",
                        "description": "Heatmap point radius in pixels",
                        "default": 25
                    },
                    "max_zoom": {
                        "type": "integer",
                        "description": "Zoom level at which heatmap reaches full intensity",
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
                        "description": "Center latitude"
                    },
                    "lon": {
                        "type": "number",
                        "description": "Center longitude"
                    },
                    "location": {
                        "type": "string",
                        "description": "Center location name (geocoded to get lat/lon if not provided)"
                    },
                    "feature_type": {
                        "type": "string",
                        "description": "OSM feature type to search for (e.g., 'hospital', 'pharmacy', 'restaurant')"
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of nearest features to return (default 5, max 20)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20
                    },
                    "max_radius_m": {
                        "type": "integer",
                        "description": "Maximum search radius in meters (default 5000, max 50000)",
                        "default": 5000,
                        "minimum": 1,
                        "maximum": 50000
                    },
                    "osm_key": {
                        "type": "string",
                        "description": "OSM tag key for custom queries"
                    },
                    "osm_value": {
                        "type": "string",
                        "description": "OSM tag value for custom queries"
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
                        "description": "List of locations to visit. Each item has lat/lon coordinates or a location name to geocode.",
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
                        "description": "Routing profile",
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
            "description": "Compute the geometric intersection of two layers. Returns a new layer containing only the area where both layers overlap. Useful for finding where two regions coincide (e.g., parks in flood zones).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer_a": {
                        "type": "string",
                        "description": "Name of the first layer"
                    },
                    "layer_b": {
                        "type": "string",
                        "description": "Name of the second layer"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: intersection_<layer_a>_<layer_b>)"
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
                        "description": "Name of the layer to subtract FROM"
                    },
                    "layer_b": {
                        "type": "string",
                        "description": "Name of the layer to subtract"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: difference_<layer_a>_<layer_b>)"
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
                        "description": "Name of the first layer"
                    },
                    "layer_b": {
                        "type": "string",
                        "description": "Name of the second layer"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: symmetric_difference_<layer_a>_<layer_b>)"
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
                        "description": "Name of the layer to compute convex hull for"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: convex_hull_<layer_name>)"
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
                        "description": "Name of the layer to extract centroids from"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output point layer (default: centroids_<layer_name>)"
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
                        "description": "Name of the layer to simplify"
                    },
                    "tolerance": {
                        "type": "number",
                        "description": "Simplification tolerance in meters (default: 10). Higher values = more simplification.",
                        "default": 10,
                        "minimum": 0.1
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: simplified_<layer_name>)"
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
                        "description": "Name of the layer to compute bounding box for"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: bbox_<layer_name>)"
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
                        "description": "Name of the layer to dissolve"
                    },
                    "by": {
                        "type": "string",
                        "description": "Attribute name to dissolve by (features with the same value are merged)"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: dissolved_<layer_name>)"
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
                        "description": "Name of the layer to clip (features to cut)"
                    },
                    "mask_layer": {
                        "type": "string",
                        "description": "Name of the layer to use as the clipping boundary"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: clipped_<clip_layer>)"
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
                        "description": "Name of the point layer to generate Voronoi diagram from"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output polygon layer (default: voronoi_<layer_name>)"
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
                        "description": "Name of the polygon layer to test against"
                    },
                    "lat": {
                        "type": "number",
                        "description": "Latitude of a single point to test (use with lon)"
                    },
                    "lon": {
                        "type": "number",
                        "description": "Longitude of a single point to test (use with lat)"
                    },
                    "point_layer": {
                        "type": "string",
                        "description": "Name of a point layer to test against the polygon layer (batch mode)"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer in batch mode (default: pip_<polygon_layer>)"
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
                        "description": "Name of the spatial layer to join data to"
                    },
                    "join_data": {
                        "type": "array",
                        "description": "Array of objects containing the data to join (e.g., [{\"id\": \"A\", \"population\": 5000}, ...])",
                        "items": {
                            "type": "object"
                        }
                    },
                    "layer_key": {
                        "type": "string",
                        "description": "Attribute name in the layer to match on (e.g., 'district_id')"
                    },
                    "data_key": {
                        "type": "string",
                        "description": "Key in join_data objects to match on (e.g., 'id')"
                    },
                    "output_name": {
                        "type": "string",
                        "description": "Name for the output layer (default: joined_<layer_name>)"
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
                        "description": "Name of the point layer to analyze"
                    },
                    "method": {
                        "type": "string",
                        "description": "Statistical method to use",
                        "enum": ["nearest_neighbor", "dbscan"],
                        "default": "nearest_neighbor"
                    },
                    "eps": {
                        "type": "number",
                        "description": "DBSCAN: maximum distance (meters) between two points to be considered neighbors (default: 100)",
                        "default": 100
                    },
                    "min_samples": {
                        "type": "integer",
                        "description": "DBSCAN: minimum number of points to form a cluster (default: 5)",
                        "default": 5
                    }
                },
                "required": ["layer_name"]
            }
        }
    ]
