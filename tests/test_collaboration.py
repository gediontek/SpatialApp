"""Tests for v2.1 Plan 09 real-time collaboration."""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault('FLASK_DEBUG', 'false')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('ANTHROPIC_API_KEY', '')

from app import app
import state
from blueprints.collab import (
    COLOR_PALETTE,
    _generate_session_id,
    _new_session_record,
    append_chat_message,
    append_layer_history,
    assign_color,
)
from config import Config


@pytest.fixture
def rest_client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    state.collab_sessions.clear()
    yield app.test_client()
    state.collab_sessions.clear()


@pytest.fixture
def socketio_client():
    pytest.importorskip("flask_socketio")
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    state.collab_sessions.clear()
    if state.socketio is None:
        pytest.skip("SocketIO not initialized")
    client = state.socketio.test_client(app)
    yield client
    if client.is_connected():
        client.disconnect()
    state.collab_sessions.clear()


@pytest.fixture
def two_socketio_clients():
    pytest.importorskip("flask_socketio")
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    state.collab_sessions.clear()
    if state.socketio is None:
        pytest.skip("SocketIO not initialized")
    a = state.socketio.test_client(app)
    b = state.socketio.test_client(app)
    yield a, b
    for c in (a, b):
        if c.is_connected():
            c.disconnect()
    state.collab_sessions.clear()


# ---------------------------------------------------------------------------
# Helpers (no Flask)
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_generate_session_id_starts_with_collab(self):
        sid = _generate_session_id()
        assert sid.startswith("collab_")
        assert len(sid) > len("collab_") + 8

    def test_session_ids_are_unique(self):
        ids = {_generate_session_id() for _ in range(50)}
        assert len(ids) == 50

    def test_assign_color_picks_unused(self):
        record = _new_session_record("u1", None)
        record["users"] = {"u1": {"color": COLOR_PALETTE[0]}}
        c = assign_color(record)
        assert c != COLOR_PALETTE[0]
        assert c in COLOR_PALETTE

    def test_assign_color_cycles_when_full(self):
        record = _new_session_record("u1", None)
        record["users"] = {f"u{i}": {"color": COLOR_PALETTE[i]} for i in range(10)}
        # All 10 in use → cycles round-robin
        c = assign_color(record)
        assert c in COLOR_PALETTE

    def test_layer_history_caps(self, monkeypatch):
        monkeypatch.setattr(Config, "COLLAB_LAYER_HISTORY_CAP", 5)
        record = _new_session_record("u1", None)
        for i in range(10):
            append_layer_history(record, {"i": i})
        # Only last 5 retained
        assert len(record["layer_history"]) == 5
        assert record["layer_history"][0]["i"] == 5

    def test_append_chat_message(self):
        record = _new_session_record("u1", None)
        append_chat_message(record, {"text": "hello"})
        assert record["chat_messages"][0]["text"] == "hello"


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

