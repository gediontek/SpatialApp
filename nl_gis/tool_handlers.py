"""Tool handler implementations for NL-to-GIS operations."""

import json
import logging
import urllib.request
import urllib.parse

import requests
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

from config import Config
from nl_gis.geo_utils import (
    ValidatedPoint,
    geodesic_area,
    geodesic_distance,
    geojson_to_shapely,
    shapely_to_geojson,
    buffer_geometry,
    project_to_utm,
    project_to_wgs84,
)
from services.cache import geocode_cache, overpass_cache, osrm_cache
from services.rate_limiter import nominatim_limiter, overpass_limiter

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


def _osm_to_geojson(osm_data: dict, category_name: str, feature_type: str) -> dict:
    """Convert Overpass API response to GeoJSON FeatureCollection."""
    geojson = {"type": "FeatureCollection", "features": []}
    if "elements" not in osm_data:
        return geojson

    nodes = {
        n["id"]: (n["lon"], n["lat"])
        for n in osm_data["elements"] if n["type"] == "node"
    }

    count = 0
    max_features = Config.MAX_FEATURES_PER_LAYER

    for el in osm_data["elements"]:
        if count >= max_features:
            break
        if el["type"] == "way":
            coords = [nodes[nid] for nid in el.get("nodes", []) if nid in nodes]
            if len(coords) < 3:
                continue
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            geojson["features"].append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [coords]},
                "properties": {
                    "category_name": category_name,
                    "feature_type": feature_type,
                    "osm_id": el.get("id"),
                    "osm_tags": el.get("tags", {}),
                },
            })
            count += 1

    return geojson


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
        # Phase 1
        "geocode": handle_geocode,
        "fetch_osm": handle_fetch_osm,
        "map_command": handle_map_command,
        "calculate_area": lambda p: handle_calculate_area(p, layer_store),
        "measure_distance": handle_measure_distance,
        # Phase 2
        "buffer": lambda p: handle_buffer(p, layer_store),
        "spatial_query": lambda p: handle_spatial_query(p, layer_store),
        "aggregate": lambda p: handle_aggregate(p, layer_store),
        "search_nearby": handle_search_nearby,
        "show_layer": lambda p: handle_layer_visibility(p, "show"),
        "hide_layer": lambda p: handle_layer_visibility(p, "hide"),
        "remove_layer": lambda p: handle_layer_visibility(p, "remove"),
        "highlight_features": lambda p: handle_highlight_features(p, layer_store),
        # Phase 3
        "add_annotation": lambda p: handle_add_annotation(p, layer_store),
        "classify_landcover": handle_classify_landcover,
        "export_annotations": handle_export_annotations,
        "get_annotations": handle_get_annotations,
        "import_layer": lambda p: handle_import_layer(p, layer_store),
        "merge_layers": lambda p: handle_merge_layers(p, layer_store),
        # Phase 4
        "find_route": handle_find_route,
        "isochrone": handle_isochrone,
        "heatmap": lambda p: handle_heatmap(p, layer_store),
    }

    if tool_name not in handlers:
        raise ValueError(f"Unknown tool: {tool_name}")

    return handlers[tool_name](params)


def handle_geocode(params: dict) -> dict:
    """Geocode a place name using Nominatim. Cached for 24h, rate-limited.

    Returns:
        Dict with lat, lon, display_name, bbox.
    """
    query = params.get("query", "")
    if not query:
        return {"error": "No query provided"}

    # Check cache first
    cached = geocode_cache.get(query.lower().strip())
    if cached:
        logger.debug(f"Geocode cache hit: {query}")
        return cached

    try:
        nominatim_limiter.wait()
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "SpatialLabeler/1.0"})

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())

        if not data:
            return {"error": f"Location not found: {query}"}

        result = data[0]
        bbox = result.get("boundingbox", [])

        geo_result = {
            "lat": float(result["lat"]),
            "lon": float(result["lon"]),
            "display_name": result["display_name"],
            "bbox": [float(b) for b in bbox] if bbox else None,
        }
        geocode_cache.set(query.lower().strip(), geo_result)
        return geo_result
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
        overpass_limiter.wait()
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
    geojson = _osm_to_geojson(osm_data, category_name, feature_type)
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

    if layer_name:
        features, err = _get_layer_snapshot(layer_store, layer_name)
        if err:
            return {"error": err}
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


