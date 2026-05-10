"""Annotations blueprint: CRUD operations on geo annotations, export, display."""

import datetime
import json
import logging
import os
import shutil

from flask import Blueprint, jsonify, request, render_template, send_file, after_this_request, g
import geopandas as gpd

from config import Config
import state
from blueprints.auth import require_api_token

annotation_bp = Blueprint('annotations', __name__)

# Paths
ANNOTATIONS_FILE = os.path.join(Config.LABELS_FOLDER, 'annotations.geojson')

MAX_ANNOTATIONS_STARTUP = Config.MAX_ANNOTATIONS_STARTUP


# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------

def load_annotations():
    """Load annotations from database (primary) or JSON file (fallback).

    Caps in-memory annotations to MAX_ANNOTATIONS_STARTUP to prevent
    unbounded memory usage on startup with large datasets.
    """
    # Try database first
    if state.db:
        try:
            total = state.db.get_annotation_count()
            features = state.db.get_all_annotations(limit=MAX_ANNOTATIONS_STARTUP)
            if features:
                state.geo_coco_annotations[:] = features
                if total > MAX_ANNOTATIONS_STARTUP:
                    logging.warning(
                        f"Loaded {len(features)}/{total} annotations from database "
                        f"(capped at {MAX_ANNOTATIONS_STARTUP}). Use DB queries for full dataset."
                    )
                else:
                    logging.info(f"Loaded {len(features)} annotations from database")
                return
        except Exception as e:
            logging.warning(f"DB annotation load failed, falling back to file: {e}")

    # Fallback to JSON file
    if os.path.exists(ANNOTATIONS_FILE):
        try:
            with open(ANNOTATIONS_FILE, 'r') as f:
                data = json.load(f)
                state.geo_coco_annotations[:] = data.get('features', [])

            # Migrate file annotations into database if DB available and empty
            if state.db and state.geo_coco_annotations:
                try:
                    if state.db.get_annotation_count() == 0:
                        for feat in state.geo_coco_annotations:
                            props = feat.get('properties', {})
                            state.db.save_annotation(
                                category_name=props.get('category_name', 'unknown'),
                                geometry=feat.get('geometry', {}),
                                color=props.get('color', '#3388ff'),
                                source=props.get('source', 'manual'),
                                properties=props,
                            )
                        logging.info(f"Migrated {len(state.geo_coco_annotations)} annotations from file to database")
                except Exception as mig_err:
                    logging.warning(f"Annotation migration to DB failed: {mig_err}")
        except json.JSONDecodeError:
            logging.warning("annotations.geojson is empty or malformed. Initializing with an empty FeatureCollection.")
            state.geo_coco_annotations.clear()
            initialize_annotations_file()
    else:
        state.geo_coco_annotations.clear()
        initialize_annotations_file()


def initialize_annotations_file():
    """Initialize the annotations.geojson with an empty FeatureCollection."""
    try:
        with open(ANNOTATIONS_FILE, 'w') as f:
            json.dump({"type": "FeatureCollection", "features": []}, f, indent=2)
        logging.info("Initialized annotations.geojson with an empty FeatureCollection.")
    except Exception as e:
        logging.error(f"Error initializing annotations.geojson: {str(e)}", exc_info=True)


def backup_annotations():
    """Create a timestamped backup of the annotations.geojson file."""
    if os.path.exists(ANNOTATIONS_FILE):
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        backup_file = f"annotations_backup_{timestamp}.geojson"
        backup_path = os.path.join(Config.LABELS_FOLDER, backup_file)
        shutil.copy(ANNOTATIONS_FILE, backup_path)
        logging.info(f"Backup created: {backup_file}")

        # Clean up old backups (keep last 10)
        cleanup_old_backups()


def cleanup_old_backups(keep=10):
    """Remove old backup files, keeping only the most recent ones."""
    try:
        backups = sorted([
            f for f in os.listdir(Config.LABELS_FOLDER)
            if f.startswith('annotations_backup_') and f.endswith('.geojson')
        ], reverse=True)

        for old_backup in backups[keep:]:
            os.remove(os.path.join(Config.LABELS_FOLDER, old_backup))
            logging.info(f"Removed old backup: {old_backup}")
    except Exception as e:
        logging.warning(f"Error cleaning up backups: {str(e)}")


