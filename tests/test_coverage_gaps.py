"""Tests for coverage gaps: untested routes, handlers, and edge cases."""

import json
import math
import os
import pytest
import tempfile
from unittest.mock import patch, MagicMock

# Set test environment before importing app
os.environ['FLASK_DEBUG'] = 'false'
os.environ['SECRET_KEY'] = 'test-secret-key'
os.environ['CHAT_API_TOKEN'] = ''  # Open access by default

from app import app
from config import Config
from state import geo_coco_annotations
from nl_gis.handlers import dispatch_tool
from nl_gis.geo_utils import ValidatedPoint


@pytest.fixture
def client():
    """Create a test client."""
    with tempfile.TemporaryDirectory() as temp_dir:
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['UPLOAD_FOLDER'] = os.path.join(temp_dir, 'uploads')
        Config.LABELS_FOLDER = os.path.join(temp_dir, 'labels')
        Config.LOG_FOLDER = os.path.join(temp_dir, 'logs')

        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        os.makedirs(Config.LABELS_FOLDER, exist_ok=True)
        os.makedirs(Config.LOG_FOLDER, exist_ok=True)

        geo_coco_annotations.clear()

        with app.test_client() as client:
            yield client


@pytest.fixture
def auth_client():
    """Create a test client with API token auth enabled."""
    with tempfile.TemporaryDirectory() as temp_dir:
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['UPLOAD_FOLDER'] = os.path.join(temp_dir, 'uploads')
        Config.LABELS_FOLDER = os.path.join(temp_dir, 'labels')
        Config.LOG_FOLDER = os.path.join(temp_dir, 'logs')

        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        os.makedirs(Config.LABELS_FOLDER, exist_ok=True)
        os.makedirs(Config.LOG_FOLDER, exist_ok=True)

        geo_coco_annotations.clear()

        original_token = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = 'test-secret-token'
        try:
            with app.test_client() as client:
                yield client
        finally:
            Config.CHAT_API_TOKEN = original_token


@pytest.fixture
def sample_polygon_feature():
    """A valid polygon feature for OSM annotation tests."""
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
            "category_name": "building"
        }
    }


# ---------------------------------------------------------------------------
# 1. Untested routes
# ---------------------------------------------------------------------------

class TestAddOsmAnnotationsRoute:
    """Tests for POST /add_osm_annotations."""

    def test_valid_features(self, client, sample_polygon_feature):
        """Adding valid polygon features returns success with count."""
        data = {"features": [sample_polygon_feature]}
        response = client.post(
            '/add_osm_annotations',
            data=json.dumps(data),
            content_type='application/json'
        )
        assert response.status_code == 200
        body = json.loads(response.data)
        assert body['success'] is True
        assert body['added'] == 1

    def test_empty_features(self, client):
        """Empty features list returns success with zero added."""
        response = client.post(
            '/add_osm_annotations',
            data=json.dumps({"features": []}),
            content_type='application/json'
        )
        assert response.status_code == 200
        body = json.loads(response.data)
        assert body['success'] is True
        assert body['added'] == 0

    def test_no_data(self, client):
        """No request body returns 400."""
        response = client.post(
            '/add_osm_annotations',
            data='',
            content_type='application/json'
        )
        assert response.status_code == 400

    def test_skips_non_polygon(self, client):
        """Point features are silently skipped."""
        data = {
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-122.3, 47.6]},
                "properties": {"category_name": "poi"}
            }]
        }
        response = client.post(
            '/add_osm_annotations',
            data=json.dumps(data),
            content_type='application/json'
        )
        assert response.status_code == 200
        body = json.loads(response.data)
        assert body['added'] == 0