# ============================================================
# Phase 2: Spatial Analysis Handlers
# ============================================================

def _safe_geojson_to_shapely(geojson_geom):
    """Safely convert GeoJSON to Shapely, returning None on failure."""
    try:
        geom = geojson_to_shapely(geojson_geom)
        if geom.is_empty:
            return None
        return geom
    except Exception:
        return None


def _get_layer_snapshot(layer_store, layer_name):
    """Get a snapshot of a layer's features list. Thread-safe."""
    try:
        from app import layer_lock
    except ImportError:
        layer_lock = None

    if not layer_store:
        return None, f"Layer '{layer_name}' not found"

    try:
        if layer_lock:
            with layer_lock:
                geojson = layer_store.get(layer_name)
                # Mark as recently used for LRU eviction
                if geojson is not None and hasattr(layer_store, 'move_to_end'):
                    layer_store.move_to_end(layer_name)
        else:
            geojson = layer_store.get(layer_name)
    except (KeyError, TypeError):
        return None, f"Layer '{layer_name}' not found"

    if geojson is None:
        return None, f"Layer '{layer_name}' not found"
    return list(geojson.get("features", [])), None


def _get_layer_geometries(layer_store, layer_name):
    """Extract Shapely geometries from a named layer. Thread-safe copy."""
    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return None, err
    geometries = []
    for f in features:
        geom = f.get("geometry")
        if geom:
            shapely_geom = _safe_geojson_to_shapely(geom)
            if shapely_geom:
                geometries.append(shapely_geom)
    return geometries, None


MAX_BUFFER_DISTANCE_M = 100000  # 100 km max


def handle_buffer(params: dict, layer_store: dict = None) -> dict:
    """Create a buffer around geometry or layer features."""
    distance_m = params.get("distance_m")
    if not distance_m or distance_m <= 0:
        return {"error": "distance_m must be a positive number"}
    if distance_m > MAX_BUFFER_DISTANCE_M:
        return {"error": f"distance_m must be at most {MAX_BUFFER_DISTANCE_M} meters (100 km)"}

    layer_name = params.get("layer_name")
    geometry = params.get("geometry")

    source_geoms = []

    if layer_name:
        geoms, err = _get_layer_geometries(layer_store, layer_name)
        if err:
            return {"error": err}
        source_geoms = geoms
    elif geometry:
        source_geoms = [geojson_to_shapely(geometry)]
    else:
        return {"error": "Provide either layer_name or geometry"}

    if not source_geoms:
        return {"error": "No geometries to buffer"}

    # Union all source geometries, then buffer
    combined = unary_union(source_geoms)
    buffered = buffer_geometry(combined, distance_m)

    result_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": shapely_to_geojson(buffered),
            "properties": {
                "buffer_distance_m": distance_m,
                "source": layer_name or "geometry",
            }
        }]
    }

    result_name = f"buffer_{int(distance_m)}m"
    if layer_name:
        result_name = f"buffer_{int(distance_m)}m_{layer_name}"

    return {
        "geojson": result_geojson,
        "layer_name": result_name,
        "feature_count": 1,
        "buffer_distance_m": distance_m,
        "area_sq_km": round(geodesic_area(buffered) / 1e6, 4),
    }