def save_annotations_to_file():
    """Save current annotations to file.

    IMPORTANT: Must be called with annotation_lock held, or from within
    a ``with annotation_lock:`` block.  The function reads the global
    ``geo_coco_annotations`` list without acquiring the lock itself.
    """
    geo_coco_format = {
        "type": "FeatureCollection",
        "features": state.geo_coco_annotations
    }
    with open(ANNOTATIONS_FILE, 'w') as f:
        json.dump(geo_coco_format, f, indent=2)


def _persist_annotation(annotation, user_id=None):
    """Persist annotation: DB first, then in-memory cache.
    Must be called with annotation_lock held.

    DB is source of truth. If DB write fails, the exception propagates
    and the in-memory cache is NOT updated (caller's error handler catches it).

    Audit C4: tag ownership on the in-memory feature too so reads can filter.
    """
    uid = user_id or 'anonymous'
    if state.db:
        state.db.save_annotation(
            category_name=annotation['properties'].get('category_name', 'unknown'),
            geometry=annotation.get('geometry', {}),
            color=annotation['properties'].get('color', '#3388ff'),
            source=annotation['properties'].get('source', 'manual'),
            properties=annotation.get('properties'),
            user_id=uid,
        )
    # Only update in-memory cache after DB succeeds. Tag ownership inline.
    annotation.setdefault('properties', {})['owner_user_id'] = uid
    state.geo_coco_annotations.append(annotation)
    save_annotations_to_file()


def _clear_all_annotations(user_id=None):
    """Clear annotations from DB. Caller manages in-memory cache.

    Must be called with annotation_lock held. If user_id is given,
    only that user's rows are deleted; otherwise the legacy behavior
    (clear ALL rows + reset in-memory file) is preserved.

    DB is source of truth. If DB clear fails, the exception propagates.
    """
    if state.db:
        state.db.clear_annotations(user_id=user_id)
    if user_id is None:
        # Legacy behavior: clear in-memory + reset file.
        state.geo_coco_annotations.clear()
        initialize_annotations_file()


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@annotation_bp.route('/saved_annotations')
def saved_annotations():
    return render_template('saved_annotations.html')


@annotation_bp.route('/save_annotation', methods=['POST'])
@require_api_token
def save_annotation():
    """Save a single annotation."""
    from flask import current_app, g
    data = request.json

    if not data or 'geometry' not in data:
        return jsonify(success=False, error='Invalid annotation data'), 400

    user_id = getattr(g, 'user_id', 'anonymous')
    try:
        with state.annotation_lock:
            next_id = max((a.get("id", 0) for a in state.geo_coco_annotations), default=0) + 1
            annotation = {
                "type": "Feature",
                "id": next_id,
                "properties": {
                    "category_name": data.get('properties', {}).get('category_name', 'unknown'),
                    "color": data.get('properties', {}).get('color', '#3388ff'),
                    "bbox": data.get('properties', {}).get('bbox', []),
                    "created_at": datetime.datetime.now().isoformat()
                },
                "geometry": data['geometry']
            }
            _persist_annotation(annotation, user_id=user_id)

        current_app.logger.info(f"Annotation saved: {annotation['id']}")
        return jsonify(success=True, id=annotation['id'])
    except Exception as e:
        current_app.logger.exception(f"Error saving annotation: {e}")
        return jsonify(success=False, error="An internal error occurred."), 500


