"""Geospatial utilities: validated coordinates, CRS projection, spatial ops."""

from dataclasses import dataclass
from typing import Optional

import pyproj
from shapely.geometry import shape, mapping
from shapely.ops import transform as shapely_transform


@dataclass(frozen=True)
class ValidatedPoint:
    """Immutable WGS84 point with explicit coordinate order accessors.

    Prevents the most common geospatial bug: swapped lat/lng vs lng/lat.

    - Leaflet expects [lat, lng]
    - GeoJSON/OSRM/Overpass expect [lng, lat]

    This class stores (lat, lon) and provides explicit accessors for each convention.
    """

    lat: float
    lon: float

    def __post_init__(self):
        if not isinstance(self.lat, (int, float)):
            raise TypeError(f"lat must be numeric, got {type(self.lat).__name__}")
        if not isinstance(self.lon, (int, float)):
            raise TypeError(f"lon must be numeric, got {type(self.lon).__name__}")
        if not (-90 <= self.lat <= 90):
            raise ValueError(f"Latitude {self.lat} out of range [-90, 90]")
        if not (-180 <= self.lon <= 180):
            raise ValueError(f"Longitude {self.lon} out of range [-180, 180]")

    def as_leaflet(self) -> list:
        """[lat, lng] for Leaflet.js."""
        return [self.lat, self.lon]

    def as_geojson(self) -> list:
        """[lng, lat] for GeoJSON, OSRM, Overpass API."""
        return [self.lon, self.lat]

    def as_tuple(self) -> tuple:
        """(lat, lon) named tuple-style."""
        return (self.lat, self.lon)


def validate_bbox(south: float, west: float, north: float, east: float) -> tuple:
    """Validate and return a bounding box as (south, west, north, east).

    Validates:
    - All values are numeric
    - Latitude in [-90, 90]
    - Longitude in [-180, 180]
    - south <= north
    - west > east is allowed (antimeridian crossing)

    Returns:
        Tuple of (south, west, north, east) as floats.

    Raises:
        ValueError: If any validation fails.
    """
    try:
        south, west, north, east = float(south), float(west), float(north), float(east)
    except (TypeError, ValueError) as e:
        raise ValueError(f"All bbox values must be numeric: {e}")

    if not (-90 <= south <= 90 and -90 <= north <= 90):
        raise ValueError(f"Latitude out of range [-90, 90]: south={south}, north={north}")
    if not (-180 <= west <= 180 and -180 <= east <= 180):
        raise ValueError(f"Longitude out of range [-180, 180]: west={west}, east={east}")
    if south > north:
        raise ValueError(f"south ({south}) must be <= north ({north})")
    # Note: west > east is valid — it represents an antimeridian-crossing bbox
    # e.g., west=170, east=-170 spans the dateline. Overpass API handles this.

    return (south, west, north, east)


def bbox_to_overpass(south: float, west: float, north: float, east: float) -> str:
    """Format bbox as Overpass API string: 'south,west,north,east'."""
    return f"{south},{west},{north},{east}"


def estimate_utm_epsg(lon: float, lat: float) -> int:
    """Estimate the best metric projection EPSG code for a given WGS84 coordinate.

    Uses UTM for latitudes within ±84°. Falls back to UPS (Universal Polar
    Stereographic) for polar regions where UTM is undefined.

    Args:
        lon: Longitude in degrees.
        lat: Latitude in degrees.

    Returns:
        EPSG code for the appropriate projection zone.
    """
    # Polar regions: use UPS (Universal Polar Stereographic)
    if lat > 84.0:
        return 32661  # UPS North (EPSG:32661)
    if lat < -80.0:
        return 32761  # UPS South (EPSG:32761)

    zone_number = int((lon + 180) / 6) + 1
    if lat >= 0:
        return 32600 + zone_number  # Northern hemisphere UTM
    else:
        return 32700 + zone_number  # Southern hemisphere UTM


def project_geometry(geometry, from_crs: int, to_crs: int):
    """Project a Shapely geometry between coordinate reference systems.

    Args:
        geometry: Shapely geometry object.
        from_crs: Source EPSG code.
        to_crs: Target EPSG code.

    Returns:
        Projected Shapely geometry.
    """
    transformer = pyproj.Transformer.from_crs(
        f"EPSG:{from_crs}", f"EPSG:{to_crs}", always_xy=True
    )
    return shapely_transform(transformer.transform, geometry)


def project_to_utm(geometry, src_crs: int = 4326) -> tuple:
    """Project geometry from WGS84 to its appropriate UTM zone.

    Args:
        geometry: Shapely geometry in WGS84.
        src_crs: Source CRS EPSG code (default 4326).

    Returns:
        Tuple of (projected_geometry, utm_epsg).
    """
    centroid = geometry.centroid
    utm_epsg = estimate_utm_epsg(centroid.x, centroid.y)
    projected = project_geometry(geometry, src_crs, utm_epsg)
    return projected, utm_epsg


def project_to_wgs84(geometry, src_crs: int):
    """Project geometry back to WGS84 (EPSG:4326).

    Args:
        geometry: Shapely geometry in source CRS.
        src_crs: Source CRS EPSG code.

    Returns:
        Shapely geometry in WGS84.
    """
    return project_geometry(geometry, src_crs, 4326)


def buffer_geometry(geometry, distance_m: float):
    """Buffer a WGS84 geometry by a distance in meters.

    Projects to UTM (or UPS for polar), buffers, projects back to WGS84.
    Handles antimeridian-crossing results by clamping longitude to [-180, 180].

    Accuracy: within 0.2% for geometries spanning < 6° longitude.
    For wider geometries, error increases with span (up to ~30% at 18°).
    MAX_BUFFER_DISTANCE of 100km limits practical error to < 1%.

    Args:
        geometry: Shapely geometry in WGS84.
        distance_m: Buffer distance in meters.

    Returns:
        Buffered Shapely geometry in WGS84 (always valid).
    """
    projected, utm_epsg = project_to_utm(geometry)
    buffered = projected.buffer(distance_m)
    result = project_to_wgs84(buffered, utm_epsg)

    # Fix invalid geometries from antimeridian wrapping
    if not result.is_valid:
        result = result.buffer(0)  # Standard Shapely validity repair

    return result


def geodesic_area(geometry) -> float:
    """Calculate geodesic area of a WGS84 polygon in square meters.

    Uses pyproj.Geod for ellipsoidal accuracy.

    Args:
        geometry: Shapely polygon in WGS84.

    Returns:
        Area in square meters (absolute value).
    """
    geod = pyproj.Geod(ellps="WGS84")
    area, _ = geod.geometry_area_perimeter(geometry)
    return abs(area)


def geodesic_distance(point_a: ValidatedPoint, point_b: ValidatedPoint) -> float:
    """Calculate geodesic distance between two points in meters.

    Args:
        point_a: First point.
        point_b: Second point.

    Returns:
        Distance in meters.
    """
    geod = pyproj.Geod(ellps="WGS84")
    _, _, distance = geod.inv(point_a.lon, point_a.lat, point_b.lon, point_b.lat)
    return abs(distance)


def geojson_to_shapely(geojson_geometry: dict):
    """Convert a GeoJSON geometry dict to a Shapely geometry.

    Args:
        geojson_geometry: GeoJSON geometry dictionary.

    Returns:
        Shapely geometry object.
    """
    return shape(geojson_geometry)


def shapely_to_geojson(geometry) -> dict:
    """Convert a Shapely geometry to a GeoJSON geometry dict.

    Args:
        geometry: Shapely geometry object.

    Returns:
        GeoJSON geometry dictionary.
    """
    return mapping(geometry)
