"""OSM blueprint: OSM data fetching, geocoding, auto-classification."""

import json
import logging
import os
import re
import sys
import urllib.parse
import urllib.request

from flask import Blueprint, jsonify, request, send_from_directory, render_template
import numpy as np
import rasterio
from pyproj import Transformer
import requests as http_requests
from werkzeug.utils import secure_filename

from config import Config
import state
from blueprints.auth import require_api_token

# Add OSM_auto_label to path and import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from OSM_auto_label import download_osm_landcover, OSMLandcoverClassifier
    from OSM_auto_label.downloader import download_by_bbox
    from OSM_auto_label.config import CATEGORY_COLORS
    OSM_AUTO_LABEL_AVAILABLE = True
except ImportError as e:
    OSM_AUTO_LABEL_AVAILABLE = False
    logging.warning(f"OSM_auto_label not available: {e}")

osm_bp = Blueprint('osm', __name__)

# Input validation patterns
VALID_OSM_KEY_PATTERN = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_:]*$')
VALID_OSM_VALUE_PATTERN = re.compile(r'^[a-zA-Z0-9_\-\s\*]+$')
ALLOWED_EXTENSIONS = {'tif', 'tiff'}

# Special value to fetch ALL features with a key (regardless of value)
OSM_WILDCARD_VALUES = {'*', 'any', 'all', ''}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def validate_osm_input(key, value):
    """Validate OSM query inputs to prevent injection."""
    if value is None:
        return False, "Value is required"
    if not key:
        return False, "Key is required"
    if len(key) > 50 or len(value) > 100:
        return False, "Key or value too long"
    if not VALID_OSM_KEY_PATTERN.match(key):
        return False, "Invalid key format"
    # Allow wildcard values for fetching all features with a key
    if value.lower() not in OSM_WILDCARD_VALUES and value:
        if not VALID_OSM_VALUE_PATTERN.match(value):
            return False, "Invalid value format"
    return True, None


def validate_bbox(bbox_str):
    """Validate bounding box string."""
    try:
        parts = [float(x) for x in bbox_str.split(',')]
        if len(parts) != 4:
            return False, None
        south, west, north, east = parts
        if not (-90 <= south <= 90 and -90 <= north <= 90):
            return False, None
        if not (-180 <= west <= 180 and -180 <= east <= 180):
            return False, None
        if south > north:
            return False, None
        # west > east is valid (antimeridian crossing)
        return True, bbox_str
    except (ValueError, AttributeError):
        return False, None


def render_overlay(image_path):
    """Process raster file and return overlay information.

    Reprojects bounds to EPSG:4326, converts raster data to a
    browser-renderable PNG, and returns an HTTP URL for Leaflet.
    """
    from flask import current_app
    try:
        with rasterio.open(image_path) as src:
            bounds = src.bounds
            transformer = Transformer.from_crs(src.crs, 'epsg:4326', always_xy=True)

            min_lon, min_lat = transformer.transform(bounds.left, bounds.bottom)
            max_lon, max_lat = transformer.transform(bounds.right, bounds.top)

            image_bounds = [[min_lat, min_lon], [max_lat, max_lon]]
            center_lat = (min_lat + max_lat) / 2
            center_lon = (min_lon + max_lon) / 2

            # Convert GeoTIFF to PNG (browsers cannot render .tif)
            png_filename = os.path.splitext(os.path.basename(image_path))[0] + '.png'
            png_path = os.path.join(current_app.config['UPLOAD_FOLDER'], png_filename)

            band_count = src.count

            if band_count >= 3:
                # RGB or RGBA -- use first 3 bands
                rgb = np.stack([src.read(i + 1) for i in range(3)])
            elif band_count == 1:
                # Single band -- replicate to RGB
                band = src.read(1)
                rgb = np.stack([band, band, band])
            else:
                # 2 bands -- use first as grayscale
                band = src.read(1)
                rgb = np.stack([band, band, band])

            # Normalize each band to 0-255 uint8 for PNG
            rgb_uint8 = np.zeros_like(rgb, dtype=np.uint8)
            for i in range(3):
                band = rgb[i].astype(np.float64)
                nodata = src.nodata
                if nodata is not None:
                    mask = band != nodata
                else:
                    mask = np.ones_like(band, dtype=bool)
                if mask.any():
                    bmin = band[mask].min()
                    bmax = band[mask].max()
                    if bmax > bmin:
                        band = (band - bmin) / (bmax - bmin) * 255
                    else:
                        band = np.where(mask, 128, 0)
                rgb_uint8[i] = np.clip(band, 0, 255).astype(np.uint8)

            # Write PNG with rasterio
            with rasterio.open(
                png_path, 'w', driver='PNG',
                height=rgb_uint8.shape[1], width=rgb_uint8.shape[2],
                count=3, dtype='uint8',
            ) as dst:
                for i in range(3):
                    dst.write(rgb_uint8[i], i + 1)

        image_url = f"/static/uploads/{png_filename}"
        return jsonify(
            image_url=image_url,
            image_bounds=image_bounds,
            center_lat=center_lat,
            center_lon=center_lon
        )
    except Exception as e:
        current_app.logger.error(f"Error rendering overlay: {str(e)}", exc_info=True)
        return jsonify(message='Error processing the raster file.'), 500


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@osm_bp.route('/')
def index():
    return render_template('index.html')


