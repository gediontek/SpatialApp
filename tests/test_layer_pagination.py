"""Tests for layer pagination in /api/layers endpoint."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def client():
    """Test client with layers pre-populated."""
    os.environ['FLASK_DEBUG'] = 'false'
    os.environ['SECRET_KEY'] = 'test-secret-key'
    os.environ.pop('CHAT_API_TOKEN', None)

    from app import app
    import state

    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    # Clear and populate layer_store
    state.layer_store.clear()
    for i in range(15):
        state.layer_store[f"layer_{i:02d}"] = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {}}
            ] * (i + 1),
        }

    with app.test_client() as c:
        yield c

    state.layer_store.clear()


class TestLayerPaginationBackwardCompat:
    def test_no_pagination_params_returns_all(self, client):
        resp = client.get('/api/layers')
        data = resp.get_json()
        assert resp.status_code == 200
        assert len(data['layers']) == 15
        # No pagination metadata when not requested
        assert 'total' not in data
        assert 'page' not in data

    def test_unpaginated_has_feature_counts(self, client):
        resp = client.get('/api/layers')
        data = resp.get_json()
        names = {l['name'] for l in data['layers']}
        assert 'layer_00' in names


class TestLayerPagination:
    def test_first_page(self, client):
        resp = client.get('/api/layers?page=1&per_page=5')
        data = resp.get_json()
        assert resp.status_code == 200
        assert len(data['layers']) == 5
        assert data['total'] == 15
        assert data['page'] == 1
        assert data['per_page'] == 5
        assert data['total_pages'] == 3

    def test_second_page(self, client):
        resp = client.get('/api/layers?page=2&per_page=5')
        data = resp.get_json()
        assert len(data['layers']) == 5
        assert data['page'] == 2

    def test_last_page_partial(self, client):
        resp = client.get('/api/layers?page=3&per_page=5')
        data = resp.get_json()
        assert len(data['layers']) == 5
        assert data['page'] == 3

    def test_out_of_range_page(self, client):
        resp = client.get('/api/layers?page=100&per_page=5')
        data = resp.get_json()
        assert resp.status_code == 200
        assert len(data['layers']) == 0
        assert data['total'] == 15

    def test_default_per_page(self, client):
        resp = client.get('/api/layers?page=1')
        data = resp.get_json()
        assert data['per_page'] == 100
        # All 15 fit in default page
        assert len(data['layers']) == 15

    def test_per_page_clamped_to_max(self, client):
        resp = client.get('/api/layers?page=1&per_page=9999')
        data = resp.get_json()
        assert data['per_page'] == 500

    def test_per_page_clamped_to_min(self, client):
        resp = client.get('/api/layers?page=1&per_page=0')
        data = resp.get_json()
        assert data['per_page'] == 1

    def test_invalid_page_defaults(self, client):
        resp = client.get('/api/layers?page=abc&per_page=5')
        data = resp.get_json()
        assert data['page'] == 1

    def test_invalid_per_page_defaults(self, client):
        resp = client.get('/api/layers?page=1&per_page=abc')
        data = resp.get_json()
        assert data['per_page'] == 100

    def test_feature_counts_present(self, client):
        resp = client.get('/api/layers?page=1&per_page=5')
        data = resp.get_json()
        for layer in data['layers']:
            assert 'name' in layer
            assert 'feature_count' in layer
            assert isinstance(layer['feature_count'], int)