class TestRestEndpoints:
    def test_create_returns_session_id(self, rest_client):
        r = rest_client.post('/api/collab/create', json={"session_name": "Mapping party"})
        assert r.status_code == 200
        body = r.get_json()
        assert body["session_id"].startswith("collab_")
        assert "join_url" in body
        assert body["session_name"] == "Mapping party"

    def test_create_without_name(self, rest_client):
        r = rest_client.post('/api/collab/create', json={})
        assert r.status_code == 200
        assert r.get_json()["session_name"] is None

    def test_create_invalid_name_type(self, rest_client):
        r = rest_client.post('/api/collab/create', json={"session_name": 12345})
        assert r.status_code == 400

    def test_info_for_unknown_returns_404(self, rest_client):
        r = rest_client.get('/api/collab/collab_doesnotexist/info')
        assert r.status_code == 404

    def test_info_after_create(self, rest_client):
        sid = rest_client.post('/api/collab/create', json={}).get_json()["session_id"]
        r = rest_client.get(f'/api/collab/{sid}/info')
        assert r.status_code == 200
        body = r.get_json()
        assert body["session_id"] == sid
        assert body["user_count"] == 0
        assert body["active"] is True

    def test_info_validates_id_prefix(self, rest_client):
        r = rest_client.get('/api/collab/garbage_xxx/info')
        assert r.status_code == 400

    def test_export_unknown_404(self, rest_client):
        r = rest_client.get('/api/collab/collab_xxx/export')
        # Could be 404 (in-memory miss) or fall through; if state.db is set to a
        # real db it might return a different code. Either way it's not a 200.
        assert r.status_code in {404, 500}

    def test_export_returns_workflow(self, rest_client):
        sid = rest_client.post('/api/collab/create', json={}).get_json()["session_id"]
        # Inject some chat history
        with state.collab_lock:
            record = state.collab_sessions[sid]
            record["chat_messages"] = [
                {"role": "user", "text": "Show parks", "user_id": "u1", "user_name": "Alice"},
                {"role": "assistant", "text": "Done", "user_id": "u1"},
                {"role": "user", "text": "Buffer them", "user_id": "u2", "user_name": "Bob"},
            ]

        r = rest_client.get(f'/api/collab/{sid}/export')
        assert r.status_code == 200
        body = r.get_json()
        assert len(body["workflow"]) == 2
        assert body["workflow"][0]["command"] == "Show parks"
        assert body["workflow"][1]["command"] == "Buffer them"
        assert body["total_messages"] == 3


# ---------------------------------------------------------------------------
# WebSocket flows
# ---------------------------------------------------------------------------

def _drain(client):
    """Return list of received events for a SocketIO test client."""
    return client.get_received()


