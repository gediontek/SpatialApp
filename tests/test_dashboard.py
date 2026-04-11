"""Tests for the dashboard blueprint and database methods."""

import json
import os
import pytest
import sys

os.environ['FLASK_DEBUG'] = 'false'
os.environ['SECRET_KEY'] = 'test-secret-key'
os.environ['ANTHROPIC_API_KEY'] = ''
os.environ['CHAT_API_TOKEN'] = ''

from app import app
from state import chat_sessions
from config import Config
import state


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Set up a temporary database for each test."""
    db_path = str(tmp_path / "test_dashboard.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)

    import importlib
    import services.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


@pytest.fixture
def client(test_db):
    """Create a test client with database available."""
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    original_db = state.db
    state.db = test_db
    chat_sessions.clear()

    with app.test_client() as client:
        yield client

    state.db = original_db


@pytest.fixture
def auth_user(test_db):
    """Create a test user and return (user_id, token) tuple."""
    user = test_db.create_user("testuser", api_token="sk-test-dashboard-token")
    return user["user_id"], "sk-test-dashboard-token"


@pytest.fixture
def auth_headers(auth_user):
    """Return auth headers for the test user."""
    _, token = auth_user
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# Database method tests
# ============================================================

class TestDatabaseDashboardMethods:
    """Test new database methods for dashboard."""

    def test_get_user_sessions_empty(self, test_db, auth_user):
        user_id, _ = auth_user
        sessions = test_db.get_user_sessions(user_id)
        assert sessions == []

    def test_get_user_sessions_with_data(self, test_db, auth_user):
        user_id, _ = auth_user
        test_db.save_chat_session("sess-1", [{"role": "user", "content": "hello"}], user_id=user_id)
        test_db.save_chat_session("sess-2", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hey"}], user_id=user_id)

        sessions = test_db.get_user_sessions(user_id)
        assert len(sessions) == 2
        # Check structure
        for s in sessions:
            assert "session_id" in s
            assert "message_count" in s
            assert "updated_at" in s
        # sess-2 has 2 messages
        sess_2 = [s for s in sessions if s["session_id"] == "sess-2"][0]
        assert sess_2["message_count"] == 2

    def test_get_user_sessions_isolation(self, test_db, auth_user):
        """Sessions of another user are not returned."""
        user_id, _ = auth_user
        other_user = test_db.create_user("other", api_token="sk-other-token")
        test_db.save_chat_session("sess-mine", [{"role": "user", "content": "x"}], user_id=user_id)
        test_db.save_chat_session("sess-theirs", [{"role": "user", "content": "y"}], user_id=other_user["user_id"])

        sessions = test_db.get_user_sessions(user_id)
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "sess-mine"

    def test_get_user_layers(self, test_db, auth_user):
        user_id, _ = auth_user
        geojson = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {}}]}
        test_db.save_layer("test-layer", geojson, user_id=user_id)

        layers = test_db.get_user_layers(user_id)
        assert len(layers) == 1
        assert layers[0]["name"] == "test-layer"
        assert layers[0]["feature_count"] == 1

    def test_get_user_stats(self, test_db, auth_user):
        user_id, _ = auth_user
        test_db.log_query_metric(user_id=user_id, message="test", tool_calls=2,
                                 input_tokens=100, output_tokens=50, duration_ms=500)
        test_db.log_query_metric(user_id=user_id, message="test2", tool_calls=1,
                                 input_tokens=200, output_tokens=100, duration_ms=300)

        stats = test_db.get_user_stats(user_id)
        assert stats["total_queries"] == 2
        assert stats["total_tokens_used"] == 450  # 100+200+50+100
        assert stats["total_tool_calls"] == 3

    def test_get_chat_session_with_owner(self, test_db, auth_user):
        user_id, _ = auth_user
        test_db.save_chat_session("sess-x", [{"role": "user", "content": "hello"}], user_id=user_id)

        result = test_db.get_chat_session_with_owner("sess-x")
        assert result is not None
        assert result["user_id"] == user_id
        assert result["session_id"] == "sess-x"
        assert len(result["messages"]) == 1

    def test_get_chat_session_with_owner_not_found(self, test_db):
        result = test_db.get_chat_session_with_owner("nonexistent")
        assert result is None

    def test_delete_chat_session_for_user(self, test_db, auth_user):
        user_id, _ = auth_user
        test_db.save_chat_session("sess-del", [{"role": "user", "content": "bye"}], user_id=user_id)

        deleted = test_db.delete_chat_session_for_user("sess-del", user_id)
        assert deleted is True

        # Verify it's gone
        result = test_db.get_chat_session_with_owner("sess-del")
        assert result is None

    def test_delete_chat_session_wrong_user(self, test_db, auth_user):
        user_id, _ = auth_user
        test_db.save_chat_session("sess-nope", [{"role": "user", "content": "nope"}], user_id=user_id)

        deleted = test_db.delete_chat_session_for_user("sess-nope", "wrong-user-id")
        assert deleted is False


# ============================================================
# API endpoint tests
# ============================================================

class TestDashboardAPI:
    """Tests for GET /api/dashboard."""

    def test_dashboard_returns_correct_structure(self, client, auth_headers, auth_user, test_db):
        user_id, _ = auth_user
        # Seed some data
        test_db.save_chat_session("s1", [{"role": "user", "content": "hi"}], user_id=user_id)
        test_db.log_query_metric(user_id=user_id, message="hi", tool_calls=1,
                                 input_tokens=10, output_tokens=5, duration_ms=100)

        response = client.get('/api/dashboard', headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()

        assert "user" in data
        assert "sessions" in data
        assert "layers" in data
        assert "stats" in data

        assert data["user"]["username"] == "testuser"
        assert len(data["sessions"]) == 1
        assert data["stats"]["total_queries"] == 1

    def test_dashboard_requires_auth(self, client):
        """Dashboard returns 401 without valid token when token is required."""
        original = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = "required-token"
        try:
            response = client.get('/api/dashboard')
            assert response.status_code == 401
        finally:
            Config.CHAT_API_TOKEN = original

    def test_dashboard_empty_data(self, client, auth_headers):
        """Dashboard works with no sessions/layers/metrics."""
        response = client.get('/api/dashboard', headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert data["sessions"] == []
        assert data["layers"] == []
        assert data["stats"]["total_queries"] == 0


class TestDeleteSessionAPI:
    """Tests for DELETE /api/sessions/<session_id>."""

    def test_delete_session_success(self, client, auth_headers, auth_user, test_db):
        user_id, _ = auth_user
        test_db.save_chat_session("del-me", [{"role": "user", "content": "x"}], user_id=user_id)

        response = client.delete('/api/sessions/del-me', headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

        # Verify gone
        result = test_db.get_chat_session_with_owner("del-me")
        assert result is None

    def test_delete_session_not_found(self, client, auth_headers):
        response = client.delete('/api/sessions/nonexistent', headers=auth_headers)
        assert response.status_code == 404

    def test_delete_session_wrong_owner(self, client, auth_headers, auth_user, test_db):
        """Cannot delete another user's session."""
        user_id, _ = auth_user
        other_user = test_db.create_user("other2", api_token="sk-other2-token")
        test_db.save_chat_session("other-sess", [{"role": "user", "content": "y"}], user_id=other_user["user_id"])

        response = client.delete('/api/sessions/other-sess', headers=auth_headers)
        assert response.status_code == 403

    def test_delete_session_requires_auth(self, client):
        original = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = "required-token"
        try:
            response = client.delete('/api/sessions/any')
            assert response.status_code == 401
        finally:
            Config.CHAT_API_TOKEN = original


