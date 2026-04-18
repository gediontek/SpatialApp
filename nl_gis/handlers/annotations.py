"""Annotation handlers: add, classify landcover, export, get annotations.

ERROR PATHS (audit 2026-04-17 for v2.1 Plan 05 M1):
    12 error returns · 4 except blocks · 1 leaky str(e) at line 167.
    Leak must be replaced with generic message + logger.exception().
"""

import logging

from nl_gis.handlers import _get_layer_snapshot
from state import geo_coco_annotations, annotation_lock, db as app_db
from blueprints.annotations import save_annotations_to_file

logger = logging.getLogger(__name__)


def handle_add_annotation(params: dict, layer_store: dict = None) -> dict:
    """Save geometry/layer as annotations."""
    import datetime

    geometry = params.get("geometry")
    layer_name = params.get("layer_name")
    category_name = params.get("category_name", "unknown")
    color = params.get("color", "#3388ff")

    # Uses top-level imports: geo_coco_annotations, save_annotations_to_file, annotation_lock

    added = 0

    # Get layer snapshot BEFORE acquiring annotation_lock to avoid
    # deadlock (_get_layer_snapshot acquires layer_lock internally).
    layer_features = None
    if layer_name:
        layer_features, _ = _get_layer_snapshot(layer_store, layer_name)

    with annotation_lock:
        if layer_name:
            if layer_features:
                for f in layer_features:
                    geom = f.get("geometry")
                    if geom:
                        next_id = max((a.get("id", 0) for a in geo_coco_annotations), default=0) + 1
                        annotation = {
                            "type": "Feature",
                            "id": next_id,
                            "properties": {
                                "category_name": category_name,
                                "color": color,
                                "source": "chat",
                                "created_at": datetime.datetime.now().isoformat(),
                            },
                            "geometry": geom,
                        }
                        geo_coco_annotations.append(annotation)
                        added += 1
        elif geometry:
            next_id = max((a.get("id", 0) for a in geo_coco_annotations), default=0) + 1
            annotation = {
                "type": "Feature",
                "id": next_id,
                "properties": {
                    "category_name": category_name,
                    "color": color,
                    "source": "chat",
                    "created_at": datetime.datetime.now().isoformat(),
                },
                "geometry": geometry,
            }
            geo_coco_annotations.append(annotation)
            added = 1
        else:
            return {"error": "Provide either geometry or layer_name"}

        if added > 0:
            save_annotations_to_file()

            # Persist to database
            try:
                if app_db:
                    if layer_name and layer_features:
                        for f in layer_features:
                            geom = f.get("geometry")
                            if geom:
                                app_db.save_annotation(category_name, geom, color, "chat")
                    elif geometry:
                        app_db.save_annotation(category_name, geometry, color, "chat")
            except Exception as db_err:
                logger.warning(f"DB save failed (chat annotation): {db_err}")

    return {"success": True, "added": added, "category": category_name}


def _classify_landcover_work(params: dict) -> dict:
    """Heavy classification work -- runs in a thread pool to avoid blocking."""
    from OSM_auto_label import download_osm_landcover, OSMLandcoverClassifier
    from OSM_auto_label.downloader import download_by_bbox
    from OSM_auto_label.config import CATEGORY_COLORS
    import re

    location = params.get("location")
    bbox = params.get("bbox")
    classes = params.get("classes")

    if bbox:
        n, s, e, w = bbox.get("north"), bbox.get("south"), bbox.get("east"), bbox.get("west")
        if None in (n, s, e, w):
            return {"error": "bbox requires north, south, east, west"}
        gdf = download_by_bbox(north=n, south=s, east=e, west=w, timeout=300)
        safe_name = f"bbox_{abs(hash((n, s, e, w))) % 10000}"
    else:
        if not location:
            return {"error": "No location or bbox provided"}
        gdf = download_osm_landcover(location, timeout=300)
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', location.split(',')[0].strip().lower())

    if gdf is None or len(gdf) == 0:
        return {"error": "No landcover data found"}

    classifier = OSMLandcoverClassifier()
    gdf_classified = classifier.process_geodataframe(gdf, name=None)

    if gdf_classified is None or len(gdf_classified) == 0:
        return {"error": "Classification produced no results"}

    if classes and len(classes) > 0:
        gdf_classified = gdf_classified[gdf_classified['classname'].isin(classes)]

    if len(gdf_classified) == 0:
        return {"error": "No features found for selected classes"}

    import json as json_mod
    geojson_data = json_mod.loads(gdf_classified.to_json())
    layer_name = f"classified_{safe_name}"

    return {
        "geojson": geojson_data,
        "layer_name": layer_name,
        "feature_count": len(gdf_classified),
        "colors": CATEGORY_COLORS,
    }


def handle_classify_landcover(params: dict) -> dict:
    """Classify landcover using OSM_auto_label module.

    Runs the heavy download+classify work in a thread pool so it doesn't
    block the Flask server for other requests. Timeout: 5 minutes.
    """
    try:
        from OSM_auto_label import download_osm_landcover  # noqa: F401
    except ImportError:
        return {"error": "OSM auto-label module not available"}

    location = params.get("location")
    bbox = params.get("bbox")

    if not location and not bbox:
        return {"error": "Provide either location or bbox"}

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_classify_landcover_work, params)
            result = future.result(timeout=300)  # 5 minute timeout
        return result
    except FutureTimeout:
        logger.error("Classification timed out after 300s")
        return {"error": "Classification timed out. Try a smaller area."}
    except Exception as e:
        logger.error(f"Classification error: {e}", exc_info=True)
        return {"error": str(e)}


def handle_export_annotations(params: dict) -> dict:
    """Export annotations to file."""
    format_type = params.get("format", "geojson")
    valid_formats = ["geojson", "shapefile", "geopackage"]

    if format_type not in valid_formats:
        return {"error": f"Invalid format. Choose from: {', '.join(valid_formats)}"}

    with annotation_lock:
        count = len(geo_coco_annotations)

    if count == 0:
        return {"error": "No annotations to export"}

    return {
        "success": True,
        "format": format_type,
        "count": count,
        "download_url": f"/export_annotations/{format_type}",
        "description": f"Export {count} annotations as {format_type}",
    }


def handle_get_annotations(params: dict) -> dict:
    """Get current annotations summary."""
    with annotation_lock:
        features = list(geo_coco_annotations)

    categories = {}
    for f in features:
        cat = f.get("properties", {}).get("category_name", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "total": len(features),
        "categories": [{"name": k, "count": v} for k, v in sorted(categories.items(), key=lambda x: -x[1])],
        "geojson": {"type": "FeatureCollection", "features": features},
    }
