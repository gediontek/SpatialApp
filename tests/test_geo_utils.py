"""Tests for nl_gis.geo_utils module."""

import pytest
from shapely.geometry import Point, Polygon, box

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl_gis.geo_utils import (
    ValidatedPoint,
    validate_bbox,
    bbox_to_overpass,
    estimate_utm_epsg,
    project_to_utm,
    project_to_wgs84,
    buffer_geometry,
    geodesic_area,
    geodesic_distance,
    geojson_to_shapely,
    shapely_to_geojson,
)


class TestValidatedPoint:
    """Tests for ValidatedPoint immutable coordinate class."""

    def test_valid_point(self):
        p = ValidatedPoint(lat=47.6062, lon=-122.3321)
        assert p.lat == 47.6062
        assert p.lon == -122.3321

    def test_as_leaflet(self):
        """Leaflet expects [lat, lng]."""
        p = ValidatedPoint(lat=47.6, lon=-122.3)
        assert p.as_leaflet() == [47.6, -122.3]

    def test_as_geojson(self):
        """GeoJSON expects [lng, lat]."""
        p = ValidatedPoint(lat=47.6, lon=-122.3)
        assert p.as_geojson() == [-122.3, 47.6]

    def test_as_tuple(self):
        p = ValidatedPoint(lat=47.6, lon=-122.3)
        assert p.as_tuple() == (47.6, -122.3)

    def test_immutable(self):
        """ValidatedPoint is frozen (immutable)."""
        p = ValidatedPoint(lat=47.6, lon=-122.3)
        with pytest.raises(AttributeError):
            p.lat = 0

    def test_latitude_out_of_range_high(self):
        with pytest.raises(ValueError, match="out of range"):
            ValidatedPoint(lat=91.0, lon=0.0)

    def test_latitude_out_of_range_low(self):
        with pytest.raises(ValueError, match="out of range"):
            ValidatedPoint(lat=-91.0, lon=0.0)

    def test_longitude_out_of_range_high(self):
        with pytest.raises(ValueError, match="out of range"):
            ValidatedPoint(lat=0.0, lon=181.0)

    def test_longitude_out_of_range_low(self):
        with pytest.raises(ValueError, match="out of range"):
            ValidatedPoint(lat=0.0, lon=-181.0)

    def test_boundary_values(self):
        """Boundary coordinates should be valid."""
        ValidatedPoint(lat=90.0, lon=180.0)
        ValidatedPoint(lat=-90.0, lon=-180.0)
        ValidatedPoint(lat=0.0, lon=0.0)

    def test_non_numeric_lat(self):
        with pytest.raises(TypeError, match="numeric"):
            ValidatedPoint(lat="47.6", lon=-122.3)

    def test_non_numeric_lon(self):
        with pytest.raises(TypeError, match="numeric"):
            ValidatedPoint(lat=47.6, lon="bad")

    def test_int_coordinates(self):
        """Integer coordinates should work."""
        p = ValidatedPoint(lat=47, lon=-122)
        assert p.lat == 47
        assert p.lon == -122

    def test_equality(self):
        """Frozen dataclasses support equality."""
        p1 = ValidatedPoint(lat=47.6, lon=-122.3)
        p2 = ValidatedPoint(lat=47.6, lon=-122.3)
        assert p1 == p2

    def test_hashable(self):
        """Frozen dataclasses are hashable (usable in sets/dicts)."""
        p = ValidatedPoint(lat=47.6, lon=-122.3)
        s = {p}
        assert p in s


class TestValidateBbox:
    """Tests for validate_bbox function."""

    def test_valid_bbox(self):
        result = validate_bbox(47.5, -122.5, 47.7, -122.3)
        assert result == (47.5, -122.5, 47.7, -122.3)

    def test_south_greater_than_north(self):
        with pytest.raises(ValueError, match="south.*north"):
            validate_bbox(47.7, -122.5, 47.5, -122.3)

    def test_latitude_out_of_range(self):
        with pytest.raises(ValueError, match="Latitude"):
            validate_bbox(-91, -122.5, 47.7, -122.3)

    def test_longitude_out_of_range(self):
        with pytest.raises(ValueError, match="Longitude"):
            validate_bbox(47.5, -181, 47.7, -122.3)

    def test_string_inputs_converted(self):
        result = validate_bbox("47.5", "-122.5", "47.7", "-122.3")
        assert result == (47.5, -122.5, 47.7, -122.3)

    def test_non_numeric_input(self):
        with pytest.raises(ValueError, match="numeric"):
            validate_bbox("bad", -122.5, 47.7, -122.3)

    def test_equal_south_north(self):
        """south == north is valid (zero-height bbox)."""
        result = validate_bbox(47.5, -122.5, 47.5, -122.3)
        assert result == (47.5, -122.5, 47.5, -122.3)


