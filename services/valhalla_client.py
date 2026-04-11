"""Valhalla routing client with auto-detection of local vs public instance.

Provides route finding and true network-based isochrone calculation.
Auto-detects local Docker instance (port 8002) or falls back to
FOSSGIS public demo at valhalla1.openstreetmap.de.
"""

import logging
import socket
import threading
import time as _time
from typing import Optional

import polyline
import requests

from services.cache import valhalla_cache
from services.rate_limiter import valhalla_limiter

logger = logging.getLogger(__name__)

# FOSSGIS public Valhalla instance (rate-limited: 1 req/s)
PUBLIC_VALHALLA = "https://valhalla1.openstreetmap.de"

# Local Docker instance
LOCAL_VALHALLA = "http://localhost:8002"

# Map SpatialApp profile names to Valhalla costing models
COSTING_MAP = {
    "driving": "auto",
    "walking": "pedestrian",
    "cycling": "bicycle",
}

# Cached detection result with TTL (re-probe every 5 minutes)
_detected_url = None
_detected_at = 0.0
_DETECTION_TTL = 300  # Re-probe every 5 minutes
_detection_lock = threading.Lock()


def _probe_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a port is listening."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, OSError, socket.timeout):
        return False


def reset_detection():
    """Force re-probe on next call. Call after connection failure."""
    global _detected_url, _detected_at
    with _detection_lock:
        _detected_url = None
        _detected_at = 0.0


def detect_valhalla_url() -> str:
    """Auto-detect available Valhalla instance.

    Checks local Docker (port 8002) first, falls back to public demo.
    Caches result for 5 minutes, then re-probes.
    """
    import time
    global _detected_url, _detected_at

    with _detection_lock:
        if _detected_url is not None and (time.time() - _detected_at) < _DETECTION_TTL:
            return _detected_url

        if _probe_port("localhost", 8002):
            logger.info("Using local Valhalla instance on port 8002")
            _detected_url = LOCAL_VALHALLA
        else:
            logger.info("Using public Valhalla demo server (rate-limited)")
            _detected_url = PUBLIC_VALHALLA

        _detected_at = time.time()
        return _detected_url


def _request_with_retry(url, json_data, timeout, max_retries=2):
    """Make HTTP POST with exponential backoff retry for transient errors.

    Retries on ConnectionError, Timeout, and HTTP 5xx responses.
    Does NOT retry on 4xx client errors.

    Args:
        url: Request URL.
        json_data: JSON payload dict.
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retries (default 2).

    Returns:
        requests.Response on success, None after all retries exhausted.
    """
    delays = [0.5, 1.0]
    for attempt in range(1 + max_retries):
        try:
            response = requests.post(url, json=json_data, timeout=timeout)
            status = response.status_code
            if isinstance(status, int) and status >= 500 and attempt < max_retries:
                logger.warning(
                    "Valhalla returned %d on attempt %d/%d, retrying",
                    response.status_code, attempt + 1, 1 + max_retries,
                )
                _time.sleep(delays[attempt] if attempt < len(delays) else delays[-1])
                continue
            return response
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < max_retries:
                logger.warning(
                    "Valhalla request failed on attempt %d/%d (%s), retrying",
                    attempt + 1, 1 + max_retries, type(e).__name__,
                )
                _time.sleep(delays[attempt] if attempt < len(delays) else delays[-1])
            else:
                logger.warning(
                    "Valhalla request failed after %d attempts: %s",
                    1 + max_retries, e,
                )
                return None
    return None


def _decode_polyline6(encoded: str) -> list:
    """Decode Valhalla's polyline6-encoded shape to [[lon, lat], ...] for GeoJSON.

    Validates that all decoded coordinates are within WGS84 bounds.
    """
    if not encoded or not isinstance(encoded, str):
        raise ValueError("Invalid polyline: empty or not a string")
    coords = polyline.decode(encoded, 6)  # Returns [(lat, lon), ...]
    if not coords:
        raise ValueError("Polyline decoded to empty coordinate list")
    result = []
    for lat, lon in coords:
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            raise ValueError(f"Invalid decoded coordinate: lat={lat}, lon={lon}")
        result.append([lon, lat])
    return result


