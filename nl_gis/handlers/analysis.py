"""Spatial analysis handlers: buffer, spatial query, aggregate, area, distance, filter, geometry, advanced analysis."""

import hashlib
import json
import logging
import math
import time

from shapely.ops import unary_union

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