class TestBboxToOverpass:
    """Tests for bbox_to_overpass."""

    def test_format(self):
        result = bbox_to_overpass(47.5, -122.5, 47.7, -122.3)
        assert result == "47.5,-122.5,47.7,-122.3"


class TestEstimateUtmEpsg:
    """Tests for UTM zone estimation."""

    def test_seattle(self):
        """Seattle is in UTM zone 10N (EPSG:32610)."""
        epsg = estimate_utm_epsg(-122.3, 47.6)
        assert epsg == 32610

    def test_london(self):
        """London is in UTM zone 30N (EPSG:32630)."""
        epsg = estimate_utm_epsg(-0.1, 51.5)
        assert epsg == 32630

    def test_southern_hemisphere(self):
        """Sydney is in UTM zone 56S (EPSG:32756)."""
        epsg = estimate_utm_epsg(151.2, -33.9)
        assert epsg == 32756


class TestProjection:
    """Tests for CRS projection functions."""

    def test_project_to_utm_and_back(self):
        """Round-trip projection should preserve geometry."""
        original = Point(-122.3, 47.6)  # GeoJSON order: lon, lat
        projected, utm_epsg = project_to_utm(original)

        # UTM coordinates should be in meters (large numbers)
        assert projected.x > 100000
        assert projected.y > 1000000

        # Round-trip back to WGS84
        restored = project_to_wgs84(projected, utm_epsg)
        assert abs(restored.x - original.x) < 1e-6
        assert abs(restored.y - original.y) < 1e-6


class TestBufferGeometry:
    """Tests for buffer_geometry."""

    def test_buffer_point(self):
        """Buffer a point by 1000m should create a polygon."""
        point = Point(-122.3, 47.6)
        buffered = buffer_geometry(point, 1000)

        assert buffered.geom_type == "Polygon"
        assert not buffered.is_empty

        # Check approximate area (pi * r^2 = ~3.14 km^2 for 1000m)
        area = geodesic_area(buffered)
        expected = 3.14159 * 1000 * 1000  # ~3,141,593 sq m
        assert abs(area - expected) / expected < 0.05  # Within 5%

    def test_buffer_polygon(self):
        """Buffer a polygon should expand it."""
        poly = box(-122.35, 47.55, -122.25, 47.65)
        buffered = buffer_geometry(poly, 500)

        # Buffered area should be larger
        original_area = geodesic_area(poly)
        buffered_area = geodesic_area(buffered)
        assert buffered_area > original_area


class TestGeodesicArea:
    """Tests for geodesic_area."""

    def test_known_area(self):
        """Test area calculation for a roughly known polygon."""
        # ~1 degree x ~1 degree box near equator ≈ 111km x 111km ≈ 12,321 sq km
        poly = box(0, 0, 1, 1)
        area = geodesic_area(poly)
        area_sq_km = area / 1e6
        assert 12000 < area_sq_km < 12500

    def test_small_polygon(self):
        """Small polygon should have small area."""
        poly = box(-122.35, 47.59, -122.34, 47.60)
        area = geodesic_area(poly)
        assert area > 0
        assert area < 1e7  # Less than 10 sq km


class TestGeodesicDistance:
    """Tests for geodesic_distance."""

    def test_known_distance(self):
        """Seattle to Portland is ~233 km."""
        seattle = ValidatedPoint(lat=47.6062, lon=-122.3321)
        portland = ValidatedPoint(lat=45.5152, lon=-122.6784)
        distance = geodesic_distance(seattle, portland)
        distance_km = distance / 1000
        assert 230 < distance_km < 240

    def test_same_point(self):
        """Distance from a point to itself is 0."""
        p = ValidatedPoint(lat=47.6, lon=-122.3)
        assert geodesic_distance(p, p) == 0.0

    def test_antipodal(self):
        """Distance between antipodal points ≈ half earth circumference."""
        p1 = ValidatedPoint(lat=0, lon=0)
        p2 = ValidatedPoint(lat=0, lon=180)
        distance = geodesic_distance(p1, p2)
        distance_km = distance / 1000
        assert 20000 < distance_km < 20100  # ~20,038 km


