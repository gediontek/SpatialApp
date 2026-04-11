"""Handlers package for NL-to-GIS tool operations.

Shared helpers, constants, and dispatch function live here.
Domain-specific handlers are in sub-modules.
"""

import logging

from shapely.geometry import shape, mapping
from shapely.validation import make_valid
from shapely import STRtree

from config import Config
from nl_gis.geo_utils import (
    ValidatedPoint,
    geojson_to_shapely,
)

logger = logging.getLogger(__name__)

# Tools that produce layers (used by chat.py for layer_add events)
LAYER_PRODUCING_TOOLS = {
    "search_nearby", "buffer", "spatial_query",
    "filter_layer", "fetch_osm", "merge_layers",
    "import_layer", "import_csv", "import_wkt", "import_kml",
    "import_geoparquet", "clean_layer",
    "find_route", "isochrone", "closest_facility", "optimize_route",
    "classify_landcover", "intersection", "difference",
    "symmetric_difference", "convex_hull", "centroid", "simplify",
    "bounding_box", "dissolve", "clip", "voronoi", "batch_geocode",
    "point_in_polygon", "attribute_join", "spatial_statistics",
    "hot_spot_analysis", "execute_code",
    "interpolate", "repair_topology", "service_area",
}

# Reuse OSM feature mappings from app.py
OSM_FEATURE_MAPPINGS = {
    # Land use
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
    # Amenities
    'restaurant': {'key': 'amenity', 'value': 'restaurant'},
    'school': {'key': 'amenity', 'value': 'school'},
    'hospital': {'key': 'amenity', 'value': 'hospital'},
    'pharmacy': {'key': 'amenity', 'value': 'pharmacy'},
    'supermarket': {'key': 'shop', 'value': 'supermarket'},
    'hotel': {'key': 'tourism', 'value': 'hotel'},
    'church': {'key': 'amenity', 'value': 'place_of_worship'},
    'mosque': {'key': 'amenity', 'value': 'place_of_worship'},
    'bank': {'key': 'amenity', 'value': 'bank'},
    'atm': {'key': 'amenity', 'value': 'atm'},
    'cafe': {'key': 'amenity', 'value': 'cafe'},
    'bar': {'key': 'amenity', 'value': 'bar'},
    'cinema': {'key': 'amenity', 'value': 'cinema'},
    'library': {'key': 'amenity', 'value': 'library'},
    'university': {'key': 'amenity', 'value': 'university'},
    'police': {'key': 'amenity', 'value': 'police'},
    'fire_station': {'key': 'amenity', 'value': 'fire_station'},
    'post_office': {'key': 'amenity', 'value': 'post_office'},
    # Transport
    'bus_stop': {'key': 'highway', 'value': 'bus_stop'},
    'rail': {'key': 'railway', 'value': 'rail'},
    'parking': {'key': 'amenity', 'value': 'parking'},
    'fuel': {'key': 'amenity', 'value': 'fuel'},
    # Recreation
    'playground': {'key': 'leisure', 'value': 'playground'},
    'stadium': {'key': 'leisure', 'value': 'stadium'},
    'swimming_pool': {'key': 'leisure', 'value': 'swimming_pool'},
    'cemetery': {'key': 'landuse', 'value': 'cemetery'},
    # Nature
    'wetland': {'key': 'natural', 'value': 'wetland'},
    'beach': {'key': 'natural', 'value': 'beach'},
    'cliff': {'key': 'natural', 'value': 'cliff'},
}


# ============================================================
# Shared helpers
# ============================================================

def _resolve_point(params, lat_key="lat", lon_key="lon", location_key="location"):
    """Resolve a geographic point from coordinates or location name.

    Returns (ValidatedPoint, display_name, error_string).
    If error_string is not None, point and display_name are None.
    """
    from nl_gis.handlers.navigation import handle_geocode

    lat = params.get(lat_key)
    lon = params.get(lon_key)
    location = params.get(location_key)

    if lat is not None and lon is not None:
        try:
            return ValidatedPoint(lat=float(lat), lon=float(lon)), None, None
        except (ValueError, TypeError) as e:
            return None, None, f"Invalid coordinates: {e}"
    elif location:
        result = handle_geocode({"query": location})
        if "error" in result:
            return None, None, f"Could not find location: {location}"
        return ValidatedPoint(lat=result["lat"], lon=result["lon"]), result.get("display_name"), None
    else:
        return None, None, f"Provide {lat_key}/{lon_key} coordinates or {location_key} name"


def _resolve_point_from_object(params, point_key="from_point", location_key="from_location"):
    """Resolve a geographic point from a point object or location name.

    For tools like find_route/measure_distance that use {lat, lon} objects.
    Returns (ValidatedPoint, display_name, error_string).
    """
    from nl_gis.handlers.navigation import handle_geocode

    point_obj = params.get(point_key)
    location = params.get(location_key)

    if point_obj and "lat" in point_obj and "lon" in point_obj:
        try:
            return ValidatedPoint(lat=float(point_obj["lat"]), lon=float(point_obj["lon"])), None, None
        except (ValueError, TypeError) as e:
            return None, None, f"Invalid coordinates: {e}"
    elif location:
        result = handle_geocode({"query": location})
        if "error" in result:
            return None, None, f"Could not geocode: {result['error']}"
        return ValidatedPoint(lat=result["lat"], lon=result["lon"]), result.get("display_name"), None
    else:
        return None, None, f"Provide {point_key} or {location_key}"


