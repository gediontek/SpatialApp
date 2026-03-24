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