def handle_spatial_query(params: dict, layer_store: dict = None) -> dict:
    """Find features matching a spatial predicate."""
    source_layer = params.get("source_layer")
    predicate = params.get("predicate")
    target_layer = params.get("target_layer")
    target_geometry = params.get("target_geometry")
    distance_m = params.get("distance_m", 0)

    valid_predicates = ["intersects", "contains", "within", "within_distance"]
    if predicate not in valid_predicates:
        return {"error": f"Unknown predicate: {predicate}. Valid: {', '.join(valid_predicates)}"}

    # Get source features
    source_geoms, err = _get_layer_geometries(layer_store, source_layer)
    if err:
        return {"error": f"Source: {err}"}

    # Get target geometry
    if target_layer:
        target_geoms, err = _get_layer_geometries(layer_store, target_layer)
        if err:
            return {"error": f"Target: {err}"}
        target_geom = unary_union(target_geoms) if target_geoms else None
    elif target_geometry:
        target_geom = geojson_to_shapely(target_geometry)
    else:
        return {"error": "Provide either target_layer or target_geometry"}

    if target_geom is None:
        return {"error": "No target geometry found"}

    # For within_distance, buffer the target
    if predicate == "within_distance":
        if not distance_m or distance_m <= 0:
            return {"error": "within_distance requires positive distance_m"}
        target_geom = buffer_geometry(target_geom, distance_m)

    # Get original features from source layer for result
    source_features, _ = _get_layer_snapshot(layer_store, source_layer)
    source_features = source_features or []

    matching_features = []
    for i, (geom, feature) in enumerate(zip(source_geoms, source_features)):
        match = False
        if predicate == "intersects" or predicate == "within_distance":
            match = geom.intersects(target_geom)
        elif predicate == "contains":
            match = target_geom.contains(geom)
        elif predicate == "within":
            match = geom.within(target_geom)

        if match:
            matching_features.append(feature)

    result_geojson = {
        "type": "FeatureCollection",
        "features": matching_features[:Config.MAX_FEATURES_PER_LAYER],
    }

    result_name = f"{predicate}_{source_layer}"

    return {
        "geojson": result_geojson,
        "layer_name": result_name,
        "feature_count": len(matching_features),
        "source_total": len(source_geoms),
        "match_percentage": round(len(matching_features) / max(len(source_geoms), 1) * 100, 1),
    }


def handle_aggregate(params: dict, layer_store: dict = None) -> dict:
    """Summarize features in a layer."""
    layer_name = params.get("layer_name")
    operation = params.get("operation")
    group_by_attr = params.get("group_by")

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}

    if operation == "count":
        if group_by_attr:
            groups = {}
            for f in features:
                val = f.get("properties", {}).get(group_by_attr, "unknown")
                groups[val] = groups.get(val, 0) + 1
            return {
                "total": len(features),
                "groups": [{"value": k, "count": v} for k, v in sorted(groups.items(), key=lambda x: -x[1])],
                "group_by": group_by_attr,
            }
        return {"total": len(features)}

    elif operation == "area":
        total_area = 0.0
        for f in features:
            geom = f.get("geometry")
            if geom and geom.get("type") in ("Polygon", "MultiPolygon"):
                total_area += geodesic_area(geojson_to_shapely(geom))
        return {
            "total_area_sq_m": round(total_area, 2),
            "total_area_sq_km": round(total_area / 1e6, 4),
            "total_area_acres": round(total_area / 4046.86, 2),
            "feature_count": len(features),
        }

    elif operation == "group_by":
        if not group_by_attr:
            return {"error": "group_by operation requires group_by attribute name"}
        groups = {}
        for f in features:
            val = f.get("properties", {}).get(group_by_attr, "unknown")
            groups[val] = groups.get(val, 0) + 1
        return {
            "groups": [{"value": k, "count": v} for k, v in sorted(groups.items(), key=lambda x: -x[1])],
            "total": len(features),
            "group_by": group_by_attr,
        }

    return {"error": f"Unknown operation: {operation}"}


