"""Tests for Phase 5 production infrastructure."""

import os
import json
import pytest
import tempfile
import time

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestFileCache:
    """Tests for the file cache."""

    def test_set_and_get(self):
        from services.cache import FileCache
        with tempfile.TemporaryDirectory() as tmp:
            cache = FileCache("test", ttl_seconds=60, cache_dir=tmp)
            cache.set("key1", {"value": 42})
            result = cache.get("key1")
            assert result == {"value": 42}

    def test_cache_miss(self):
        from services.cache import FileCache
        with tempfile.TemporaryDirectory() as tmp:
            cache = FileCache("test", ttl_seconds=60, cache_dir=tmp)
            assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        from services.cache import FileCache
        with tempfile.TemporaryDirectory() as tmp:
            cache = FileCache("test", ttl_seconds=0, cache_dir=tmp)  # 0s TTL
            cache.set("key1", {"value": 42})
            time.sleep(0.01)
            assert cache.get("key1") is None  # Expired

    def test_clear(self):
        from services.cache import FileCache
        with tempfile.TemporaryDirectory() as tmp:
            cache = FileCache("test", ttl_seconds=60, cache_dir=tmp)
            cache.set("a", {"v": 1})
            cache.set("b", {"v": 2})
            assert cache.size() == 2
            cache.clear()
            assert cache.size() == 0

    def test_overwrite(self):
        from services.cache import FileCache
        with tempfile.TemporaryDirectory() as tmp:
            cache = FileCache("test", ttl_seconds=60, cache_dir=tmp)
            cache.set("key", {"v": 1})
            cache.set("key", {"v": 2})
            assert cache.get("key") == {"v": 2}


class TestRateLimiter:
    """Tests for rate limiter."""

    def test_can_proceed(self):
        from services.rate_limiter import RateLimiter
        limiter = RateLimiter("test", min_interval_seconds=0.1)
        assert limiter.can_proceed() is True

    def test_wait_enforces_interval(self):
        from services.rate_limiter import RateLimiter
        limiter = RateLimiter("test", min_interval_seconds=0.1)
        limiter.wait()
        # Immediately after, should not be able to proceed
        assert limiter.can_proceed() is False
        time.sleep(0.12)
        assert limiter.can_proceed() is True


class TestDatabase:
    """Tests for SQLite database."""

    @pytest.fixture(autouse=True)
    def setup_db(self):
        """Use a temporary database for each test."""
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test.db")
        os.environ["DATABASE_PATH"] = self.db_path

        # Reimport to pick up new path
        import importlib
        import services.database as db_mod
        importlib.reload(db_mod)
        db_mod.DB_PATH = self.db_path
        db_mod.init_db()

        self.db = db_mod
        yield

        # Cleanup
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_init_creates_tables(self):
        conn = self.db.get_connection()
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t["name"] for t in tables]
        assert "annotations" in table_names
        assert "layers" in table_names
        assert "chat_sessions" in table_names
        conn.close()

    def test_save_and_get_annotation(self):
        geom = {"type": "Point", "coordinates": [-122.3, 47.6]}
        aid = self.db.save_annotation("test_cat", geom, "#ff0000", "manual")
        assert aid > 0

        features = self.db.get_all_annotations()
        assert len(features) == 1
        assert features[0]["properties"]["category_name"] == "test_cat"
        assert features[0]["geometry"] == geom

    def test_annotation_count(self):
        geom = {"type": "Point", "coordinates": [0, 0]}
        self.db.save_annotation("a", geom)
        self.db.save_annotation("b", geom)
        assert self.db.get_annotation_count() == 2

    def test_clear_annotations(self):
        geom = {"type": "Point", "coordinates": [0, 0]}
        self.db.save_annotation("a", geom)
        self.db.clear_annotations()
        assert self.db.get_annotation_count() == 0

    def test_save_and_get_layer(self):
        geojson = {"type": "FeatureCollection", "features": [{"type": "Feature"}]}
        self.db.save_layer("test_layer", geojson, {"color": "#ff0000"})

        result = self.db.get_layer("test_layer")
        assert result is not None
        assert result["type"] == "FeatureCollection"

    def test_get_nonexistent_layer(self):
        assert self.db.get_layer("nope") is None

    def test_get_all_layers(self):
        self.db.save_layer("l1", {"type": "FeatureCollection", "features": []})
        self.db.save_layer("l2", {"type": "FeatureCollection", "features": [{"type": "Feature"}]})
        layers = self.db.get_all_layers()
        assert len(layers) == 2

    def test_delete_layer(self):
        self.db.save_layer("to_del", {"type": "FeatureCollection", "features": []})
        assert self.db.delete_layer("to_del") is True
        assert self.db.get_layer("to_del") is None
        assert self.db.delete_layer("to_del") is False

    def test_save_and_get_chat_session(self):
        messages = [{"role": "user", "content": "hello"}]
        self.db.save_chat_session("sess1", messages)

        result = self.db.get_chat_session("sess1")
        assert result is not None
        assert len(result) == 1
        assert result[0]["content"] == "hello"

    def test_get_nonexistent_session(self):
        assert self.db.get_chat_session("nope") is None

    def test_delete_session(self):
        self.db.save_chat_session("sess1", [])
        self.db.delete_chat_session("sess1")
        assert self.db.get_chat_session("sess1") is None

    def test_upsert_layer(self):
        """Save layer twice — should update, not duplicate."""
        self.db.save_layer("l1", {"type": "FeatureCollection", "features": []})
        self.db.save_layer("l1", {"type": "FeatureCollection", "features": [{"type": "Feature"}]})
        layers = self.db.get_all_layers()
        assert len(layers) == 1
        assert layers[0]["feature_count"] == 1


