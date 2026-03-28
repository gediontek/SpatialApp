import os
import json
import logging
import datetime
import shutil
import re
import sys
import threading
import urllib.request
import urllib.parse

from flask import Flask, render_template, jsonify, request, send_from_directory, send_file
from flask_wtf.csrf import CSRFProtect
import rasterio
from pyproj import Transformer
import geopandas as gpd
from shapely.geometry import shape
import requests
from werkzeug.utils import secure_filename

from config import Config

# Add OSM_auto_label to path and import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from OSM_auto_label import download_osm_landcover, OSMLandcoverClassifier
    from OSM_auto_label.downloader import download_by_bbox
    from OSM_auto_label.config import CATEGORY_COLORS
    OSM_AUTO_LABEL_AVAILABLE = True
except ImportError as e:
    OSM_AUTO_LABEL_AVAILABLE = False
    logging.warning(f"OSM_auto_label not available: {e}")

app = Flask(__name__)
app.config.from_object(Config)
app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER

# Validate critical config (fails startup if SECRET_KEY not set in production)
try:
    Config.validate()
except RuntimeError as e:
    logging.warning(f"Config warning: {e}")

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Paths
ANNOTATIONS_FILE = os.path.join(Config.LABELS_FOLDER, 'annotations.geojson')

# Ensure directories exist
os.makedirs(Config.LABELS_FOLDER, exist_ok=True)
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(Config.LOG_FOLDER, exist_ok=True)

# Configure logging
logging.basicConfig(
    filename=os.path.join(Config.LOG_FOLDER, 'app.log'),
    level=logging.DEBUG if Config.DEBUG else logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
)

# Store annotations (thread-safe access via annotation_lock)
geo_coco_annotations = []
annotation_lock = threading.Lock()

# Initialize database (Phase 5)
db = None
try:
    import services.database as db_module
    db_module.init_db()
    if db_module.verify_db_integrity():
        db = db_module
        # Clean up old metrics on startup
        try:
            db_module.cleanup_old_metrics(days=180)
        except Exception:
            pass
    else:
        logging.error("Database integrity check failed — running without DB persistence")
except Exception as e:
    logging.warning(f"Database init skipped: {e}")

# Input validation patterns
VALID_OSM_KEY_PATTERN = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_:]*$')
VALID_OSM_VALUE_PATTERN = re.compile(r'^[a-zA-Z0-9_\-\s\*]+$')
ALLOWED_EXTENSIONS = {'tif', 'tiff'}

# Special value to fetch ALL features with a key (regardless of value)
OSM_WILDCARD_VALUES = {'*', 'any', 'all', ''}


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def validate_osm_input(key, value):
    """Validate OSM query inputs to prevent injection."""
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
        if south > north or west > east:
            return False, None
        return True, bbox_str
    except (ValueError, AttributeError):
        return False, None


MAX_ANNOTATIONS_STARTUP = 10000  # Cap in-memory annotations on startup


def load_annotations():
    """Load annotations from database (primary) or JSON file (fallback).

    Caps in-memory annotations to MAX_ANNOTATIONS_STARTUP to prevent
    unbounded memory usage on startup with large datasets.
    """
    global geo_coco_annotations

    # Try database first
    if db:
        try:
            total = db.get_annotation_count()
            features = db.get_all_annotations(limit=MAX_ANNOTATIONS_STARTUP)
            if features:
                geo_coco_annotations = features
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
                geo_coco_annotations = data.get('features', [])

            # Migrate file annotations into database if DB available and empty
            if db and geo_coco_annotations:
                try:
                    if db.get_annotation_count() == 0:
                        for feat in geo_coco_annotations:
                            props = feat.get('properties', {})
                            db.save_annotation(
                                category_name=props.get('category_name', 'unknown'),
                                geometry=feat.get('geometry', {}),
                                color=props.get('color', '#3388ff'),
                                source=props.get('source', 'manual'),
                                properties=props,
                            )
                        logging.info(f"Migrated {len(geo_coco_annotations)} annotations from file to database")
                except Exception as mig_err:
                    logging.warning(f"Annotation migration to DB failed: {mig_err}")
        except json.JSONDecodeError:
            app.logger.warning("annotations.geojson is empty or malformed. Initializing with an empty FeatureCollection.")
            geo_coco_annotations = []
            initialize_annotations_file()
    else:
        geo_coco_annotations = []
        initialize_annotations_file()