class TestSessionMessagesAPI:
    """Tests for GET /api/sessions/<session_id>/messages."""

    def test_get_messages_success(self, client, auth_headers, auth_user, test_db):
        user_id, _ = auth_user
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi there"}]
        test_db.save_chat_session("msg-sess", messages, user_id=user_id)

        response = client.get('/api/sessions/msg-sess/messages', headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert data["session_id"] == "msg-sess"
        assert data["message_count"] == 2
        assert len(data["messages"]) == 2

    def test_get_messages_not_found(self, client, auth_headers):
        response = client.get('/api/sessions/nonexistent/messages', headers=auth_headers)
        assert response.status_code == 404

    def test_get_messages_wrong_owner(self, client, auth_headers, auth_user, test_db):
        user_id, _ = auth_user
        other_user = test_db.create_user("other3", api_token="sk-other3-token")
        test_db.save_chat_session("private-sess", [{"role": "user", "content": "secret"}], user_id=other_user["user_id"])

        response = client.get('/api/sessions/private-sess/messages', headers=auth_headers)
        assert response.status_code == 403


class TestDashboardPage:
    """Tests for GET /dashboard page route."""

    def test_dashboard_page_loads(self, client, auth_headers):
        response = client.get('/dashboard', headers=auth_headers)
        assert response.status_code == 200
        assert b'Dashboard' in response.data

    def test_dashboard_page_requires_auth(self, client):
        original = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = "required-token"
        try:
            response = client.get('/dashboard')
            assert response.status_code == 401
        finally:
            Config.CHAT_API_TOKEN = original
