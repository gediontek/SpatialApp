"""Data fetching handlers: geocode, OSM fetch, map commands, nearby search.

ERROR PATHS (audit 2026-04-17 for v2.1 Plan 05 M1):
    28 error returns · 9 except blocks · 3 leaky str(e) at lines 58, 143, 382.
    Leaks are fixed by Plan 05 M2 (Nominatim/Overpass degradation).
"""

import logging
import requests

from config import Config
from nl_gis.geo_utils import ValidatedPoint
from services.cache import geocode_cache, overpass_cache
from services.rate_limiter import nominatim_limiter, overpass_limiter

logger = logging.getLogger(__name__)


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
        url = "https://nominatim.openstreetmap.org/search"
        resp = requests.get(
            url,
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "SpatialLabeler/1.0"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

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
        logger.error("Geocoding error: %s", e, exc_info=True)
        return {"error": f"Geocoding failed: {str(e)}"}


def handle_fetch_osm(params: dict) -> dict:
    """Fetch OSM features via Overpass API.

    Returns:
        GeoJSON FeatureCollection with fetched features,
        plus metadata (feature_count, layer_name).
    """
    from nl_gis.handlers import OSM_FEATURE_MAPPINGS, _osm_to_geojson

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

    if feature_type in OSM_FEATURE_MAPPINGS:
        mapping = OSM_FEATURE_MAPPINGS[feature_type]
        key = mapping["key"]
        value = mapping["value"]
    else:
        # Allow custom key=value for arbitrary OSM queries
        key = params.get("osm_key")
        value = params.get("osm_value")
        if not key:
            return {"error": f"Unknown feature type: '{feature_type}'. Use a known type or provide osm_key/osm_value for custom queries."}

    # Build Overpass query — use `out geom` to get coordinates inline
    # (avoids slow node-by-node reconstruction)
    if value is None:
        overpass_query = f"""
        [out:json][timeout:30];
        (
          way["{key}"]({bbox});
          relation["{key}"]({bbox});
        );
        out geom qt;
        """
    else:
        overpass_query = f"""
        [out:json][timeout:30];
        (
          way["{key}"="{value}"]({bbox});
          relation["{key}"="{value}"]({bbox});
        );
        out geom qt;
        """

    # Check cache before hitting the API
    cache_key = f"{key}={value}|{bbox}"
    cached = overpass_cache.get(cache_key)
    if cached:
        logger.debug(f"Overpass cache hit: {cache_key}")
        return cached

    try:
        overpass_limiter.wait()
        response = requests.get(
            "https://overpass-api.de/api/interpreter",
            params={"data": overpass_query},
            timeout=(5, Config.OSM_REQUEST_TIMEOUT),
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

    count = len(geojson["features"])
    capped = count >= Config.MAX_FEATURES_PER_LAYER
    result = {
        "geojson": geojson,
        "feature_count": count,
        "layer_name": layer_name,
        "capped": capped,
    }
    if capped:
        result["note"] = f"Results capped at {Config.MAX_FEATURES_PER_LAYER} features. The actual area may contain more. Try a smaller area for complete data."

    # Cache successful result
    overpass_cache.set(cache_key, result)
    return result


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


def handle_reverse_geocode(params: dict) -> dict:
    """Reverse geocode coordinates to an address/place name. Cached, rate-limited.

    Returns:
        Dict with display_name, address components, lat, lon, osm metadata.
    """
    lat = params.get("lat")
    lon = params.get("lon")
    if lat is None or lon is None:
        return {"error": "lat and lon are required"}

    # Validate coordinates
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return {"error": "lat and lon must be numbers"}

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return {"error": "Invalid coordinates: lat must be -90..90, lon must be -180..180"}

    # Check cache first
    cache_key = f"reverse_{lat}_{lon}"
    cached = geocode_cache.get(cache_key)
    if cached:
        logger.debug(f"Reverse geocode cache hit: {lat},{lon}")
        return cached

    try:
        nominatim_limiter.wait()
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
        headers = {"User-Agent": "SpatialApp/1.0"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            return {"error": f"No result found for coordinates ({lat}, {lon})"}

        result = {
            "display_name": data.get("display_name", "Unknown location"),
            "address": data.get("address", {}),
            "lat": lat,
            "lon": lon,
            "osm_type": data.get("osm_type"),
            "osm_id": data.get("osm_id"),
        }
        geocode_cache.set(cache_key, result)
        return result
    except Exception as e:
        logger.error("Reverse geocoding error: %s", e, exc_info=True)
        return {"error": "Reverse geocoding failed"}


def handle_batch_geocode(params: dict, layer_store: dict = None) -> dict:
    """Geocode a list of addresses into a point layer.

    Returns:
        Dict with geojson FeatureCollection, layer_name, counts, and failed list.
    """
    addresses = params.get("addresses", [])
    if not addresses:
        return {"error": "addresses list is required"}
    if len(addresses) > 50:
        return {"error": "Maximum 50 addresses per batch"}

    features = []
    failed = []
    for addr in addresses:
        result = handle_geocode({"query": addr})
        if "error" in result:
            failed.append(addr)
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [result["lon"], result["lat"]]},
            "properties": {"address": addr, "display_name": result.get("display_name", addr)}
        })

    layer_name = params.get("layer_name", "geocoded_points")
    geojson = {"type": "FeatureCollection", "features": features}
    return {
        "geojson": geojson,
        "layer_name": layer_name,
        "geocoded": len(features),
        "failed": failed,
        "total": len(addresses),
    }


def handle_search_nearby(params: dict) -> dict:
    """Search for OSM features near a point."""
    from nl_gis.handlers import OSM_FEATURE_MAPPINGS, _osm_to_geojson

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

    if feature_type in OSM_FEATURE_MAPPINGS:
        mapping = OSM_FEATURE_MAPPINGS[feature_type]
        key = mapping["key"]
        value = mapping["value"]
    else:
        # Allow custom key=value for arbitrary OSM queries
        key = params.get("osm_key")
        value = params.get("osm_value")
        if not key:
            return {"error": f"Unknown feature type: '{feature_type}'. Use a known type or provide osm_key/osm_value for custom queries."}

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
    out geom qt;
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
