"""Tests for services.database module."""

import json
import os
import pytest
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Set up a temporary database for each test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)

    # Reload the module so it picks up the new DB_PATH
    import importlib
    import services.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


SAMPLE_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
}


class TestInitDB:
    """Test database initialization."""

    def test_init_creates_tables(self, test_db):
        """init_db creates all expected tables."""
        conn = test_db.get_connection()
        try:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            for expected in ("users", "annotations", "layers", "chat_sessions", "query_metrics"):
                assert expected in tables, f"Missing table: {expected}"
        finally:
            conn.close()

    def test_init_is_idempotent(self, test_db):
        """Running init_db twice should not fail."""
        test_db.init_db()  # Second call
        assert test_db.verify_db_integrity() is True

    def test_verify_integrity(self, test_db):
        assert test_db.verify_db_integrity() is True


class TestAnnotationCRUD:
    """Test annotation save/get round-trip."""

    def test_save_and_get_annotation(self, test_db):
        ann_id = test_db.save_annotation(
            category_name="building",
            geometry=SAMPLE_GEOMETRY,
            color="#ff0000",
            source="manual",
            properties={"height": 10},
        )
        assert isinstance(ann_id, int)
        assert ann_id > 0

        features = test_db.get_all_annotations()
        assert len(features) == 1
        feat = features[0]
        assert feat["properties"]["category_name"] == "building"
        assert feat["properties"]["color"] == "#ff0000"
        assert feat["geometry"]["type"] == "Polygon"

    def test_annotation_count(self, test_db):
        assert test_db.get_annotation_count() == 0
        test_db.save_annotation("park", SAMPLE_GEOMETRY)
        test_db.save_annotation("water", SAMPLE_GEOMETRY)
        assert test_db.get_annotation_count() == 2

    def test_annotation_user_filter(self, test_db):
        test_db.save_annotation("a", SAMPLE_GEOMETRY, user_id="user1")
        test_db.save_annotation("b", SAMPLE_GEOMETRY, user_id="user2")
        test_db.save_annotation("c", SAMPLE_GEOMETRY, user_id="user1")

        assert test_db.get_annotation_count(user_id="user1") == 2
        assert test_db.get_annotation_count(user_id="user2") == 1

        features = test_db.get_all_annotations(user_id="user1")
        assert len(features) == 2

    def test_clear_annotations(self, test_db):
        test_db.save_annotation("building", SAMPLE_GEOMETRY)
        test_db.save_annotation("park", SAMPLE_GEOMETRY)
        assert test_db.get_annotation_count() == 2

        test_db.clear_annotations()
        assert test_db.get_annotation_count() == 0

    def test_clear_annotations_by_user(self, test_db):
        test_db.save_annotation("a", SAMPLE_GEOMETRY, user_id="user1")
        test_db.save_annotation("b", SAMPLE_GEOMETRY, user_id="user2")

        test_db.clear_annotations(user_id="user1")
        assert test_db.get_annotation_count() == 1
        features = test_db.get_all_annotations()
        assert features[0]["properties"]["category_name"] == "b"

    def test_annotation_pagination(self, test_db):
        for i in range(5):
            test_db.save_annotation(f"cat_{i}", SAMPLE_GEOMETRY)

        page = test_db.get_all_annotations(limit=2, offset=0)
        assert len(page) == 2

        page2 = test_db.get_all_annotations(limit=2, offset=2)
        assert len(page2) == 2


class TestLayerCRUD:
    """Test layer save/get round-trip."""

    def test_save_and_get_layer(self, test_db):
        geojson = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": SAMPLE_GEOMETRY, "properties": {}}
        ]}
        test_db.save_layer("test_layer", geojson, style={"color": "red"})

        result = test_db.get_layer("test_layer")
        assert result is not None
        assert result["type"] == "FeatureCollection"
        assert len(result["features"]) == 1

    def test_get_nonexistent_layer(self, test_db):
        assert test_db.get_layer("nonexistent") is None

    def test_get_all_layers(self, test_db):
        geojson = {"type": "FeatureCollection", "features": []}
        test_db.save_layer("layer_a", geojson)
        test_db.save_layer("layer_b", geojson)

        layers = test_db.get_all_layers()
        assert len(layers) == 2
        names = {l["name"] for l in layers}
        assert names == {"layer_a", "layer_b"}

    def test_delete_layer(self, test_db):
        geojson = {"type": "FeatureCollection", "features": []}
        test_db.save_layer("to_delete", geojson)
        assert test_db.get_layer("to_delete") is not None

        deleted = test_db.delete_layer("to_delete")
        assert deleted is True
        assert test_db.get_layer("to_delete") is None

    def test_delete_nonexistent_layer(self, test_db):
        deleted = test_db.delete_layer("nonexistent")
        assert deleted is False

    def test_save_layer_upsert(self, test_db):
        geojson_v1 = {"type": "FeatureCollection", "features": []}
        geojson_v2 = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": SAMPLE_GEOMETRY, "properties": {}}
        ]}
        test_db.save_layer("upsert_layer", geojson_v1)
        test_db.save_layer("upsert_layer", geojson_v2)

        result = test_db.get_layer("upsert_layer")
        assert len(result["features"]) == 1


