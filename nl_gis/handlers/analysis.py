"""Spatial analysis handlers: buffer, spatial query, aggregate, area, distance, filter, geometry, advanced analysis.

ERROR PATHS (audit 2026-04-17 for v2.1 Plan 05 M1):
    166 error returns · 44 except blocks · 0 leaky str(e).
    No exception-detail leaks; errors already use generic messages.
    Candidates for size-guard integration (M3): handlers returning geojson.
"""

import hashlib
import json
import logging
import math
import time
from collections import defaultdict
from datetime import datetime

from shapely.geometry import mapping, shape, Point
from shapely.ops import unary_union, split

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
    project_geometry,
)
from nl_gis.handlers import (
    _resolve_point_from_object,
    _safe_geojson_to_shapely,
    _get_layer_snapshot,
    _get_layer_geometries,
    _build_spatial_index,
)

logger = logging.getLogger(__name__)

MAX_BUFFER_DISTANCE_M = 100000  # 100 km max

# ---------------------------------------------------------------------------
# Spatial query result cache
# ---------------------------------------------------------------------------
_spatial_cache = {}  # key -> (result, timestamp)
_SPATIAL_CACHE_TTL = 300  # 5 minutes
_SPATIAL_CACHE_MAX = 100  # max entries


def _spatial_query_cache_key(source_features, target_geojson, predicate, distance_m):
    """Generate cache key from query parameters."""
    key_data = json.dumps({
        "source_count": len(source_features),
        "source_hash": hashlib.md5(
            json.dumps(source_features, sort_keys=True).encode()
        ).hexdigest()[:8],
        "target": target_geojson,
        "predicate": predicate,
        "distance_m": distance_m,
    }, sort_keys=True)
    return hashlib.md5(key_data.encode()).hexdigest()


def _get_cached_spatial_result(key):
    """Return cached result if present and not expired."""
    entry = _spatial_cache.get(key)
    if entry and (time.time() - entry[1]) < _SPATIAL_CACHE_TTL:
        return entry[0]
    return None


def _set_cached_spatial_result(key, result):
    """Store result in cache, evicting oldest entry if at capacity."""
    if len(_spatial_cache) >= _SPATIAL_CACHE_MAX:
        oldest_key = min(_spatial_cache, key=lambda k: _spatial_cache[k][1])
        del _spatial_cache[oldest_key]
    _spatial_cache[key] = (result, time.time())


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
    # Resolve from point
    from_vp, from_name, err = _resolve_point_from_object(params, "from_point", "from_location")
    if err:
        return {"error": err}

    # Resolve to point
    to_vp, to_name, err = _resolve_point_from_object(params, "to_point", "to_location")
    if err:
        return {"error": err}

    distance = geodesic_distance(from_vp, to_vp)

    return {
        "distance_m": round(distance, 2),
        "distance_km": round(distance / 1000, 2),
        "distance_mi": round(distance / 1609.344, 2),
        "from_name": from_name,
        "to_name": to_name,
    }


def handle_buffer(params: dict, layer_store: dict = None) -> dict:
    """Create a buffer around geometry or layer features."""
    try:
        distance_m = float(params.get("distance_m", 0))
    except (TypeError, ValueError):
        return {"error": "distance_m must be a number"}
    if distance_m <= 0:
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

    # Get target geometry specification for cache key
    target_geojson_for_cache = None
    if target_layer:
        target_geojson_for_cache = {"target_layer": target_layer}
    elif target_geometry:
        target_geojson_for_cache = target_geometry

    # Get original features from source layer for cache key computation.
    source_features, _ = _get_layer_snapshot(layer_store, source_layer)
    source_features = source_features or []

    # Check cache before doing expensive spatial operations
    cache_key = _spatial_query_cache_key(
        source_features, target_geojson_for_cache, predicate, distance_m
    )
    cached = _get_cached_spatial_result(cache_key)
    if cached:
        return cached

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

    # Filter to features with valid geometry, aligned with source_geoms.
    # _get_layer_geometries filters out features with invalid/missing geometry,
    # so we must apply the same filter to keep indices aligned.
    valid_source_features = []
    for f in source_features:
        geom = f.get("geometry")
        if geom:
            shapely_geom = _safe_geojson_to_shapely(geom)
            if shapely_geom:
                valid_source_features.append(f)

    matching_features = []

    # Use spatial index (STRtree) to filter candidates by bounding box overlap,
    # then verify with exact predicate. Identical results, faster for large layers.
    tree = _build_spatial_index(source_geoms)
    if tree is not None:
        candidate_indices = tree.query(target_geom)
        for i in candidate_indices:
            geom = source_geoms[i]
            match = False
            if predicate == "intersects" or predicate == "within_distance":
                match = geom.intersects(target_geom)
            elif predicate == "contains":
                match = geom.contains(target_geom)
            elif predicate == "within":
                match = geom.within(target_geom)
            if match:
                matching_features.append(valid_source_features[i])

    result_geojson = {
        "type": "FeatureCollection",
        "features": matching_features[:Config.MAX_FEATURES_PER_LAYER],
    }

    result_name = f"{predicate}_{source_layer}"

    result = {
        "geojson": result_geojson,
        "layer_name": result_name,
        "feature_count": len(matching_features),
        "source_total": len(source_geoms),
        "match_percentage": round(len(matching_features) / max(len(source_geoms), 1) * 100, 1),
    }

    _set_cached_spatial_result(cache_key, result)
    return result


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
        polygon_count = 0
        for f in features:
            geom = f.get("geometry")
            if geom and geom.get("type") in ("Polygon", "MultiPolygon"):
                total_area += geodesic_area(geojson_to_shapely(geom))
                polygon_count += 1
        return {
            "total_area_sq_m": round(total_area, 2),
            "total_area_sq_km": round(total_area / 1e6, 4),
            "total_area_acres": round(total_area / 4046.86, 2),
            "polygon_count": polygon_count,
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


def handle_filter_layer(params: dict, layer_store: dict = None) -> dict:
    """Filter features in a layer by attribute value. Returns a new layer."""
    layer_name = params.get("layer_name")
    attribute = params.get("attribute")
    operator = params.get("operator", "equals")
    value = params.get("value") or ""
    output_name = params.get("output_name", f"filtered_{layer_name}")

    if not layer_name or not attribute:
        return {"error": "layer_name and attribute are required"}

    supported_operators = {"equals", "not_equals", "contains", "starts_with",
                           "greater_than", "less_than", "greater_equal", "less_equal", "between"}
    if operator not in supported_operators:
        return {"error": f"Unknown operator '{operator}'. Supported: {', '.join(sorted(supported_operators))}"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}

    # Attribute validation (Plan 04 M4.2): if the attribute doesn't appear
    # on ANY sampled feature (including nested osm_tags), tell the user which
    # attributes actually exist. Silent zero-result filters are confusing.
    available: set[str] = set()
    for f in features[:200]:
        props = f.get("properties") if isinstance(f, dict) else None
        if isinstance(props, dict):
            available.update(props.keys())
            tags = props.get("osm_tags")
            if isinstance(tags, dict):
                available.update(tags.keys())
    if available and attribute not in available:
        preview = ", ".join(sorted(available)[:15])
        return {
            "error": (
                f"Attribute '{attribute}' not found in layer '{layer_name}'. "
                f"Available attributes: {preview}"
                + (" (...more)" if len(available) > 15 else "")
            )
        }

    filtered = []
    val_lower = value.lower()
    for feature in features:
        props = feature.get("properties", {})
        tags = props.get("osm_tags", {})
        # Check both direct properties and OSM tags
        prop_val = str(props.get(attribute, tags.get(attribute, "")))

        match = False
        if operator == "equals":
            match = prop_val.lower() == val_lower
        elif operator == "not_equals":
            match = prop_val.lower() != val_lower
        elif operator == "contains":
            match = val_lower in prop_val.lower()
        elif operator == "starts_with":
            match = prop_val.lower().startswith(val_lower)
        elif operator == "greater_than":
            try:
                match = float(prop_val) > float(value)
            except (ValueError, TypeError):
                match = False
        elif operator == "less_than":
            try:
                match = float(prop_val) < float(value)
            except (ValueError, TypeError):
                match = False
        elif operator == "greater_equal":
            try:
                match = float(prop_val) >= float(value)
            except (ValueError, TypeError):
                match = False
        elif operator == "less_equal":
            try:
                match = float(prop_val) <= float(value)
            except (ValueError, TypeError):
                match = False
        elif operator == "between":
            try:
                parts = value.split(",")
                if len(parts) != 2:
                    match = False
                else:
                    min_val, max_val = float(parts[0].strip()), float(parts[1].strip())
                    match = min_val <= float(prop_val) <= max_val
            except (ValueError, TypeError):
                match = False

        if match:
            filtered.append(feature)

    result_geojson = {"type": "FeatureCollection", "features": filtered}
    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": len(filtered),
        "original_count": len(features),
    }