@annotation_bp.route('/add_osm_annotations', methods=['POST'])
@require_api_token
def add_osm_annotations():
    """Add OSM features as annotations.

    Audit N9: caps features at MAX_OSM_ANNOTATIONS_PER_REQUEST to prevent
    DoS / DB bloat / annotation_lock starvation.
    """
    from flask import current_app, g
    data = request.json
    user_id = getattr(g, 'user_id', 'anonymous')

    if not data:
        return jsonify(success=False, error='No data provided'), 400

    feats = data.get('features', []) if isinstance(data, dict) else []
    if not isinstance(feats, list):
        return jsonify(success=False, error='Invalid features payload'), 400

    MAX_PER_REQUEST = 1000
    if len(feats) > MAX_PER_REQUEST:
        return jsonify(
            success=False,
            error=f'Too many features in one request (max {MAX_PER_REQUEST}). '
                  'Split the upload into batches.',
        ), 413

    current_app.logger.debug(f"Received OSM data with {len(feats)} features")

    try:
        added_count = 0
        if feats:
            with state.annotation_lock:
                for feature in feats:
                    if 'geometry' not in feature or 'coordinates' not in feature['geometry']:
                        continue

                    geom_type = feature['geometry'].get('type', '')
                    if geom_type != 'Polygon':
                        continue

                    coordinates = feature['geometry']['coordinates'][0]
                    if len(coordinates) < 3:
                        continue

                    lons = [coord[0] for coord in coordinates]
                    lats = [coord[1] for coord in coordinates]
                    bbox = [[min(lons), min(lats)], [max(lons), min(lats)],
                            [max(lons), max(lats)], [min(lons), max(lats)]]

                    category = feature.get('properties', {}).get('category_name', 'osm_feature')

                    next_id = max((a.get("id", 0) for a in state.geo_coco_annotations), default=0) + 1
                    annotation = {
                        "type": "Feature",
                        "id": next_id,
                        "properties": {
                            "category_name": category,
                            "color": "#3388ff",
                            "bbox": bbox,
                            "source": "osm",
                            "created_at": datetime.datetime.now().isoformat()
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [coordinates]
                        }
                    }

                    _persist_annotation(annotation, user_id=user_id)
                    added_count += 1

        return jsonify(success=True, added=added_count)
    except Exception as e:
        current_app.logger.exception(f"Error adding OSM annotations: {e}")
        return jsonify(success=False, error="An internal error occurred."), 500


@annotation_bp.route('/get_annotations')
@require_api_token
def get_annotations():
    """Get all annotations visible to the requesting user (audit C4)."""
    from flask import g
    user_id = getattr(g, 'user_id', 'anonymous')
    with state.annotation_lock:
        features = [
            f for f in state.geo_coco_annotations
            if (f.get('properties') or {}).get('owner_user_id', 'anonymous') == user_id
        ]
    return jsonify({"type": "FeatureCollection", "features": features})


@annotation_bp.route('/clear_annotations', methods=['POST'])
@require_api_token
def clear_annotations():
    """Clear all annotations belonging to the requesting user (audit C4)."""
    from flask import current_app, g

    user_id = getattr(g, 'user_id', 'anonymous')
    try:
        with state.annotation_lock:
            if state.geo_coco_annotations:
                backup_annotations()
            _clear_all_annotations(user_id=user_id)
            # Drop only this user's annotations from in-memory cache.
            state.geo_coco_annotations[:] = [
                f for f in state.geo_coco_annotations
                if (f.get('properties') or {}).get('owner_user_id', 'anonymous') != user_id
            ]
            save_annotations_to_file()

        current_app.logger.info("All annotations cleared.")
        return jsonify(success=True)
    except Exception as e:
        current_app.logger.error(f"Error clearing annotations: {str(e)}", exc_info=True)
        return jsonify(success=False, error='An internal error occurred'), 500


@annotation_bp.route('/finalize_annotations', methods=['POST'])
@require_api_token
def finalize_annotations():
    """Finalize and save annotations with backup."""
    from flask import current_app
    try:
        with state.annotation_lock:
            backup_annotations()
            save_annotations_to_file()
            count = len(state.geo_coco_annotations)
        current_app.logger.info("Annotations finalized and saved.")
        return jsonify(success=True, count=count)
    except Exception as e:
        current_app.logger.exception(f"Error finalizing annotations: {e}")
        return jsonify(success=False, error="An internal error occurred."), 500