def _osm_to_geojson(osm_data: dict, category_name: str, feature_type: str) -> dict:
    """Convert Overpass API response to GeoJSON FeatureCollection.

    Supports both `out geom` (inline geometry) and legacy `out body + >`
    (separate node elements) response formats.
    """
    geojson = {"type": "FeatureCollection", "features": []}
    if "elements" not in osm_data:
        return geojson

    # Build node lookup only if needed (legacy format)
    nodes = None

    count = 0
    max_features = Config.MAX_FEATURES_PER_LAYER

    for el in osm_data["elements"]:
        if count >= max_features:
            break
        if el["type"] == "way":
            # Prefer inline geometry from `out geom`
            if "geometry" in el:
                coords = [(pt["lon"], pt["lat"]) for pt in el["geometry"]]
            else:
                # Fallback: node ID lookup (legacy format)
                if nodes is None:
                    nodes = {
                        n["id"]: (n["lon"], n["lat"])
                        for n in osm_data["elements"] if n["type"] == "node"
                    }
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

        elif el["type"] == "relation":
            # Handle relation elements (parks, water bodies, admin boundaries)
            # When using `out geom`, member ways include inline geometry
            members = el.get("members", [])
            if not members:
                continue

            # Collect outer and inner rings from member ways
            outer_rings = []
            inner_rings = []
            for member in members:
                if member.get("type") != "way" or "geometry" not in member:
                    continue
                coords = [(pt["lon"], pt["lat"]) for pt in member["geometry"]]
                if len(coords) < 3:
                    continue
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                role = member.get("role", "outer")
                if role == "inner":
                    inner_rings.append(coords)
                else:
                    outer_rings.append(coords)

            if not outer_rings:
                # Fallback: check if the relation itself has a geometry key
                if "geometry" in el:
                    coords = [(pt["lon"], pt["lat"]) for pt in el["geometry"]]
                    if len(coords) >= 3:
                        if coords[0] != coords[-1]:
                            coords.append(coords[0])
                        outer_rings.append(coords)

            if not outer_rings:
                continue

            # Build polygon(s): simple case -- one outer ring with holes
            if len(outer_rings) == 1:
                polygon_coords = [outer_rings[0]] + inner_rings
                geom = {"type": "Polygon", "coordinates": polygon_coords}
            else:
                # Multiple outer rings -> MultiPolygon
                # Simple assignment: all inner rings go to the first outer ring
                # (a full implementation would match inners to their enclosing outer)
                polygons = []
                for i, outer in enumerate(outer_rings):
                    if i == 0:
                        polygons.append([outer] + inner_rings)
                    else:
                        polygons.append([outer])
                geom = {"type": "MultiPolygon", "coordinates": polygons}

            # Validate constructed geometry (OSM way ordering can be inconsistent)
            try:
                shapely_geom = shape(geom)
                if not shapely_geom.is_valid:
                    shapely_geom = make_valid(shapely_geom)
                    geom = mapping(shapely_geom)
            except Exception:
                logger.warning("Invalid relation geometry for osm_id=%s, skipping", el.get("id"))
                continue

            geojson["features"].append({
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "category_name": category_name,
                    "feature_type": feature_type,
                    "osm_id": el.get("id"),
                    "osm_tags": el.get("tags", {}),
                },
            })
            count += 1

    return geojson


def _build_spatial_index(geometries):
    """Build an STRtree spatial index from a list of Shapely geometries.

    Returns the tree for use with query(), or None if the list is empty.
    The tree is built per-query (not cached) since layers can change between queries.
    """
    if not geometries:
        return None
    return STRtree(geometries)


def _safe_geojson_to_shapely(geojson_geom):
    """Safely convert GeoJSON to Shapely, returning None on failure.

    Automatically repairs invalid geometries (e.g., self-intersecting polygons)
    using the buffer(0) technique.
    """
    try:
        geom = geojson_to_shapely(geojson_geom)
        if geom.is_empty:
            return None
        # Auto-repair invalid geometries (self-intersections, etc.)
        if not geom.is_valid:
            geom = geom.buffer(0)
            if geom.is_empty:
                return None
        return geom
    except Exception:
        logger.debug("Failed to parse geometry in _safe_shape", exc_info=True)
        return None


def _get_layer_snapshot(layer_store, layer_name):
    """Get a snapshot of a layer's features list. Thread-safe."""
    from state import layer_lock

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


# ============================================================
# Import all handler functions from sub-modules for re-export
# ============================================================