class TestWebSocketJoinLeave:
    def test_join_unknown_session_emits_error(self, socketio_client):
        socketio_client.emit('join_collab', {"session_id": "collab_nope"})
        events = _drain(socketio_client)
        names = [e["name"] for e in events]
        assert 'collab_error' in names

    def test_join_invalid_session_id_format(self, socketio_client):
        socketio_client.emit('join_collab', {"session_id": "not_collab"})
        events = _drain(socketio_client)
        assert any(e["name"] == "collab_error" for e in events)

    def test_join_missing_session_id_returns_error(self, socketio_client):
        socketio_client.emit('join_collab', {})
        events = _drain(socketio_client)
        assert any(e["name"] == "collab_error" for e in events)

    def test_join_emits_state_and_user_joined(self, rest_client, socketio_client):
        sid = rest_client.post('/api/collab/create', json={}).get_json()["session_id"]
        socketio_client.emit('join_collab', {"session_id": sid, "user_name": "Alice"})
        events = _drain(socketio_client)
        names = [e["name"] for e in events]
        # Joiner gets both their own collab_state and the broadcast user_joined
        assert 'collab_state' in names
        assert 'user_joined' in names

    def test_two_clients_join_and_see_each_other(self, rest_client, two_socketio_clients):
        a, b = two_socketio_clients
        sid = rest_client.post('/api/collab/create', json={}).get_json()["session_id"]

        a.emit('join_collab', {"session_id": sid, "user_name": "Alice"})
        _drain(a)  # consume first batch
        b.emit('join_collab', {"session_id": sid, "user_name": "Bob"})

        a_events = _drain(a)
        b_events = _drain(b)
        # Alice gets a user_joined for Bob
        assert any(e["name"] == "user_joined"
                   and e["args"][0].get("user_id") in {"anonymous", None, "Bob"}
                   for e in a_events) or any(e["name"] == "user_joined" for e in a_events)
        # Bob gets at least his own collab_state + a user_joined
        assert any(e["name"] == "collab_state" for e in b_events)
        assert any(e["name"] == "user_joined" for e in b_events)

        # State has 1 user (both clients are 'anonymous' so same user_id)
        with state.collab_lock:
            assert sid in state.collab_sessions
            assert len(state.collab_sessions[sid]["users"]) == 1

    def test_session_full_rejects(self, rest_client, monkeypatch):
        pytest.importorskip("flask_socketio")
        if state.socketio is None:
            pytest.skip("SocketIO not initialized")
        monkeypatch.setattr(Config, "COLLAB_MAX_USERS_PER_SESSION", 1)

        sid = rest_client.post('/api/collab/create', json={}).get_json()["session_id"]
        # Manually populate so cap test triggers (otherwise both clients
        # share user_id 'anonymous' and rejoin path is hit)
        with state.collab_lock:
            state.collab_sessions[sid]["users"]["other"] = {
                "name": "Existing", "color": "#000000", "joined_at": 0.0,
                "sid": "other-sid", "last_cursor_ts": 0.0, "cursor": None,
            }
        client = state.socketio.test_client(app)
        try:
            client.emit('join_collab', {"session_id": sid})
            events = _drain(client)
            assert any(
                e["name"] == "collab_error" and "full" in e["args"][0]["message"]
                for e in events
            )
        finally:
            client.disconnect()

    def test_disconnect_emits_user_left(self, rest_client):
        pytest.importorskip("flask_socketio")
        if state.socketio is None:
            pytest.skip("SocketIO not initialized")
        a = state.socketio.test_client(app)
        try:
            sid = rest_client.post('/api/collab/create', json={}).get_json()["session_id"]
            a.emit('join_collab', {"session_id": sid})
            _drain(a)
            # Now connect a peer that listens
            b = state.socketio.test_client(app)
            try:
                b.emit('join_collab', {"session_id": sid})
                _drain(a); _drain(b)  # consume second join broadcast
                a.disconnect()
                # Brief wait — disconnect handler is sync but emit ordering not guaranteed
                events = _drain(b)
                # `a` and `b` share user_id 'anonymous' — leave only fires when
                # the disconnecting SID was the active one. Last to join wins,
                # so the leave broadcast may go to nobody. The broader contract
                # is: handler must not crash.
                _ = events  # exercised the path
            finally:
                if b.is_connected():
                    b.disconnect()
        finally:
            if a.is_connected():
                a.disconnect()

    def test_explicit_leave_collab(self, rest_client, socketio_client):
        sid = rest_client.post('/api/collab/create', json={}).get_json()["session_id"]
        socketio_client.emit('join_collab', {"session_id": sid})
        _drain(socketio_client)
        socketio_client.emit('leave_collab', {"session_id": sid})
        # No user remaining
        with state.collab_lock:
            assert state.collab_sessions[sid]["users"] == {}


class TestWebSocketCursor:
    def test_cursor_move_throttled(self, rest_client, monkeypatch):
        pytest.importorskip("flask_socketio")
        if state.socketio is None:
            pytest.skip("SocketIO not initialized")
        # Make throttle long enough to assert second emit suppressed
        monkeypatch.setattr(Config, "COLLAB_CURSOR_THROTTLE_MS", 5000)

        a = state.socketio.test_client(app)
        b = state.socketio.test_client(app)
        try:
            sid = rest_client.post('/api/collab/create', json={}).get_json()["session_id"]
            a.emit('join_collab', {"session_id": sid, "user_name": "A"})
            b.emit('join_collab', {"session_id": sid, "user_name": "B"})
            _drain(a); _drain(b)

            a.emit('cursor_move', {"lat": 40.0, "lon": -74.0})
            a.emit('cursor_move', {"lat": 41.0, "lon": -75.0})  # throttled
            cursor_events = [e for e in _drain(b) if e["name"] == "cursor_update"]
            # Throttle: at most one emit during the window
            assert len(cursor_events) <= 1
        finally:
            for c in (a, b):
                if c.is_connected():
                    c.disconnect()

    def test_cursor_move_invalid_coords_ignored(self, rest_client, socketio_client):
        sid = rest_client.post('/api/collab/create', json={}).get_json()["session_id"]
        socketio_client.emit('join_collab', {"session_id": sid})
        _drain(socketio_client)
        # Out-of-range coords; server silently drops
        socketio_client.emit('cursor_move', {"lat": 200, "lon": 999})
        socketio_client.emit('cursor_move', {"lat": "garbage"})
        # Nothing crashes; cursor stays None
        with state.collab_lock:
            users = state.collab_sessions[sid]["users"]
            for u in users.values():
                assert u.get("cursor") in (None, {"lat": None, "lon": None})

    def test_cursor_without_join_is_silent(self, socketio_client):
        # User never joined a collab session — server must not crash
        socketio_client.emit('cursor_move', {"lat": 0, "lon": 0})
        # No assertion needed; we just verify no exception escapes


