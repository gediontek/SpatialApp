"""Tests for the Flask app module."""

import pytest
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock
import geopandas as gpd
from shapely.geometry import Polygon

# Skip all tests if Flask is not available
pytest.importorskip("flask")

from OSM_auto_label.app import create_app, create_map_html, _get_color
from OSM_auto_label import config


class TestGetColor:
    """Tests for _get_color helper function."""

    def test_known_category(self):
        """Test color for known category."""
        color = _get_color("builtup_area")
        assert color == config.CATEGORY_COLORS["builtup_area"]

    def test_unknown_category(self):
        """Test default color for unknown category."""
        color = _get_color("unknown_category")
        assert color == config.DEFAULT_COLOR


class TestCreateMapHtml:
    """Tests for create_map_html function."""

    @pytest.fixture
    def sample_classified_gdf(self):
        """Create a sample classified GeoDataFrame."""
        polygons = [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        ]
        return gpd.GeoDataFrame({
            'landuse': ['residential'],
            'classname': ['builtup_area'],
            'geometry': polygons,
        }, crs="EPSG:4326")

    @pytest.fixture
    def sample_raw_gdf(self):
        """Create a sample raw GeoDataFrame."""
        polygons = [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        ]
        return gpd.GeoDataFrame({
            'landuse': ['residential'],
            'natural': [None],
            'geometry': polygons,
        }, crs="EPSG:4326")

    def test_empty_gdf_returns_html(self):
        """Test that None gdf returns valid HTML."""
        html = create_map_html(None)
        assert "<" in html  # Contains HTML tags
        assert "leaflet" in html.lower()

    def test_classified_gdf_returns_html(self, sample_classified_gdf):
        """Test that classified gdf returns valid HTML with legend."""
        html = create_map_html(sample_classified_gdf, title="Test")
        assert "<" in html
        assert "builtup_area" in html.lower() or "categories" in html.lower()

    def test_raw_gdf_returns_html(self, sample_raw_gdf):
        """Test that raw gdf returns valid HTML."""
        html = create_map_html(sample_raw_gdf, title="Test")
        assert "<" in html


class TestFlaskApp:
    """Tests for Flask application routes."""

    @pytest.fixture
    def app(self):
        """Create test Flask app."""
        app = create_app()
        app.config['TESTING'] = True
        return app

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return app.test_client()

    def test_index_route(self, client):
        """Test index route returns 200."""
        response = client.get('/')
        assert response.status_code == 200
        assert b'OSM Landcover Viewer' in response.data

    def test_load_route_no_path(self, client):
        """Test load route without path returns 400."""
        response = client.get('/load')
        assert response.status_code == 400
        assert b'No path provided' in response.data

    @patch('OSM_auto_label.app._get_data_dir')
    def test_load_route_path_outside_data_dir(self, mock_get_data, client, tmp_path):
        """Test load route rejects paths outside data directory."""
        mock_get_data.return_value = tmp_path / "data"

        # Try to access a file outside data directory
        response = client.get('/load?path=/etc/passwd')
        assert response.status_code == 403
        assert b'Access denied' in response.data

    @patch('OSM_auto_label.app._get_data_dir')
    def test_load_route_non_geojson_rejected(self, mock_get_data, client, tmp_path):
        """Test load route rejects non-GeoJSON files."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        mock_get_data.return_value = data_dir

        # Create a non-GeoJSON file
        txt_file = data_dir / "test.txt"
        txt_file.write_text("test content")

        response = client.get(f'/load?path={txt_file}')
        assert response.status_code == 403
        assert b'Only GeoJSON files are allowed' in response.data

    @patch('OSM_auto_label.app._get_data_dir')
    def test_load_route_file_not_found(self, mock_get_data, client, tmp_path):
        """Test load route returns 404 for non-existent file."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        mock_get_data.return_value = data_dir

        response = client.get(f'/load?path={data_dir}/nonexistent.geojson')
        assert response.status_code == 404

    @patch('OSM_auto_label.app._get_data_dir')
    @patch('geopandas.read_file')
    def test_load_route_success(self, mock_read_file, mock_get_data, client, tmp_path):
        """Test successful file loading."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        mock_get_data.return_value = data_dir

        # Create a GeoJSON file
        geojson_file = data_dir / "test.geojson"
        geojson_file.write_text('{"type": "FeatureCollection", "features": []}')

        # Mock geopandas read
        mock_gdf = gpd.GeoDataFrame({
            'landuse': ['residential'],
            'geometry': [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
        }, crs="EPSG:4326")
        mock_read_file.return_value = mock_gdf

        response = client.get(f'/load?path={geojson_file}')
        assert response.status_code == 200

    def test_api_files_route(self, client):
        """Test API files route returns JSON."""
        with patch('OSM_auto_label.app.list_raw_data') as mock_raw, \
             patch('OSM_auto_label.app.list_classified_data') as mock_classified:

            mock_raw.return_value = []
            mock_classified.return_value = []

            response = client.get('/api/files')
            assert response.status_code == 200
            assert response.content_type == 'application/json'

            data = response.get_json()
            assert 'raw' in data
            assert 'classified' in data


class TestSecurityValidation:
    """Security-focused tests for the app."""

    @pytest.fixture
    def app(self):
        """Create test Flask app."""
        app = create_app()
        app.config['TESTING'] = True
        return app

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return app.test_client()

    @patch('OSM_auto_label.app._get_data_dir')
    def test_path_traversal_attack_blocked(self, mock_get_data, client, tmp_path):
        """Test that path traversal attacks are blocked."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        mock_get_data.return_value = data_dir

        # Attempt path traversal
        attacks = [
            '../../../etc/passwd',
            '..%2F..%2F..%2Fetc%2Fpasswd',
            '/etc/passwd',
            'data/../../../etc/passwd',
        ]

        for attack in attacks:
            response = client.get(f'/load?path={attack}')
            assert response.status_code in [403, 404], f"Attack not blocked: {attack}"

    @patch('OSM_auto_label.app._get_data_dir')
    def test_symlink_attack_blocked(self, mock_get_data, client, tmp_path):
        """Test that symlink attacks are blocked (if symlink outside data dir)."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        mock_get_data.return_value = data_dir

        # Create a symlink pointing outside data directory
        try:
            symlink = data_dir / "malicious.geojson"
            symlink.symlink_to("/etc/passwd")

            response = client.get(f'/load?path={symlink}')
            # Should either be blocked (403) or not found (404)
            # The resolve() in our code should catch this
            assert response.status_code in [403, 404, 500]
        except OSError:
            # Skip if symlinks not supported
            pytest.skip("Symlinks not supported on this platform")
