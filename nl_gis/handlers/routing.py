"""Routing/network handlers: find route, isochrone, heatmap, closest facility, optimize route, OD matrix.

ERROR PATHS (audit 2026-04-17 for v2.1 Plan 05 M1):
    44 error returns · 14 except blocks · 1 leaky str(e) at line 337.
    Leak fixed by Plan 05 M2 (closest_facility). Valhalla-backed handlers
    gain circuit-breaker protection in M4.
"""

import logging

import requests
from shapely.geometry import shape

from config import Config
from nl_gis.geo_utils import (
    ValidatedPoint,
    geodesic_area,
    geodesic_distance,
    geojson_to_shapely,
    shapely_to_geojson,
    buffer_geometry,
)
from nl_gis.handlers import (
    _resolve_point,
    _resolve_point_from_object,
    _get_layer_snapshot,
    OSM_FEATURE_MAPPINGS,
    _osm_to_geojson,
)
from services.cache import overpass_cache
from services.rate_limiter import overpass_limiter

logger = logging.getLogger(__name__)


def handle_find_route(params: dict) -> dict:
    """Find a route between two or more points using Valhalla.

    Supports optional intermediate waypoints for multi-stop routing.
    """
    from services.valhalla_client import get_route

    profile = params.get("profile", "driving")

    # Resolve origin
    origin_vp, from_name, err = _resolve_point_from_object(params, "from_point", "from_location")
    if err:
        return {"error": err}
    origin_lat, origin_lon = origin_vp.lat, origin_vp.lon

    # Resolve destination
    dest_vp, to_name, err = _resolve_point_from_object(params, "to_point", "to_location")
    if err:
        return {"error": err}
    dest_lat, dest_lon = dest_vp.lat, dest_vp.lon

    # Resolve optional waypoints
    waypoints_param = params.get("waypoints", [])
    waypoint_coords = []  # list of (lat, lon, name)
    for i, wp in enumerate(waypoints_param):
        wp_lat = wp.get("lat")
        wp_lon = wp.get("lon")
        wp_location = wp.get("location")

        if wp_lat is not None and wp_lon is not None:
            try:
                vp = ValidatedPoint(lat=float(wp_lat), lon=float(wp_lon))
                waypoint_coords.append((vp.lat, vp.lon, None))
            except (ValueError, TypeError) as e:
                return {"error": f"Invalid waypoint {i + 1} coordinates: {e}"}
        elif wp_location:
            from nl_gis.handlers.navigation import handle_geocode
            geo_result = handle_geocode({"query": wp_location})
            if "error" in geo_result:
                return {"error": f"Could not geocode waypoint {i + 1}: {wp_location}"}
            waypoint_coords.append((
                geo_result["lat"],
                geo_result["lon"],
                geo_result.get("display_name"),
            ))
        else:
            return {"error": f"Waypoint {i + 1} must have lat/lon or location"}

    # Build full locations list: origin + waypoints + destination
    locations = [(origin_lat, origin_lon)]
    for lat, lon, _name in waypoint_coords:
        locations.append((lat, lon))
    locations.append((dest_lat, dest_lon))

    route = get_route(locations=locations, profile=profile)

    if route is None:
        # Both endpoints geocoded successfully above — so the failure is service-side
        # rather than a bad address. Distinguish by profile to hint at alternatives.
        supported_profiles = {"auto", "driving", "pedestrian", "bicycle", "walking", "cycling"}
        if profile.lower() not in supported_profiles:
            return {"error": f"Routing not available for '{profile}' mode. Try 'driving', 'walking', or 'bicycle'."}
        return {"error": "Routing service is temporarily unavailable. Try again in a minute."}

    # Build GeoJSON FeatureCollection with route line and markers
    features = [
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
    ]

    # Add waypoint markers
    waypoint_names = []
    for i, (lat, lon, name) in enumerate(waypoint_coords):
        label = name or f"Waypoint {i + 1}"
        waypoint_names.append(label)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"role": "waypoint", "name": label, "waypoint_index": i + 1},
        })

    route_geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    origin_label = from_name.split(",")[0] if from_name else "origin"
    dest_label = to_name.split(",")[0] if to_name else "dest"
    layer_name = f"route_{origin_label}_{dest_label}".replace(" ", "_").lower()[:50]

    result = {
        "geojson": route_geojson,
        "layer_name": layer_name,
        "feature_count": 1,
        "distance_km": route["distance_km"],
        "duration_min": route["duration_min"],
        "profile": profile,
        "from_name": from_name,
        "to_name": to_name,
    }

    if waypoint_names:
        result["waypoint_names"] = waypoint_names
        result["waypoint_count"] = len(waypoint_names)
        result["leg_count"] = route.get("leg_count", 1)
        if "legs" in route:
            result["legs"] = route["legs"]

    return result