def _overlay_operation(params: dict, layer_store: dict, op_name: str) -> dict:
    """Shared logic for overlay operations (intersection, difference, symmetric_difference).

    Args:
        params: Tool parameters with layer_a, layer_b, output_name.
        layer_store: Server-side layer store.
        op_name: One of 'intersection', 'difference', 'symmetric_difference'.

    Returns:
        Result dict with geojson, layer_name, or error.
    """
    from shapely.validation import make_valid

    layer_a = params.get("layer_a")
    layer_b = params.get("layer_b")

    if not layer_a or not layer_b:
        return {"error": "Both layer_a and layer_b are required"}

    output_name = params.get("output_name", f"{op_name}_{layer_a}_{layer_b}")

    # Get geometries from both layers
    geoms_a, err = _get_layer_geometries(layer_store, layer_a)
    if err:
        return {"error": f"layer_a: {err}"}
    geoms_b, err = _get_layer_geometries(layer_store, layer_b)
    if err:
        return {"error": f"layer_b: {err}"}

    if not geoms_a:
        return {"error": f"Layer '{layer_a}' has no valid geometries"}
    if not geoms_b:
        return {"error": f"Layer '{layer_b}' has no valid geometries"}

    # Union each layer's geometries, then apply the overlay operation
    geom_a = unary_union(geoms_a)
    geom_b = unary_union(geoms_b)

    # Ensure valid geometries before overlay
    if not geom_a.is_valid:
        geom_a = make_valid(geom_a)
    if not geom_b.is_valid:
        geom_b = make_valid(geom_b)

    try:
        if op_name == "intersection":
            result = geom_a.intersection(geom_b)
        elif op_name == "difference":
            result = geom_a.difference(geom_b)
        elif op_name == "symmetric_difference":
            result = geom_a.symmetric_difference(geom_b)
        else:
            return {"error": f"Unknown overlay operation: {op_name}"}
    except Exception as e:
        logger.error("Overlay %s failed: %s", op_name, e, exc_info=True)
        return {"error": f"Overlay operation failed. The geometries may be incompatible."}

    # Handle empty result
    if result.is_empty:
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "layer_name": output_name,
            "feature_count": 0,
            "message": f"The {op_name} produced an empty result (no overlapping area).",
        }

    # Ensure result is valid
    if not result.is_valid:
        result = make_valid(result)

    result_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": shapely_to_geojson(result),
            "properties": {
                "operation": op_name,
                "layer_a": layer_a,
                "layer_b": layer_b,
            }
        }]
    }

    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": 1,
        "area_sq_km": round(geodesic_area(result) / 1e6, 4),
    }


def handle_intersection(params: dict, layer_store: dict = None) -> dict:
    """Compute geometric intersection of two layers."""
    return _overlay_operation(params, layer_store, "intersection")


def handle_difference(params: dict, layer_store: dict = None) -> dict:
    """Subtract layer B geometry from layer A geometry."""
    return _overlay_operation(params, layer_store, "difference")


def handle_symmetric_difference(params: dict, layer_store: dict = None) -> dict:
    """Compute areas in either layer but not both."""
    return _overlay_operation(params, layer_store, "symmetric_difference")


# ============================================================
# Geometry Tools
# ============================================================


def handle_convex_hull(params: dict, layer_store: dict = None) -> dict:
    """Compute the convex hull of a layer's features."""
    layer_name = params.get("layer_name")
    output_name = params.get("output_name", f"convex_hull_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}

    geoms, err = _get_layer_geometries(layer_store, layer_name)
    if err:
        return {"error": err}
    if not geoms:
        return {"error": f"Layer '{layer_name}' has no valid geometries"}

    hull = unary_union(geoms).convex_hull

    if hull.is_empty:
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "layer_name": output_name,
            "feature_count": 0,
            "message": "Convex hull produced an empty result.",
        }

    result_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": shapely_to_geojson(hull),
            "properties": {
                "operation": "convex_hull",
                "source_layer": layer_name,
            }
        }]
    }

    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": 1,
    }


def handle_centroid(params: dict, layer_store: dict = None) -> dict:
    """Extract centroids of features as a point layer."""
    layer_name = params.get("layer_name")
    output_name = params.get("output_name", f"centroids_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    centroid_features = []
    for f in features:
        geom = f.get("geometry")
        if not geom:
            continue
        shapely_geom = _safe_geojson_to_shapely(geom)
        if not shapely_geom:
            continue
        centroid = shapely_geom.centroid
        centroid_features.append({
            "type": "Feature",
            "geometry": shapely_to_geojson(centroid),
            "properties": dict(f.get("properties", {})),
        })

    result_geojson = {
        "type": "FeatureCollection",
        "features": centroid_features,
    }

    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": len(centroid_features),
    }


def handle_simplify(params: dict, layer_store: dict = None) -> dict:
    """Simplify geometries to reduce vertex count."""
    layer_name = params.get("layer_name")
    try:
        tolerance = float(params.get("tolerance", 10))
    except (TypeError, ValueError):
        return {"error": "tolerance must be a number"}
    if tolerance <= 0:
        return {"error": "tolerance must be a positive number"}

    output_name = params.get("output_name", f"simplified_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    simplified_features = []
    for f in features:
        geom = f.get("geometry")
        if not geom:
            continue
        shapely_geom = _safe_geojson_to_shapely(geom)
        if not shapely_geom:
            continue

        # Project to UTM, simplify in meters, project back
        projected, utm_epsg = project_to_utm(shapely_geom)
        simplified = projected.simplify(tolerance, preserve_topology=True)
        result_geom = project_to_wgs84(simplified, utm_epsg)

        if result_geom.is_empty:
            continue

        simplified_features.append({
            "type": "Feature",
            "geometry": shapely_to_geojson(result_geom),
            "properties": dict(f.get("properties", {})),
        })

    result_geojson = {
        "type": "FeatureCollection",
        "features": simplified_features,
    }

    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": len(simplified_features),
        "tolerance_m": tolerance,
    }


def handle_bounding_box(params: dict, layer_store: dict = None) -> dict:
    """Create a bounding box polygon from layer extent."""
    layer_name = params.get("layer_name")
    output_name = params.get("output_name", f"bbox_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}

    geoms, err = _get_layer_geometries(layer_store, layer_name)
    if err:
        return {"error": err}
    if not geoms:
        return {"error": f"Layer '{layer_name}' has no valid geometries"}

    envelope = unary_union(geoms).envelope

    if envelope.is_empty:
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "layer_name": output_name,
            "feature_count": 0,
            "message": "Bounding box produced an empty result.",
        }

    result_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": shapely_to_geojson(envelope),
            "properties": {
                "operation": "bounding_box",
                "source_layer": layer_name,
            }
        }]
    }

    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": 1,
    }


def handle_dissolve(params: dict, layer_store: dict = None) -> dict:
    """Merge features by attribute value using GeoPandas dissolve."""
    import geopandas as gpd_mod

    layer_name = params.get("layer_name")
    by_attr = params.get("by")
    output_name = params.get("output_name", f"dissolved_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}
    if not by_attr:
        return {"error": "'by' attribute name is required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    # Build a GeoJSON FeatureCollection for GeoPandas
    fc = {"type": "FeatureCollection", "features": features}
    try:
        gdf = gpd_mod.GeoDataFrame.from_features(fc, crs="EPSG:4326")
    except Exception as exc:
        logger.error("Failed to create GeoDataFrame for dissolve", exc_info=True)
        return {"error": "Failed to parse layer features for dissolve"}

    if by_attr not in gdf.columns:
        return {"error": f"Attribute '{by_attr}' not found in layer properties. Available: {', '.join(c for c in gdf.columns if c != 'geometry')}"}

    try:
        dissolved = gdf.dissolve(by=by_attr).reset_index()
    except Exception as exc:
        logger.error("Dissolve operation failed", exc_info=True)
        return {"error": "Dissolve operation failed"}

    import json
    result_geojson = json.loads(dissolved.to_json())

    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": len(result_geojson.get("features", [])),
        "dissolved_by": by_attr,
    }


def handle_clip(params: dict, layer_store: dict = None) -> dict:
    """Clip one layer by another's boundary."""
    clip_layer = params.get("clip_layer")
    mask_layer = params.get("mask_layer")
    output_name = params.get("output_name", f"clipped_{clip_layer}")

    if not clip_layer:
        return {"error": "clip_layer is required"}
    if not mask_layer:
        return {"error": "mask_layer is required"}

    # Get clip features (need original features for properties)
    clip_features, err = _get_layer_snapshot(layer_store, clip_layer)
    if err:
        return {"error": f"clip_layer: {err}"}
    if not clip_features:
        return {"error": f"Layer '{clip_layer}' has no features"}

    # Get mask geometries and union them
    mask_geoms, err = _get_layer_geometries(layer_store, mask_layer)
    if err:
        return {"error": f"mask_layer: {err}"}
    if not mask_geoms:
        return {"error": f"Layer '{mask_layer}' has no valid geometries"}

    mask_union = unary_union(mask_geoms)

    clipped_features = []
    for f in clip_features:
        geom = f.get("geometry")
        if not geom:
            continue
        shapely_geom = _safe_geojson_to_shapely(geom)
        if not shapely_geom:
            continue

        clipped = shapely_geom.intersection(mask_union)
        if clipped.is_empty:
            continue

        clipped_features.append({
            "type": "Feature",
            "geometry": shapely_to_geojson(clipped),
            "properties": dict(f.get("properties", {})),
        })

    result_geojson = {
        "type": "FeatureCollection",
        "features": clipped_features,
    }

    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": len(clipped_features),
    }


