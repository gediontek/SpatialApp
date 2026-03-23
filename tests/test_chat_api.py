"""Tests for the /api/chat Flask endpoint."""

import json
import os
import pytest
import tempfile
from unittest.mock import patch, MagicMock

os.environ['FLASK_DEBUG'] = 'false'
os.environ['SECRET_KEY'] = 'test-secret-key'
os.environ['ANTHROPIC_API_KEY'] = ''

from app import app, layer_store, chat_sessions


@pytest.fixture
def client():
    """Create a test client."""
    with tempfile.TemporaryDirectory() as temp_dir:
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False

        # Clear state
        layer_store.clear()
        chat_sessions.clear()

        with app.test_client() as client:
            yield client


class TestChatEndpoint:
    """Tests for POST /api/chat."""

    def test_no_body(self, client):
        response = client.post('/api/chat', content_type='application/json')
        assert response.status_code == 400

    def test_no_message(self, client):
        response = client.post('/api/chat',
                               data=json.dumps({"foo": "bar"}),
                               content_type='application/json')
        assert response.status_code == 400

    def test_empty_message(self, client):
        response = client.post('/api/chat',
                               data=json.dumps({"message": "  "}),
                               content_type='application/json')
        assert response.status_code == 400

    def test_fallback_satellite(self, client):
        """Test rule-based fallback for satellite command."""
        response = client.post('/api/chat',
                               data=json.dumps({"message": "switch to satellite"}),
                               content_type='application/json')
        assert response.status_code == 200
        assert 'text/event-stream' in response.content_type

        data = response.get_data(as_text=True)
        assert 'map_command' in data
        assert 'satellite' in data

    def test_fallback_unknown(self, client):
        """Test fallback with unknown command."""
        response = client.post('/api/chat',
                               data=json.dumps({"message": "analyze spatial patterns"}),
                               content_type='application/json')
        assert response.status_code == 200
        data = response.get_data(as_text=True)
        assert 'error' in data

    @patch("nl_gis.tool_handlers.urllib.request.urlopen")
    def test_fallback_zoom_to(self, mock_urlopen, client):
        """Test rule-based geocode + pan."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps([{
            "lat": "41.8781", "lon": "-87.6298",
            "display_name": "Chicago, IL, USA",
            "boundingbox": ["41.6", "42.0", "-87.9", "-87.5"]
        }]).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        response = client.post('/api/chat',
                               data=json.dumps({"message": "zoom to Chicago"}),
                               content_type='application/json')
        assert response.status_code == 200
        data = response.get_data(as_text=True)
        assert 'map_command' in data
        assert 'Chicago' in data


class TestChatAuth:
    """Tests for bearer token auth on /api/chat."""

    def test_auth_required_when_token_set(self, client):
        from config import Config
        original = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = "test-secret-token"

        try:
            # No auth header
            response = client.post('/api/chat',
                                   data=json.dumps({"message": "hello"}),
                                   content_type='application/json')
            assert response.status_code == 401

            # Wrong token
            response = client.post('/api/chat',
                                   data=json.dumps({"message": "hello"}),
                                   content_type='application/json',
                                   headers={"Authorization": "Bearer wrong"})
            assert response.status_code == 401

            # Correct token
            response = client.post('/api/chat',
                                   data=json.dumps({"message": "switch to satellite"}),
                                   content_type='application/json',
                                   headers={"Authorization": "Bearer test-secret-token"})
            assert response.status_code == 200
        finally:
            Config.CHAT_API_TOKEN = original

    def test_no_auth_when_no_token(self, client):
        from config import Config
        original = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = ""

        try:
            response = client.post('/api/chat',
                                   data=json.dumps({"message": "switch to satellite"}),
                                   content_type='application/json')
            assert response.status_code == 200
        finally:
            Config.CHAT_API_TOKEN = original


class TestLayerEndpoints:
    """Tests for /api/layers endpoints."""

    def test_get_empty_layers(self, client):
        response = client.get('/api/layers')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['layers'] == []

    def test_get_layers_with_data(self, client):
        layer_store['test_layer'] = {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": {}, "properties": {}}]
        }
        response = client.get('/api/layers')
        data = json.loads(response.data)
        assert len(data['layers']) == 1
        assert data['layers'][0]['name'] == 'test_layer'
        assert data['layers'][0]['feature_count'] == 1

    def test_delete_layer(self, client):
        layer_store['to_delete'] = {"type": "FeatureCollection", "features": []}
        response = client.delete('/api/layers/to_delete')
        assert response.status_code == 200
        assert 'to_delete' not in layer_store

    def test_delete_nonexistent_layer(self, client):
        response = client.delete('/api/layers/nonexistent')
        assert response.status_code == 404