def get_route(
    origin_lon: float = None,
    origin_lat: float = None,
    dest_lon: float = None,
    dest_lat: float = None,
    profile: str = "driving",
    timeout: int = 15,
    locations: list = None,
) -> Optional[dict]:
    """Get a route through multiple locations using Valhalla.

    Supports two calling conventions:
    - Legacy 2-point: get_route(origin_lon, origin_lat, dest_lon, dest_lat)
    - Multi-stop: get_route(locations=[(lat, lon), (lat, lon), ...])

    Args:
        origin_lon, origin_lat: Origin coordinates (WGS84). Legacy interface.
        dest_lon, dest_lat: Destination coordinates (WGS84). Legacy interface.
        profile: 'driving', 'walking', or 'cycling'.
        timeout: Request timeout in seconds.
        locations: List of (lat, lon) tuples. Minimum 2. Overrides origin/dest.

    Returns:
        Dict with: geometry (GeoJSON LineString), distance_m, duration_s,
                    distance_km, duration_min, summary. None on failure.
    """
    # Build locations list from either interface
    if locations is not None:
        if len(locations) < 2:
            logger.warning("Route requires at least 2 locations, got %d", len(locations))
            return None
        valhalla_locations = [
            {"lat": lat, "lon": lon, "type": "break"} for lat, lon in locations
        ]
    elif origin_lon is not None and origin_lat is not None and dest_lon is not None and dest_lat is not None:
        valhalla_locations = [
            {"lat": origin_lat, "lon": origin_lon, "type": "break"},
            {"lat": dest_lat, "lon": dest_lon, "type": "break"},
        ]
    else:
        logger.warning("Route requires either locations list or origin/dest coordinates")
        return None

    base_url = detect_valhalla_url()
    costing = COSTING_MAP.get(profile, "auto")

    # Check cache -- build key from all locations
    loc_key = ":".join(f"{loc['lon']:.5f},{loc['lat']:.5f}" for loc in valhalla_locations)
    cache_key = f"route:{loc_key}:{costing}"
    cached = valhalla_cache.get(cache_key)
    if cached:
        return cached

    # Rate limit for public instance
    if base_url == PUBLIC_VALHALLA:
        valhalla_limiter.wait()

    payload = {
        "locations": valhalla_locations,
        "costing": costing,
        "units": "kilometers",
    }

    try:
        response = _request_with_retry(
            f"{base_url}/route", json_data=payload, timeout=timeout
        )
        if response is None:
            reset_detection()
            return None
        response.raise_for_status()
        data = response.json()

        trip = data.get("trip")
        if not trip or not trip.get("legs"):
            logger.warning("Valhalla returned no route")
            return None

        # Combine all legs into a single geometry
        all_coords = []
        all_steps = []
        legs = trip["legs"]
        for i, leg in enumerate(legs):
            encoded_shape = leg.get("shape", "")
            if not encoded_shape:
                logger.warning("Valhalla route leg %d missing shape", i)
                return None
            leg_coords = _decode_polyline6(encoded_shape)
            # Avoid duplicating the junction point between legs
            if all_coords and leg_coords:
                all_coords.extend(leg_coords[1:])
            else:
                all_coords.extend(leg_coords)

            # Extract turn-by-turn maneuvers per leg
            maneuvers = leg.get("maneuvers", [])
            for m in maneuvers:
                all_steps.append({
                    "instruction": m.get("instruction", ""),
                    "type": m.get("type", 0),
                    "distance_km": m.get("length", 0),
                    "time_s": m.get("time", 0),
                    "street_name": ", ".join(m.get("street_names", [])),
                    "leg": i,
                })

        if not all_coords:
            logger.warning("Valhalla route decoded to empty coordinates")
            return None

        geometry = {"type": "LineString", "coordinates": all_coords}

        # Use trip-level summary for totals
        summary = trip.get("summary", legs[0].get("summary", {}))
        distance_km = summary.get("length", 0)
        duration_s = summary.get("time", 0)
        distance_m = distance_km * 1000

        result = {
            "geometry": geometry,
            "distance_m": distance_m,
            "duration_s": duration_s,
            "distance_km": round(distance_km, 2),
            "duration_min": round(duration_s / 60, 1),
            "leg_count": len(legs),
        }

        if all_steps:
            result["steps"] = all_steps

        # Per-leg summaries for multi-stop routes
        if len(legs) > 1:
            result["legs"] = []
            for i, leg in enumerate(legs):
                leg_summary = leg.get("summary", {})
                result["legs"].append({
                    "leg": i,
                    "distance_km": round(leg_summary.get("length", 0), 2),
                    "duration_min": round(leg_summary.get("time", 0) / 60, 1),
                })

        valhalla_cache.set(cache_key, result)
        return result

    except requests.RequestException as e:
        logger.error(f"Valhalla route request failed: {e}")
        reset_detection()
        return None
    except Exception as e:
        logger.error(f"Valhalla route error: {e}", exc_info=True)
        return None


