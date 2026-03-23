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
            "description": "Fetch OpenStreetMap features within a bounding box or near a location. Returns a GeoJSON FeatureCollection that is displayed as a named layer on the map. Available feature types: building, forest, water, park, grass, farmland, residential, commercial, industrial, road, river, lake.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "feature_type": {
                        "type": "string",
                        "description": "Type of OSM feature to fetch",
                        "enum": ["building", "forest", "water", "park", "grass", "farmland", "residential", "commercial", "industrial", "road", "river", "lake"]
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
                    }
                },
                "required": ["feature_type", "category_name"]
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
                        }
                    },
                    "to_point": {
                        "type": "object",
                        "description": "End point as {\"lat\": number, \"lon\": number}",
                        "properties": {
                            "lat": {"type": "number"},
                            "lon": {"type": "number"}
                        }
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
        }
    ]