def handle_isochrone(params: dict) -> dict:
    """Calculate reachable area from a point using Valhalla.

    Returns a true network-based isochrone polygon (not a circular buffer).
    Falls back to buffer estimation if Valhalla is unavailable.
    """
    from services.valhalla_client import get_isochrone

    time_minutes = params.get("time_minutes")
    distance_m = params.get("distance_m")
    profile = params.get("profile", "driving")

    # Resolve center
    center_vp, _, err = _resolve_point(params, lat_key="lat", lon_key="lon", location_key="location")
    if err:
        return {"error": err}
    lat, lon = center_vp.lat, center_vp.lon

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
        # Valhalla succeeded -- true network isochrone
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
                    logger.debug("Failed to calculate isochrone area for feature", exc_info=True)

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
        "warning": (
            f"Could not compute {time_minutes}-minute {profile} "
            f"network-based reachability. Showing a circular buffer estimate "
            f"instead — actual reachable area depends on the road network."
        ),
    }


def handle_closest_facility(params: dict, layer_store: dict = None) -> dict:
    """Find the nearest N features of a type from a point.

    Combines Overpass search with geodesic distance calculation and sorting.
    Returns a GeoJSON layer with distance_m in each feature's properties.
    """
    # Resolve center point
    center_vp, center_name, err = _resolve_point(params, lat_key="lat", lon_key="lon", location_key="location")
    if err:
        return {"error": err}
    lat, lon = center_vp.lat, center_vp.lon

    feature_type = params.get("feature_type")
    if not feature_type:
        return {"error": "feature_type is required"}

    count = params.get("count", 5)
    try:
        count = int(count)
        if count < 1 or count > 20:
            return {"error": "count must be between 1 and 20"}
    except (TypeError, ValueError):
        return {"error": "count must be an integer"}

    max_radius_m = params.get("max_radius_m", 5000)
    try:
        max_radius_m = int(max_radius_m)
        if max_radius_m < 1 or max_radius_m > 50000:
            return {"error": "max_radius_m must be between 1 and 50000"}
    except (TypeError, ValueError):
        return {"error": "max_radius_m must be an integer"}

    # Resolve OSM tag
    if feature_type in OSM_FEATURE_MAPPINGS:
        mapping = OSM_FEATURE_MAPPINGS[feature_type]
        key = mapping["key"]
        value = mapping["value"]
    else:
        key = params.get("osm_key")
        value = params.get("osm_value")
        if not key:
            return {"error": f"Unknown feature type: '{feature_type}'. Use a known type or provide osm_key/osm_value."}

    # Build Overpass around query (same pattern as search_nearby)
    if value is None:
        tag_filter = f'["{key}"]'
    else:
        tag_filter = f'["{key}"="{value}"]'

    overpass_query = f"""
    [out:json][timeout:30];
    (
      node{tag_filter}(around:{max_radius_m},{lat},{lon});
      way{tag_filter}(around:{max_radius_m},{lat},{lon});
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
        logger.warning("Overpass closest-facility timeout radius=%s feature=%s", max_radius_m, feature_type, exc_info=True)
        return {"error": "Search timed out. Try a smaller radius or more specific feature type."}
    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        logger.warning("Overpass closest-facility HTTP error: status=%s", status, exc_info=True)
        if status == 429:
            return {"error": "OpenStreetMap data service is rate-limiting requests. Wait 30 seconds and try again."}
        if status == 504:
            return {"error": "The search area is too large. Reduce max_radius_m or use a more specific feature type."}
        return {"error": "OpenStreetMap data service returned an error. Try again shortly."}
    except requests.ConnectionError:
        logger.warning("Overpass closest-facility connection error", exc_info=True)
        return {"error": "Cannot reach OpenStreetMap data service. Check your internet connection."}
    except requests.RequestException:
        logger.error("Overpass closest-facility unexpected error", exc_info=True)
        return {"error": "Facility search failed. Try again with a different location."}

    # Convert to GeoJSON
    geojson = _osm_to_geojson(osm_data, feature_type, feature_type)

    # Also include node-type results (points) that _osm_to_geojson skips
    if "elements" in osm_data:
        for el in osm_data["elements"]:
            if el["type"] == "node" and "lat" in el and "lon" in el:
                geojson["features"].append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
                    "properties": {
                        "category_name": feature_type,
                        "feature_type": feature_type,
                        "osm_id": el.get("id"),
                        "osm_tags": el.get("tags", {}),
                    },
                })

    # Calculate geodesic distance from center to each feature's centroid.
    # Track how many distance calcs fail so we can warn about partial results.
    center_point = ValidatedPoint(lat=lat, lon=lon)
    distance_failures = 0
    for feature in geojson["features"]:
        geom = feature.get("geometry")
        if not geom:
            feature["properties"]["distance_m"] = float("inf")
            distance_failures += 1
            continue
        try:
            shapely_geom = geojson_to_shapely(geom)
            centroid = shapely_geom.centroid
            feature_point = ValidatedPoint(lat=centroid.y, lon=centroid.x)
            dist = geodesic_distance(center_point, feature_point)
            feature["properties"]["distance_m"] = round(dist, 1)
        except Exception:
            logger.debug("Distance calc failed for feature", exc_info=True)
            feature["properties"]["distance_m"] = float("inf")
            distance_failures += 1

    total_found = len(geojson["features"])

    # Sort by distance, take top N
    geojson["features"].sort(key=lambda f: f["properties"].get("distance_m", float("inf")))
    geojson["features"] = geojson["features"][:count]

    layer_name = f"closest_{feature_type}_{count}"

    result = {
        "geojson": geojson,
        "layer_name": layer_name,
        "feature_count": len(geojson["features"]),
        "center": {"lat": lat, "lon": lon},
        "max_radius_m": max_radius_m,
        "requested_count": count,
    }
    # Partial-failure warning: some features were found but their distances
    # couldn't be computed, so the sort is less accurate than expected.
    if distance_failures and total_found > 0:
        result["warning"] = (
            f"Found {total_found} facilities but could not compute distances "
            f"for {distance_failures} of them. Showing results without full "
            f"distance sorting."
        )
    return result


def handle_optimize_route(params: dict, layer_store: dict = None) -> dict:
    """Optimize waypoint ordering (traveling salesman approximation).

    Resolves all locations, attempts Valhalla's optimized_route endpoint,
    and falls back to a nearest-neighbor heuristic if unavailable.
    Returns a GeoJSON layer with the optimized route and ordered markers.
    """
    from services.valhalla_client import get_route

    locations = params.get("locations", [])
    if len(locations) < 3:
        return {"error": "Need at least 3 locations to optimize"}
    if len(locations) > 20:
        return {"error": "Maximum 20 locations"}

    profile = params.get("profile", "auto")
    # Normalize profile names
    profile_map = {"driving": "auto", "pedestrian": "pedestrian", "bicycle": "bicycle"}
    valhalla_costing = profile_map.get(profile, profile)

    # Resolve all locations to coordinates
    points = []  # list of (ValidatedPoint, name)
    for i, loc in enumerate(locations):
        if isinstance(loc, dict):
            loc_lat = loc.get("lat")
            loc_lon = loc.get("lon")
            loc_name = loc.get("location")

            if loc_lat is not None and loc_lon is not None:
                try:
                    vp = ValidatedPoint(lat=float(loc_lat), lon=float(loc_lon))
                    points.append((vp, f"Stop {i + 1}"))
                except (ValueError, TypeError) as e:
                    return {"error": f"Invalid coordinates for location {i + 1}: {e}"}
            elif loc_name:
                from nl_gis.handlers.navigation import handle_geocode
                geo_result = handle_geocode({"query": loc_name})
                if "error" in geo_result:
                    return {"error": f"Could not geocode location {i + 1}: {loc_name}"}
                vp = ValidatedPoint(lat=geo_result["lat"], lon=geo_result["lon"])
                points.append((vp, geo_result.get("display_name", loc_name)))
            else:
                return {"error": f"Location {i + 1} must have lat/lon or location name"}
        else:
            return {"error": f"Location {i + 1} must be an object with lat/lon or location"}

    # Try Valhalla optimized_route endpoint
    optimized_order = _try_valhalla_optimized_route(points, valhalla_costing)

    if optimized_order is None:
        # Fallback: nearest-neighbor heuristic
        optimized_order = _nearest_neighbor_order(points)

    # Reorder points
    ordered_points = [points[i] for i in optimized_order]

    # Get the actual route along the optimized order
    route_locations = [(vp.lat, vp.lon) for vp, _name in ordered_points]
    route_data = get_route(locations=route_locations, profile=profile if profile in ("driving", "walking", "cycling") else "driving")

    if route_data is None:
        return {"error": "Could not calculate optimized route. Routing service may be unavailable."}

    # Get route along original order for comparison (only after optimized route succeeds)
    original_locations = [(vp.lat, vp.lon) for vp, _name in points]
    original_route = get_route(locations=original_locations, profile=profile if profile in ("driving", "walking", "cycling") else "driving")

    # Build GeoJSON FeatureCollection
    features = [
        {
            "type": "Feature",
            "geometry": route_data["geometry"],
            "properties": {
                "distance_km": route_data["distance_km"],
                "duration_min": route_data["duration_min"],
                "profile": profile,
                "optimized": True,
            },
        },
    ]

    # Add ordered markers
    for order_idx, (vp, name) in enumerate(ordered_points):
        role = "origin" if order_idx == 0 else ("destination" if order_idx == len(ordered_points) - 1 else "waypoint")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [vp.lon, vp.lat]},
            "properties": {
                "role": role,
                "name": name,
                "optimized_order": order_idx + 1,
                "original_order": optimized_order[order_idx] + 1,
            },
        })

    route_geojson = {"type": "FeatureCollection", "features": features}

    result = {
        "geojson": route_geojson,
        "layer_name": f"optimized_route_{len(points)}stops",
        "feature_count": len(points),
        "optimized_order": [i + 1 for i in optimized_order],
        "total_distance_km": route_data["distance_km"],
        "total_duration_min": route_data["duration_min"],
        "profile": profile,
    }

    # Calculate time/distance savings vs original order
    if original_route is not None:
        original_km = original_route["distance_km"]
        optimized_km = route_data["distance_km"]
        result["original_distance_km"] = original_km
        result["distance_saved_km"] = round(original_km - optimized_km, 2)
        result["original_duration_min"] = original_route["duration_min"]
        result["time_saved_min"] = round(original_route["duration_min"] - route_data["duration_min"], 1)

    return result


def _try_valhalla_optimized_route(points, costing):
    """Try Valhalla's optimized_route endpoint.

    Returns list of indices representing optimized order, or None on failure.
    """
    from services.valhalla_client import detect_valhalla_url, _request_with_retry, PUBLIC_VALHALLA
    from services.rate_limiter import valhalla_limiter

    base_url = detect_valhalla_url()

    if base_url == PUBLIC_VALHALLA:
        valhalla_limiter.wait()

    valhalla_locations = [
        {"lat": vp.lat, "lon": vp.lon, "type": "break"} for vp, _name in points
    ]

    payload = {
        "locations": valhalla_locations,
        "costing": costing,
        "units": "kilometers",
    }

    try:
        response = _request_with_retry(
            f"{base_url}/optimized_route",
            json_data=payload,
            timeout=30,
            max_retries=1,
        )
        if response is None:
            return None
        if response.status_code != 200:
            logger.debug("Valhalla optimized_route returned %d", response.status_code)
            return None

        data = response.json()
        trip = data.get("trip", {})
        locations = trip.get("locations", [])

        if not locations:
            return None

        # Extract optimized order from Valhalla response
        # Valhalla returns locations in optimized order with original_index
        order = [loc.get("original_index", i) for i, loc in enumerate(locations)]
        if len(order) == len(points):
            return order

        return None
    except Exception as e:
        logger.debug("Valhalla optimized_route failed: %s", e)
        return None


def _nearest_neighbor_order(points):
    """Compute a nearest-neighbor TSP approximation.

    Starts from the first point, greedily picks the nearest unvisited point.
    Returns list of indices in visit order.
    """
    n = len(points)
    visited = [False] * n
    order = [0]
    visited[0] = True

    for _ in range(n - 1):
        current = order[-1]
        current_vp = points[current][0]
        best_dist = float("inf")
        best_idx = -1

        for j in range(n):
            if visited[j]:
                continue
            dist = geodesic_distance(current_vp, points[j][0])
            if dist < best_dist:
                best_dist = dist
                best_idx = j

        if best_idx >= 0:
            order.append(best_idx)
            visited[best_idx] = True

    return order


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


def handle_service_area(params: dict, layer_store: dict = None) -> dict:
    """Compute multi-facility reachability zones.

    Accepts either a facility_layer (point layer) or a list of facility
    coordinates. For each facility, computes an isochrone polygon using
    Valhalla (or buffer fallback), then unions all isochrones into a
    single coverage polygon. Optionally computes gap areas (unreachable
    zones within the bounding box of all facilities).
    """
    from services.valhalla_client import get_isochrone
    from shapely.ops import unary_union
    from shapely.geometry import box as shapely_box

    facility_layer = params.get("facility_layer")
    facilities = params.get("facilities", [])
    time_minutes = params.get("time_minutes")
    distance_m = params.get("distance_m")
    profile = params.get("profile", "auto")
    output_name = params.get("output_name", "service_area")
    show_gaps = params.get("show_gaps", False)

    if not time_minutes and not distance_m:
        return {"error": "Provide time_minutes or distance_m"}

    # Collect facility points
    facility_points = []  # list of ValidatedPoint

    if facility_layer:
        features, err = _get_layer_snapshot(layer_store, facility_layer)
        if err:
            return {"error": err}
        if not features:
            return {"error": f"Layer '{facility_layer}' has no features"}

        for feat in features:
            geom = feat.get("geometry")
            if not geom:
                continue
            try:
                shapely_geom = geojson_to_shapely(geom)
                centroid = shapely_geom.centroid
                vp = ValidatedPoint(lat=centroid.y, lon=centroid.x)
                facility_points.append(vp)
            except Exception:
                continue

    if facilities:
        for i, fac in enumerate(facilities):
            lat = fac.get("lat")
            lon = fac.get("lon")
            if lat is None or lon is None:
                return {"error": f"Facility {i + 1} must have lat and lon"}
            try:
                vp = ValidatedPoint(lat=float(lat), lon=float(lon))
                facility_points.append(vp)
            except (ValueError, TypeError) as e:
                return {"error": f"Invalid coordinates for facility {i + 1}: {e}"}

    if not facility_points:
        return {"error": "No valid facility locations. Provide facility_layer or facilities array."}

    if len(facility_points) > 50:
        return {"error": f"Too many facilities ({len(facility_points)}). Maximum is 50."}

    # Map profile names for Valhalla
    profile_map = {"driving": "driving", "auto": "driving",
                   "pedestrian": "walking", "walking": "walking",
                   "bicycle": "cycling", "cycling": "cycling"}
    valhalla_profile = profile_map.get(profile, "driving")

    # Compute isochrone for each facility
    distance_km = distance_m / 1000 if distance_m else None
    iso_polygons = []
    failed_count = 0

    for vp in facility_points:
        iso_data = get_isochrone(
            vp.lon, vp.lat,
            time_minutes=time_minutes,
            distance_km=distance_km,
            profile=valhalla_profile,
        )

        if iso_data is not None:
            # Extract polygon geometries from the isochrone response
            for feat in iso_data.get("features", []):
                geom_type = feat.get("geometry", {}).get("type", "")
                if geom_type in ("Polygon", "MultiPolygon"):
                    try:
                        shapely_geom = shape(feat["geometry"])
                        if not shapely_geom.is_empty:
                            iso_polygons.append(shapely_geom)
                    except Exception:
                        continue
        else:
            # Fallback: buffer-based estimation
            PROFILE_SPEEDS = {"driving": 13.9, "walking": 1.4, "cycling": 4.2}
            if time_minutes:
                speed = PROFILE_SPEEDS.get(valhalla_profile, PROFILE_SPEEDS["driving"])
                radius_m = time_minutes * 60 * speed
            else:
                radius_m = distance_m

            from shapely.geometry import Point as ShapelyPoint
            center = ShapelyPoint(vp.lon, vp.lat)
            buffered = buffer_geometry(center, radius_m)
            if not buffered.is_empty:
                iso_polygons.append(buffered)
            else:
                failed_count += 1

    if not iso_polygons:
        return {"error": "Could not compute isochrones for any facility. Routing service may be unavailable."}

    # Union all isochrone polygons into coverage
    coverage = unary_union(iso_polygons)
    if not coverage.is_valid:
        coverage = coverage.buffer(0)

    result_features = [{
        "type": "Feature",
        "geometry": shapely_to_geojson(coverage),
        "properties": {
            "type": "coverage",
            "facility_count": len(facility_points),
            "profile": profile,
            "time_minutes": time_minutes,
            "distance_m": distance_m,
        },
    }]

    # Optionally compute gap areas
    gap_area_sq_km = None
    if show_gaps:
        # Compute bounding box of all facility points with buffer
        all_lons = [vp.lon for vp in facility_points]
        all_lats = [vp.lat for vp in facility_points]
        # Extend bbox by the isochrone radius
        lon_buffer = 0.05  # ~5km at equator
        lat_buffer = 0.05
        bbox = shapely_box(
            min(all_lons) - lon_buffer, min(all_lats) - lat_buffer,
            max(all_lons) + lon_buffer, max(all_lats) + lat_buffer,
        )
        gaps = bbox.difference(coverage)
        if not gaps.is_empty:
            gap_area_sq_km = round(geodesic_area(gaps) / 1e6, 2)
            result_features.append({
                "type": "Feature",
                "geometry": shapely_to_geojson(gaps),
                "properties": {
                    "type": "gap",
                    "gap_area_sq_km": gap_area_sq_km,
                },
            })

    coverage_area_sq_km = round(geodesic_area(coverage) / 1e6, 2)

    result_geojson = {
        "type": "FeatureCollection",
        "features": result_features,
    }

    result = {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": len(result_features),
        "facility_count": len(facility_points),
        "coverage_area_sq_km": coverage_area_sq_km,
        "profile": profile,
        "failed_facilities": failed_count,
    }
    if gap_area_sq_km is not None:
        result["gap_area_sq_km"] = gap_area_sq_km

    return result


def handle_od_matrix(params: dict, layer_store: dict = None) -> dict:
    """Compute origin-destination cost matrix using geodesic distances."""
    origins_raw = params.get("origins", [])
    destinations_raw = params.get("destinations", [])
    profile = params.get("profile", "driving")

    if not origins_raw:
        return {"error": "origins array is required and must not be empty"}
    if not destinations_raw:
        return {"error": "destinations array is required and must not be empty"}

    MAX_POINTS = 50
    if len(origins_raw) > MAX_POINTS or len(destinations_raw) > MAX_POINTS:
        return {"error": f"Maximum {MAX_POINTS} origins and {MAX_POINTS} destinations allowed"}

    # Resolve origins
    origin_points = []
    for i, o in enumerate(origins_raw):
        if "lat" in o and "lon" in o:
            try:
                vp = ValidatedPoint(lat=float(o["lat"]), lon=float(o["lon"]))
                origin_points.append(vp)
            except (ValueError, TypeError) as e:
                return {"error": f"Invalid origin {i}: {e}"}
        elif "location" in o:
            from nl_gis.handlers.navigation import handle_geocode
            result = handle_geocode({"query": o["location"]})
            if "error" in result:
                return {"error": f"Could not geocode origin {i} '{o['location']}': {result['error']}"}
            origin_points.append(ValidatedPoint(lat=result["lat"], lon=result["lon"]))
        else:
            return {"error": f"Origin {i} must have lat/lon or location"}

    # Resolve destinations
    dest_points = []
    for i, d in enumerate(destinations_raw):
        if "lat" in d and "lon" in d:
            try:
                vp = ValidatedPoint(lat=float(d["lat"]), lon=float(d["lon"]))
                dest_points.append(vp)
            except (ValueError, TypeError) as e:
                return {"error": f"Invalid destination {i}: {e}"}
        elif "location" in d:
            from nl_gis.handlers.navigation import handle_geocode
            result = handle_geocode({"query": d["location"]})
            if "error" in result:
                return {"error": f"Could not geocode destination {i} '{d['location']}': {result['error']}"}
            dest_points.append(ValidatedPoint(lat=result["lat"], lon=result["lon"]))
        else:
            return {"error": f"Destination {i} must have lat/lon or location"}

    # Compute pairwise geodesic distances
    matrix = []
    for o_idx, origin in enumerate(origin_points):
        row = []
        for d_idx, dest in enumerate(dest_points):
            dist = geodesic_distance(origin, dest)
            row.append(round(dist, 1))
        matrix.append(row)

    return {
        "matrix": matrix,
        "origins_count": len(origin_points),
        "destinations_count": len(dest_points),
        "profile": profile,
        "unit": "meters",
        "method": "geodesic",
        "origins": [{"lat": p.lat, "lon": p.lon} for p in origin_points],
        "destinations": [{"lat": p.lat, "lon": p.lon} for p in dest_points],
    }