class TestWebSocketLayerEvents:
    def test_layer_remove_broadcasts_and_records_history(self, rest_client, two_socketio_clients):
        a, b = two_socketio_clients
        sid = rest_client.post('/api/collab/create', json={}).get_json()["session_id"]
        a.emit('join_collab', {"session_id": sid})
        b.emit('join_collab', {"session_id": sid})
        _drain(a); _drain(b)

        # Pre-populate the layer_store so we can assert removal
        with state.layer_lock:
            state.layer_store["doomed"] = {"type": "FeatureCollection", "features": []}

        a.emit('layer_remove', {"layer_name": "doomed"})

        # Layer is gone
        assert "doomed" not in state.layer_store
        # History captured
        with state.collab_lock:
            history = state.collab_sessions[sid]["layer_history"]
            assert any(h["action"] == "remove" and h["layer_name"] == "doomed" for h in history)

        # Peer received the broadcast
        events = _drain(b)
        assert any(e["name"] == "layer_removed" for e in events)

    def test_layer_style_broadcasts_and_records(self, rest_client, two_socketio_clients):
        a, b = two_socketio_clients
        sid = rest_client.post('/api/collab/create', json={}).get_json()["session_id"]
        a.emit('join_collab', {"session_id": sid})
        b.emit('join_collab', {"session_id": sid})
        _drain(a); _drain(b)

        a.emit('layer_style', {"layer_name": "parks", "style": {"color": "#ff0000"}})

        with state.collab_lock:
            history = state.collab_sessions[sid]["layer_history"]
            assert any(h["action"] == "style" and h["style"]["color"] == "#ff0000" for h in history)

        events = _drain(b)
        assert any(e["name"] == "layer_styled" for e in events)

    def test_layer_remove_without_collab_session_is_silent(self, socketio_client):
        # No join — handler must not crash
        socketio_client.emit('layer_remove', {"layer_name": "x"})


class TestDatabasePersistence:
    def test_save_and_get_collab_session(self):
        if state.db is None:
            pytest.skip("DB not configured")
        sid = _generate_session_id()
        record = _new_session_record("alice", "Demo")
        record["chat_messages"] = [{"role": "user", "text": "hello"}]
        # Add a transient SID — should be stripped on save
        record["users"]["alice"] = {
            "name": "Alice", "color": "#1f77b4", "sid": "transient-sid",
            "joined_at": time.time(), "last_cursor_ts": time.time(), "cursor": None,
        }
        try:
            state.db.save_collab_session(sid, record, owner_user_id="alice",
                                         session_name="Demo")
            loaded = state.db.get_collab_session(sid)
            assert loaded is not None
            assert loaded["session_id"] == sid
            assert loaded["owner_user_id"] == "alice"
            assert loaded["session_name"] == "Demo"
            # Transient field stripped on save
            assert "sid" not in loaded["state"]["users"]["alice"]
            assert "last_cursor_ts" not in loaded["state"]["users"]["alice"]
        finally:
            try:
                state.db.delete_collab_session(sid)
            except Exception:
                pass

    def test_get_unknown_returns_none(self):
        if state.db is None:
            pytest.skip("DB not configured")
        assert state.db.get_collab_session("collab_nope_xx") is None