@annotation_bp.route('/export_annotations/<format_type>')
@require_api_token
def export_annotations(format_type):
    """Export annotations belonging to the requesting user (audit C4)."""
    from flask import current_app, g
    valid_formats = ['geojson', 'shapefile', 'geopackage']
    if format_type not in valid_formats:
        return jsonify(error=f'Invalid format. Choose from: {", ".join(valid_formats)}'), 400

    user_id = getattr(g, 'user_id', 'anonymous')
    with state.annotation_lock:
        # Snapshot under lock, filtered by owner.
        features_copy = [
            f for f in state.geo_coco_annotations
            if (f.get('properties') or {}).get('owner_user_id', 'anonymous') == user_id
        ]
        if not features_copy:
            return jsonify(error='No annotations to export'), 400

    try:
        # Create GeoDataFrame from snapshot
        gdf = gpd.GeoDataFrame.from_features(features_copy)
        gdf.set_crs(epsg=4326, inplace=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")

        if format_type == 'geojson':
            output_path = os.path.join(Config.LABELS_FOLDER, f'export_{timestamp}.geojson')
            gdf.to_file(output_path, driver='GeoJSON')
            cleanup_path = output_path

            @after_this_request
            def cleanup_geojson(response):
                try:
                    os.remove(cleanup_path)
                except OSError:
                    pass
                return response

            return send_file(output_path, as_attachment=True, download_name=f'annotations_{timestamp}.geojson')

        elif format_type == 'shapefile':
            output_dir = os.path.join(Config.LABELS_FOLDER, f'export_{timestamp}_shp')
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, 'annotations.shp')
            gdf.to_file(output_path, driver='ESRI Shapefile')

            # Create zip file
            zip_path = os.path.join(Config.LABELS_FOLDER, f'annotations_{timestamp}.zip')
            shutil.make_archive(zip_path.replace('.zip', ''), 'zip', output_dir)

            # Clean up directory
            shutil.rmtree(output_dir)

            cleanup_zip = zip_path

            @after_this_request
            def cleanup_shapefile(response):
                try:
                    os.remove(cleanup_zip)
                except OSError:
                    pass
                return response

            return send_file(zip_path, as_attachment=True, download_name=f'annotations_{timestamp}.zip')

        elif format_type == 'geopackage':
            output_path = os.path.join(Config.LABELS_FOLDER, f'annotations_{timestamp}.gpkg')
            gdf.to_file(output_path, driver='GPKG')
            cleanup_gpkg = output_path

            @after_this_request
            def cleanup_geopackage(response):
                try:
                    os.remove(cleanup_gpkg)
                except OSError:
                    pass
                return response

            return send_file(output_path, as_attachment=True, download_name=f'annotations_{timestamp}.gpkg')

    except Exception as e:
        current_app.logger.error(f"Error exporting annotations: {str(e)}", exc_info=True)
        return jsonify(error='Export failed'), 500


@annotation_bp.route('/display_table', methods=['POST'])
def display_table():
    """Convert GeoJSON to HTML table with essential columns only.

    Audit N38: per-user rate limit + payload feature cap. The handler
    routes user-supplied GeoJSON through GeoDataFrame.from_features +
    pandas.to_html — both unbounded in feature count pre-fix. A
    100k-feature POST blew up memory + CPU.
    """
    from flask import current_app
    from services.rate_limiter import display_table_limiter

    user_id = getattr(g, 'user_id', 'anonymous')
    if not display_table_limiter.allow(user_id):
        return ('<p class="error">Rate limit exceeded '
                '(30 table renders/min). Slow down.</p>', 429)

    try:
        geojson_data = request.json
        if not geojson_data or 'features' not in geojson_data:
            return '<p class="error">Invalid GeoJSON data.</p>', 400

        if not geojson_data['features']:
            return '<p>No annotations to display.</p>'

        # N38: cap features before geopandas/pandas conversion. The
        # rendered HTML is human-readable; >5k rows is unusable in a
        # browser anyway. Reject loud rather than truncating silently
        # so callers know their data didn't all render.
        feature_count = len(geojson_data['features'])
        DISPLAY_TABLE_MAX_FEATURES = 5000
        if feature_count > DISPLAY_TABLE_MAX_FEATURES:
            return (
                f'<p class="error">Too many features ({feature_count}) '
                f'for table display (max {DISPLAY_TABLE_MAX_FEATURES}). '
                f'Filter the layer first or export to GeoJSON.</p>',
                413,  # Payload Too Large
            )

        gdf = gpd.GeoDataFrame.from_features(geojson_data["features"])

        # Create a simplified table with essential columns
        table_data = []
        for idx, row in gdf.iterrows():
            # Get geometry type
            geom_type = row.geometry.geom_type if row.geometry else 'Unknown'

            # Get category name
            category = row.get('category_name', 'Unknown')

            # Get source (osm or manual)
            source = row.get('source', 'manual')

            # Get feature ID
            feature_id = row.get('id', idx + 1)

            table_data.append({
                'ID': feature_id,
                'Category': category,
                'Type': geom_type,
                'Source': source
            })

        import pandas as pd
        df = pd.DataFrame(table_data)
        return df.to_html(classes='table', index=False, escape=True)
    except Exception as e:
        current_app.logger.exception(f"Error displaying table: {e}")
        return '<p class="error">An internal error occurred while generating the table.</p>', 500