def get_isochrone(
    lon: float,
    lat: float,
    time_minutes: float = None,
    distance_km: float = None,
    profile: str = "driving",
    timeout: int = 30,
) -> Optional[dict]:
    """Get isochrone (service area) polygon using Valhalla.

    Returns a GeoJSON FeatureCollection with the reachable area polygon.
    This is a TRUE network-based isochrone, not a circular buffer.

    Args:
        lon, lat: Center point coordinates (WGS84).
        time_minutes: Travel time in minutes (use this OR distance_km).
        distance_km: Travel distance in kilometers.
        profile: 'driving', 'walking', or 'cycling'.
        timeout: Request timeout in seconds.

    Returns:
        GeoJSON FeatureCollection with isochrone polygon(s). None on failure.
    """
    base_url = detect_valhalla_url()
    costing = COSTING_MAP.get(profile, "auto")

    # Build contour specification
    if time_minutes is not None:
        if time_minutes <= 0:
            logger.warning("Isochrone time_minutes must be positive, got %s", time_minutes)
            return None
        contour = {"time": time_minutes}
        cache_key = f"iso:{lon:.5f},{lat:.5f}:t{time_minutes}:{costing}"
    elif distance_km is not None:
        if distance_km <= 0:
            logger.warning("Isochrone distance_km must be positive, got %s", distance_km)
            return None
        contour = {"distance": distance_km}
        cache_key = f"iso:{lon:.5f},{lat:.5f}:d{distance_km}:{costing}"
    else:
        return None

    # Check cache
    cached = valhalla_cache.get(cache_key)
    if cached:
        return cached

    # Rate limit for public instance
    if base_url == PUBLIC_VALHALLA:
        valhalla_limiter.wait()

    payload = {
        "locations": [{"lat": lat, "lon": lon}],
        "costing": costing,
        "contours": [contour],
        "polygons": True,
        "denoise": 1,
        "generalize": 10,
        "show_locations": False,
    }

    try:
        response = _request_with_retry(
            f"{base_url}/isochrone", json_data=payload, timeout=timeout,
            max_retries=1
        )
        if response is None:
            reset_detection()
            return None
        response.raise_for_status()
        data = response.json()

        # Valhalla returns GeoJSON FeatureCollection directly
        if data.get("type") != "FeatureCollection":
            logger.warning("Valhalla isochrone returned unexpected format")
            return None

        valhalla_cache.set(cache_key, data)
        return data

    except requests.RequestException as e:
        logger.error(f"Valhalla isochrone request failed: {e}")
        reset_detection()
        return None
    except Exception as e:
        logger.error(f"Valhalla isochrone error: {e}", exc_info=True)
        return None
