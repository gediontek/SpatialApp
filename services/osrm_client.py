"""OSRM routing client with auto-detection of local vs public instance."""

import logging
import socket
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Public OSRM demo (rate-limited, for development only)
PUBLIC_OSRM = "https://router.project-osrm.org"

# Local OSRM ports (Docker)
LOCAL_OSRM_CAR = "http://localhost:5001"
LOCAL_OSRM_FOOT = "http://localhost:5002"


def _probe_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a port is listening."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, OSError, socket.timeout):
        return False


def detect_osrm_url(profile: str = "driving") -> str:
    """Auto-detect available OSRM instance.

    Checks local Docker instances first, falls back to public demo.

    Args:
        profile: Routing profile ('driving' or 'walking').

    Returns:
        Base URL for the OSRM instance.
    """
    if profile == "walking":
        if _probe_port("localhost", 5002):
            logger.info("Using local OSRM foot instance on port 5002")
            return LOCAL_OSRM_FOOT
    else:
        if _probe_port("localhost", 5001):
            logger.info("Using local OSRM car instance on port 5001")
            return LOCAL_OSRM_CAR

    logger.info("Using public OSRM demo server (rate-limited)")
    return PUBLIC_OSRM


def get_route(
    origin_lon: float,
    origin_lat: float,
    dest_lon: float,
    dest_lat: float,
    profile: str = "driving",
    alternatives: bool = False,
    steps: bool = False,
    timeout: int = 15,
) -> Optional[dict]:
    """Get a route between two points.

    Args:
        origin_lon, origin_lat: Origin coordinates (WGS84).
        dest_lon, dest_lat: Destination coordinates (WGS84).
        profile: 'driving', 'walking', or 'cycling'.
        alternatives: Whether to return alternative routes.
        steps: Whether to include turn-by-turn steps.
        timeout: Request timeout in seconds.

    Returns:
        Dict with: geometry (GeoJSON LineString), distance_m, duration_s,
                    summary, steps (if requested). None on failure.
    """
    base_url = detect_osrm_url(profile)

    # OSRM uses driving/walking/cycling profiles
    osrm_profile = {
        "driving": "car",
        "walking": "foot",
        "cycling": "bike",
    }.get(profile, "car")

    # For public OSRM, profile is part of URL differently
    if base_url == PUBLIC_OSRM:
        osrm_profile = profile if profile in ("driving", "walking", "cycling") else "driving"

    coords = f"{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
    url = f"{base_url}/route/v1/{osrm_profile}/{coords}"

    params = {
        "overview": "full",
        "geometries": "geojson",
        "alternatives": str(alternatives).lower(),
        "steps": str(steps).lower(),
    }

    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        routes = data.get("routes") or []
        if data.get("code") != "Ok" or len(routes) == 0:
            logger.warning(f"OSRM returned no routes: {data.get('code')}")
            return None

        route = routes[0]
        geometry = route.get("geometry")
        distance = route.get("distance", 0)
        duration = route.get("duration", 0)

        if not geometry:
            logger.warning("OSRM route missing geometry")
            return None

        result = {
            "geometry": geometry,
            "distance_m": distance,
            "duration_s": duration,
            "distance_km": round(distance / 1000, 2),
            "duration_min": round(duration / 60, 1),
        }

        # Add summary if available
        legs = route.get("legs", [])
        if legs:
            result["summary"] = legs[0].get("summary", "")

        # Add turn-by-turn steps
        if steps and legs:
            result["steps"] = []
            for leg in legs:
                for step in leg.get("steps", []):
                    result["steps"].append({
                        "instruction": step.get("maneuver", {}).get("type", ""),
                        "modifier": step.get("maneuver", {}).get("modifier", ""),
                        "name": step.get("name", ""),
                        "distance_m": step.get("distance", 0),
                        "duration_s": step.get("duration", 0),
                    })

        return result

    except requests.Timeout:
        logger.error("OSRM request timed out")
        return None
    except requests.RequestException as e:
        logger.error(f"OSRM request failed: {e}")
        return None
    except Exception as e:
        logger.error(f"OSRM error: {e}", exc_info=True)
        return None


def get_nearest(lon: float, lat: float, profile: str = "driving", timeout: int = 10) -> Optional[dict]:
    """Snap a coordinate to the nearest road.

    Returns:
        Dict with snapped_lon, snapped_lat, distance_m, name.
    """
    base_url = detect_osrm_url(profile)
    osrm_profile = "driving" if base_url == PUBLIC_OSRM else "car"

    url = f"{base_url}/nearest/v1/{osrm_profile}/{lon},{lat}"
    params = {"number": 1}

    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        if data.get("code") != "Ok" or not data.get("waypoints"):
            return None

        wp = data["waypoints"][0]
        return {
            "snapped_lon": wp["location"][0],
            "snapped_lat": wp["location"][1],
            "distance_m": wp.get("distance", 0),
            "name": wp.get("name", ""),
        }
    except Exception as e:
        logger.error(f"OSRM nearest error: {e}")
        return None
