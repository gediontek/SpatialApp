"""Handlers package for NL-to-GIS tool operations.

Shared helpers, constants, and dispatch function live here.
Domain-specific handlers are in sub-modules.
"""

import json
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

# ---------------------------------------------------------------------------
# Result size guards (Plan 05 M3)
# ---------------------------------------------------------------------------

# Feature-count thresholds.
WARN_FEATURE_COUNT = 5000
PAGINATE_FEATURE_COUNT = 10000
# Hard refusal size (bytes). At 100MB a single SSE payload will stall the
# browser and exhaust server memory during serialization.
REFUSE_SIZE_BYTES = 100 * 1024 * 1024

SIZE_THRESHOLDS = {
    "warn_feature_count": WARN_FEATURE_COUNT,
    "paginate_feature_count": PAGINATE_FEATURE_COUNT,
    "refuse_size_bytes": REFUSE_SIZE_BYTES,
}


def estimate_geojson_size(geojson: dict) -> int:
    """Estimate the serialized byte size of a GeoJSON FeatureCollection.

    Samples the first 10 features to avoid paying O(n) serialization cost
    on a guard check. Returns 0 for empty collections.
    """
    if not isinstance(geojson, dict):
        return 0
    features = geojson.get("features") or []
    n = len(features)
    if n == 0:
        return 0
    sample = features[: min(10, n)]
    try:
        sample_bytes = sum(len(json.dumps(f, default=str)) for f in sample)
    except (TypeError, ValueError):
        # Fall back to a conservative estimate if a feature isn't
        # JSON-serializable — assume 1KB per feature.
        return n * 1024
    avg = sample_bytes / len(sample)
    # 80 bytes of envelope for the FeatureCollection wrapper.
    return int(n * avg) + 80


def check_result_size(result: dict) -> dict:
    """Apply size guards in-place to a tool result containing `geojson`.

    - > WARN_FEATURE_COUNT:     add `size_warning` field.
    - > PAGINATE_FEATURE_COUNT: truncate features, add `truncated` + `original_count`.
    - > REFUSE_SIZE_BYTES:      empty the collection, add `error` field.

    Non-layer results (no `geojson`) pass through unchanged.
    """
    if not isinstance(result, dict):
        return result
    geojson = result.get("geojson")
    if not isinstance(geojson, dict):
        return result
    features = geojson.get("features")
    if not isinstance(features, list):
        return result

    count = len(features)

    # Refusal check first — before truncation so we bail loudly on huge payloads.
    size_bytes = estimate_geojson_size(geojson)
    if size_bytes > REFUSE_SIZE_BYTES:
        size_mb = size_bytes / (1024 * 1024)
        logger.warning(
            "Refusing oversized layer result: ~%.0f MB (%d features)",
            size_mb, count,
        )
        geojson["features"] = []
        result["error"] = (
            f"Result too large (~{size_mb:.0f} MB). Narrow your query — "
            f"use a smaller area or more specific feature type."
        )
        result["refused_size_bytes"] = size_bytes
        return result

    # Truncate if past the pagination threshold.
    if count > PAGINATE_FEATURE_COUNT:
        geojson["features"] = features[:PAGINATE_FEATURE_COUNT]
        result["truncated"] = True
        result["original_count"] = count
        result["feature_count"] = PAGINATE_FEATURE_COUNT
        logger.info(
            "Truncated layer result: %d -> %d features",
            count, PAGINATE_FEATURE_COUNT,
        )
        # Fall through — also emit the size warning below.
        count = PAGINATE_FEATURE_COUNT

    if count > WARN_FEATURE_COUNT:
        result["size_warning"] = (
            f"Large result: {count} features. Map performance may be affected. "
            f"Use filter_layer to narrow, or re-run with a smaller area."
        )

    return result

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
    "reproject_layer", "split_feature", "merge_features",
    "extract_vertices", "temporal_filter",
    # Raster layer-producing tools (v2.1 Plan 08)
    "raster_profile", "raster_classify", "raster_statistics",
    # Data pipeline layer producers (v2.1 Plan 10)
    "clip_to_bbox", "generalize", "import_auto",
    # v2.1 Plan 11: visualize_3d returns annotated polygons as a layer
    "visualize_3d",
    # v2.1 Plan 12: classification produces a layer
    "classify_area", "predict_labels",
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
    handle_reproject_layer,
    handle_detect_crs,
    handle_split_feature,
    handle_merge_features,
    handle_extract_vertices,
    handle_temporal_filter,
    handle_attribute_statistics,
    handle_clip_to_bbox,  # v2.1 Plan 10
    handle_generalize,    # v2.1 Plan 10
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
    handle_export_gpkg,   # v2.1 Plan 10
    handle_import_auto,   # v2.1 Plan 10
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
    handle_od_matrix,
)
from nl_gis.handlers.visualization import (  # noqa: E402,F401
    handle_choropleth_map,
    handle_chart,
    handle_animate_layer,
    handle_visualize_3d,
)
from nl_gis.handlers.autolabel import (  # noqa: E402,F401
    handle_classify_area,
    handle_predict_labels,
    handle_train_classifier,
    handle_export_training_data,
    handle_evaluate_classifier,
)


