"""Layer management handlers: style, visibility, highlight, merge, import."""

import logging

from nl_gis.handlers import _get_layer_snapshot

logger = logging.getLogger(__name__)


def handle_style_layer(params: dict) -> dict:
    """Change the visual style of a layer. Returns instruction for frontend."""
    layer_name = params.get("layer_name")
    if not layer_name:
        return {"error": "layer_name is required"}

    style = {}
    for key in ("color", "fill_color", "weight", "fill_opacity", "opacity"):
        if params.get(key) is not None:
            # Convert fill_color -> fillColor for Leaflet
            leaflet_key = key.replace("fill_color", "fillColor").replace("fill_opacity", "fillOpacity")
            style[leaflet_key] = params[key]

    if not style:
        return {"error": "At least one style property (color, weight, fill_opacity, etc.) is required"}

    return {
        "success": True,
        "action": "style",
        "layer_name": layer_name,
        "style": style,
        "description": f"Styled layer '{layer_name}'",
    }


def handle_layer_visibility(params: dict, action: str) -> dict:
    """Handle show/hide/remove layer commands. Returns instruction for frontend."""
    layer_name = params.get("layer_name")
    if not layer_name:
        return {"error": "layer_name is required"}
    return {
        "success": True,
        "action": action,
        "layer_name": layer_name,
        "description": f"Layer '{layer_name}' {action}",
    }


def handle_highlight_features(params: dict, layer_store: dict = None) -> dict:
    """Highlight features matching an attribute value. Returns instruction for frontend."""
    layer_name = params.get("layer_name")
    attribute = params.get("attribute")
    value = params.get("value")
    color = params.get("color", "#ff0000")

    if not layer_name:
        return {"error": "layer_name is required"}
    if not attribute or not value:
        return {"error": "attribute and value are required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}

    matched = 0
    for f in features:
        props = f.get("properties", {})
        # Check nested osm_tags as well
        if str(props.get(attribute, "")) == str(value):
            matched += 1
        elif str(props.get("osm_tags", {}).get(attribute, "")) == str(value):
            matched += 1

    return {
        "success": True,
        "action": "highlight",
        "layer_name": layer_name,
        "attribute": attribute,
        "value": value,
        "color": color,
        "highlighted": matched,
        "total": len(features),
        "description": f"Highlighted {matched}/{len(features)} features where {attribute}={value}",
    }


def handle_merge_layers(params: dict, layer_store: dict = None) -> dict:
    """Merge two layers or perform a spatial join."""
    import geopandas as gpd_mod

    layer_a = params.get("layer_a")
    layer_b = params.get("layer_b")
    output_name = params.get("output_name")
    operation = params.get("operation", "union")

    if not layer_a or not layer_b or not output_name:
        return {"error": "layer_a, layer_b, and output_name are required"}

    if not layer_store:
        return {"error": "No layer store available"}

    features_a, err_a = _get_layer_snapshot(layer_store, layer_a)
    if err_a:
        return {"error": f"Layer '{layer_a}' not found"}
    features_b, err_b = _get_layer_snapshot(layer_store, layer_b)
    if err_b:
        return {"error": f"Layer '{layer_b}' not found"}

    try:
        gdf_a = gpd_mod.GeoDataFrame.from_features(features_a)
        gdf_b = gpd_mod.GeoDataFrame.from_features(features_b
        )

        if gdf_a.crs is None:
            gdf_a.set_crs(epsg=4326, inplace=True)
        if gdf_b.crs is None:
            gdf_b.set_crs(epsg=4326, inplace=True)

        if operation == "spatial_join":
            merged = gpd_mod.sjoin(gdf_a, gdf_b, how="left", predicate="intersects")
            # Drop the index_right column that sjoin adds
            if "index_right" in merged.columns:
                merged = merged.drop(columns=["index_right"])
        else:
            # Union: concatenate both GeoDataFrames
            import pandas as pd_mod
            merged = gpd_mod.GeoDataFrame(
                pd_mod.concat([gdf_a, gdf_b], ignore_index=True),
                crs=gdf_a.crs,
            )

        import json as json_mod
        geojson_data = json_mod.loads(merged.to_json())

        if layer_store is not None:
            try:
                from state import layer_lock as _lk
            except ImportError:
                _lk = None
            if _lk:
                with _lk:
                    layer_store[output_name] = geojson_data
            else:
                layer_store[output_name] = geojson_data

        return {
            "geojson": geojson_data,
            "layer_name": output_name,
            "feature_count": len(geojson_data.get("features", [])),
            "operation": operation,
            "description": f"Merged '{layer_a}' + '{layer_b}' -> '{output_name}' ({operation}, {len(geojson_data.get('features', []))} features)",
        }
    except Exception as e:
        logger.error(f"Merge error: {e}", exc_info=True)
        return {"error": "Layer merge failed"}


def handle_import_layer(params: dict, layer_store: dict = None) -> dict:
    """Import GeoJSON data as a named layer."""
    layer_name = params.get("layer_name")
    geojson = params.get("geojson")

    if not layer_name:
        return {"error": "layer_name is required"}

    if geojson:
        # Direct GeoJSON import
        if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
            return {"error": "geojson must be a GeoJSON FeatureCollection"}

        if layer_store is not None:
            try:
                from state import layer_lock as _lk
            except ImportError:
                _lk = None
            if _lk:
                with _lk:
                    layer_store[layer_name] = geojson
            else:
                layer_store[layer_name] = geojson

        return {
            "geojson": geojson,
            "layer_name": layer_name,
            "feature_count": len(geojson.get("features", [])),
            "description": f"Imported {len(geojson.get('features', []))} features as '{layer_name}'",
        }

    # No inline GeoJSON -- tell the user to use the file upload
    return {
        "success": True,
        "layer_name": layer_name,
        "description": "To import a file, use the upload button or drag-and-drop a GeoJSON, Shapefile (.zip), or GeoPackage (.gpkg) file onto the map.",
        "upload_url": "/api/import",
    }
