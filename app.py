import os
import json
import logging
import datetime
import shutil
import re
import sys
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

# Store annotations
geo_coco_annotations = []

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


def load_annotations():
    """Load annotations from file."""
    global geo_coco_annotations
    if os.path.exists(ANNOTATIONS_FILE):
        try:
            with open(ANNOTATIONS_FILE, 'r') as f:
                data = json.load(f)
                geo_coco_annotations = data.get('features', [])
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
        # Create proper GeoJSON Feature
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
            for feature in data['features']:
                if 'geometry' not in feature or 'coordinates' not in feature['geometry']:
                    continue

                coordinates = feature['geometry']['coordinates'][0]
                if len(coordinates) < 3:
                    continue

                # Calculate bbox
                lons = [coord[0] for coord in coordinates]
                lats = [coord[1] for coord in coordinates]
                bbox = [[min(lons), min(lats)], [max(lons), min(lats)],
                        [max(lons), max(lats)], [min(lons), max(lats)]]

                # Get category from properties or use key_value
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
                app.logger.info(f"OSM Annotation added: {annotation['id']}")

        if added_count > 0:
            save_annotations_to_file()

        return jsonify(success=True, added=added_count)
    except Exception as e:
        app.logger.error(f"Error adding OSM annotations: {str(e)}", exc_info=True)
        return jsonify(success=False, error=str(e)), 500


@app.route('/get_annotations')
def get_annotations():
    """Get all annotations."""
    return jsonify({"type": "FeatureCollection", "features": geo_coco_annotations})


@app.route('/clear_annotations', methods=['POST'])
def clear_annotations():
    """Clear all annotations."""
    global geo_coco_annotations

    # Backup before clearing
    if geo_coco_annotations:
        backup_annotations()

    geo_coco_annotations = []
    try:
        initialize_annotations_file()
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
    query = request.args.get('q', '')
    if not query:
        return jsonify(error='No query provided'), 400

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

    try:
        # Download OSM landcover data
        if bbox:
            # Use bounding box
            north = bbox.get('north')
            south = bbox.get('south')
            east = bbox.get('east')
            west = bbox.get('west')

            if None in (north, south, east, west):
                return jsonify(error='Invalid bounding box'), 400

            app.logger.info(f"Auto-classifying landcover for bbox: N={north}, S={south}, E={east}, W={west}")
            gdf = download_by_bbox(north=north, south=south, east=east, west=west, timeout=300)
            safe_name = f"bbox_{abs(hash((north, south, east, west))) % 10000}"
        else:
            # Use place name
            app.logger.info(f"Auto-classifying landcover for: {place}")
            gdf = download_osm_landcover(place, timeout=300)
            safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', place.split(',')[0].strip().lower())

        if gdf is None or len(gdf) == 0:
            return jsonify(error='No landcover data found for this location'), 404

        app.logger.info(f"Downloaded {len(gdf)} features, starting classification...")

        # Classify using word embeddings
        classifier = OSMLandcoverClassifier()
        gdf_classified = classifier.process_geodataframe(gdf, name=None)  # Don't auto-save

        if gdf_classified is None or len(gdf_classified) == 0:
            return jsonify(error='Classification produced no results'), 500

        # Filter by selected classes if provided
        if selected_classes and len(selected_classes) > 0:
            gdf_classified = gdf_classified[gdf_classified['classname'].isin(selected_classes)]
            app.logger.info(f"Filtered to {len(gdf_classified)} features for classes: {selected_classes}")

        if len(gdf_classified) == 0:
            return jsonify(error='No features found for the selected classes'), 404

        # Save to labels folder
        output_path = os.path.join(Config.LABELS_FOLDER, f'classified_{safe_name}.geojson')
        gdf_classified.to_file(output_path, driver='GeoJSON')

        app.logger.info(f"Classification complete: {len(gdf_classified)} features saved to {output_path}")

        # Convert to GeoJSON for response
        geojson_data = json.loads(gdf_classified.to_json())

        return jsonify(
            success=True,
            features=len(gdf_classified),
            geojson=geojson_data,
            saved_to=output_path,
            colors=CATEGORY_COLORS
        )

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


if __name__ == '__main__':
    app.run(debug=Config.DEBUG, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
