"""Layers blueprint: layer CRUD and import."""

import json
import logging
import os

from flask import Blueprint, jsonify, request, g
import geopandas as gpd
from werkzeug.utils import secure_filename

from config import Config
import state
from blueprints.auth import require_api_token

layers_bp = Blueprint('layers', __name__)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _evict_layers_if_needed():
    """Remove oldest layers when store exceeds limit. Call under layer_lock."""
    while len(state.layer_store) > state.MAX_LAYERS_IN_MEMORY:
        evicted_name, _ = state.layer_store.popitem(last=False)
        state.layer_owners.pop(evicted_name, None)
        logging.info(f"Evicted layer '{evicted_name}' from memory (limit: {state.MAX_LAYERS_IN_MEMORY})")


def _user_can_see(layer_name: str, user_id: str) -> bool:
    """Per-user isolation check (audit C4, path B).

    Returns True if the requesting user is the layer's owner. Layers
    with no recorded owner default to 'anonymous' and are visible only
    to anonymous callers.
    """
    owner = state.layer_owners.get(layer_name, "anonymous")
    return owner == user_id


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@layers_bp.route('/api/layers')
@require_api_token
def api_get_layers():
    """Get list of named layers with optional pagination.

    Query parameters
    ----------------
    page : int, optional
        1-based page number (default: 1).  When omitted the full list is
        returned for backward compatibility.
    per_page : int, optional
        Items per page, clamped to [1, 500] (default: 100).
    """
    user_id = getattr(g, 'user_id', 'anonymous')
    # Build full list under the lock, filtering by user (audit C4).
    with state.layer_lock:
        all_layers = []
        for name, geojson in state.layer_store.items():
            if not _user_can_see(name, user_id):
                continue
            feature_count = len(geojson.get('features', [])) if isinstance(geojson, dict) else 0
            all_layers.append({
                'name': name,
                'feature_count': feature_count,
            })

    total = len(all_layers)

    # Check for pagination params
    page_param = request.args.get('page')
    per_page_param = request.args.get('per_page')

    if page_param is None and per_page_param is None:
        # No pagination requested — return full list (backward compatible)
        return jsonify(layers=all_layers)

    # Parse and clamp pagination values
    try:
        page = max(1, int(page_param or 1))
    except (ValueError, TypeError):
        page = 1
    try:
        per_page = min(500, max(1, int(per_page_param or 100)))
    except (ValueError, TypeError):
        per_page = 100

    start = (page - 1) * per_page
    end = start + per_page
    page_layers = all_layers[start:end]
    total_pages = max(1, (total + per_page - 1) // per_page)

    return jsonify(
        layers=page_layers,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@layers_bp.route('/api/layers/<layer_name>', methods=['DELETE'])
@require_api_token
def api_delete_layer(layer_name):
    """Delete a named layer."""
    from flask import current_app
    user_id = getattr(g, 'user_id', 'anonymous')
    with state.layer_lock:
        if layer_name not in state.layer_store:
            return jsonify(error='Layer not found'), 404
        # Per-user isolation (audit C4): only the owner may delete.
        if not _user_can_see(layer_name, user_id):
            # Same 404 to avoid leaking that the layer exists for another user.
            return jsonify(error='Layer not found'), 404
        # DB first: if delete fails, in-memory stays consistent
        if state.db:
            state.db.delete_layer(layer_name, user_id=user_id)
        # Only remove from cache after DB succeeds
        del state.layer_store[layer_name]
        state.layer_owners.pop(layer_name, None)
        return jsonify(success=True)


@layers_bp.route('/api/import', methods=['POST'])
@require_api_token
def api_import_layer():
    """Import a vector file (GeoJSON, Shapefile zip, GeoPackage) as a named layer."""
    from flask import current_app
    if 'file' not in request.files:
        return jsonify(error='No file provided'), 400

    file = request.files['file']
    layer_name = request.form.get('layer_name', '')
    if not file.filename:
        return jsonify(error='No file selected'), 400

    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    if ext not in ('geojson', 'json', 'zip', 'gpkg'):
        return jsonify(error='Supported formats: .geojson, .json, .zip (shapefile), .gpkg'), 400

    import tempfile
    try:
        with tempfile.TemporaryDirectory() as tmp:
            filepath = os.path.join(tmp, filename)
            file.save(filepath)

            # For shapefile zips, extract first.
            # Audit N8: bound decompressed size + per-entry size + entry count
            # to prevent zip-bomb DoS. Path traversal is handled by Python's
            # zipfile.extractall (3.12+) but we still belt-and-suspenders by
            # rejecting any member whose normalized path escapes tmp.
            if ext == 'zip':
                import zipfile
                MAX_TOTAL_BYTES = 500 * 1024 * 1024  # 500 MB decompressed
                MAX_PER_FILE_BYTES = 100 * 1024 * 1024  # 100 MB single entry
                MAX_ENTRIES = 1000
                with zipfile.ZipFile(filepath, 'r') as zf:
                    infos = zf.infolist()
                    if len(infos) > MAX_ENTRIES:
                        return jsonify(error=f'Zip has too many entries (>{MAX_ENTRIES})'), 400
                    total = 0
                    for info in infos:
                        # Reject path traversal: any component '..' or absolute paths.
                        norm = os.path.normpath(info.filename)
                        if norm.startswith('..') or os.path.isabs(norm):
                            return jsonify(error='Zip contains unsafe path'), 400
                        if info.file_size > MAX_PER_FILE_BYTES:
                            return jsonify(error='Zip entry too large'), 400
                        total += info.file_size
                        if total > MAX_TOTAL_BYTES:
                            return jsonify(error='Zip decompressed size exceeds limit'), 400
                    zf.extractall(tmp)
                # Find the .shp file
                shp_files = [f for f in os.listdir(tmp) if f.endswith('.shp')]
                if not shp_files:
                    return jsonify(error='No .shp file found in zip'), 400
                filepath = os.path.join(tmp, shp_files[0])

            gdf = gpd.read_file(filepath)
            if len(gdf) == 0:
                return jsonify(error='File contains no features'), 400

            # Ensure WGS84
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)

            geojson_data = json.loads(gdf.to_json())

            if not layer_name:
                layer_name = filename.rsplit('.', 1)[0].replace(' ', '_').lower()

            # Cap features
            if len(geojson_data.get('features', [])) > Config.MAX_FEATURES_PER_LAYER:
                geojson_data['features'] = geojson_data['features'][:Config.MAX_FEATURES_PER_LAYER]

            uid = getattr(g, 'user_id', 'anonymous')
            # DB first: if save fails, in-memory stays consistent
            if state.db:
                state.db.save_layer(layer_name, geojson_data, user_id=uid)
            # Only update cache after DB succeeds. Tag ownership so
            # /api/layers + delete enforce isolation. (Audit C4.)
            with state.layer_lock:
                state.layer_store[layer_name] = geojson_data
                state.layer_owners[layer_name] = uid
                _evict_layers_if_needed()

            return jsonify(
                success=True,
                layer_name=layer_name,
                feature_count=len(geojson_data.get('features', [])),
                geojson=geojson_data,
            )
    except Exception as e:
        current_app.logger.error(f"Import error: {e}", exc_info=True)
        return jsonify(error='Import failed'), 500