def handle_search_nearby(params: dict) -> dict:
    """Search for OSM features near a point."""
    lat = params.get("lat")
    lon = params.get("lon")
    location = params.get("location")
    radius_m = params.get("radius_m", 500)
    feature_type = params.get("feature_type", "building")

    # Validate radius
    try:
        radius_m = float(radius_m)
        if radius_m <= 0 or radius_m > 50000:
            return {"error": "radius_m must be between 0 and 50000 meters"}
    except (TypeError, ValueError):
        return {"error": "radius_m must be a number"}

    # Resolve location to coordinates
    if lat is None or lon is None:
        if location:
            geo = handle_geocode({"query": location})
            if "error" in geo:
                return {"error": f"Could not geocode location: {geo['error']}"}
            lat, lon = geo["lat"], geo["lon"]
        else:
            return {"error": "Provide lat/lon or location name"}

    # Validate coordinates
    try:
        vp = ValidatedPoint(lat=float(lat), lon=float(lon))
        lat, lon = vp.lat, vp.lon
    except (ValueError, TypeError) as e:
        return {"error": f"Invalid coordinates: {e}"}

    if feature_type not in OSM_FEATURE_MAPPINGS:
        return {"error": f"Unknown feature type: {feature_type}"}

    mapping = OSM_FEATURE_MAPPINGS[feature_type]
    key = mapping["key"]
    value = mapping["value"]

    # Build Overpass around query
    if value is None:
        tag_filter = f'["{key}"]'
    else:
        tag_filter = f'["{key}"="{value}"]'

    overpass_query = f"""
    [out:json][timeout:30];
    (
      way{tag_filter}(around:{radius_m},{lat},{lon});
    );
    out body;
    >;
    out skel qt;
    """

    try:
        overpass_limiter.wait()
        response = requests.get(
            "https://overpass-api.de/api/interpreter",
            params={"data": overpass_query},
            timeout=Config.OSM_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        osm_data = response.json()
    except requests.Timeout:
        return {"error": "Search timed out. Try a smaller radius."}
    except requests.RequestException as e:
        return {"error": f"OSM request failed: {str(e)}"}

    geojson = _osm_to_geojson(osm_data, feature_type, feature_type)
    layer_name = f"nearby_{feature_type}_{int(radius_m)}m"

    return {
        "geojson": geojson,
        "layer_name": layer_name,
        "feature_count": len(geojson["features"]),
        "center": {"lat": lat, "lon": lon},
        "radius_m": radius_m,
    }


def handle_layer_visibility(params: dict, action: str) -> dict:
    """Handle show/hide/remove layer commands. Returns instruction for frontend."""
    layer_name = params.get("layer_name")
    if not layer_name:
        return {"error": "layer_name is required"}
    return {
        "success": True,
        "action": action,
        "layer_name": layer_name,
        "description": f"Layer '{layer_name}' {action}",
    }


def handle_highlight_features(params: dict, layer_store: dict = None) -> dict:
    """Highlight features matching an attribute value. Returns instruction for frontend."""
    layer_name = params.get("layer_name")
    attribute = params.get("attribute")
    value = params.get("value")
    color = params.get("color", "#ff0000")

    if not layer_name:
        return {"error": "layer_name is required"}
    if not attribute or not value:
        return {"error": "attribute and value are required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}

    matched = 0
    for f in features:
        props = f.get("properties", {})
        # Check nested osm_tags as well
        if str(props.get(attribute, "")) == str(value):
            matched += 1
        elif str(props.get("osm_tags", {}).get(attribute, "")) == str(value):
            matched += 1

    return {
        "success": True,
        "action": "highlight",
        "layer_name": layer_name,
        "attribute": attribute,
        "value": value,
        "color": color,
        "highlighted": matched,
        "total": len(features),
        "description": f"Highlighted {matched}/{len(features)} features where {attribute}={value}",
    }


# ============================================================
# Phase 3: Annotation & Classification Handlers
# ============================================================

def handle_add_annotation(params: dict, layer_store: dict = None) -> dict:
    """Save geometry/layer as annotations."""
    import datetime

    geometry = params.get("geometry")
    layer_name = params.get("layer_name")
    category_name = params.get("category_name", "unknown")
    color = params.get("color", "#3388ff")

    # Import app-level annotation functions + lock
    try:
        from app import geo_coco_annotations, save_annotations_to_file, annotation_lock
    except ImportError:
        return {"error": "Cannot access annotation store"}

    added = 0

    with annotation_lock:
        if layer_name:
            layer_features, _ = _get_layer_snapshot(layer_store, layer_name)
            if layer_features:
                for f in layer_features:
                    geom = f.get("geometry")
                    if geom:
                        annotation = {
                            "type": "Feature",
                            "id": len(geo_coco_annotations) + 1,
                            "properties": {
                                "category_name": category_name,
                                "color": color,
                                "source": "chat",
                                "created_at": datetime.datetime.now().isoformat(),
                            },
                            "geometry": geom,
                        }
                        geo_coco_annotations.append(annotation)
                        added += 1
        elif geometry:
            annotation = {
                "type": "Feature",
                "id": len(geo_coco_annotations) + 1,
                "properties": {
                    "category_name": category_name,
                    "color": color,
                    "source": "chat",
                    "created_at": datetime.datetime.now().isoformat(),
                },
                "geometry": geometry,
            }
            geo_coco_annotations.append(annotation)
            added = 1
        else:
            return {"error": "Provide either geometry or layer_name"}

        if added > 0:
            save_annotations_to_file()

            # Persist to database
            try:
                from app import db as app_db
                if app_db:
                    if layer_name and layer_store and layer_name in layer_store:
                        for f in layer_store[layer_name].get("features", []):
                            geom = f.get("geometry")
                            if geom:
                                app_db.save_annotation(category_name, geom, color, "chat")
                    elif geometry:
                        app_db.save_annotation(category_name, geometry, color, "chat")
            except Exception as db_err:
                logger.warning(f"DB save failed (chat annotation): {db_err}")

    return {"success": True, "added": added, "category": category_name}


def _classify_landcover_work(params: dict) -> dict:
    """Heavy classification work — runs in a thread pool to avoid blocking."""
    from OSM_auto_label import download_osm_landcover, OSMLandcoverClassifier
    from OSM_auto_label.downloader import download_by_bbox
    from OSM_auto_label.config import CATEGORY_COLORS
    import re

    location = params.get("location")
    bbox = params.get("bbox")
    classes = params.get("classes")

    if bbox:
        n, s, e, w = bbox.get("north"), bbox.get("south"), bbox.get("east"), bbox.get("west")
        if None in (n, s, e, w):
            return {"error": "bbox requires north, south, east, west"}
        gdf = download_by_bbox(north=n, south=s, east=e, west=w, timeout=300)
        safe_name = f"bbox_{abs(hash((n, s, e, w))) % 10000}"
    else:
        gdf = download_osm_landcover(location, timeout=300)
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', location.split(',')[0].strip().lower())

    if gdf is None or len(gdf) == 0:
        return {"error": "No landcover data found"}

    classifier = OSMLandcoverClassifier()
    gdf_classified = classifier.process_geodataframe(gdf, name=None)

    if gdf_classified is None or len(gdf_classified) == 0:
        return {"error": "Classification produced no results"}

    if classes and len(classes) > 0:
        gdf_classified = gdf_classified[gdf_classified['classname'].isin(classes)]

    if len(gdf_classified) == 0:
        return {"error": "No features found for selected classes"}

    import json as json_mod
    geojson_data = json_mod.loads(gdf_classified.to_json())
    layer_name = f"classified_{safe_name}"

    return {
        "geojson": geojson_data,
        "layer_name": layer_name,
        "feature_count": len(gdf_classified),
        "colors": CATEGORY_COLORS,
    }


def handle_classify_landcover(params: dict) -> dict:
    """Classify landcover using OSM_auto_label module.

    Runs the heavy download+classify work in a thread pool so it doesn't
    block the Flask server for other requests. Timeout: 5 minutes.
    """
    try:
        from OSM_auto_label import download_osm_landcover  # noqa: F401
    except ImportError:
        return {"error": "OSM auto-label module not available"}

    location = params.get("location")
    bbox = params.get("bbox")

    if not location and not bbox:
        return {"error": "Provide either location or bbox"}

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_classify_landcover_work, params)
            result = future.result(timeout=300)  # 5 minute timeout
        return result
    except FutureTimeout:
        logger.error("Classification timed out after 300s")
        return {"error": "Classification timed out. Try a smaller area."}
    except Exception as e:
        logger.error(f"Classification error: {e}", exc_info=True)
        return {"error": str(e)}


def handle_export_annotations(params: dict) -> dict:
    """Export annotations to file."""
    format_type = params.get("format", "geojson")
    valid_formats = ["geojson", "shapefile", "geopackage"]

    if format_type not in valid_formats:
        return {"error": f"Invalid format. Choose from: {', '.join(valid_formats)}"}

    try:
        from app import geo_coco_annotations
    except ImportError:
        return {"error": "Cannot access annotation store"}

    if not geo_coco_annotations:
        return {"error": "No annotations to export"}

    return {
        "success": True,
        "format": format_type,
        "count": len(geo_coco_annotations),
        "download_url": f"/export_annotations/{format_type}",
        "description": f"Export {len(geo_coco_annotations)} annotations as {format_type}",
    }


def handle_get_annotations(params: dict) -> dict:
    """Get current annotations summary."""
    try:
        from app import geo_coco_annotations
    except ImportError:
        return {"error": "Cannot access annotation store"}

    features = geo_coco_annotations
    categories = {}
    for f in features:
        cat = f.get("properties", {}).get("category_name", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "total": len(features),
        "categories": [{"name": k, "count": v} for k, v in sorted(categories.items(), key=lambda x: -x[1])],
        "geojson": {"type": "FeatureCollection", "features": features},
    }


def handle_merge_layers(params: dict, layer_store: dict = None) -> dict:
    """Merge two layers or perform a spatial join."""
    import geopandas as gpd_mod

    layer_a = params.get("layer_a")
    layer_b = params.get("layer_b")
    output_name = params.get("output_name")
    operation = params.get("operation", "union")

    if not layer_a or not layer_b or not output_name:
        return {"error": "layer_a, layer_b, and output_name are required"}

    if not layer_store:
        return {"error": "No layer store available"}

    if layer_a not in layer_store:
        return {"error": f"Layer '{layer_a}' not found"}
    if layer_b not in layer_store:
        return {"error": f"Layer '{layer_b}' not found"}

    try:
        gdf_a = gpd_mod.GeoDataFrame.from_features(
            layer_store[layer_a].get("features", [])
        )
        gdf_b = gpd_mod.GeoDataFrame.from_features(
            layer_store[layer_b].get("features", [])
        )

        if gdf_a.crs is None:
            gdf_a.set_crs(epsg=4326, inplace=True)
        if gdf_b.crs is None:
            gdf_b.set_crs(epsg=4326, inplace=True)

        if operation == "spatial_join":
            merged = gpd_mod.sjoin(gdf_a, gdf_b, how="left", predicate="intersects")
            # Drop the index_right column that sjoin adds
            if "index_right" in merged.columns:
                merged = merged.drop(columns=["index_right"])
        else:
            # Union: concatenate both GeoDataFrames
            import pandas as pd_mod
            merged = gpd_mod.GeoDataFrame(
                pd_mod.concat([gdf_a, gdf_b], ignore_index=True),
                crs=gdf_a.crs,
            )

        import json as json_mod
        geojson_data = json_mod.loads(merged.to_json())

        if layer_store is not None:
            layer_store[output_name] = geojson_data

        return {
            "geojson": geojson_data,
            "layer_name": output_name,
            "feature_count": len(geojson_data.get("features", [])),
            "operation": operation,
            "description": f"Merged '{layer_a}' + '{layer_b}' → '{output_name}' ({operation}, {len(geojson_data.get('features', []))} features)",
        }
    except Exception as e:
        logger.error(f"Merge error: {e}", exc_info=True)
        return {"error": str(e)}


def handle_import_layer(params: dict, layer_store: dict = None) -> dict:
    """Import GeoJSON data as a named layer."""
    layer_name = params.get("layer_name")
    geojson = params.get("geojson")

    if not layer_name:
        return {"error": "layer_name is required"}

    if geojson:
        # Direct GeoJSON import
        if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
            return {"error": "geojson must be a GeoJSON FeatureCollection"}

        if layer_store is not None:
            layer_store[layer_name] = geojson

        return {
            "geojson": geojson,
            "layer_name": layer_name,
            "feature_count": len(geojson.get("features", [])),
            "description": f"Imported {len(geojson.get('features', []))} features as '{layer_name}'",
        }

    # No inline GeoJSON — tell the user to use the file upload
    return {
        "success": True,
        "layer_name": layer_name,
        "description": "To import a file, use the upload button or drag-and-drop a GeoJSON, Shapefile (.zip), or GeoPackage (.gpkg) file onto the map.",
        "upload_url": "/api/import",
    }


# ============================================================
# Phase 4: Routing Handlers
# ============================================================

def handle_find_route(params: dict) -> dict:
    """Find a route between two points using Valhalla."""
    from services.valhalla_client import get_route

    from_point = params.get("from_point")
    to_point = params.get("to_point")
    from_location = params.get("from_location")
    to_location = params.get("to_location")
    profile = params.get("profile", "driving")

    from_name, to_name = None, None

    # Resolve origin
    if from_point and "lat" in from_point and "lon" in from_point:
        try:
            vp = ValidatedPoint(lat=float(from_point["lat"]), lon=float(from_point["lon"]))
            origin_lat, origin_lon = vp.lat, vp.lon
        except (ValueError, TypeError) as e:
            return {"error": f"Invalid origin coordinates: {e}"}
    elif from_location:
        geo = handle_geocode({"query": from_location})
        if "error" in geo:
            return {"error": f"Could not geocode origin: {geo['error']}"}
        origin_lat, origin_lon = geo["lat"], geo["lon"]
        from_name = geo["display_name"]
    else:
        return {"error": "Provide from_point or from_location"}

    # Resolve destination
    if to_point and "lat" in to_point and "lon" in to_point:
        try:
            vp = ValidatedPoint(lat=float(to_point["lat"]), lon=float(to_point["lon"]))
            dest_lat, dest_lon = vp.lat, vp.lon
        except (ValueError, TypeError) as e:
            return {"error": f"Invalid destination coordinates: {e}"}
    elif to_location:
        geo = handle_geocode({"query": to_location})
        if "error" in geo:
            return {"error": f"Could not geocode destination: {geo['error']}"}
        dest_lat, dest_lon = geo["lat"], geo["lon"]
        to_name = geo["display_name"]
    else:
        return {"error": "Provide to_point or to_location"}

    route = get_route(origin_lon, origin_lat, dest_lon, dest_lat, profile=profile)

    if route is None:
        return {"error": "Could not find a route. The routing service may be unavailable."}

    # Build GeoJSON FeatureCollection with route line
    route_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": route["geometry"],
                "properties": {
                    "distance_km": route["distance_km"],
                    "duration_min": route["duration_min"],
                    "profile": profile,
                },
            },
            # Origin marker
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [origin_lon, origin_lat]},
                "properties": {"role": "origin", "name": from_name or "Origin"},
            },
            # Destination marker
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [dest_lon, dest_lat]},
                "properties": {"role": "destination", "name": to_name or "Destination"},
            },
        ],
    }

    origin_label = from_name.split(",")[0] if from_name else "origin"
    dest_label = to_name.split(",")[0] if to_name else "dest"
    layer_name = f"route_{origin_label}_{dest_label}".replace(" ", "_").lower()[:50]

    return {
        "geojson": route_geojson,
        "layer_name": layer_name,
        "feature_count": 1,
        "distance_km": route["distance_km"],
        "duration_min": route["duration_min"],
        "profile": profile,
        "from_name": from_name,
        "to_name": to_name,
    }