def initialize_annotations_file():
    """Initialize the annotations.geojson with an empty FeatureCollection."""
    try:
        with open(ANNOTATIONS_FILE, 'w') as f:
            json.dump({"type": "FeatureCollection", "features": []}, f, indent=2)
        app.logger.info("Initialized annotations.geojson with an empty FeatureCollection.")
    except Exception as e:
        app.logger.error(f"Error initializing annotations.geojson: {str(e)}", exc_info=True)


def backup_annotations():
    """Create a timestamped backup of the annotations.geojson file."""
    if os.path.exists(ANNOTATIONS_FILE):
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        backup_file = f"annotations_backup_{timestamp}.geojson"
        backup_path = os.path.join(Config.LABELS_FOLDER, backup_file)
        shutil.copy(ANNOTATIONS_FILE, backup_path)
        app.logger.info(f"Backup created: {backup_file}")

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
            app.logger.info(f"Removed old backup: {old_backup}")
    except Exception as e:
        app.logger.warning(f"Error cleaning up backups: {str(e)}")


def save_annotations_to_file():
    """Save current annotations to file."""
    geo_coco_format = {
        "type": "FeatureCollection",
        "features": geo_coco_annotations
    }
    with open(ANNOTATIONS_FILE, 'w') as f:
        json.dump(geo_coco_format, f, indent=2)


load_annotations()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify(message='No file part in the request.'), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify(message='No file selected for uploading.'), 400

    if not allowed_file(file.filename):
        return jsonify(message='Invalid file type. Only .tif and .tiff files are allowed.'), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    try:
        file.save(filepath)
        app.logger.info(f"Uploaded file saved to {filepath}.")
        return render_overlay(filepath)
    except Exception as e:
        app.logger.error(f"Error saving uploaded file: {str(e)}", exc_info=True)
        return jsonify(message='Error saving the uploaded file.'), 500


def render_overlay(image_path):
    """Process raster file and return overlay information."""
    try:
        with rasterio.open(image_path) as src:
            bounds = src.bounds
            transformer = Transformer.from_crs(src.crs, 'epsg:4326', always_xy=True)

            min_lon, min_lat = transformer.transform(bounds.left, bounds.bottom)
            max_lon, max_lat = transformer.transform(bounds.right, bounds.top)

            image_bounds = [[min_lat, min_lon], [max_lat, max_lon]]
            center_lat = (min_lat + max_lat) / 2
            center_lon = (min_lon + max_lon) / 2

        image_url = image_path.replace('\\', '/')
        return jsonify(
            image_url=image_url,
            image_bounds=image_bounds,
            center_lat=center_lat,
            center_lon=center_lon
        )
    except Exception as e:
        app.logger.error(f"Error rendering overlay: {str(e)}", exc_info=True)
        return jsonify(message='Error processing the raster file.'), 500


@app.route('/saved_annotations')
def saved_annotations():
    return render_template('saved_annotations.html')