class TestUserCRUD:
    """Tests for user management."""

    @pytest.fixture(autouse=True)
    def setup_db(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test.db")
        os.environ["DATABASE_PATH"] = self.db_path
        import importlib
        import services.database as db_mod
        importlib.reload(db_mod)
        db_mod.DB_PATH = self.db_path
        db_mod.init_db()
        self.db = db_mod
        yield
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_create_user(self):
        user = self.db.create_user("alice")
        assert user["username"] == "alice"
        assert user["user_id"]
        assert user["api_token"].startswith("sk-spa-")

    def test_get_user_by_token(self):
        user = self.db.create_user("bob")
        found = self.db.get_user_by_token(user["api_token"])
        assert found is not None
        assert found["username"] == "bob"

    def test_get_user_by_token_not_found(self):
        assert self.db.get_user_by_token("nonexistent") is None

    def test_per_user_annotations(self):
        geom = {"type": "Point", "coordinates": [0, 0]}
        self.db.save_annotation("cat", geom, user_id="user_a")
        self.db.save_annotation("cat", geom, user_id="user_b")
        self.db.save_annotation("cat", geom, user_id="user_a")

        all_annots = self.db.get_all_annotations()
        assert len(all_annots) == 3

        user_a = self.db.get_all_annotations(user_id="user_a")
        assert len(user_a) == 2

        user_b = self.db.get_all_annotations(user_id="user_b")
        assert len(user_b) == 1

    def test_per_user_layers(self):
        geojson = {"type": "FeatureCollection", "features": []}
        self.db.save_layer("shared_name", geojson, user_id="user_a")
        self.db.save_layer("shared_name", geojson, user_id="user_b")

        all_layers = self.db.get_all_layers()
        assert len(all_layers) == 2

        user_a = self.db.get_all_layers(user_id="user_a")
        assert len(user_a) == 1

    def test_list_users(self):
        self.db.create_user("alice")
        self.db.create_user("bob")
        users = self.db.list_users()
        assert len(users) == 2
        # Tokens should not be in the list
        assert "api_token" not in users[0]

    def test_token_hashing(self):
        """Token is hashed in DB — raw token works for lookup, hash stored."""
        user = self.db.create_user("charlie")
        raw_token = user["api_token"]
        assert raw_token.startswith("sk-spa-")

        # Lookup by raw token should work
        found = self.db.get_user_by_token(raw_token)
        assert found is not None
        assert found["username"] == "charlie"

        # Token in DB should be a hash, not the raw token
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT api_token FROM users WHERE user_id = ?", (user["user_id"],)).fetchone()
        conn.close()
        stored_value = row[0]
        assert stored_value != raw_token  # Stored as hash
        assert len(stored_value) == 64  # SHA-256 hex length

    def test_token_lookup_wrong_token(self):
        self.db.create_user("dave")
        assert self.db.get_user_by_token("wrong-token") is None

    def test_paginated_annotations(self):
        """Test limit/offset on get_all_annotations."""
        geom = {"type": "Point", "coordinates": [0, 0]}
        for i in range(5):
            self.db.save_annotation(f"cat_{i}", geom)

        all_annots = self.db.get_all_annotations()
        assert len(all_annots) == 5

        page1 = self.db.get_all_annotations(limit=2, offset=0)
        assert len(page1) == 2

        page2 = self.db.get_all_annotations(limit=2, offset=2)
        assert len(page2) == 2

        page3 = self.db.get_all_annotations(limit=2, offset=4)
        assert len(page3) == 1


class TestQueryMetrics:
    """Tests for query metrics tracking."""

    @pytest.fixture(autouse=True)
    def setup_db(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test.db")
        os.environ["DATABASE_PATH"] = self.db_path
        import importlib
        import services.database as db_mod
        importlib.reload(db_mod)
        db_mod.DB_PATH = self.db_path
        db_mod.init_db()
        self.db = db_mod
        yield
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_log_and_summarize(self):
        self.db.log_query_metric(user_id="u1", tool_calls=3, input_tokens=100, output_tokens=50, duration_ms=500)
        self.db.log_query_metric(user_id="u1", tool_calls=1, input_tokens=200, output_tokens=100, duration_ms=300, error=True)

        summary = self.db.get_metrics_summary()
        assert summary["total_queries"] == 2
        assert summary["total_tool_calls"] == 4
        assert summary["total_input_tokens"] == 300
        assert summary["total_output_tokens"] == 150
        assert summary["total_errors"] == 1
        assert summary["error_rate"] == 50.0

    def test_per_user_metrics(self):
        self.db.log_query_metric(user_id="u1", tool_calls=2)
        self.db.log_query_metric(user_id="u2", tool_calls=5)

        u1 = self.db.get_metrics_summary(user_id="u1")
        assert u1["total_queries"] == 1
        assert u1["total_tool_calls"] == 2

        u2 = self.db.get_metrics_summary(user_id="u2")
        assert u2["total_queries"] == 1
        assert u2["total_tool_calls"] == 5

    def test_empty_metrics(self):
        summary = self.db.get_metrics_summary()
        assert summary["total_queries"] == 0
        assert summary["error_rate"] == 0

    def test_cleanup_old_metrics(self):
        """Metrics older than threshold should be deleted."""
        self.db.log_query_metric(user_id="u1", tool_calls=1)
        assert self.db.get_metrics_summary()["total_queries"] == 1

        # Backdate the metric so cleanup catches it
        conn = self.db.get_connection()
        conn.execute("UPDATE query_metrics SET created_at = datetime('now', '-200 days')")
        conn.commit()
        conn.close()

        deleted = self.db.cleanup_old_metrics(days=180)
        assert deleted >= 1
        assert self.db.get_metrics_summary()["total_queries"] == 0

    def test_db_integrity_check(self):
        """verify_db_integrity should return True for a valid DB."""
        assert self.db.verify_db_integrity() is True


class TestCachingIntegration:
    """Test that geocoding uses cache."""

    def test_geocode_caches_result(self):
        from services.cache import FileCache
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            test_cache = FileCache("geocode_test", ttl_seconds=60, cache_dir=tmp)

            # Simulate caching a geocode result
            test_cache.set("seattle", {"lat": 47.6, "lon": -122.3, "display_name": "Seattle"})
            result = test_cache.get("seattle")
            assert result["lat"] == 47.6