class TestChatSessionCRUD:
    """Test chat session save/get round-trip."""

    def test_save_and_get_session(self, test_db):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        test_db.save_chat_session("session_1", messages)

        result = test_db.get_chat_session("session_1")
        assert result is not None
        assert len(result) == 2
        assert result[0]["role"] == "user"

    def test_get_nonexistent_session(self, test_db):
        assert test_db.get_chat_session("nonexistent") is None

    def test_delete_session(self, test_db):
        test_db.save_chat_session("to_delete", [{"role": "user", "content": "hi"}])
        assert test_db.get_chat_session("to_delete") is not None

        test_db.delete_chat_session("to_delete")
        assert test_db.get_chat_session("to_delete") is None

    def test_session_update(self, test_db):
        test_db.save_chat_session("session_1", [{"role": "user", "content": "v1"}])
        test_db.save_chat_session("session_1", [
            {"role": "user", "content": "v1"},
            {"role": "assistant", "content": "v2"},
        ])
        result = test_db.get_chat_session("session_1")
        assert len(result) == 2


class TestMetrics:
    """Test query metrics logging and summary."""

    def test_log_and_get_metrics(self, test_db):
        test_db.log_query_metric(
            user_id="user1",
            session_id="sess1",
            message="show parks",
            tool_calls=2,
            input_tokens=500,
            output_tokens=200,
            duration_ms=1500,
            error=False,
        )
        summary = test_db.get_metrics_summary()
        assert summary["total_queries"] == 1
        assert summary["total_input_tokens"] == 500
        assert summary["total_output_tokens"] == 200
        assert summary["total_tool_calls"] == 2
        assert summary["total_errors"] == 0

    def test_metrics_with_errors(self, test_db):
        test_db.log_query_metric(error=True)
        test_db.log_query_metric(error=False)
        summary = test_db.get_metrics_summary()
        assert summary["total_queries"] == 2
        assert summary["total_errors"] == 1
        assert summary["error_rate"] == 50.0

    def test_metrics_user_filter(self, test_db):
        test_db.log_query_metric(user_id="user1", input_tokens=100)
        test_db.log_query_metric(user_id="user2", input_tokens=200)

        summary = test_db.get_metrics_summary(user_id="user1")
        assert summary["total_queries"] == 1
        assert summary["total_input_tokens"] == 100

    def test_cleanup_old_metrics(self, test_db):
        test_db.log_query_metric(message="recent")
        # Force-insert an old metric
        conn = test_db.get_connection()
        try:
            conn.execute(
                "INSERT INTO query_metrics (message, created_at) VALUES (?, datetime('now', '-200 days'))",
                ("old",),
            )
            conn.commit()
        finally:
            conn.close()

        deleted = test_db.cleanup_old_metrics(days=180)
        assert deleted == 1
        summary = test_db.get_metrics_summary()
        assert summary["total_queries"] == 1

    def test_empty_metrics_summary(self, test_db):
        summary = test_db.get_metrics_summary()
        assert summary["total_queries"] == 0
        assert summary["error_rate"] == 0


class TestDeleteOperations:
    """Test delete operations across all entity types."""

    def test_delete_all_annotations(self, test_db):
        for i in range(3):
            test_db.save_annotation(f"cat_{i}", SAMPLE_GEOMETRY)
        test_db.clear_annotations()
        assert test_db.get_annotation_count() == 0

    def test_delete_layer_returns_false_for_missing(self, test_db):
        assert test_db.delete_layer("no_such_layer") is False

    def test_delete_session_idempotent(self, test_db):
        # Deleting a non-existent session should not raise
        test_db.delete_chat_session("no_such_session")