@app.route('/save_annotation', methods=['POST'])
def save_annotation():
    """Save a single annotation."""
    global geo_coco_annotations
    data = request.json

    if not data or 'geometry' not in data:
        return jsonify(success=False, error='Invalid annotation data'), 400

    try:
        with annotation_lock:
            annotation = {
                "type": "Feature",
                "id": len(geo_coco_annotations) + 1,
                "properties": {
                    "category_name": data.get('properties', {}).get('category_name', 'unknown'),
                    "color": data.get('properties', {}).get('color', '#3388ff'),
                    "bbox": data.get('properties', {}).get('bbox', []),
                    "created_at": datetime.datetime.now().isoformat()
                },
                "geometry": data['geometry']
            }
            geo_coco_annotations.append(annotation)
            save_annotations_to_file()

            # Persist to database
            if db:
                try:
                    db.save_annotation(
                        category_name=annotation['properties']['category_name'],
                        geometry=data['geometry'],
                        color=annotation['properties']['color'],
                        source='manual',
                        properties=annotation['properties'],
                    )
                except Exception as db_err:
                    app.logger.warning(f"DB save failed (annotation): {db_err}")

        app.logger.info(f"Annotation saved: {annotation['id']}")
        return jsonify(success=True, id=annotation['id'])
    except Exception as e:
        app.logger.error(f"Error saving annotation: {str(e)}", exc_info=True)
        return jsonify(success=False, error=str(e)), 500