class TestGeoJsonConversion:
    """Tests for GeoJSON ↔ Shapely conversion."""

    def test_geojson_to_shapely_point(self):
        geojson = {"type": "Point", "coordinates": [-122.3, 47.6]}
        geom = geojson_to_shapely(geojson)
        assert geom.geom_type == "Point"
        assert geom.x == -122.3
        assert geom.y == 47.6

    def test_shapely_to_geojson_point(self):
        point = Point(-122.3, 47.6)
        geojson = shapely_to_geojson(point)
        assert geojson["type"] == "Point"
        assert geojson["coordinates"] == (-122.3, 47.6)

    def test_round_trip_polygon(self):
        coords = [[-122.4, 47.6], [-122.4, 47.7], [-122.3, 47.7],
                  [-122.3, 47.6], [-122.4, 47.6]]
        geojson = {"type": "Polygon", "coordinates": [coords]}

        geom = geojson_to_shapely(geojson)
        assert geom.geom_type == "Polygon"

        restored = shapely_to_geojson(geom)
        assert restored["type"] == "Polygon"
        assert len(restored["coordinates"][0]) == 5


class TestSpatialEdgeCases:
    """Spatial edge cases: antimeridian, poles, degenerate geometry."""

    def test_bbox_antimeridian_crossing(self):
        """west > east is valid for antimeridian-crossing bbox."""
        result = validate_bbox(south=-45, west=170, north=-30, east=-170)
        assert result == (-45.0, 170.0, -30.0, -170.0)

    def test_bbox_normal(self):
        result = validate_bbox(south=47.5, west=-122.5, north=47.6, east=-122.3)
        assert result[0] == 47.5

    def test_bbox_south_greater_than_north_rejected(self):
        with pytest.raises(ValueError):
            validate_bbox(south=48, west=-122, north=47, east=-121)

    def test_utm_polar_north(self):
        """Polar regions should use UPS, not crash."""
        epsg = estimate_utm_epsg(lon=0, lat=85)
        assert epsg == 32661  # UPS North

    def test_utm_polar_south(self):
        epsg = estimate_utm_epsg(lon=0, lat=-81)
        assert epsg == 32761  # UPS South

    def test_utm_mid_latitude(self):
        epsg = estimate_utm_epsg(lon=-122.3, lat=47.6)
        assert 32601 <= epsg <= 32660  # Northern UTM zone

    def test_buffer_at_pole(self):
        """Buffer at high latitude should not crash."""
        from shapely.geometry import Point
        # Svalbard (78°N) — within UTM range
        point = Point(15.6, 78.2)
        buffered = buffer_geometry(point, 1000)
        assert buffered.is_valid
        assert not buffered.is_empty

    def test_buffer_near_antimeridian(self):
        """Buffer near 180° longitude should produce valid geometry."""
        from shapely.geometry import Point
        point = Point(179.9, 0)
        buffered = buffer_geometry(point, 5000)
        assert buffered.is_valid

    def test_buffer_crossing_antimeridian(self):
        """Large buffer crossing the antimeridian must still be valid."""
        from shapely.geometry import Point
        point = Point(179.9, 0)
        buffered = buffer_geometry(point, 50000)  # 50km — will cross 180°
        assert buffered.is_valid
        assert not buffered.is_empty
        assert geodesic_area(buffered) > 0

    def test_geodesic_area_zero_area_polygon(self):
        """Degenerate polygon (line) should return ~0 area."""
        from shapely.geometry import Polygon
        # Three collinear points forming a degenerate polygon
        poly = Polygon([(-122.3, 47.6), (-122.3, 47.7), (-122.3, 47.6)])
        area = geodesic_area(poly)
        assert area < 1.0  # Essentially zero

    def test_geodesic_distance_same_point(self):
        p = ValidatedPoint(lat=47.6, lon=-122.3)
        assert geodesic_distance(p, p) == 0.0

    def test_validated_point_antimeridian(self):
        """Points at ±180 longitude are valid."""
        p1 = ValidatedPoint(lat=0, lon=180)
        p2 = ValidatedPoint(lat=0, lon=-180)
        assert p1.as_geojson() == [180, 0]
        assert p2.as_geojson() == [-180, 0]