@osm_bp.route('/upload', methods=['POST'])
@require_api_token
def upload():
    from flask import current_app
    if 'file' not in request.files:
        return jsonify(message='No file part in the request.'), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify(message='No file selected for uploading.'), 400

    if not allowed_file(file.filename):
        return jsonify(message='Invalid file type. Only .tif and .tiff files are allowed.'), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)

    try:
        file.save(filepath)
        current_app.logger.info(f"Uploaded file saved to {filepath}.")
        return render_overlay(filepath)
    except Exception as e:
        current_app.logger.error(f"Error saving uploaded file: {str(e)}", exc_info=True)
        return jsonify(message='Error saving the uploaded file.'), 500


@osm_bp.route('/static/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files."""
    from flask import current_app
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)


@osm_bp.route('/fetch_osm_data', methods=['POST'])
@require_api_token
def fetch_osm_data():
    """Fetch data from OpenStreetMap via Overpass API."""
    from flask import current_app
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify(success=False, error='No data provided'), 400

        bbox = data.get('bbox', '')
        feature_type = data.get('feature_type', 'building')
        category_name = data.get('category_name', '')

        # Validate category name
        if not category_name:
            return jsonify(success=False, error='Category name is required'), 400

        # Validate bbox
        valid, sanitized_bbox = validate_bbox(bbox)
        if not valid:
            return jsonify(success=False, error='Invalid bounding box'), 400

        # Mapping of user-friendly feature types to OSM query parameters
        from nl_gis.handlers import OSM_FEATURE_MAPPINGS

        # Get OSM query parameters for this feature type
        if feature_type not in OSM_FEATURE_MAPPINGS:
            return jsonify(success=False, error=f'Unknown feature type: {feature_type}'), 400

        mapping = OSM_FEATURE_MAPPINGS[feature_type]
        key = mapping['key']
        value = mapping['value']

        overpass_url = "https://overpass-api.de/api/interpreter"

        # Build query based on whether we have a specific value or not
        if value is None:
            # Fetch ALL features with this key (e.g., all buildings)
            overpass_query = f"""
            [out:json][timeout:30];
            (
              way["{key}"]({sanitized_bbox});
              relation["{key}"]({sanitized_bbox});
            );
            out geom qt;
            """
        else:
            # Fetch only features with specific key=value
            overpass_query = f"""
            [out:json][timeout:30];
            (
              way["{key}"="{value}"]({sanitized_bbox});
              relation["{key}"="{value}"]({sanitized_bbox});
            );
            out geom qt;
            """

        current_app.logger.debug(f"Overpass query for feature_type={feature_type}, key={key}, value={value}")

        # Rate limit before making the actual external request
        from services.rate_limiter import overpass_limiter
        overpass_limiter.wait()

        response = http_requests.get(
            overpass_url,
            params={'data': overpass_query},
            headers={"User-Agent": "SpatialApp/1.0 (https://github.com/gediontek/SpatialApp)"},
            timeout=Config.OSM_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        osm_data = response.json()

        # Use the shared converter which handles BOTH formats:
        #   - `out geom`  → inline coords on each way / relation member
        #   - `out body + >` → separate node elements + node-id refs
        # The previous in-route parser only handled the legacy form, so
        # the modern `out geom qt` query above was producing zero
        # features even when Overpass returned 200.
        from nl_gis.handlers import _osm_to_geojson
        geojson_data = _osm_to_geojson(osm_data, category_name, feature_type)

        if not geojson_data["features"]:
            current_app.logger.warning(
                "No OSM features parsed for feature_type=%s in bbox=%s",
                feature_type, sanitized_bbox,
            )

        current_app.logger.info(f"Fetched {len(geojson_data['features'])} {feature_type} features with category '{category_name}'")
        return jsonify(geojson_data)
    except http_requests.Timeout:
        current_app.logger.error("OSM request timed out")
        return jsonify(success=False, error='Request timed out. Try a smaller area.'), 504
    except http_requests.RequestException as e:
        current_app.logger.error(f"Error fetching OSM data: {str(e)}", exc_info=True)
        return jsonify(success=False, error='Error connecting to OSM service'), 502
    except Exception as e:
        current_app.logger.error(f"Error fetching OSM data: {str(e)}", exc_info=True)
        return jsonify(success=False, error='An internal error occurred'), 500


@osm_bp.route('/api/geocode')
def api_geocode():
    """Geocode a place name using Nominatim."""
    from flask import current_app
    from services.rate_limiter import nominatim_limiter
    query = request.args.get('q', '')
    if not query:
        return jsonify(error='No query provided'), 400

    if not nominatim_limiter.can_proceed():
        return jsonify(error='Rate limit exceeded. Please wait a moment.'), 429
    nominatim_limiter.wait()

    try:
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "SpatialLabeler/1.0"})

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())

        if not data:
            return jsonify(error='Location not found'), 404

        result = data[0]
        return jsonify(
            lat=float(result['lat']),
            lon=float(result['lon']),
            display_name=result['display_name']
        )
    except Exception as e:
        current_app.logger.error(f"Geocoding error: {str(e)}", exc_info=True)
        return jsonify(error='An internal error occurred'), 500