def handle_clip_to_bbox(params: dict, layer_store: dict = None) -> dict:
    """Clip a layer to a bounding box (v2.1 Plan 10 M1)."""
    from shapely.geometry import box as shapely_box

    layer_name = params.get("layer_name")
    bbox = params.get("bbox")
    location = params.get("location")
    output_name = params.get("output_name", f"clipped_bbox_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}

    # Resolve bbox — either explicit, or via geocoded location.
    if not bbox and location:
        from nl_gis.handlers.navigation import handle_geocode
        geo = handle_geocode({"query": location})
        if "error" in geo:
            return {"error": f"Could not geocode location: {geo['error']}"}
        bbox_raw = geo.get("bbox")
        if not bbox_raw or len(bbox_raw) != 4:
            return {"error": f"Geocoded '{location}' but no bounding box returned."}
        # Nominatim returns [south, north, west, east] as strings — normalize.
        try:
            s, n, w, e = [float(v) for v in bbox_raw]
            bbox = [s, w, n, e]
        except (TypeError, ValueError):
            return {"error": "Could not parse geocoded bounding box."}
    if not bbox or len(bbox) != 4:
        return {"error": "bbox must be [south, west, north, east] or provide a location."}

    try:
        s, w, n, e = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return {"error": "bbox values must be numeric."}
    # Shapely box expects (minx, miny, maxx, maxy) = (west, south, east, north)
    mask = shapely_box(w, s, e, n)

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}

    clipped = []
    for f in features:
        geom = f.get("geometry")
        if not geom:
            continue
        shp = _safe_geojson_to_shapely(geom)
        if not shp:
            continue
        inter = shp.intersection(mask)
        if inter.is_empty:
            continue
        clipped.append({
            "type": "Feature",
            "geometry": shapely_to_geojson(inter),
            "properties": dict(f.get("properties", {})),
        })

    if not clipped:
        return {"error": "No features found within the bounding box"}

    return {
        "geojson": {"type": "FeatureCollection", "features": clipped},
        "layer_name": output_name,
        "feature_count": len(clipped),
        "bbox": [s, w, n, e],
    }


