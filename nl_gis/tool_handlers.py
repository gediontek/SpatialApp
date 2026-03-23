"""Tool handler implementations for NL-to-GIS operations."""

import json
import logging
import urllib.request
import urllib.parse

import requests
from shapely.geometry import shape

from config import Config
from nl_gis.geo_utils import (
    ValidatedPoint,
    geodesic_area,
    geodesic_distance,
    geojson_to_shapely,
)

logger = logging.getLogger(__name__)

# Reuse OSM feature mappings from app.py
OSM_FEATURE_MAPPINGS = {
    'building': {'key': 'building', 'value': None},
    'forest': {'key': 'landuse', 'value': 'forest'},
    'water': {'key': 'natural', 'value': 'water'},
    'park': {'key': 'leisure', 'value': 'park'},
    'grass': {'key': 'landuse', 'value': 'grass'},
    'farmland': {'key': 'landuse', 'value': 'farmland'},
    'residential': {'key': 'landuse', 'value': 'residential'},
    'commercial': {'key': 'landuse', 'value': 'commercial'},
    'industrial': {'key': 'landuse', 'value': 'industrial'},
    'road': {'key': 'highway', 'value': None},
    'river': {'key': 'waterway', 'value': 'river'},
    'lake': {'key': 'natural', 'value': 'water'},
}


def dispatch_tool(tool_name: str, params: dict, layer_store: dict = None) -> dict:
    """Route a tool call to the appropriate handler.

    Args:
        tool_name: Name of the tool to call.
        params: Tool input parameters.
        layer_store: Server-side layer store for cross-tool references.

    Returns:
        Tool result as a dictionary.

    Raises:
        ValueError: If tool_name is unknown.
    """
    handlers = {
        "geocode": handle_geocode,
        "fetch_osm": handle_fetch_osm,
        "map_command": handle_map_command,
        "calculate_area": lambda p: handle_calculate_area(p, layer_store),
        "measure_distance": handle_measure_distance,
    }

    if tool_name not in handlers:
        raise ValueError(f"Unknown tool: {tool_name}")

    return handlers[tool_name](params)


def handle_geocode(params: dict) -> dict:
    """Geocode a place name using Nominatim.

    Returns:
        Dict with lat, lon, display_name, bbox.
    """
    query = params.get("query", "")
    if not query:
        return {"error": "No query provided"}

    try:
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "SpatialLabeler/1.0"})

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())

        if not data:
            return {"error": f"Location not found: {query}"}

        result = data[0]
        bbox = result.get("boundingbox", [])

        return {
            "lat": float(result["lat"]),
            "lon": float(result["lon"]),
            "display_name": result["display_name"],
            "bbox": [float(b) for b in bbox] if bbox else None,
        }
    except Exception as e:
        logger.error(f"Geocoding error: {e}")
        return {"error": f"Geocoding failed: {str(e)}"}