@osm_bp.route('/api/auto-classify', methods=['POST'])
@require_api_token
def api_auto_classify():
    """Download OSM data and classify landcover."""
    from flask import current_app
    if not OSM_AUTO_LABEL_AVAILABLE:
        return jsonify(error='OSM auto-label module not available. Please install dependencies.'), 500

    data = request.get_json()
    if not data:
        return jsonify(error='No data provided'), 400

    place = data.get('place', '')
    bbox = data.get('bbox', None)
    selected_classes = data.get('selected_classes', None)

    # Validate input: need either place or bbox
    if not place and not bbox:
        return jsonify(error='Please provide a place name or use current map extent'), 400

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    def _do_classify():
        if bbox:
            north = bbox.get('north')
            south = bbox.get('south')
            east = bbox.get('east')
            west = bbox.get('west')

            if None in (north, south, east, west):
                return None, 'Invalid bounding box', 400

            current_app.logger.info(f"Auto-classifying landcover for bbox: N={north}, S={south}, E={east}, W={west}")
            gdf = download_by_bbox(north=north, south=south, east=east, west=west, timeout=300)
            safe_name = f"bbox_{abs(hash((north, south, east, west))) % 10000}"
        else:
            current_app.logger.info(f"Auto-classifying landcover for: {place}")
            gdf = download_osm_landcover(place, timeout=300)
            safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', place.split(',')[0].strip().lower())

        if gdf is None or len(gdf) == 0:
            return None, 'No landcover data found for this location', 404

        current_app.logger.info(f"Downloaded {len(gdf)} features, starting classification...")

        classifier = OSMLandcoverClassifier()
        gdf_classified = classifier.process_geodataframe(gdf, name=None)

        if gdf_classified is None or len(gdf_classified) == 0:
            return None, 'Classification produced no results', 500

        if selected_classes and len(selected_classes) > 0:
            gdf_classified = gdf_classified[gdf_classified['classname'].isin(selected_classes)]
            current_app.logger.info(f"Filtered to {len(gdf_classified)} features for classes: {selected_classes}")

        if len(gdf_classified) == 0:
            return None, 'No features found for the selected classes', 404

        output_path = os.path.join(Config.LABELS_FOLDER, f'classified_{safe_name}.geojson')
        gdf_classified.to_file(output_path, driver='GeoJSON')
        current_app.logger.info(f"Classification complete: {len(gdf_classified)} features saved to {output_path}")

        geojson_data = json.loads(gdf_classified.to_json())
        return {
            'success': True,
            'features': len(gdf_classified),
            'geojson': geojson_data,
            'saved_to': output_path,
            'colors': CATEGORY_COLORS,
        }, None, None

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_classify)
            result, error_msg, status_code = future.result(timeout=300)

        if error_msg:
            return jsonify(error=error_msg), status_code
        return jsonify(**result)

    except FutureTimeout:
        current_app.logger.error("Auto-classification timed out after 300s")
        return jsonify(error='Classification timed out. Try a smaller area.'), 504
    except Exception as e:
        current_app.logger.error(f"Auto-classification error: {str(e)}", exc_info=True)
        return jsonify(error='An internal error occurred'), 500


@osm_bp.route('/api/category-colors')
def api_category_colors():
    """Get the category colors for the legend."""
    if not OSM_AUTO_LABEL_AVAILABLE:
        return jsonify(error='OSM auto-label module not available'), 500
    return jsonify(colors=CATEGORY_COLORS)