class TestApiRegisterRoute:
    """Tests for POST /api/register."""

    @patch('state.db')
    def test_successful_registration(self, mock_db, client):
        """Valid username returns 201 with user data."""
        mock_db.create_user.return_value = {
            'user_id': 'u123',
            'username': 'testuser',
            'token': 'tok_abc'
        }
        response = client.post(
            '/api/register',
            data=json.dumps({"username": "testuser"}),
            content_type='application/json'
        )
        assert response.status_code == 201
        body = json.loads(response.data)
        assert body['success'] is True
        assert body['username'] == 'testuser'

    @patch('state.db')
    def test_duplicate_username(self, mock_db, client):
        """Duplicate username returns 409."""
        mock_db.create_user.side_effect = Exception('UNIQUE constraint failed')
        response = client.post(
            '/api/register',
            data=json.dumps({"username": "taken"}),
            content_type='application/json'
        )
        assert response.status_code == 409
        body = json.loads(response.data)
        assert 'already exists' in body['error']

    def test_missing_username(self, client):
        """Missing username returns 400."""
        response = client.post(
            '/api/register',
            data=json.dumps({}),
            content_type='application/json'
        )
        assert response.status_code == 400


class TestApiImportRoute:
    """Tests for POST /api/import."""

    def test_geojson_import(self, client):
        """Importing a valid GeoJSON file succeeds."""
        geojson_content = json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-122.3, 47.6]
                },
                "properties": {"name": "test"}
            }]
        })
        import io
        data = {
            'file': (io.BytesIO(geojson_content.encode()), 'test.geojson'),
            'layer_name': 'test_layer'
        }
        response = client.post(
            '/api/import',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 200
        body = json.loads(response.data)
        assert body.get('success') is True or body.get('layer_name') is not None

    def test_invalid_format(self, client):
        """Unsupported file extension returns 400."""
        import io
        data = {
            'file': (io.BytesIO(b'not a geo file'), 'test.csv'),
        }
        response = client.post(
            '/api/import',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 400
        body = json.loads(response.data)
        assert 'Supported formats' in body['error']

    def test_no_file(self, client):
        """Missing file returns 400."""
        response = client.post(
            '/api/import',
            data={},
            content_type='multipart/form-data'
        )
        assert response.status_code == 400


class TestApiMeRoute:
    """Tests for GET /api/me."""

    def test_authenticated_user(self, auth_client):
        """Valid bearer token returns user info."""
        with patch('state.db') as mock_db:
            mock_db.get_user_by_token.return_value = {
                'user_id': 'u123',
                'username': 'alice',
                'created_at': '2024-01-01'
            }
            mock_db.get_user_by_id.return_value = {
                'user_id': 'u123',
                'username': 'alice',
                'created_at': '2024-01-01'
            }
            response = auth_client.get(
                '/api/me',
                headers={'Authorization': 'Bearer test-secret-token'}
            )
        assert response.status_code == 200
        body = json.loads(response.data)
        assert 'user_id' in body

    def test_unauthenticated(self, auth_client):
        """Missing token returns 401 when auth is required."""
        response = auth_client.get('/api/me')
        assert response.status_code == 401
        body = json.loads(response.data)
        assert body['error'] == 'Unauthorized'


class TestApiHealthRoute:
    """Tests for GET /api/health."""

    def test_returns_200_with_expected_keys(self, client):
        """Health endpoint returns 200 with status and checks."""
        response = client.get('/api/health')
        assert response.status_code == 200
        body = json.loads(response.data)
        assert 'status' in body
        assert 'checks' in body
        assert 'database' in body['checks']
        assert 'disk' in body['checks']
        assert 'llm' in body['checks']
        assert 'layers' in body['checks']
        assert 'sessions' in body['checks']


class TestApiGeocodeRoute:
    """Tests for GET /api/geocode."""

    @patch('services.rate_limiter.nominatim_limiter')
    @patch('blueprints.osm.urllib.request.urlopen')
    def test_valid_query(self, mock_urlopen, mock_limiter, client):
        """Valid query returns lat, lon, display_name."""
        mock_limiter.can_proceed.return_value = True
        mock_limiter.wait.return_value = None
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps([{
            "lat": "48.8566",
            "lon": "2.3522",
            "display_name": "Paris, France"
        }]).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        response = client.get('/api/geocode?q=Paris')
        assert response.status_code == 200
        body = json.loads(response.data)
        assert body['lat'] == 48.8566
        assert body['lon'] == 2.3522
        assert 'Paris' in body['display_name']

    def test_missing_query(self, client):
        """Missing query parameter returns 400."""
        response = client.get('/api/geocode')
        assert response.status_code == 400
        body = json.loads(response.data)
        assert 'No query' in body['error']

    @patch('services.rate_limiter.nominatim_limiter')
    @patch('blueprints.osm.urllib.request.urlopen')
    def test_unicode_place_name(self, mock_urlopen, mock_limiter, client):
        """Unicode place names (e.g., Japanese) are handled correctly."""
        mock_limiter.can_proceed.return_value = True
        mock_limiter.wait.return_value = None
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps([{
            "lat": "35.6762",
            "lon": "139.6503",
            "display_name": "\u6771\u4eac\u90fd, \u65e5\u672c"
        }]).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        response = client.get('/api/geocode?q=%E6%9D%B1%E4%BA%AC')
        assert response.status_code == 200
        body = json.loads(response.data)
        assert body['lat'] == 35.6762
        assert '\u6771\u4eac' in body['display_name']


class TestApiAutoClassifyRoute:
    """Tests for POST /api/auto-classify."""

    def test_requires_auth(self, auth_client):
        """Auto-classify returns 401 without valid token."""
        response = auth_client.post(
            '/api/auto-classify',
            data=json.dumps({"place": "Seattle"}),
            content_type='application/json'
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# 2. Untested handler: handle_style_layer
# ---------------------------------------------------------------------------

class TestHandleStyleLayer:
    """Tests for handle_style_layer tool handler."""

    def test_change_color(self):
        """Setting color returns style with color."""
        from nl_gis.handlers.layers import handle_style_layer
        result = handle_style_layer({
            "layer_name": "buildings",
            "color": "#ff0000"
        })
        assert result["success"] is True
        assert result["style"]["color"] == "#ff0000"
        assert result["layer_name"] == "buildings"
        assert result["action"] == "style"

    def test_change_opacity(self):
        """Setting fill_opacity returns style with fillOpacity (Leaflet key)."""
        from nl_gis.handlers.layers import handle_style_layer
        result = handle_style_layer({
            "layer_name": "parks",
            "fill_opacity": 0.5
        })
        assert result["success"] is True
        assert result["style"]["fillOpacity"] == 0.5

    def test_layer_not_found_still_returns_instruction(self):
        """handle_style_layer does not check layer existence; it returns instruction for frontend."""
        from nl_gis.handlers.layers import handle_style_layer
        result = handle_style_layer({
            "layer_name": "nonexistent_layer",
            "color": "#00ff00"
        })
        # Handler returns success because it just builds an instruction
        assert result["success"] is True
        assert result["layer_name"] == "nonexistent_layer"

    def test_missing_layer_name(self):
        """Missing layer_name returns error."""
        from nl_gis.handlers.layers import handle_style_layer
        result = handle_style_layer({"color": "#ff0000"})
        assert "error" in result
        assert "layer_name" in result["error"]

    def test_missing_style_properties(self):
        """No style properties returns error."""
        from nl_gis.handlers.layers import handle_style_layer
        result = handle_style_layer({"layer_name": "buildings"})
        assert "error" in result
        assert "style property" in result["error"].lower() or "required" in result["error"].lower()

    def test_multiple_style_properties(self):
        """Multiple style properties are all included."""
        from nl_gis.handlers.layers import handle_style_layer
        result = handle_style_layer({
            "layer_name": "roads",
            "color": "#333333",
            "weight": 3,
            "fill_opacity": 0.8,
            "opacity": 0.9
        })
        assert result["success"] is True
        style = result["style"]
        assert style["color"] == "#333333"
        assert style["weight"] == 3
        assert style["fillOpacity"] == 0.8
        assert style["opacity"] == 0.9

    def test_dispatch_style_layer(self):
        """style_layer is dispatched correctly via dispatch_tool."""
        result = dispatch_tool("style_layer", {
            "layer_name": "test",
            "color": "#abcdef"
        })
        assert result["success"] is True
        assert result["style"]["color"] == "#abcdef"


# ---------------------------------------------------------------------------
# 3. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases: special characters, NaN coordinates, unicode."""

    def test_nan_latitude_rejected(self):
        """ValidatedPoint rejects NaN latitude."""
        with pytest.raises((ValueError, TypeError)):
            ValidatedPoint(lat=float('nan'), lon=-122.3)

    def test_nan_longitude_rejected(self):
        """ValidatedPoint rejects NaN longitude."""
        with pytest.raises((ValueError, TypeError)):
            ValidatedPoint(lat=47.6, lon=float('nan'))

    def test_inf_latitude_rejected(self):
        """ValidatedPoint rejects infinite latitude."""
        with pytest.raises(ValueError):
            ValidatedPoint(lat=float('inf'), lon=-122.3)

    def test_inf_longitude_rejected(self):
        """ValidatedPoint rejects infinite longitude."""
        with pytest.raises(ValueError):
            ValidatedPoint(lat=47.6, lon=float('inf'))

    def test_special_characters_in_layer_names(self):
        """Layer names with special characters in style handler."""
        from nl_gis.handlers.layers import handle_style_layer
        result = handle_style_layer({
            "layer_name": "layer with spaces & <special> chars!",
            "color": "#ff0000"
        })
        assert result["success"] is True
        assert result["layer_name"] == "layer with spaces & <special> chars!"

    def test_unicode_layer_name(self):
        """Unicode layer names are handled."""
        from nl_gis.handlers.layers import handle_style_layer
        result = handle_style_layer({
            "layer_name": "\u6771\u4eac_\u5efa\u7269",
            "color": "#0000ff"
        })
        assert result["success"] is True
        assert result["layer_name"] == "\u6771\u4eac_\u5efa\u7269"

    @patch('services.rate_limiter.nominatim_limiter')
    @patch('blueprints.osm.urllib.request.urlopen')
    def test_geocode_unicode_result_display_name(self, mock_urlopen, mock_limiter, client):
        """Geocode returns unicode display names correctly."""
        mock_limiter.can_proceed.return_value = True
        mock_limiter.wait.return_value = None
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps([{
            "lat": "55.7558",
            "lon": "37.6173",
            "display_name": "\u041c\u043e\u0441\u043a\u0432\u0430, \u0420\u043e\u0441\u0441\u0438\u044f"
        }]).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        response = client.get('/api/geocode?q=Moscow')
        assert response.status_code == 200
        body = json.loads(response.data)
        assert '\u041c\u043e\u0441\u043a\u0432\u0430' in body['display_name']

    def test_add_osm_annotation_with_special_category(self, client, sample_polygon_feature):
        """Category names with special characters are stored."""
        sample_polygon_feature['properties']['category_name'] = 'caf\u00e9 & bar <test>'
        data = {"features": [sample_polygon_feature]}
        response = client.post(
            '/add_osm_annotations',
            data=json.dumps(data),
            content_type='application/json'
        )
        assert response.status_code == 200
        body = json.loads(response.data)
        assert body['added'] == 1

    def test_validated_point_boundary_values(self):
        """ValidatedPoint accepts boundary values."""
        p1 = ValidatedPoint(lat=90.0, lon=180.0)
        assert p1.lat == 90.0
        assert p1.lon == 180.0

        p2 = ValidatedPoint(lat=-90.0, lon=-180.0)
        assert p2.lat == -90.0
        assert p2.lon == -180.0

        p3 = ValidatedPoint(lat=0.0, lon=0.0)
        assert p3.lat == 0.0
        assert p3.lon == 0.0

    def test_validated_point_out_of_range(self):
        """ValidatedPoint rejects out-of-range values."""
        with pytest.raises(ValueError):
            ValidatedPoint(lat=91.0, lon=0.0)
        with pytest.raises(ValueError):
            ValidatedPoint(lat=0.0, lon=181.0)
        with pytest.raises(ValueError):
            ValidatedPoint(lat=-91.0, lon=0.0)
        with pytest.raises(ValueError):
            ValidatedPoint(lat=0.0, lon=-181.0)