def handle_fetch_osm(params: dict) -> dict:
    """Fetch OSM features via Overpass API.

    Returns:
        GeoJSON FeatureCollection with fetched features,
        plus metadata (feature_count, layer_name).
    """
    feature_type = params.get("feature_type", "building")
    category_name = params.get("category_name", feature_type)
    bbox = params.get("bbox")
    location = params.get("location")

    # If no bbox but location given, geocode to get bbox
    if not bbox and location:
        geo_result = handle_geocode({"query": location})
        if "error" in geo_result:
            return geo_result
        # Nominatim bbox is [south_lat, north_lat, west_lon, east_lon]
        nom_bbox = geo_result.get("bbox")
        if nom_bbox and len(nom_bbox) == 4:
            bbox = f"{nom_bbox[0]},{nom_bbox[2]},{nom_bbox[1]},{nom_bbox[3]}"
        else:
            # Fallback: create small bbox around point
            lat, lon = geo_result["lat"], geo_result["lon"]
            bbox = f"{lat - 0.01},{lon - 0.01},{lat + 0.01},{lon + 0.01}"

    if not bbox:
        return {"error": "No bounding box or location provided"}

    if feature_type not in OSM_FEATURE_MAPPINGS:
        return {"error": f"Unknown feature type: {feature_type}. Valid types: {', '.join(OSM_FEATURE_MAPPINGS.keys())}"}

    mapping = OSM_FEATURE_MAPPINGS[feature_type]
    key = mapping["key"]
    value = mapping["value"]

    # Build Overpass query
    if value is None:
        overpass_query = f"""
        [out:json][timeout:30];
        (
          way["{key}"]({bbox});
          relation["{key}"]({bbox});
        );
        out body;
        >;
        out skel qt;
        """
    else:
        overpass_query = f"""
        [out:json][timeout:30];
        (
          way["{key}"="{value}"]({bbox});
          relation["{key}"="{value}"]({bbox});
        );
        out body;
        >;
        out skel qt;
        """

    try:
        response = requests.get(
            "https://overpass-api.de/api/interpreter",
            params={"data": overpass_query},
            timeout=Config.OSM_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        osm_data = response.json()
    except requests.Timeout:
        return {"error": "OSM request timed out. Try a smaller area."}
    except requests.RequestException as e:
        return {"error": f"OSM request failed: {str(e)}"}

    # Convert to GeoJSON
    geojson = {"type": "FeatureCollection", "features": []}

    if "elements" in osm_data:
        nodes = {
            node["id"]: (node["lon"], node["lat"])
            for node in osm_data["elements"]
            if node["type"] == "node"
        }

        feature_count = 0
        max_features = Config.MAX_FEATURES_PER_LAYER

        for element in osm_data["elements"]:
            if feature_count >= max_features:
                break

            if element["type"] == "way":
                coords = [
                    nodes[nid] for nid in element.get("nodes", []) if nid in nodes
                ]
                if len(coords) < 3:
                    continue

                # Close polygon
                if coords[0] != coords[-1]:
                    coords.append(coords[0])

                geojson["features"].append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [coords],
                    },
                    "properties": {
                        "category_name": category_name,
                        "feature_type": feature_type,
                        "osm_id": element.get("id"),
                        "osm_tags": element.get("tags", {}),
                    },
                })
                feature_count += 1

    layer_name = f"{feature_type}_{category_name}".replace(" ", "_").lower()

    return {
        "geojson": geojson,
        "feature_count": len(geojson["features"]),
        "layer_name": layer_name,
        "capped": len(geojson["features"]) >= Config.MAX_FEATURES_PER_LAYER,
    }


def handle_map_command(params: dict) -> dict:
    """Process a map control command.

    Returns instruction dict for the frontend to execute.
    """
    action = params.get("action")
    valid_actions = ["pan", "zoom", "pan_and_zoom", "fit_bounds", "change_basemap"]

    if action not in valid_actions:
        return {"error": f"Unknown action: {action}. Valid: {', '.join(valid_actions)}"}

    result = {"success": True, "action": action}

    if action == "pan":
        lat, lon = params.get("lat"), params.get("lon")
        if lat is None or lon is None:
            return {"error": "pan requires lat and lon"}
        result["lat"] = lat
        result["lon"] = lon
        result["description"] = f"Panned to ({lat:.4f}, {lon:.4f})"

    elif action == "zoom":
        zoom = params.get("zoom")
        if zoom is None:
            return {"error": "zoom requires zoom level"}
        result["zoom"] = max(1, min(20, zoom))
        result["description"] = f"Zoom set to {result['zoom']}"

    elif action == "pan_and_zoom":
        lat, lon = params.get("lat"), params.get("lon")
        zoom = params.get("zoom", 13)
        if lat is None or lon is None:
            return {"error": "pan_and_zoom requires lat and lon"}
        result["lat"] = lat
        result["lon"] = lon
        result["zoom"] = max(1, min(20, zoom))
        result["description"] = f"Panned to ({lat:.4f}, {lon:.4f}) at zoom {result['zoom']}"

    elif action == "fit_bounds":
        bbox = params.get("bbox")
        if not bbox or len(bbox) != 4:
            return {"error": "fit_bounds requires bbox [south, west, north, east]"}
        result["bbox"] = bbox
        result["description"] = f"Fitted map to bounds"

    elif action == "change_basemap":
        basemap = params.get("basemap", "osm")
        if basemap not in ("osm", "satellite"):
            return {"error": f"Unknown basemap: {basemap}. Use 'osm' or 'satellite'"}
        result["basemap"] = basemap
        result["description"] = f"Changed basemap to {basemap}"

    return result