def _raster_call(tool_name: str, params: dict, layer_store: dict | None):
    """Lazy raster dispatcher — imports nl_gis.handlers.raster on demand so
    rasterio isn't required at module load time."""
    from nl_gis.handlers import raster as raster_mod
    if tool_name == "raster_info":
        return raster_mod.handle_raster_info(params)
    if tool_name == "raster_value":
        return raster_mod.handle_raster_value(params)
    if tool_name == "raster_statistics":
        return raster_mod.handle_raster_statistics(params, layer_store)
    if tool_name == "raster_profile":
        return raster_mod.handle_raster_profile(params)
    if tool_name == "raster_classify":
        return raster_mod.handle_raster_classify(params, layer_store)
    raise ValueError(f"Unknown raster tool: {tool_name}")


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
        # Missing capabilities (Milestone 5)
        "reproject_layer": lambda p: handle_reproject_layer(p, layer_store),
        "detect_crs": lambda p: handle_detect_crs(p, layer_store),
        "od_matrix": lambda p: handle_od_matrix(p, layer_store),
        "split_feature": lambda p: handle_split_feature(p, layer_store),
        "merge_features": lambda p: handle_merge_features(p, layer_store),
        "extract_vertices": lambda p: handle_extract_vertices(p, layer_store),
        "temporal_filter": lambda p: handle_temporal_filter(p, layer_store),
        "attribute_statistics": lambda p: handle_attribute_statistics(p, layer_store),
        # Raster analysis (v2.1 Plan 08)
        "raster_info": lambda p: _raster_call("raster_info", p, layer_store),
        "raster_value": lambda p: _raster_call("raster_value", p, layer_store),
        "raster_statistics": lambda p: _raster_call("raster_statistics", p, layer_store),
        "raster_profile": lambda p: _raster_call("raster_profile", p, layer_store),
        "raster_classify": lambda p: _raster_call("raster_classify", p, layer_store),
        # Data pipeline (v2.1 Plan 10)
        "clip_to_bbox": lambda p: handle_clip_to_bbox(p, layer_store),
        "generalize": lambda p: handle_generalize(p, layer_store),
        "export_gpkg": lambda p: handle_export_gpkg(p, layer_store),
        "import_auto": lambda p: handle_import_auto(p, layer_store),
        # Visualization (v2.1 Plan 11)
        "choropleth_map": lambda p: handle_choropleth_map(p, layer_store),
        "chart": lambda p: handle_chart(p, layer_store),
        "animate_layer": lambda p: handle_animate_layer(p, layer_store),
        "visualize_3d": lambda p: handle_visualize_3d(p, layer_store),
        # OSM auto-label (v2.1 Plan 12)
        "classify_area": lambda p: handle_classify_area(p, layer_store),
        "predict_labels": lambda p: handle_predict_labels(p, layer_store),
        "train_classifier": lambda p: handle_train_classifier(p, layer_store),
        "export_training_data": lambda p: handle_export_training_data(p, layer_store),
        "evaluate_classifier": lambda p: handle_evaluate_classifier(p, layer_store),
    }

    if tool_name not in handlers:
        raise ValueError(f"Unknown tool: {tool_name}")

    # (raster handlers imported lazily inside _raster_call below)

    result = handlers[tool_name](params)
    # Apply size guards to layer-producing tools so oversized results
    # never reach the browser without a warning / truncation.
    if tool_name in LAYER_PRODUCING_TOOLS and isinstance(result, dict):
        result = check_result_size(result)
    return result