def handle_isochrone(params: dict) -> dict:
    """Calculate reachable area from a point using Valhalla.

    Returns a true network-based isochrone polygon (not a circular buffer).
    Falls back to buffer estimation if Valhalla is unavailable.
    """
    from services.valhalla_client import get_isochrone

    lat = params.get("lat")
    lon = params.get("lon")
    location = params.get("location")
    time_minutes = params.get("time_minutes")
    distance_m = params.get("distance_m")
    profile = params.get("profile", "driving")

    # Resolve center
    if lat is None or lon is None:
        if location:
            geo = handle_geocode({"query": location})
            if "error" in geo:
                return {"error": f"Could not geocode: {geo['error']}"}
            lat, lon = geo["lat"], geo["lon"]
        else:
            return {"error": "Provide lat/lon or location"}

    if not time_minutes and not distance_m:
        return {"error": "Provide time_minutes or distance_m"}

    # Try Valhalla network-based isochrone
    distance_km = distance_m / 1000 if distance_m else None
    iso_data = get_isochrone(
        lon, lat,
        time_minutes=time_minutes,
        distance_km=distance_km,
        profile=profile,
    )

    if iso_data is not None:
        # Valhalla succeeded — true network isochrone
        # Add center marker
        iso_data["features"].append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"role": "center"},
        })

        desc = f"{time_minutes}min" if time_minutes else f"{int(distance_m)}m"
        layer_name = f"isochrone_{desc}_{profile}"

        # Calculate area of the isochrone polygon
        area_sq_km = 0
        for f in iso_data["features"]:
            geom_type = f.get("geometry", {}).get("type", "")
            if geom_type in ("Polygon", "MultiPolygon"):
                try:
                    shp = shape(f["geometry"])
                    area_sq_km += abs(geodesic_area(shp)) / 1e6
                except Exception:
                    pass

        return {
            "geojson": iso_data,
            "layer_name": layer_name,
            "feature_count": len(iso_data["features"]),
            "area_sq_km": round(area_sq_km, 2),
            "profile": profile,
            "method": "valhalla_network",
        }

    # Fallback: buffer-based estimation if Valhalla unavailable
    logger.warning("Valhalla unavailable, falling back to buffer estimation")

    PROFILE_SPEEDS = {"driving": 13.9, "walking": 1.4, "cycling": 4.2}

    if time_minutes:
        speed = PROFILE_SPEEDS.get(profile, PROFILE_SPEEDS["driving"])
        radius_m = time_minutes * 60 * speed
    else:
        radius_m = distance_m

    from shapely.geometry import Point as ShapelyPoint
    center = ShapelyPoint(lon, lat)
    buffered = buffer_geometry(center, radius_m)

    iso_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": shapely_to_geojson(buffered),
                "properties": {
                    "radius_m": round(radius_m),
                    "time_minutes": time_minutes,
                    "profile": profile,
                    "method": "buffer_estimate",
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"role": "center"},
            },
        ],
    }

    desc = f"{time_minutes}min" if time_minutes else f"{int(distance_m)}m"
    layer_name = f"isochrone_{desc}_{profile}"

    return {
        "geojson": iso_geojson,
        "layer_name": layer_name,
        "feature_count": 1,
        "radius_m": round(radius_m),
        "area_sq_km": round(geodesic_area(buffered) / 1e6, 2),
        "profile": profile,
        "method": "buffer_estimate",
    }


def handle_heatmap(params: dict, layer_store: dict = None) -> dict:
    """Generate heatmap data from layer features."""
    layer_name = params.get("layer_name")
    radius = params.get("radius", 25)
    max_zoom = params.get("max_zoom", 15)

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": "Layer has no features"}

    # Extract centroids as heatmap points [lat, lng, intensity]
    points = []
    for f in features:
        geom = f.get("geometry")
        if not geom:
            continue
        shapely_geom = geojson_to_shapely(geom)
        centroid = shapely_geom.centroid
        points.append([centroid.y, centroid.x, 1.0])  # Leaflet order: lat, lng

    if not points:
        return {"error": "Could not extract points from features"}

    return {
        "success": True,
        "action": "heatmap",
        "layer_name": f"heatmap_{layer_name}",
        "points": points,
        "options": {"radius": radius, "maxZoom": max_zoom},
        "point_count": len(points),
        "description": f"Heatmap of {len(points)} points from {layer_name}",
    }