@app.route('/add_osm_annotations', methods=['POST'])
def add_osm_annotations():
    """Add OSM features as annotations."""
    global geo_coco_annotations
    data = request.json

    if not data:
        return jsonify(success=False, error='No data provided'), 400

    app.logger.debug(f"Received OSM data with {len(data.get('features', []))} features")

    try:
        added_count = 0
        if 'features' in data:
            with annotation_lock:
                for feature in data['features']:
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

                    annotation = {
                        "type": "Feature",
                        "id": len(geo_coco_annotations) + 1,
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

                    geo_coco_annotations.append(annotation)
                    added_count += 1

        if added_count > 0:
            save_annotations_to_file()

            # Persist to database
            if db:
                try:
                    for feature in data.get('features', [])[:added_count]:
                        geom = feature.get('geometry')
                        cat = feature.get('properties', {}).get('category_name', 'osm_feature')
                        if geom:
                            db.save_annotation(cat, geom, '#3388ff', 'osm')
                except Exception as db_err:
                    app.logger.warning(f"DB save failed (osm annotations): {db_err}")

        return jsonify(success=True, added=added_count)
    except Exception as e:
        app.logger.error(f"Error adding OSM annotations: {str(e)}", exc_info=True)
        return jsonify(success=False, error=str(e)), 500


@app.route('/get_annotations')
def get_annotations():
    """Get all annotations."""
    with annotation_lock:
        features = list(geo_coco_annotations)
    return jsonify({"type": "FeatureCollection", "features": features})


@app.route('/clear_annotations', methods=['POST'])
def clear_annotations():
    """Clear all annotations."""
    global geo_coco_annotations

    try:
        with annotation_lock:
            if geo_coco_annotations:
                backup_annotations()
            geo_coco_annotations = []
            initialize_annotations_file()

            # Clear database
            if db:
                try:
                    db.clear_annotations()
                except Exception as db_err:
                    app.logger.warning(f"DB clear failed: {db_err}")

        app.logger.info("All annotations cleared.")
        return jsonify(success=True)
    except Exception as e:
        app.logger.error(f"Error clearing annotations: {str(e)}", exc_info=True)
        return jsonify(success=False, error=str(e)), 500


# Mapping of user-friendly feature types to OSM query parameters
OSM_FEATURE_MAPPINGS = {
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
}


@app.route('/fetch_osm_data', methods=['POST'])
def fetch_osm_data():
    """Fetch data from OpenStreetMap via Overpass API."""
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
            out body;
            >;
            out skel qt;
            """
        else:
            # Fetch only features with specific key=value
            overpass_query = f"""
            [out:json][timeout:30];
            (
              way["{key}"="{value}"]({sanitized_bbox});
              relation["{key}"="{value}"]({sanitized_bbox});
            );
            out body;
            >;
            out skel qt;
            """

        app.logger.debug(f"Overpass query for feature_type={feature_type}, key={key}, value={value}")

        # Rate limit before making the actual external request
        from services.rate_limiter import overpass_limiter
        overpass_limiter.wait()

        response = requests.get(
            overpass_url,
            params={'data': overpass_query},
            timeout=Config.OSM_REQUEST_TIMEOUT
        )
        response.raise_for_status()
        osm_data = response.json()

        geojson_data = {
            "type": "FeatureCollection",
            "features": []
        }

        if 'elements' in osm_data:
            nodes = {
                node['id']: (node['lon'], node['lat'])
                for node in osm_data['elements']
                if node['type'] == 'node'
            }

            for element in osm_data['elements']:
                if element['type'] == 'way':
                    coords = [nodes[node_id] for node_id in element.get('nodes', []) if node_id in nodes]
                    if len(coords) < 3:
                        continue

                    # Ensure polygon is closed
                    if coords[0] != coords[-1]:
                        coords.append(coords[0])

                    # Calculate bbox
                    lons = [c[0] for c in coords]
                    lats = [c[1] for c in coords]
                    bbox_feature = [[min(lons), min(lats)], [max(lons), min(lats)],
                                    [max(lons), max(lats)], [min(lons), max(lats)]]

                    osm_tags = element.get('tags', {})

                    geojson_data['features'].append({
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [coords]
                        },
                        "properties": {
                            "category_name": category_name,  # Use user-specified category name
                            "feature_type": feature_type,  # Store the OSM feature type
                            "osm_id": element.get('id'),
                            "osm_tags": osm_tags,
                            "bbox": bbox_feature
                        }
                    })
        else:
            app.logger.warning("No OSM data found for the given parameters.")

        app.logger.info(f"Fetched {len(geojson_data['features'])} {feature_type} features with category '{category_name}'")
        return jsonify(geojson_data)
    except requests.Timeout:
        app.logger.error("OSM request timed out")
        return jsonify(success=False, error='Request timed out. Try a smaller area.'), 504
    except requests.RequestException as e:
        app.logger.error(f"Error fetching OSM data: {str(e)}", exc_info=True)
        return jsonify(success=False, error='Error connecting to OSM service'), 502
    except Exception as e:
        app.logger.error(f"Error fetching OSM data: {str(e)}", exc_info=True)
        return jsonify(success=False, error=str(e)), 500


@app.route('/display_table', methods=['POST'])
def display_table():
    """Convert GeoJSON to HTML table with essential columns only."""
    try:
        geojson_data = request.json
        if not geojson_data or 'features' not in geojson_data:
            return jsonify(message='Invalid GeoJSON data'), 400

        if not geojson_data['features']:
            return '<p>No annotations to display.</p>'

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
        return df.to_html(classes='table', index=False, escape=False)
    except Exception as e:
        app.logger.error(f"Error displaying table: {str(e)}", exc_info=True)
        return jsonify(message=str(e)), 500


@app.route('/finalize_annotations', methods=['POST'])
def finalize_annotations():
    """Finalize and save annotations with backup."""
    global geo_coco_annotations
    try:
        backup_annotations()
        save_annotations_to_file()
        app.logger.info("Annotations finalized and saved.")
        return jsonify(success=True, count=len(geo_coco_annotations))
    except Exception as e:
        app.logger.error(f"Error finalizing annotations: {str(e)}", exc_info=True)
        return jsonify(success=False, error=str(e)), 500


@app.route('/export_annotations/<format_type>')
def export_annotations(format_type):
    """Export annotations in different formats."""
    global geo_coco_annotations

    if not geo_coco_annotations:
        return jsonify(error='No annotations to export'), 400

    valid_formats = ['geojson', 'shapefile', 'geopackage']
    if format_type not in valid_formats:
        return jsonify(error=f'Invalid format. Choose from: {", ".join(valid_formats)}'), 400

    try:
        # Create GeoDataFrame from annotations
        gdf = gpd.GeoDataFrame.from_features(geo_coco_annotations)
        gdf.set_crs(epsg=4326, inplace=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")

        if format_type == 'geojson':
            output_path = os.path.join(Config.LABELS_FOLDER, f'export_{timestamp}.geojson')
            gdf.to_file(output_path, driver='GeoJSON')
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

            return send_file(zip_path, as_attachment=True, download_name=f'annotations_{timestamp}.zip')

        elif format_type == 'geopackage':
            output_path = os.path.join(Config.LABELS_FOLDER, f'annotations_{timestamp}.gpkg')
            gdf.to_file(output_path, driver='GPKG')
            return send_file(output_path, as_attachment=True, download_name=f'annotations_{timestamp}.gpkg')

    except Exception as e:
        app.logger.error(f"Error exporting annotations: {str(e)}", exc_info=True)
        return jsonify(error=f'Export failed: {str(e)}'), 500


@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ============================================================
# Auto Classification Routes (OSM_auto_label integration)
# ============================================================

@app.route('/api/geocode')
def api_geocode():
    """Geocode a place name using Nominatim."""
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
        app.logger.error(f"Geocoding error: {str(e)}")
        return jsonify(error=str(e)), 500


@app.route('/api/auto-classify', methods=['POST'])
@csrf.exempt  # Exempt from CSRF for API calls
def api_auto_classify():
    """Download OSM data and classify landcover."""
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

            app.logger.info(f"Auto-classifying landcover for bbox: N={north}, S={south}, E={east}, W={west}")
            gdf = download_by_bbox(north=north, south=south, east=east, west=west, timeout=300)
            safe_name = f"bbox_{abs(hash((north, south, east, west))) % 10000}"
        else:
            app.logger.info(f"Auto-classifying landcover for: {place}")
            gdf = download_osm_landcover(place, timeout=300)
            safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', place.split(',')[0].strip().lower())

        if gdf is None or len(gdf) == 0:
            return None, 'No landcover data found for this location', 404

        app.logger.info(f"Downloaded {len(gdf)} features, starting classification...")

        classifier = OSMLandcoverClassifier()
        gdf_classified = classifier.process_geodataframe(gdf, name=None)

        if gdf_classified is None or len(gdf_classified) == 0:
            return None, 'Classification produced no results', 500

        if selected_classes and len(selected_classes) > 0:
            gdf_classified = gdf_classified[gdf_classified['classname'].isin(selected_classes)]
            app.logger.info(f"Filtered to {len(gdf_classified)} features for classes: {selected_classes}")

        if len(gdf_classified) == 0:
            return None, 'No features found for the selected classes', 404

        output_path = os.path.join(Config.LABELS_FOLDER, f'classified_{safe_name}.geojson')
        gdf_classified.to_file(output_path, driver='GeoJSON')
        app.logger.info(f"Classification complete: {len(gdf_classified)} features saved to {output_path}")

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
        app.logger.error("Auto-classification timed out after 300s")
        return jsonify(error='Classification timed out. Try a smaller area.'), 504
    except Exception as e:
        app.logger.error(f"Auto-classification error: {str(e)}", exc_info=True)
        return jsonify(error=str(e)), 500


@app.route('/api/category-colors')
def api_category_colors():
    """Get the category colors for the legend."""
    if not OSM_AUTO_LABEL_AVAILABLE:
        return jsonify(error='OSM auto-label module not available'), 500
    return jsonify(colors=CATEGORY_COLORS)


@app.errorhandler(413)
def too_large(e):
    """Handle file too large error."""
    return jsonify(message='File is too large. Maximum size is 50MB.'), 413


@app.errorhandler(500)
def internal_error(e):
    """Handle internal server error."""
    app.logger.error(f"Internal server error: {str(e)}")
    return jsonify(message='An internal error occurred.'), 500


# ============================================================
# NL-to-GIS Chat API
# ============================================================

def require_api_token(f):
    """Decorator: enforce bearer token auth. Resolves user_id onto flask.g.

    Supports two modes:
    - Single shared token (CHAT_API_TOKEN env var) → user_id = 'anonymous'
    - Per-user tokens (stored in users table) → user_id from DB lookup
    - No token configured → open access, user_id = 'anonymous'
    """
    from functools import wraps
    from flask import g

    @wraps(f)
    def decorated(*args, **kwargs):
        g.user_id = 'anonymous'

        auth = request.headers.get('Authorization', '')
        token = auth[7:] if auth.startswith('Bearer ') else ''

        if token:
            # Try per-user token lookup first
            if db:
                user = db.get_user_by_token(token)
                if user:
                    g.user_id = user['user_id']
                    return f(*args, **kwargs)

            # Fall back to shared token check
            if Config.CHAT_API_TOKEN and token == Config.CHAT_API_TOKEN:
                return f(*args, **kwargs)

            # Token provided but invalid
            return jsonify(error='Unauthorized'), 401

        elif Config.CHAT_API_TOKEN:
            # Token required but not provided
            return jsonify(error='Unauthorized'), 401

        # No token required — open access
        return f(*args, **kwargs)
    return decorated

@app.route('/api/register', methods=['POST'])
@csrf.exempt
def api_register():
    """Register a new user. Returns user_id and API token."""
    if not db:
        return jsonify(error='Database not available'), 500

    data = request.get_json(silent=True)
    if not data or not data.get('username'):
        return jsonify(error='username is required'), 400

    username = data['username'].strip()
    if not username or len(username) > 100:
        return jsonify(error='Invalid username'), 400

    try:
        user = db.create_user(username)
        return jsonify(success=True, **user), 201
    except Exception as e:
        if 'UNIQUE' in str(e):
            return jsonify(error='Username or token already exists'), 409
        app.logger.error(f"Registration error: {e}")
        return jsonify(error='Registration failed'), 500


@app.route('/api/me')
@require_api_token
def api_me():
    """Get current user info."""
    from flask import g
    user_id = getattr(g, 'user_id', 'anonymous')
    if user_id == 'anonymous':
        return jsonify(user_id='anonymous', username='anonymous')
    if db:
        user = db.get_user_by_id(user_id)
        if user:
            return jsonify(user_id=user['user_id'], username=user['username'], created_at=user['created_at'])
    return jsonify(user_id=user_id, username='unknown')


@app.route('/api/import', methods=['POST'])
@csrf.exempt
@require_api_token
def api_import_layer():
    """Import a vector file (GeoJSON, Shapefile zip, GeoPackage) as a named layer."""
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

            # For shapefile zips, extract first
            if ext == 'zip':
                import zipfile
                with zipfile.ZipFile(filepath, 'r') as zf:
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

            with layer_lock:
                layer_store[layer_name] = geojson_data
                _evict_layers_if_needed()

            if db:
                try:
                    from flask import g
                    uid = getattr(g, 'user_id', 'anonymous')
                    db.save_layer(layer_name, geojson_data, user_id=uid)
                except Exception as db_err:
                    app.logger.warning(f"DB save failed (import): {db_err}")

            return jsonify(
                success=True,
                layer_name=layer_name,
                feature_count=len(geojson_data.get('features', [])),
                geojson=geojson_data,
            )
    except Exception as e:
        app.logger.error(f"Import error: {e}", exc_info=True)
        return jsonify(error=f'Import failed: {str(e)}'), 500


# Server-side layer store for cross-tool references (thread-safe via layer_lock)
# Uses OrderedDict for LRU eviction when max layers exceeded
from collections import OrderedDict
layer_store = OrderedDict()
layer_lock = threading.Lock()
MAX_LAYERS_IN_MEMORY = 100


def _evict_layers_if_needed():
    """Remove oldest layers when store exceeds limit. Call under layer_lock."""
    while len(layer_store) > MAX_LAYERS_IN_MEMORY:
        evicted_name, _ = layer_store.popitem(last=False)
        logging.info(f"Evicted layer '{evicted_name}' from memory (limit: {MAX_LAYERS_IN_MEMORY})")

# Restore layers from database on startup
if db:
    try:
        for layer_meta in db.get_all_layers():
            geojson = db.get_layer(layer_meta['name'])
            if geojson:
                layer_store[layer_meta['name']] = geojson
        if layer_store:
            logging.info(f"Restored {len(layer_store)} layers from database")
    except Exception as e:
        logging.warning(f"Layer restore from DB failed: {e}")

# In-memory chat sessions (keyed by session_id)
chat_sessions = {}  # {session_id: {"session": ChatSession, "last_access": float}}
session_lock = threading.Lock()
SESSION_TTL_SECONDS = 3600  # Evict sessions idle for 1 hour


def _cleanup_expired_sessions():
    """Remove sessions not accessed within TTL. Acquires session_lock internally."""
    import time as _t
    with session_lock:
        now = _t.time()
        expired = [sid for sid, entry in chat_sessions.items()
                   if now - entry.get("last_access", 0) > SESSION_TTL_SECONDS]
        for sid in expired:
            entry = chat_sessions.pop(sid)
            if db:
                try:
                    db.save_chat_session(sid, entry["session"].messages)
                except Exception:
                    pass
        if expired:
            logging.info(f"Evicted {len(expired)} expired chat sessions")


def _start_session_cleanup_timer():
    """Run session cleanup every 5 minutes in a background thread."""
    def _loop():
        while True:
            import time as _t
            _t.sleep(300)  # Every 5 minutes
            try:
                _cleanup_expired_sessions()
            except Exception:
                pass

    t = threading.Thread(target=_loop, daemon=True, name="session-cleanup")
    t.start()


_start_session_cleanup_timer()


def _get_chat_session(session_id: str = "default"):
    """Get or create a chat session (thread-safe).

    Restores message history from database if available.
    """
    import time as _t
    from nl_gis.chat import ChatSession
    with session_lock:

        if session_id in chat_sessions:
            chat_sessions[session_id]["last_access"] = _t.time()
            return chat_sessions[session_id]["session"]

        session = ChatSession(layer_store=layer_store)
        # Restore message history from database
        if db:
            try:
                saved = db.get_chat_session(session_id)
                if saved:
                    session.messages = saved
            except Exception as db_err:
                app.logger.warning(f"DB restore failed (session): {db_err}")
        chat_sessions[session_id] = {"session": session, "last_access": _t.time()}
        return session


def _persist_chat_session(session_id: str, session):
    """Persist chat session messages to database."""
    if db:
        try:
            db.save_chat_session(session_id, session.messages)
        except Exception as db_err:
            app.logger.warning(f"DB save failed (session): {db_err}")


@app.route('/api/chat', methods=['POST'])
@csrf.exempt
@require_api_token
def api_chat():
    """Process a natural language message and return SSE event stream."""
    from flask import g
    import time as _time

    data = request.get_json(silent=True)
    if not data or 'message' not in data:
        return jsonify(error='No message provided'), 400

    message = data['message'].strip()
    if not message:
        return jsonify(error='Empty message'), 400

    session_id = data.get('session_id', 'default')
    map_context = data.get('context', {})
    user_id = getattr(g, 'user_id', 'anonymous')

    session = _get_chat_session(session_id)

    def generate():
        start_time = _time.time()
        tool_count = 0
        had_error = False
        try:
            for event in session.process_message(message, map_context):
                event_type = event.get('type', 'message')

                if event_type == 'tool_result':
                    tool_count += 1
                if event_type == 'error':
                    had_error = True

                # Store layer in server-side store (with lock)
                if event_type == 'layer_add':
                    layer_name = event.get('name')
                    geojson = event.get('geojson')
                    if layer_name and geojson:
                        with layer_lock:
                            layer_store[layer_name] = geojson
                            _evict_layers_if_needed()
                        # Persist to database
                        if db:
                            try:
                                db.save_layer(layer_name, geojson, event.get('style'), user_id=user_id)
                            except Exception as db_err:
                                app.logger.warning(f"DB save failed (layer): {db_err}")

                yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"

            # Persist chat session after stream completes
            _persist_chat_session(session_id, session)

            # Log query metrics
            if db:
                try:
                    duration_ms = int((_time.time() - start_time) * 1000)
                    db.log_query_metric(
                        user_id=user_id,
                        session_id=session_id,
                        message=message,
                        tool_calls=tool_count,
                        input_tokens=session.usage.get("total_input_tokens", 0),
                        output_tokens=session.usage.get("total_output_tokens", 0),
                        duration_ms=duration_ms,
                        error=had_error,
                    )
                except Exception:
                    pass
        except Exception as e:
            app.logger.error(f"SSE stream error: {e}", exc_info=True)
            error_event = {"type": "error", "text": f"Stream error: {str(e)}"}
            yield f"event: error\ndata: {json.dumps(error_event)}\n\n"

    return app.response_class(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        }
    )


@app.route('/api/layers')
@require_api_token
def api_get_layers():
    """Get list of named layers."""
    with layer_lock:
        layers = []
        for name, geojson in layer_store.items():
            feature_count = len(geojson.get('features', [])) if isinstance(geojson, dict) else 0
            layers.append({
                'name': name,
                'feature_count': feature_count,
            })
    return jsonify(layers=layers)


@app.route('/api/layers/<layer_name>', methods=['DELETE'])
@csrf.exempt
@require_api_token
def api_delete_layer(layer_name):
    """Delete a named layer."""
    with layer_lock:
        if layer_name in layer_store:
            del layer_store[layer_name]
            # Remove from database
            if db:
                try:
                    db.delete_layer(layer_name)
                except Exception as db_err:
                    app.logger.warning(f"DB delete failed (layer): {db_err}")
            return jsonify(success=True)
    return jsonify(error='Layer not found'), 404


@app.route('/api/usage')
@require_api_token
def api_usage():
    """Get token usage stats for a chat session."""
    session_id = request.args.get('session_id', 'default')
    with session_lock:
        entry = chat_sessions.get(session_id)
    if not entry:
        return jsonify(usage={"total_input_tokens": 0, "total_output_tokens": 0, "api_calls": 0})
    return jsonify(usage=entry["session"].usage)


@app.route('/api/metrics')
@require_api_token
def api_metrics():
    """Get aggregated query metrics.

    Returns total queries, tool calls, tokens, avg duration, error rate.
    Filters by current user if authenticated with per-user token.
    """
    from flask import g
    if not db:
        return jsonify(error='Database not available'), 500

    user_id = getattr(g, 'user_id', 'anonymous')

    # If anonymous or shared token, show all metrics; otherwise per-user
    filter_user = user_id if user_id != 'anonymous' else None
    summary = db.get_metrics_summary(user_id=filter_user)
    summary['user_id'] = user_id
    return jsonify(metrics=summary)


@app.route('/api/health')
def api_health():
    """Health check endpoint. Returns status of all subsystems."""
    import shutil

    health = {"status": "ok", "checks": {}}

    # Database check
    if db:
        try:
            count = db.get_annotation_count()
            health["checks"]["database"] = {"status": "ok", "annotation_count": count}
        except Exception as e:
            health["checks"]["database"] = {"status": "error", "detail": str(e)}
            health["status"] = "degraded"
    else:
        health["checks"]["database"] = {"status": "unavailable"}
        health["status"] = "degraded"

    # Disk space check
    try:
        usage = shutil.disk_usage(os.path.dirname(os.path.abspath(__file__)))
        free_mb = usage.free / (1024 * 1024)
        health["checks"]["disk"] = {"status": "ok" if free_mb > 100 else "warning", "free_mb": round(free_mb)}
    except Exception:
        health["checks"]["disk"] = {"status": "unknown"}

    # Claude API check
    health["checks"]["claude_api"] = {
        "status": "configured" if Config.ANTHROPIC_API_KEY else "not_configured"
    }

    # Layer store
    with layer_lock:
        layer_count = len(layer_store)
    health["checks"]["layers"] = {"count": layer_count, "max": MAX_LAYERS_IN_MEMORY}

    # Sessions
    with session_lock:
        session_count = len(chat_sessions)
    health["checks"]["sessions"] = {"count": session_count}

    return jsonify(health)


if __name__ == '__main__':
    app.run(debug=Config.DEBUG, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
