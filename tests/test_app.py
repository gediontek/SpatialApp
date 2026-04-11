"""Tests for the Spatial Labeler application."""

import json
import os
import pytest
import tempfile
import shutil

# Set test environment before importing app
os.environ['FLASK_DEBUG'] = 'false'
os.environ['SECRET_KEY'] = 'test-secret-key'

from app import app
from config import Config
from state import geo_coco_annotations


@pytest.fixture
def client():
    """Create a test client."""
    # Use temporary directories for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for testing
        app.config['UPLOAD_FOLDER'] = os.path.join(temp_dir, 'uploads')
        Config.LABELS_FOLDER = os.path.join(temp_dir, 'labels')
        Config.LOG_FOLDER = os.path.join(temp_dir, 'logs')

        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        os.makedirs(Config.LABELS_FOLDER, exist_ok=True)
        os.makedirs(Config.LOG_FOLDER, exist_ok=True)

        # Clear annotations for each test
        geo_coco_annotations.clear()

        with app.test_client() as client:
            yield client


@pytest.fixture
def sample_annotation():
    """Sample annotation data."""
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-122.4, 47.6],
                [-122.4, 47.7],
                [-122.3, 47.7],
                [-122.3, 47.6],
                [-122.4, 47.6]
            ]]
        },
        "properties": {
            "category_name": "test_category",
            "color": "#ff0000"
        }
    }


class TestIndexRoute:
    """Tests for the index route."""

    def test_index_returns_200(self, client):
        """Test that index page loads successfully."""
        response = client.get('/')
        assert response.status_code == 200

    def test_index_contains_map(self, client):
        """Test that index page contains map container."""
        response = client.get('/')
        assert b'id="map"' in response.data


class TestAnnotationRoutes:
    """Tests for annotation-related routes."""

    def test_get_annotations_empty(self, client):
        """Test getting annotations when none exist."""
        response = client.get('/get_annotations')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['type'] == 'FeatureCollection'
        assert data['features'] == []

    def test_save_annotation(self, client, sample_annotation):
        """Test saving an annotation."""
        response = client.post(
            '/save_annotation',
            data=json.dumps(sample_annotation),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'id' in data

    def test_save_annotation_invalid_data(self, client):
        """Test saving annotation with invalid data."""
        response = client.post(
            '/save_annotation',
            data=json.dumps({"invalid": "data"}),
            content_type='application/json'
        )
        assert response.status_code == 400

    def test_get_annotations_after_save(self, client, sample_annotation):
        """Test getting annotations after saving one."""
        # Save an annotation
        client.post(
            '/save_annotation',
            data=json.dumps(sample_annotation),
            content_type='application/json'
        )

        # Get annotations
        response = client.get('/get_annotations')
        data = json.loads(response.data)
        assert len(data['features']) == 1
        assert data['features'][0]['properties']['category_name'] == 'test_category'

    def test_clear_annotations(self, client, sample_annotation):
        """Test clearing annotations."""
        # Save an annotation first
        client.post(
            '/save_annotation',
            data=json.dumps(sample_annotation),
            content_type='application/json'
        )

        # Clear annotations
        response = client.post('/clear_annotations')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

        # Verify annotations are cleared
        response = client.get('/get_annotations')
        data = json.loads(response.data)
        assert len(data['features']) == 0

    def test_finalize_annotations(self, client, sample_annotation):
        """Test finalizing annotations."""
        # Save an annotation
        client.post(
            '/save_annotation',
            data=json.dumps(sample_annotation),
            content_type='application/json'
        )

        # Finalize
        response = client.post('/finalize_annotations')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['count'] == 1


class TestOSMValidation:
    """Tests for OSM input validation."""

    def test_fetch_osm_missing_category_name(self, client):
        """Test OSM fetch with missing category_name."""
        response = client.post(
            '/fetch_osm_data',
            data=json.dumps({
                'bbox': '47.5,-122.5,47.7,-122.3',
                'feature_type': 'building'
            }),
            content_type='application/json'
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'Category name' in data['error']

    def test_fetch_osm_invalid_feature_type(self, client):
        """Test OSM fetch with unknown feature type."""
        response = client.post(
            '/fetch_osm_data',
            data=json.dumps({
                'bbox': '47.5,-122.5,47.7,-122.3',
                'feature_type': 'nonexistent_type',
                'category_name': 'test'
            }),
            content_type='application/json'
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'Unknown feature type' in data['error']

    def test_fetch_osm_invalid_bbox(self, client):
        """Test OSM fetch with invalid bounding box."""
        response = client.post(
            '/fetch_osm_data',
            data=json.dumps({
                'bbox': 'invalid',
                'feature_type': 'building',
                'category_name': 'test'
            }),
            content_type='application/json'
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'bounding box' in data['error'].lower()

    def test_fetch_osm_no_data(self, client):
        """Test OSM fetch with no request body."""
        response = client.post(
            '/fetch_osm_data',
            data='',
            content_type='application/json'
        )
        assert response.status_code == 400


class TestUploadValidation:
    """Tests for file upload validation."""

    def test_upload_no_file(self, client):
        """Test upload with no file."""
        response = client.post('/upload')
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'No file' in data['message']

    def test_upload_empty_filename(self, client):
        """Test upload with empty filename."""
        response = client.post(
            '/upload',
            data={'file': (b'', '')},
            content_type='multipart/form-data'
        )
        assert response.status_code == 400


class TestDisplayTable:
    """Tests for display table route."""

    def test_display_table_valid_geojson(self, client, sample_annotation):
        """Test display table with valid GeoJSON."""
        geojson = {
            "type": "FeatureCollection",
            "features": [sample_annotation]
        }
        response = client.post(
            '/display_table',
            data=json.dumps(geojson),
            content_type='application/json'
        )
        assert response.status_code == 200

    def test_display_table_empty_features(self, client):
        """Test display table with empty features."""
        geojson = {
            "type": "FeatureCollection",
            "features": []
        }
        response = client.post(
            '/display_table',
            data=json.dumps(geojson),
            content_type='application/json'
        )
        assert response.status_code == 200
        assert b'No annotations' in response.data

    def test_display_table_invalid_data(self, client):
        """Test display table with invalid data."""
        response = client.post(
            '/display_table',
            data=json.dumps({"invalid": "data"}),
            content_type='application/json'
        )
        assert response.status_code == 400


class TestExportRoutes:
    """Tests for export routes."""

    def test_export_no_annotations(self, client):
        """Test export when no annotations exist."""
        # Clear via API endpoint (also clears in-memory state)
        client.post('/clear_annotations')

        # Also clear global list directly
        geo_coco_annotations.clear()

        response = client.get('/export_annotations/geojson')
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'No annotations' in data['error']

    def test_export_invalid_format(self, client, sample_annotation):
        """Test export with invalid format."""
        # Save an annotation first
        client.post(
            '/save_annotation',
            data=json.dumps(sample_annotation),
            content_type='application/json'
        )

        response = client.get('/export_annotations/invalid')
        assert response.status_code == 400


class TestSavedAnnotationsPage:
    """Tests for saved annotations page."""

    def test_saved_annotations_page_loads(self, client):
        """Test that saved annotations page loads."""
        response = client.get('/saved_annotations')
        assert response.status_code == 200