def handle_generalize(params: dict, layer_store: dict = None) -> dict:
    """Simplify geometries by a tolerance specified in METERS (v2.1 Plan 10 M1).

    Unlike `handle_simplify` (tolerance in CRS units), this accepts meters and
    converts using the layer centroid's latitude. Reports vertex reduction.
    """
    layer_name = params.get("layer_name")
    tolerance_m = params.get("tolerance")
    preserve_topology = bool(params.get("preserve_topology", True))
    output_name = params.get("output_name", f"generalized_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}
    if tolerance_m is None:
        return {"error": "tolerance (in meters) is required"}
    try:
        tolerance_m = float(tolerance_m)
    except (TypeError, ValueError):
        return {"error": "tolerance must be numeric"}
    if tolerance_m <= 0:
        return {"error": "tolerance must be > 0"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    # Centroid lat for meters->degrees conversion.
    geoms = [
        _safe_geojson_to_shapely(f.get("geometry"))
        for f in features
        if f.get("geometry")
    ]
    geoms = [g for g in geoms if g]
    if not geoms:
        return {"error": f"Layer '{layer_name}' has no valid geometries"}
    centroid = unary_union(geoms).centroid
    center_lat = centroid.y
    # 1 degree latitude ~ 111,320 m; longitude scales by cos(lat).
    meters_per_deg = 111_320.0 * max(0.01, math.cos(math.radians(center_lat)))
    tolerance_deg = tolerance_m / meters_per_deg

    def count_vertices(g) -> int:
        try:
            return len(list(g.coords))
        except NotImplementedError:
            return sum(
                count_vertices(part)
                for part in getattr(g, "geoms", [])
            )

    original_vertices = 0
    simplified_features = []
    simplified_vertices = 0
    for f in features:
        geom = f.get("geometry")
        shp = _safe_geojson_to_shapely(geom) if geom else None
        if not shp:
            continue
        try:
            original_vertices += count_vertices(shp)
        except Exception:
            pass
        simplified = shp.simplify(tolerance_deg, preserve_topology=preserve_topology)
        if simplified.is_empty:
            continue
        try:
            simplified_vertices += count_vertices(simplified)
        except Exception:
            pass
        simplified_features.append({
            "type": "Feature",
            "geometry": shapely_to_geojson(simplified),
            "properties": dict(f.get("properties", {})),
        })

    reduction_pct = (
        100.0 * (original_vertices - simplified_vertices) / original_vertices
        if original_vertices else 0.0
    )

    return {
        "geojson": {"type": "FeatureCollection", "features": simplified_features},
        "layer_name": output_name,
        "feature_count": len(simplified_features),
        "tolerance_m": tolerance_m,
        "tolerance_deg": round(tolerance_deg, 8),
        "original_vertices": original_vertices,
        "simplified_vertices": simplified_vertices,
        "reduction_pct": round(reduction_pct, 1),
        "preserve_topology": preserve_topology,
    }


def handle_voronoi(params: dict, layer_store: dict = None) -> dict:
    """Generate Voronoi diagram from point features."""
    from shapely.geometry import MultiPoint, box
    from shapely.ops import voronoi_diagram

    MAX_VORONOI_POINTS = 5000

    layer_name = params.get("layer_name")
    output_name = params.get("output_name", f"voronoi_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}

    geoms, err = _get_layer_geometries(layer_store, layer_name)
    if err:
        return {"error": err}
    if not geoms:
        return {"error": f"Layer '{layer_name}' has no valid geometries"}

    if len(geoms) > MAX_VORONOI_POINTS:
        return {"error": f"Too many features ({len(geoms)}). Voronoi supports at most {MAX_VORONOI_POINTS} points."}

    # Extract point coordinates (use centroids for non-point geometries)
    points = []
    for g in geoms:
        if g.geom_type == "Point":
            points.append(g)
        else:
            points.append(g.centroid)

    if len(points) < 2:
        return {"error": "Voronoi diagram requires at least 2 points"}

    multi_point = MultiPoint(points)
    try:
        regions = voronoi_diagram(multi_point)
    except Exception as exc:
        logger.error("Voronoi diagram generation failed", exc_info=True)
        return {"error": "Voronoi diagram generation failed"}

    # Clip voronoi regions to the bounding box of input points (with small buffer)
    bounds = multi_point.envelope.buffer(0.01)

    voronoi_features = []
    for geom in regions.geoms:
        clipped = geom.intersection(bounds)
        if clipped.is_empty:
            continue
        voronoi_features.append({
            "type": "Feature",
            "geometry": shapely_to_geojson(clipped),
            "properties": {
                "operation": "voronoi",
                "source_layer": layer_name,
            }
        })

    result_geojson = {
        "type": "FeatureCollection",
        "features": voronoi_features,
    }

    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": len(voronoi_features),
    }


# ============================================================
# Advanced Analysis Tools
# ============================================================


def handle_point_in_polygon(params: dict, layer_store: dict = None) -> dict:
    """Determine which polygon contains a point or batch of points."""
    polygon_layer = params.get("polygon_layer")
    lat = params.get("lat")
    lon = params.get("lon")
    point_layer = params.get("point_layer")
    output_name = params.get("output_name", f"pip_{polygon_layer}")

    if not polygon_layer:
        return {"error": "polygon_layer is required"}

    # Get polygon geometries + features (filtered in parallel to keep indices aligned)
    poly_geoms, err = _get_layer_geometries(layer_store, polygon_layer)
    if err:
        return {"error": err}
    all_poly_features, _ = _get_layer_snapshot(layer_store, polygon_layer)
    all_poly_features = all_poly_features or []
    poly_features = []
    for f in all_poly_features:
        geom = f.get("geometry")
        if geom:
            shapely_geom = _safe_geojson_to_shapely(geom)
            if shapely_geom:
                poly_features.append(f)

    if not poly_geoms:
        return {"error": f"Layer '{polygon_layer}' has no valid polygon geometries"}

    # Build spatial index on polygons
    tree = _build_spatial_index(poly_geoms)

    if lat is not None and lon is not None:
        # Single point query
        from shapely.geometry import Point
        try:
            pt = Point(float(lon), float(lat))
        except (TypeError, ValueError):
            return {"error": "lat and lon must be valid numbers"}
        candidates = tree.query(pt)
        for idx in candidates:
            if poly_geoms[idx].contains(pt):
                return {
                    "found": True,
                    "polygon": poly_features[idx].get("properties", {}),
                    "polygon_index": int(idx),
                }
        return {"found": False, "message": "Point is not inside any polygon"}

    elif point_layer:
        # Multi-point query: for each point, find containing polygon
        point_geoms, err = _get_layer_geometries(layer_store, point_layer)
        if err:
            return {"error": err}
        all_point_features, err = _get_layer_snapshot(layer_store, point_layer)
        if err:
            return {"error": err}
        all_point_features = all_point_features or []
        # Filter point features in parallel with point_geoms to keep indices aligned
        point_features = []
        for f in all_point_features:
            geom = f.get("geometry")
            if geom:
                shapely_geom = _safe_geojson_to_shapely(geom)
                if shapely_geom:
                    point_features.append(f)

        result_features = []
        for pt_geom, pt_feat in zip(point_geoms, point_features):
            centroid = pt_geom.centroid  # works for any geometry
            candidates = tree.query(centroid)
            containing = None
            for idx in candidates:
                if poly_geoms[idx].contains(centroid):
                    containing = poly_features[idx]
                    break

            # Merge point properties with containing polygon properties
            props = dict(pt_feat.get("properties", {}))
            if containing:
                props["containing_polygon"] = containing.get("properties", {})
                props["in_polygon"] = True
            else:
                props["in_polygon"] = False

            result_features.append({
                "type": "Feature",
                "geometry": pt_feat.get("geometry"),
                "properties": props
            })

        geojson = {"type": "FeatureCollection", "features": result_features}
        inside_count = sum(1 for f in result_features if f["properties"].get("in_polygon"))
        return {
            "geojson": geojson,
            "layer_name": output_name,
            "total_points": len(result_features),
            "inside": inside_count,
            "outside": len(result_features) - inside_count,
        }
    else:
        return {"error": "Provide lat/lon for single point or point_layer for batch query"}


def handle_attribute_join(params: dict, layer_store: dict = None) -> dict:
    """Join tabular data to a spatial layer by matching attribute."""
    layer_name = params.get("layer_name")
    join_data = params.get("join_data", [])
    layer_key = params.get("layer_key")
    data_key = params.get("data_key")
    output_name = params.get("output_name", f"joined_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}
    if not layer_key:
        return {"error": "layer_key is required"}
    if not data_key:
        return {"error": "data_key is required"}
    if not join_data:
        return {"error": "join_data must be a non-empty array"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' not found"}

    # Build lookup from join data
    lookup = {}
    for item in join_data:
        key_val = item.get(data_key)
        if key_val is not None:
            lookup[str(key_val)] = item

    result_features = []
    matched = 0
    for feat in features:
        props = dict(feat.get("properties", {}))
        key_val = str(props.get(layer_key, ""))
        if key_val in lookup:
            # Merge join data into properties (prefix with "joined_")
            for k, v in lookup[key_val].items():
                if k != data_key:
                    props[f"joined_{k}"] = v
            matched += 1
        result_features.append({
            "type": "Feature",
            "geometry": feat.get("geometry"),
            "properties": props
        })

    geojson = {"type": "FeatureCollection", "features": result_features}
    return {
        "geojson": geojson,
        "layer_name": output_name,
        "total_features": len(result_features),
        "matched": matched,
        "unmatched": len(result_features) - matched,
    }


def handle_spatial_statistics(params: dict, layer_store: dict = None) -> dict:
    """Compute spatial clustering statistics for point features."""
    layer_name = params.get("layer_name")
    method = params.get("method", "nearest_neighbor")

    if not layer_name:
        return {"error": "layer_name is required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    geoms, err = _get_layer_geometries(layer_store, layer_name)
    if err:
        return {"error": err}
    if len(geoms) < 2:
        return {"error": "Spatial statistics require at least 2 features"}

    # Extract centroids as (lon, lat) for spatial operations
    centroids = [g.centroid for g in geoms]

    if method == "nearest_neighbor":
        try:
            from scipy.spatial import cKDTree
        except ImportError:
            return {"error": "scipy is required for nearest neighbor analysis. Install with: pip install scipy"}

        import numpy as np

        try:
            # Project to UTM for metric distances
            coords_wgs84 = np.array([[c.x, c.y] for c in centroids])

            # Use the first centroid to determine UTM zone
            from nl_gis.geo_utils import estimate_utm_epsg, project_geometry
            utm_epsg = estimate_utm_epsg(centroids[0].x, centroids[0].y)

            from shapely.geometry import Point as ShapelyPoint
            projected_coords = []
            for c in centroids:
                projected = project_geometry(ShapelyPoint(c.x, c.y), 4326, utm_epsg)
                projected_coords.append([projected.x, projected.y])
            projected_coords = np.array(projected_coords)

            # Build KDTree on projected coordinates
            tree = cKDTree(projected_coords)
            # Find nearest neighbor for each point (k=2 because k=1 is the point itself)
            distances, _ = tree.query(projected_coords, k=2)
            nn_distances = distances[:, 1]  # second column = nearest neighbor

            observed_mean = float(np.mean(nn_distances))
            n = len(centroids)

            # Calculate study area from convex hull of projected points
            from shapely.geometry import MultiPoint
            hull = MultiPoint([ShapelyPoint(p) for p in projected_coords]).convex_hull
            area = hull.area

            if area == 0:
                return {"error": "All points are collinear or coincident; cannot compute NNI"}

            # Expected mean nearest neighbor distance for random pattern
            expected_mean = 0.5 * math.sqrt(area / n)

            nni = observed_mean / expected_mean if expected_mean > 0 else float('inf')

            if nni < 0.8:
                interpretation = "clustered"
            elif nni > 1.2:
                interpretation = "dispersed"
            else:
                interpretation = "random"

            return {
                "method": "nearest_neighbor",
                "nni": round(nni, 4),
                "interpretation": interpretation,
                "observed_mean_distance_m": round(observed_mean, 2),
                "expected_mean_distance_m": round(expected_mean, 2),
                "point_count": n,
                "study_area_sq_m": round(area, 2),
            }
        except Exception as e:
            logger.error("Spatial statistics failed: %s", e, exc_info=True)
            return {"error": "Spatial statistics computation failed"}

    elif method == "dbscan":
        try:
            from sklearn.cluster import DBSCAN
        except ImportError:
            return {"error": "scikit-learn is required for DBSCAN clustering. Install with: pip install scikit-learn"}

        import numpy as np

        try:
            eps = float(params.get("eps", 100))
            min_samples = int(params.get("min_samples", 5))
        except (ValueError, TypeError):
            return {"error": "eps must be a number and min_samples must be an integer"}
        if eps <= 0:
            return {"error": "eps must be positive"}
        if min_samples < 1:
            return {"error": "min_samples must be at least 1"}

        # Project to UTM for metric distances
        from nl_gis.geo_utils import estimate_utm_epsg, project_geometry
        from shapely.geometry import Point as ShapelyPoint

        utm_epsg = estimate_utm_epsg(centroids[0].x, centroids[0].y)

        projected_coords = []
        for c in centroids:
            projected = project_geometry(ShapelyPoint(c.x, c.y), 4326, utm_epsg)
            projected_coords.append([projected.x, projected.y])
        projected_coords = np.array(projected_coords)

        # Run DBSCAN
        clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(projected_coords)
        labels = clustering.labels_

        # Build result features with cluster_id
        # Filter features to match geoms (same filtering as _get_layer_geometries)
        valid_features = []
        for f in features:
            geom = f.get("geometry")
            if geom:
                shapely_geom = _safe_geojson_to_shapely(geom)
                if shapely_geom:
                    valid_features.append(f)

        result_features = []
        for feat, label in zip(valid_features, labels):
            props = dict(feat.get("properties", {}))
            props["cluster_id"] = int(label)  # -1 = noise
            result_features.append({
                "type": "Feature",
                "geometry": feat.get("geometry"),
                "properties": props
            })

        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        noise_count = int(np.sum(labels == -1))

        output_name = params.get("output_name", f"dbscan_{layer_name}")
        geojson = {"type": "FeatureCollection", "features": result_features}

        return {
            "geojson": geojson,
            "layer_name": output_name,
            "method": "dbscan",
            "n_clusters": n_clusters,
            "noise_points": noise_count,
            "total_points": len(result_features),
            "eps_m": eps,
            "min_samples": min_samples,
        }

    else:
        return {"error": f"Unknown method: {method}. Valid: nearest_neighbor, dbscan"}


def handle_hot_spot_analysis(params: dict, layer_store: dict = None) -> dict:
    """Perform Getis-Ord Gi* hot spot analysis on a point or polygon layer.

    Requires a numeric attribute to analyze (e.g., population, crime count, price).
    Returns a GeoJSON layer with z-scores and p-values for each feature,
    colored by significance (hot=red, cold=blue, not significant=gray).
    """
    layer_name = params.get("layer_name")
    attribute = params.get("attribute")
    output_name = params.get("output_name", f"hotspot_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}
    if not attribute:
        return {"error": "attribute is required — specify the numeric field to analyze"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' not found or empty"}

    # Extract values and coordinates
    try:
        import numpy as np
        from scipy.spatial import cKDTree

        points = []
        values = []
        valid_features = []

        for feat in features:
            geom = feat.get("geometry")
            props = feat.get("properties", {})
            val = props.get(attribute)

            if geom is None or val is None:
                continue

            try:
                val = float(val)
            except (ValueError, TypeError):
                continue

            # Get centroid for point extraction
            shapely_geom = _safe_geojson_to_shapely(geom)
            if shapely_geom is None or shapely_geom.is_empty:
                continue

            centroid = shapely_geom.centroid
            points.append([centroid.x, centroid.y])
            values.append(val)
            valid_features.append(feat)

        if len(points) < 3:
            return {"error": f"Need at least 3 features with valid '{attribute}' values"}

        points = np.array(points)
        values = np.array(values, dtype=float)

        # Project to UTM for distance-based weights
        from nl_gis.geo_utils import estimate_utm_epsg, project_geometry
        from shapely.geometry import MultiPoint

        avg_lat = np.mean(points[:, 1])
        avg_lon = np.mean(points[:, 0])
        epsg = estimate_utm_epsg(avg_lat, avg_lon)

        # Transform points to projected coordinates
        mp = MultiPoint([(p[0], p[1]) for p in points])
        mp_proj = project_geometry(mp, 4326, epsg)
        proj_points = np.array([(p.x, p.y) for p in mp_proj.geoms])

        # Build spatial weights using KD-tree
        tree = cKDTree(proj_points)

        # Adaptive bandwidth: use k nearest neighbors
        k = min(8, len(points) - 1)
        distances, indices = tree.query(proj_points, k=k + 1)  # +1 for self
        bandwidth = np.median(distances[:, -1])  # median distance to kth neighbor

        # Compute Gi* statistic for each feature
        n = len(values)
        x_mean = np.mean(values)
        s = np.std(values)

        z_scores = np.zeros(n)
        p_values = np.ones(n)

        if s > 0:
            from scipy.stats import norm

            for i in range(n):
                # Get neighbors within bandwidth (includes self for Gi*)
                neighbor_idx = tree.query_ball_point(proj_points[i], bandwidth)

                wij_sum = len(neighbor_idx)
                wij_xj_sum = sum(values[j] for j in neighbor_idx)
                wij_sq_sum = wij_sum  # binary weights (1 if neighbor, 0 if not)

                numerator = wij_xj_sum - x_mean * wij_sum
                denominator = s * np.sqrt(
                    (n * wij_sq_sum - wij_sum ** 2) / (n - 1)
                )

                if denominator > 0:
                    z_scores[i] = numerator / denominator
                    # Two-tailed p-value from z-score
                    p_values[i] = 2 * (1 - norm.cdf(abs(z_scores[i])))

        # Build result GeoJSON with z-scores, p-values, and colors
        result_features = []
        hot_count = 0
        cold_count = 0
        not_sig_count = 0

        for i, feat in enumerate(valid_features):
            props = dict(feat.get("properties", {}))
            props["gi_z_score"] = round(float(z_scores[i]), 4)
            props["gi_p_value"] = round(float(p_values[i]), 6)

            if p_values[i] < 0.05 and z_scores[i] > 0:
                props["hotspot_class"] = "hot"
                hot_count += 1
            elif p_values[i] < 0.05 and z_scores[i] < 0:
                props["hotspot_class"] = "cold"
                cold_count += 1
            else:
                props["hotspot_class"] = "not_significant"
                not_sig_count += 1

            result_features.append({
                "type": "Feature",
                "geometry": feat["geometry"],
                "properties": props,
            })

        geojson = {"type": "FeatureCollection", "features": result_features}

        return {
            "geojson": geojson,
            "layer_name": output_name,
            "analysis": {
                "total_features": len(result_features),
                "hot_spots": hot_count,
                "cold_spots": cold_count,
                "not_significant": not_sig_count,
                "attribute": attribute,
                "bandwidth_m": round(float(bandwidth), 1),
                "significance_level": 0.05,
            },
            "colors": {
                "hot": "#ff0000",
                "cold": "#0000ff",
                "not_significant": "#808080",
            },
        }

    except ImportError as e:
        return {"error": f"Required library not available: {e}"}
    except Exception:
        logger.error("Hot spot analysis failed", exc_info=True)
        return {"error": "Hot spot analysis failed"}


# ============================================================
# Interpolation Tools
# ============================================================


def handle_interpolate(params: dict, layer_store: dict = None) -> dict:
    """Interpolate point values to create a contour surface.

    Extracts numeric values from point features, builds a regular grid
    in projected (UTM) coordinates, interpolates using scipy.interpolate.griddata,
    generates contour polygons via matplotlib, and returns them as GeoJSON.

    Requires scipy and matplotlib (optional dependencies).
    """
    try:
        import numpy as np
        from scipy.interpolate import griddata as scipy_griddata
    except ImportError:
        return {"error": "scipy is required for interpolation. Install with: pip install scipy"}

    try:
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend
        import matplotlib.pyplot as plt
    except ImportError:
        return {"error": "matplotlib is required for contour generation. Install with: pip install matplotlib"}

    layer_name = params.get("layer_name")
    attribute = params.get("attribute")
    method = params.get("method", "linear")
    resolution = min(int(params.get("resolution", 50)), 200)
    contour_levels = int(params.get("contour_levels", 10))
    output_name = params.get("output_name", f"interpolated_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}
    if not attribute:
        return {"error": "attribute is required — specify the numeric field to interpolate"}
    if method not in ("linear", "cubic", "nearest"):
        return {"error": f"Invalid method '{method}'. Valid: linear, cubic, nearest"}
    if resolution < 2:
        return {"error": "resolution must be at least 2"}
    if contour_levels < 2:
        return {"error": "contour_levels must be at least 2"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    # Extract point coordinates and values
    points_xy = []  # (lon, lat) in WGS84
    values = []
    for feat in features:
        geom = feat.get("geometry")
        props = feat.get("properties", {})
        val = props.get(attribute)

        if geom is None or val is None:
            continue

        try:
            val = float(val)
        except (ValueError, TypeError):
            continue

        shapely_geom = _safe_geojson_to_shapely(geom)
        if shapely_geom is None or shapely_geom.is_empty:
            continue

        centroid = shapely_geom.centroid
        points_xy.append([centroid.x, centroid.y])
        values.append(val)

    if len(points_xy) < 3:
        return {"error": f"Need at least 3 points with valid numeric '{attribute}' values, found {len(points_xy)}"}

    points_xy = np.array(points_xy)
    values = np.array(values, dtype=float)

    # Project to UTM for metric grid
    from nl_gis.geo_utils import estimate_utm_epsg, project_geometry
    from shapely.geometry import Point as ShapelyPoint, MultiPoint

    avg_lon = float(np.mean(points_xy[:, 0]))
    avg_lat = float(np.mean(points_xy[:, 1]))
    utm_epsg = estimate_utm_epsg(avg_lon, avg_lat)

    # Project all points to UTM
    projected_coords = []
    for px, py in points_xy:
        proj_pt = project_geometry(ShapelyPoint(px, py), 4326, utm_epsg)
        projected_coords.append([proj_pt.x, proj_pt.y])
    projected_coords = np.array(projected_coords)

    # Build regular grid in projected space
    x_min, y_min = projected_coords.min(axis=0)
    x_max, y_max = projected_coords.max(axis=0)

    # Add small buffer (5%) to avoid edge artifacts
    x_range = x_max - x_min
    y_range = y_max - y_min
    if x_range == 0 or y_range == 0:
        return {"error": "All points are collinear — cannot create interpolation grid"}

    x_min -= x_range * 0.05
    x_max += x_range * 0.05
    y_min -= y_range * 0.05
    y_max += y_range * 0.05

    grid_x = np.linspace(x_min, x_max, resolution)
    grid_y = np.linspace(y_min, y_max, resolution)
    grid_xx, grid_yy = np.meshgrid(grid_x, grid_y)

    # Interpolate
    try:
        grid_values = scipy_griddata(
            projected_coords, values,
            (grid_xx, grid_yy),
            method=method,
            fill_value=float("nan"),
        )
    except Exception:
        logger.error("Interpolation failed", exc_info=True)
        return {"error": "Interpolation computation failed"}

    # Generate contour polygons using matplotlib
    try:
        fig, ax = plt.subplots()
        v_min = float(np.nanmin(values))
        v_max = float(np.nanmax(values))
        levels = np.linspace(v_min, v_max, contour_levels + 1)
        contour_set = ax.contourf(grid_xx, grid_yy, grid_values, levels=levels)
        plt.close(fig)
    except Exception:
        logger.error("Contour generation failed", exc_info=True)
        return {"error": "Contour generation failed"}

    # Convert contour collections to GeoJSON polygons
    from shapely.geometry import Polygon as ShapelyPolygon

    contour_features = []
    for i, collection in enumerate(contour_set.collections):
        level_min = float(contour_set.levels[i])
        level_max = float(contour_set.levels[i + 1]) if i + 1 < len(contour_set.levels) else level_min

        for path in collection.get_paths():
            # Each path may have multiple polygons (with holes)
            for polygon_coords in path.to_polygons():
                if len(polygon_coords) < 3:
                    continue

                # Project back to WGS84
                wgs84_coords = []
                for px, py in polygon_coords:
                    wgs_pt = project_geometry(ShapelyPoint(px, py), utm_epsg, 4326)
                    wgs84_coords.append([wgs_pt.x, wgs_pt.y])

                # Close ring if needed
                if wgs84_coords[0] != wgs84_coords[-1]:
                    wgs84_coords.append(wgs84_coords[0])

                try:
                    poly = ShapelyPolygon(wgs84_coords)
                    if poly.is_valid and not poly.is_empty:
                        contour_features.append({
                            "type": "Feature",
                            "geometry": shapely_to_geojson(poly),
                            "properties": {
                                "value_min": round(level_min, 4),
                                "value_max": round(level_max, 4),
                                "level": i,
                                "attribute": attribute,
                            }
                        })
                except Exception:
                    continue

    result_geojson = {
        "type": "FeatureCollection",
        "features": contour_features,
    }

    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": len(contour_features),
        "method": method,
        "resolution": resolution,
        "contour_levels": contour_levels,
        "attribute": attribute,
        "value_range": {"min": round(v_min, 4), "max": round(v_max, 4)},
    }


# ============================================================
# Topology Validation Tools
# ============================================================


def handle_validate_topology(params: dict, layer_store: dict = None) -> dict:
    """Check geometry validity for all features in a layer.

    Uses Shapely's is_valid and explain_validity to identify and report
    topology issues (self-intersections, ring errors, etc.).
    """
    from shapely.validation import explain_validity

    layer_name = params.get("layer_name")

    if not layer_name:
        return {"error": "layer_name is required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    valid_count = 0
    invalid_count = 0
    errors = []

    for i, feat in enumerate(features):
        geom = feat.get("geometry")
        if geom is None:
            invalid_count += 1
            errors.append({
                "index": i,
                "error_type": "missing_geometry",
                "explanation": "Feature has no geometry",
            })
            continue

        try:
            shapely_geom = geojson_to_shapely(geom)
        except Exception as exc:
            invalid_count += 1
            errors.append({
                "index": i,
                "error_type": "parse_error",
                "explanation": f"Cannot parse geometry: {type(exc).__name__}",
            })
            continue

        if shapely_geom.is_empty:
            invalid_count += 1
            errors.append({
                "index": i,
                "error_type": "empty_geometry",
                "explanation": "Geometry is empty",
            })
        elif shapely_geom.is_valid:
            valid_count += 1
        else:
            invalid_count += 1
            explanation = explain_validity(shapely_geom)
            errors.append({
                "index": i,
                "error_type": "invalid_geometry",
                "explanation": explanation,
            })

    return {
        "layer_name": layer_name,
        "total_features": len(features),
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "errors": errors,
    }


def handle_repair_topology(params: dict, layer_store: dict = None) -> dict:
    """Auto-repair invalid geometries in a layer.

    Uses Shapely's make_valid to fix geometry issues while preserving
    as much of the original shape as possible.
    """
    from shapely.validation import make_valid

    layer_name = params.get("layer_name")
    output_name = params.get("output_name", f"repaired_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    repaired_count = 0
    already_valid_count = 0
    skipped_count = 0
    result_features = []

    for feat in features:
        geom = feat.get("geometry")
        props = dict(feat.get("properties", {}))

        if geom is None:
            skipped_count += 1
            continue

        try:
            shapely_geom = geojson_to_shapely(geom)
        except Exception:
            skipped_count += 1
            continue

        if shapely_geom.is_empty:
            skipped_count += 1
            continue

        if shapely_geom.is_valid:
            already_valid_count += 1
            result_features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": props,
            })
        else:
            repaired = make_valid(shapely_geom)
            if repaired.is_empty:
                skipped_count += 1
                continue
            repaired_count += 1
            props["_repaired"] = True
            result_features.append({
                "type": "Feature",
                "geometry": shapely_to_geojson(repaired),
                "properties": props,
            })

    result_geojson = {
        "type": "FeatureCollection",
        "features": result_features,
    }

    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": len(result_features),
        "repaired_count": repaired_count,
        "already_valid_count": already_valid_count,
        "skipped_count": skipped_count,
    }


def handle_execute_code(params: dict, layer_store: dict = None) -> dict:
    """Execute sandboxed Python code for spatial analysis.

    Used as a fallback when no existing tool matches the user's request.
    """
    from services.code_executor import execute_safely

    code = params.get("code", "")
    if not code.strip():
        return {"error": "No code provided"}

    # Provide layer data as input
    input_data = {}
    input_layer = params.get("input_layer")
    if input_layer and layer_store:
        snapshot, err = _get_layer_snapshot(layer_store, input_layer)
        if snapshot:
            input_data["layer"] = {"type": "FeatureCollection", "features": snapshot}

    result = execute_safely(code, input_data=input_data, timeout=15)

    if not result["success"]:
        return {"error": result["error"]}

    response = {"success": True}
    if result.get("stdout"):
        response["output"] = result["stdout"]
    if result.get("result"):
        response["result"] = result["result"]
    if result.get("geojson"):
        response["geojson"] = result["geojson"]
        response["layer_name"] = params.get("output_layer", "code_result")

    return response


# ============================================================
# Data Quality Tools
# ============================================================

def handle_describe_layer(params: dict, layer_store: dict = None) -> dict:
    """Summary statistics for a layer."""
    layer_name = params.get("layer_name")
    if not layer_name:
        return {"error": "layer_name is required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}

    feature_count = len(features)
    if feature_count == 0:
        return {
            "success": True,
            "layer_name": layer_name,
            "feature_count": 0,
            "geometry_types": [],
            "bbox": None,
            "crs": "EPSG:4326",
            "attributes": {},
            "description": f"Layer '{layer_name}' has no features",
        }

    # Geometry types and bbox
    geometry_types = set()
    bbox_state = {
        "min_lon": float("inf"), "min_lat": float("inf"),
        "max_lon": float("-inf"), "max_lat": float("-inf"),
    }

    for f in features:
        geom = f.get("geometry")
        if geom:
            geometry_types.add(geom.get("type", "Unknown"))
            _update_bbox_from_geom(geom, bbox_state)

    # Attribute statistics
    all_keys = set()
    for f in features:
        props = f.get("properties") or {}
        all_keys.update(props.keys())

    attributes = {}
    for key in sorted(all_keys):
        values = [f.get("properties", {}).get(key) for f in features]
        null_count = sum(1 for v in values if v is None)
        non_null = [v for v in values if v is not None]
        unique_count = len(set(str(v) for v in non_null)) if non_null else 0

        attr_info = {
            "null_count": null_count,
            "unique_count": unique_count,
            "total_count": feature_count,
        }

        # Detect numeric values
        numeric_values = []
        for v in non_null:
            try:
                numeric_values.append(float(v))
            except (ValueError, TypeError):
                pass

        if numeric_values and len(numeric_values) == len(non_null):
            attr_info["type"] = "numeric"
            attr_info["min"] = min(numeric_values)
            attr_info["max"] = max(numeric_values)
            attr_info["mean"] = sum(numeric_values) / len(numeric_values)
        elif non_null:
            attr_info["type"] = "string"
        else:
            attr_info["type"] = "null"

        attributes[key] = attr_info

    bbox = None
    if bbox_state["min_lon"] != float("inf"):
        bbox = [bbox_state["min_lon"], bbox_state["min_lat"],
                bbox_state["max_lon"], bbox_state["max_lat"]]

    return {
        "success": True,
        "layer_name": layer_name,
        "feature_count": feature_count,
        "geometry_types": sorted(geometry_types),
        "bbox": bbox,
        "crs": "EPSG:4326",
        "attributes": attributes,
        "description": (
            f"Layer '{layer_name}': {feature_count} features, "
            f"types: {', '.join(sorted(geometry_types))}, "
            f"{len(all_keys)} attributes"
        ),
    }


def _update_bbox_from_geom(geom: dict, bbox_vars: dict):
    """Recursively extract coordinate bounds from a GeoJSON geometry."""
    coords = geom.get("coordinates")
    if coords is None:
        # GeometryCollection
        for sub_geom in geom.get("geometries", []):
            _update_bbox_from_geom(sub_geom, bbox_vars)
        return

    def _walk(c):
        if isinstance(c, (list, tuple)):
            if c and isinstance(c[0], (int, float)):
                # This is a coordinate pair [lon, lat] or [lon, lat, alt]
                lon, lat = float(c[0]), float(c[1])
                if lon < bbox_vars["min_lon"]:
                    bbox_vars["min_lon"] = lon
                if lon > bbox_vars["max_lon"]:
                    bbox_vars["max_lon"] = lon
                if lat < bbox_vars["min_lat"]:
                    bbox_vars["min_lat"] = lat
                if lat > bbox_vars["max_lat"]:
                    bbox_vars["max_lat"] = lat
            else:
                for item in c:
                    _walk(item)

    _walk(coords)


def handle_detect_duplicates(params: dict, layer_store: dict = None) -> dict:
    """Find duplicate or near-duplicate features in a layer."""
    from shapely.geometry import shape as shapely_shape

    layer_name = params.get("layer_name")
    if not layer_name:
        return {"error": "layer_name is required"}

    threshold_m = params.get("threshold_m", 1.0)
    try:
        threshold_m = float(threshold_m)
    except (ValueError, TypeError):
        return {"error": "threshold_m must be a number"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}

    if len(features) < 2:
        return {
            "success": True,
            "layer_name": layer_name,
            "duplicate_groups": [],
            "total_duplicates": 0,
            "description": f"Layer '{layer_name}' has fewer than 2 features, no duplicates possible",
        }

    # Parse geometries
    geometries = []
    for i, f in enumerate(features):
        geom = f.get("geometry")
        if geom:
            try:
                geometries.append((i, shapely_shape(geom)))
            except Exception:
                geometries.append((i, None))
        else:
            geometries.append((i, None))

    # Find exact and near duplicates
    # Track which features are already in a group
    grouped = set()
    duplicate_groups = []

    for i_idx in range(len(geometries)):
        if i_idx in grouped:
            continue
        idx_i, geom_i = geometries[i_idx]
        if geom_i is None:
            continue

        group = []
        for j_idx in range(i_idx + 1, len(geometries)):
            if j_idx in grouped:
                continue
            idx_j, geom_j = geometries[j_idx]
            if geom_j is None:
                continue

            # Check exact match
            try:
                if geom_i.equals(geom_j):
                    group.append({"index": idx_j, "type": "exact"})
                    grouped.add(j_idx)
                    continue
            except Exception:
                pass

            # Check near match (centroid distance)
            if threshold_m > 0:
                try:
                    c_i = geom_i.centroid
                    c_j = geom_j.centroid
                    dist = geodesic_distance(
                        ValidatedPoint(lat=c_i.y, lon=c_i.x),
                        ValidatedPoint(lat=c_j.y, lon=c_j.x),
                    )
                    if dist <= threshold_m:
                        group.append({"index": idx_j, "type": "near", "distance_m": round(dist, 2)})
                        grouped.add(j_idx)
                except Exception:
                    pass

        if group:
            grouped.add(i_idx)
            duplicate_groups.append({
                "reference_index": idx_i,
                "duplicates": group,
            })

    total_duplicates = sum(len(g["duplicates"]) for g in duplicate_groups)

    return {
        "success": True,
        "layer_name": layer_name,
        "duplicate_groups": duplicate_groups,
        "total_duplicates": total_duplicates,
        "threshold_m": threshold_m,
        "description": (
            f"Found {total_duplicates} duplicates in {len(duplicate_groups)} groups "
            f"in layer '{layer_name}' (threshold: {threshold_m}m)"
        ),
    }


def handle_clean_layer(params: dict, layer_store: dict = None) -> dict:
    """Remove null geometries, fix encoding, normalize attributes."""
    layer_name = params.get("layer_name")
    if not layer_name:
        return {"error": "layer_name is required"}

    output_name = params.get("output_name", f"{layer_name}_cleaned")

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}

    original_count = len(features)
    if original_count == 0:
        return {"error": f"Layer '{layer_name}' has no features to clean"}

    # Step 1: Remove features with null/empty geometry
    cleaned = []
    null_geom_removed = 0
    for f in features:
        geom = f.get("geometry")
        if not geom or not geom.get("coordinates"):
            null_geom_removed += 1
            continue
        cleaned.append(f)

    # Step 2: Find all-null attributes (across remaining features)
    all_keys = set()
    for f in cleaned:
        props = f.get("properties") or {}
        all_keys.update(props.keys())

    all_null_keys = set()
    for key in all_keys:
        all_null = all(
            (f.get("properties") or {}).get(key) is None
            for f in cleaned
        )
        if all_null:
            all_null_keys.add(key)

    # Step 3: Strip whitespace from string properties + remove all-null attrs
    whitespace_trimmed = 0
    for f in cleaned:
        props = f.get("properties")
        if not props:
            continue
        # Remove all-null keys
        for key in all_null_keys:
            props.pop(key, None)
        # Strip whitespace
        for key, val in list(props.items()):
            if isinstance(val, str):
                stripped = val.strip()
                if stripped != val:
                    props[key] = stripped
                    whitespace_trimmed += 1

    geojson = {"type": "FeatureCollection", "features": cleaned}

    if layer_store is not None:
        try:
            from state import layer_lock as _lk
        except ImportError:
            _lk = None
        if _lk:
            with _lk:
                layer_store[output_name] = geojson
        else:
            layer_store[output_name] = geojson

    report = {
        "original_count": original_count,
        "cleaned_count": len(cleaned),
        "null_geometries_removed": null_geom_removed,
        "all_null_attributes_removed": sorted(all_null_keys),
        "whitespace_values_trimmed": whitespace_trimmed,
    }

    return {
        "geojson": geojson,
        "layer_name": output_name,
        "report": report,
        "description": (
            f"Cleaned '{layer_name}' -> '{output_name}': "
            f"removed {null_geom_removed} null geometries, "
            f"{len(all_null_keys)} all-null attributes, "
            f"trimmed {whitespace_trimmed} whitespace values. "
            f"{len(cleaned)}/{original_count} features remain."
        ),
    }


# ============================================================
# Milestone 5.1: Coordinate Tools
# ============================================================

def handle_reproject_layer(params: dict, layer_store: dict = None) -> dict:
    """Transform layer CRS metadata. Display stays WGS84, adds source_crs property."""
    layer_name = params.get("layer_name")
    from_crs = params.get("from_crs")
    to_crs = params.get("to_crs", 4326)
    output_name = params.get("output_name", f"reprojected_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}
    if from_crs is None:
        return {"error": "from_crs (EPSG code) is required"}

    try:
        from_crs = int(from_crs)
        to_crs = int(to_crs)
    except (ValueError, TypeError):
        return {"error": "from_crs and to_crs must be integer EPSG codes"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    reprojected_features = []
    for f in features:
        new_f = {
            "type": "Feature",
            "geometry": f.get("geometry"),
            "properties": dict(f.get("properties", {})),
        }
        new_f["properties"]["source_crs"] = f"EPSG:{from_crs}"
        new_f["properties"]["display_crs"] = f"EPSG:{to_crs}"

        # If from_crs != to_crs and from_crs != 4326, actually reproject geometry
        if from_crs != to_crs and f.get("geometry"):
            try:
                geom = geojson_to_shapely(f["geometry"])
                reprojected = project_geometry(geom, from_crs, to_crs)
                new_f["geometry"] = shapely_to_geojson(reprojected)
            except Exception:
                logger.warning("Failed to reproject feature, keeping original", exc_info=True)

        reprojected_features.append(new_f)

    result_geojson = {"type": "FeatureCollection", "features": reprojected_features}

    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": len(reprojected_features),
        "from_crs": f"EPSG:{from_crs}",
        "to_crs": f"EPSG:{to_crs}",
    }


def handle_detect_crs(params: dict, layer_store: dict = None) -> dict:
    """Heuristic CRS detection from coordinate ranges."""
    layer_name = params.get("layer_name")
    if not layer_name:
        return {"error": "layer_name is required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    all_x = []
    all_y = []
    for f in features:
        geom = f.get("geometry")
        if not geom:
            continue
        try:
            shapely_geom = geojson_to_shapely(geom)
            bounds = shapely_geom.bounds  # (minx, miny, maxx, maxy)
            all_x.extend([bounds[0], bounds[2]])
            all_y.extend([bounds[1], bounds[3]])
        except Exception:
            continue

    if not all_x:
        return {"error": "No valid geometries found to detect CRS"}

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)

    # Heuristic: WGS84 if all coords in [-180,180] x [-90,90]
    if -180 <= min_x <= 180 and -180 <= max_x <= 180 and -90 <= min_y <= 90 and -90 <= max_y <= 90:
        detected_crs = "EPSG:4326"
        confidence = "high"
        description = "Coordinates are within WGS84 geographic range (longitude [-180,180], latitude [-90,90])"
    else:
        detected_crs = "unknown_projected"
        confidence = "low"
        description = (
            f"Coordinates exceed geographic range (x: {min_x:.1f} to {max_x:.1f}, "
            f"y: {min_y:.1f} to {max_y:.1f}). Likely a projected CRS (e.g., UTM, State Plane)."
        )

    return {
        "layer_name": layer_name,
        "detected_crs": detected_crs,
        "confidence": confidence,
        "description": description,
        "coordinate_ranges": {
            "x_min": round(min_x, 6),
            "x_max": round(max_x, 6),
            "y_min": round(min_y, 6),
            "y_max": round(max_y, 6),
        },
        "feature_count": len(features),
    }


# ============================================================
# Milestone 5.3: Geometry Editing
# ============================================================

def handle_split_feature(params: dict, layer_store: dict = None) -> dict:
    """Split a polygon by a line using shapely.ops.split."""
    layer_name = params.get("layer_name")
    feature_index = params.get("feature_index")
    split_line = params.get("split_line")
    output_name = params.get("output_name", f"split_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}
    if feature_index is None:
        return {"error": "feature_index is required"}
    if not split_line:
        return {"error": "split_line (GeoJSON LineString) is required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    try:
        feature_index = int(feature_index)
    except (ValueError, TypeError):
        return {"error": "feature_index must be an integer"}

    if feature_index < 0 or feature_index >= len(features):
        return {"error": f"feature_index {feature_index} out of range (0-{len(features)-1})"}

    target_feature = features[feature_index]
    target_geom = target_feature.get("geometry")
    if not target_geom:
        return {"error": "Target feature has no geometry"}

    try:
        shapely_target = geojson_to_shapely(target_geom)
    except Exception:
        return {"error": "Failed to parse target feature geometry"}

    try:
        shapely_line = geojson_to_shapely(split_line)
    except Exception:
        return {"error": "Failed to parse split_line geometry"}

    if shapely_line.geom_type != "LineString":
        return {"error": f"split_line must be a LineString, got {shapely_line.geom_type}"}

    try:
        result_geoms = split(shapely_target, shapely_line)
    except Exception as exc:
        logger.error("Split operation failed", exc_info=True)
        return {"error": "Split operation failed. Ensure the line crosses the polygon."}

    if len(result_geoms.geoms) < 2:
        return {"error": "Split did not produce multiple parts. Ensure the line fully crosses the polygon."}

    # Build result: other features unchanged, split feature replaced by parts
    result_features = []
    for i, f in enumerate(features):
        if i == feature_index:
            for j, part in enumerate(result_geoms.geoms):
                new_props = dict(target_feature.get("properties", {}))
                new_props["split_part"] = j
                result_features.append({
                    "type": "Feature",
                    "geometry": shapely_to_geojson(part),
                    "properties": new_props,
                })
        else:
            result_features.append(f)

    result_geojson = {"type": "FeatureCollection", "features": result_features}

    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": len(result_features),
        "split_into": len(result_geoms.geoms),
    }


def handle_merge_features(params: dict, layer_store: dict = None) -> dict:
    """Merge features within a layer by attribute value."""
    layer_name = params.get("layer_name")
    by_attr = params.get("by")
    output_name = params.get("output_name", f"merged_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}
    if not by_attr:
        return {"error": "'by' attribute name is required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    # Check attribute exists in at least one feature
    attr_found = any(by_attr in (f.get("properties") or {}) for f in features)
    if not attr_found:
        available = set()
        for f in features:
            available.update((f.get("properties") or {}).keys())
        return {"error": f"Attribute '{by_attr}' not found. Available: {', '.join(sorted(available))}"}

    # Group features by attribute value
    groups = defaultdict(list)
    for f in features:
        val = (f.get("properties") or {}).get(by_attr)
        groups[val].append(f)

    merged_features = []
    for val, group_features in groups.items():
        geoms = []
        for f in group_features:
            g = f.get("geometry")
            if g:
                sg = _safe_geojson_to_shapely(g)
                if sg:
                    geoms.append(sg)

        if not geoms:
            continue

        merged_geom = unary_union(geoms)
        merged_features.append({
            "type": "Feature",
            "geometry": shapely_to_geojson(merged_geom),
            "properties": {by_attr: val, "merged_count": len(group_features)},
        })

    result_geojson = {"type": "FeatureCollection", "features": merged_features}

    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": len(merged_features),
        "grouped_by": by_attr,
        "original_count": len(features),
    }


def handle_extract_vertices(params: dict, layer_store: dict = None) -> dict:
    """Convert polygon/line boundaries to a point layer."""
    layer_name = params.get("layer_name")
    output_name = params.get("output_name", f"vertices_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    point_features = []
    for feat_idx, f in enumerate(features):
        geom = f.get("geometry")
        if not geom:
            continue
        try:
            shapely_geom = geojson_to_shapely(geom)
        except Exception:
            continue

        # Extract all coordinates
        if hasattr(shapely_geom, 'exterior'):
            # Polygon
            coords = list(shapely_geom.exterior.coords)
        elif hasattr(shapely_geom, 'coords'):
            # LineString or Point
            coords = list(shapely_geom.coords)
        elif hasattr(shapely_geom, 'geoms'):
            # Multi* or GeometryCollection
            coords = []
            for sub_geom in shapely_geom.geoms:
                if hasattr(sub_geom, 'exterior'):
                    coords.extend(sub_geom.exterior.coords)
                elif hasattr(sub_geom, 'coords'):
                    coords.extend(sub_geom.coords)
        else:
            continue

        for vert_idx, coord in enumerate(coords):
            point_features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [coord[0], coord[1]]},
                "properties": {
                    "source_feature": feat_idx,
                    "vertex_index": vert_idx,
                },
            })

    result_geojson = {"type": "FeatureCollection", "features": point_features}

    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": len(point_features),
        "source_features": len(features),
    }


# ============================================================
# Milestone 5.4: Temporal & Attribute
# ============================================================

def handle_temporal_filter(params: dict, layer_store: dict = None) -> dict:
    """Filter features by date attribute."""
    layer_name = params.get("layer_name")
    date_attribute = params.get("date_attribute")
    after_str = params.get("after")
    before_str = params.get("before")
    output_name = params.get("output_name", f"filtered_{layer_name}")

    if not layer_name:
        return {"error": "layer_name is required"}
    if not date_attribute:
        return {"error": "date_attribute is required"}
    if not after_str and not before_str:
        return {"error": "At least one of 'after' or 'before' is required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    # Parse boundary dates
    after_dt = None
    before_dt = None
    try:
        if after_str:
            after_dt = datetime.fromisoformat(after_str)
        if before_str:
            before_dt = datetime.fromisoformat(before_str)
    except ValueError as e:
        return {"error": f"Invalid date format (use ISO format, e.g., '2023-01-01'): {e}"}

    filtered = []
    skipped = 0
    for f in features:
        props = f.get("properties") or {}
        date_val = props.get(date_attribute)
        if date_val is None:
            skipped += 1
            continue

        try:
            if isinstance(date_val, str):
                feat_dt = datetime.fromisoformat(date_val)
            else:
                skipped += 1
                continue
        except ValueError:
            skipped += 1
            continue

        if after_dt and feat_dt < after_dt:
            continue
        if before_dt and feat_dt > before_dt:
            continue

        filtered.append(f)

    result_geojson = {"type": "FeatureCollection", "features": filtered}

    return {
        "geojson": result_geojson,
        "layer_name": output_name,
        "feature_count": len(filtered),
        "original_count": len(features),
        "skipped_no_date": skipped,
        "date_attribute": date_attribute,
        "after": after_str,
        "before": before_str,
    }


def handle_attribute_statistics(params: dict, layer_store: dict = None) -> dict:
    """Compute detailed statistics for a numeric attribute."""
    import numpy as np

    layer_name = params.get("layer_name")
    attribute = params.get("attribute")

    if not layer_name:
        return {"error": "layer_name is required"}
    if not attribute:
        return {"error": "attribute is required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    values = []
    non_numeric = 0
    for f in features:
        props = f.get("properties") or {}
        val = props.get(attribute)
        if val is None:
            continue
        try:
            values.append(float(val))
        except (ValueError, TypeError):
            non_numeric += 1

    if not values:
        return {"error": f"No numeric values found for attribute '{attribute}'"}

    arr = np.array(values)
    p25, p50, p75 = np.percentile(arr, [25, 50, 75]).tolist()

    # Histogram with 10 bins
    hist_counts, hist_edges = np.histogram(arr, bins=10)
    histogram = []
    for i in range(len(hist_counts)):
        histogram.append({
            "bin_min": round(float(hist_edges[i]), 4),
            "bin_max": round(float(hist_edges[i + 1]), 4),
            "count": int(hist_counts[i]),
        })

    return {
        "layer_name": layer_name,
        "attribute": attribute,
        "count": len(values),
        "non_numeric_skipped": non_numeric,
        "min": round(float(np.min(arr)), 4),
        "max": round(float(np.max(arr)), 4),
        "mean": round(float(np.mean(arr)), 4),
        "median": round(float(np.median(arr)), 4),
        "std": round(float(np.std(arr, ddof=1)) if len(values) > 1 else 0.0, 4),
        "percentiles": {
            "25": round(p25, 4),
            "50": round(p50, 4),
            "75": round(p75, 4),
        },
        "histogram": histogram,
    }
