"""Routing/network handlers: find route, isochrone, heatmap."""

import logging

from shapely.geometry import shape

from nl_gis.geo_utils import (
    ValidatedPoint,
    geodesic_area,
    geojson_to_shapely,
    shapely_to_geojson,
    buffer_geometry,
)
from nl_gis.handlers import (
    _resolve_point,
    _resolve_point_from_object,
    _get_layer_snapshot,
)

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
        return {"error": "Could not find a route. The routing service may be unavailable."}

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