from nl_gis.handlers.navigation import (  # noqa: E402,F401
    handle_geocode,
    handle_fetch_osm,
    handle_map_command,
    handle_search_nearby,
    handle_reverse_geocode,
    handle_batch_geocode,
)
from nl_gis.handlers.analysis import (  # noqa: E402,F401
    handle_buffer,
    handle_spatial_query,
    handle_aggregate,
    handle_calculate_area,
    handle_measure_distance,
    handle_filter_layer,
    handle_intersection,
    handle_difference,
    handle_symmetric_difference,
    handle_convex_hull,
    handle_centroid,
    handle_simplify,
    handle_bounding_box,
    handle_dissolve,
    handle_clip,
    handle_voronoi,
    handle_point_in_polygon,
    handle_attribute_join,
    handle_spatial_statistics,
    handle_hot_spot_analysis,
    handle_execute_code,
    handle_interpolate,
    handle_validate_topology,
    handle_repair_topology,
    handle_describe_layer,
    handle_detect_duplicates,
    handle_clean_layer,
)
from nl_gis.handlers.layers import (  # noqa: E402,F401
    handle_style_layer,
    handle_layer_visibility,
    handle_highlight_features,
    handle_merge_layers,
    handle_import_layer,
    handle_import_csv,
    handle_import_wkt,
    handle_export_layer,
    handle_import_kml,
    handle_import_geoparquet,
    handle_export_geoparquet,
)
from nl_gis.handlers.annotations import (  # noqa: E402,F401
    handle_add_annotation,
    handle_classify_landcover,
    _classify_landcover_work,
    handle_export_annotations,
    handle_get_annotations,
)
from nl_gis.handlers.routing import (  # noqa: E402,F401
    handle_find_route,
    handle_isochrone,
    handle_heatmap,
    handle_closest_facility,
    handle_optimize_route,
    handle_service_area,
)


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
        "reverse_geocode": handle_reverse_geocode,
        "batch_geocode": lambda p: handle_batch_geocode(p, layer_store),
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
        "filter_layer": lambda p: handle_filter_layer(p, layer_store),
        "style_layer": handle_style_layer,
        # Phase 3
        "add_annotation": lambda p: handle_add_annotation(p, layer_store),
        "classify_landcover": handle_classify_landcover,
        "export_annotations": handle_export_annotations,
        "get_annotations": handle_get_annotations,
        "import_layer": lambda p: handle_import_layer(p, layer_store),
        "import_csv": lambda p: handle_import_csv(p, layer_store),
        "import_wkt": lambda p: handle_import_wkt(p, layer_store),
        "export_layer": lambda p: handle_export_layer(p, layer_store),
        "merge_layers": lambda p: handle_merge_layers(p, layer_store),
        # Phase 4
        "find_route": handle_find_route,
        "isochrone": handle_isochrone,
        "heatmap": lambda p: handle_heatmap(p, layer_store),
        "closest_facility": lambda p: handle_closest_facility(p, layer_store),
        "optimize_route": lambda p: handle_optimize_route(p, layer_store),
        # Overlay operations
        "intersection": lambda p: handle_intersection(p, layer_store),
        "difference": lambda p: handle_difference(p, layer_store),
        "symmetric_difference": lambda p: handle_symmetric_difference(p, layer_store),
        # Geometry tools
        "convex_hull": lambda p: handle_convex_hull(p, layer_store),
        "centroid": lambda p: handle_centroid(p, layer_store),
        "simplify": lambda p: handle_simplify(p, layer_store),
        "bounding_box": lambda p: handle_bounding_box(p, layer_store),
        "dissolve": lambda p: handle_dissolve(p, layer_store),
        "clip": lambda p: handle_clip(p, layer_store),
        "voronoi": lambda p: handle_voronoi(p, layer_store),
        # Advanced analysis tools
        "point_in_polygon": lambda p: handle_point_in_polygon(p, layer_store),
        "attribute_join": lambda p: handle_attribute_join(p, layer_store),
        "spatial_statistics": lambda p: handle_spatial_statistics(p, layer_store),
        "hot_spot_analysis": lambda p: handle_hot_spot_analysis(p, layer_store),
        "execute_code": lambda p: handle_execute_code(p, layer_store),
        # Spatial analysis depth (Milestone 1)
        "interpolate": lambda p: handle_interpolate(p, layer_store),
        "validate_topology": lambda p: handle_validate_topology(p, layer_store),
        "repair_topology": lambda p: handle_repair_topology(p, layer_store),
        "service_area": lambda p: handle_service_area(p, layer_store),
        # Data pipeline & formats (Milestone 2)
        "import_kml": lambda p: handle_import_kml(p, layer_store),
        "import_geoparquet": lambda p: handle_import_geoparquet(p, layer_store),
        "export_geoparquet": lambda p: handle_export_geoparquet(p, layer_store),
        "describe_layer": lambda p: handle_describe_layer(p, layer_store),
        "detect_duplicates": lambda p: handle_detect_duplicates(p, layer_store),
        "clean_layer": lambda p: handle_clean_layer(p, layer_store),
    }

    if tool_name not in handlers:
        raise ValueError(f"Unknown tool: {tool_name}")

    return handlers[tool_name](params)