def handle_calculate_area(params: dict, layer_store: dict = None) -> dict:
    """Calculate geodesic area of polygon features.

    Accepts either a layer_name (looks up in layer_store) or a GeoJSON geometry.
    """
    layer_name = params.get("layer_name")
    geometry = params.get("geometry")

    geometries = []

    if layer_name and layer_store and layer_name in layer_store:
        # Get features from layer store
        layer_geojson = layer_store[layer_name]
        features = layer_geojson.get("features", [])
        for f in features:
            geom = f.get("geometry")
            if geom and geom.get("type") in ("Polygon", "MultiPolygon"):
                geometries.append(geojson_to_shapely(geom))
    elif geometry:
        geom = geojson_to_shapely(geometry)
        if geom.geom_type in ("Polygon", "MultiPolygon"):
            geometries.append(geom)
    else:
        return {"error": "Provide either layer_name or geometry"}

    if not geometries:
        return {"error": "No polygon geometries found to calculate area"}

    total_area = 0.0
    per_feature = []
    for i, geom in enumerate(geometries):
        area = geodesic_area(geom)
        total_area += area
        per_feature.append({"index": i, "area_sq_m": round(area, 2)})

    return {
        "total_area_sq_m": round(total_area, 2),
        "total_area_sq_km": round(total_area / 1e6, 4),
        "total_area_acres": round(total_area / 4046.86, 2),
        "feature_count": len(geometries),
        "per_feature": per_feature if len(per_feature) <= 20 else None,
    }


def handle_measure_distance(params: dict) -> dict:
    """Measure geodesic distance between two points.

    Points can be specified as {lat, lon} or as location names (geocoded).
    """
    from_point = params.get("from_point")
    to_point = params.get("to_point")
    from_location = params.get("from_location")
    to_location = params.get("to_location")

    from_name = None
    to_name = None

    # Resolve from point
    if from_point and "lat" in from_point and "lon" in from_point:
        from_vp = ValidatedPoint(lat=from_point["lat"], lon=from_point["lon"])
    elif from_location:
        geo = handle_geocode({"query": from_location})
        if "error" in geo:
            return {"error": f"Could not geocode origin: {geo['error']}"}
        from_vp = ValidatedPoint(lat=geo["lat"], lon=geo["lon"])
        from_name = geo["display_name"]
    else:
        return {"error": "Provide either from_point or from_location"}

    # Resolve to point
    if to_point and "lat" in to_point and "lon" in to_point:
        to_vp = ValidatedPoint(lat=to_point["lat"], lon=to_point["lon"])
    elif to_location:
        geo = handle_geocode({"query": to_location})
        if "error" in geo:
            return {"error": f"Could not geocode destination: {geo['error']}"}
        to_vp = ValidatedPoint(lat=geo["lat"], lon=geo["lon"])
        to_name = geo["display_name"]
    else:
        return {"error": "Provide either to_point or to_location"}

    distance = geodesic_distance(from_vp, to_vp)

    return {
        "distance_m": round(distance, 2),
        "distance_km": round(distance / 1000, 2),
        "distance_mi": round(distance / 1609.344, 2),
        "from_name": from_name,
        "to_name": to_name,
    }
