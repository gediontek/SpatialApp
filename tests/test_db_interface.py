"""Tests for database abstraction layer.

Verifies:
- DatabaseInterface defines all required methods
- Database (SQLite) implements all interface methods
- create_database() factory returns SQLite by default
- PostgresDatabase raises NotImplementedError with clear message
"""

import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDatabaseInterface:
    """Test that DatabaseInterface defines all required methods."""

    def test_interface_defines_all_crud_methods(self):
        """Interface must define all CRUD methods used by the application."""
        from services.db_interface import DatabaseInterface

        required_methods = [
            # Lifecycle
            "init_db",
            "close_connection",
            "verify_db_integrity",
            # User CRUD
            "create_user",
            "get_user_by_token",
            "get_user_by_id",
            "list_users",
            # Annotation CRUD
            "save_annotation",
            "get_all_annotations",
            "get_annotation_count",
            "clear_annotations",
            # Layer CRUD
            "save_layer",
            "get_layer",
            "get_all_layers",
            "delete_layer",
            # Chat Session CRUD
            "save_chat_session",
            "get_chat_session",
            "delete_chat_session",
            "get_chat_session_with_owner",
            "delete_chat_session_for_user",
            "get_user_sessions",
            # Layer convenience
            "get_user_layers",
            # Query Metrics
            "log_query_metric",
            "get_metrics_summary",
            "cleanup_old_metrics",
            "get_user_stats",
        ]

        for method_name in required_methods:
            assert hasattr(DatabaseInterface, method_name), (
                f"DatabaseInterface missing method: {method_name}"
            )
            method = getattr(DatabaseInterface, method_name)
            assert callable(method), f"{method_name} is not callable"

    def test_interface_methods_are_abstract(self):
        """All interface methods must be abstract."""
        from services.db_interface import DatabaseInterface

        # Get all methods that aren't dunder
        methods = [
            name for name, _ in inspect.getmembers(DatabaseInterface, predicate=inspect.isfunction)
            if not name.startswith("_")
        ]

        assert len(methods) > 0, "Interface has no public methods"

        for method_name in methods:
            method = getattr(DatabaseInterface, method_name)
            assert getattr(method, "__isabstractmethod__", False), (
                f"{method_name} should be abstract"
            )

    def test_cannot_instantiate_interface(self):
        """DatabaseInterface is abstract and cannot be instantiated."""
        from services.db_interface import DatabaseInterface

        with pytest.raises(TypeError):
            DatabaseInterface()


class TestSQLiteDatabaseImplementsInterface:
    """Test that the SQLite Database class implements all interface methods."""

    def test_database_is_subclass_of_interface(self):
        """Database must be a subclass of DatabaseInterface."""
        from services.database import Database
        from services.db_interface import DatabaseInterface

        assert issubclass(Database, DatabaseInterface)

    def test_database_implements_all_abstract_methods(self):
        """Database must implement every abstract method from the interface."""
        from services.database import Database
        from services.db_interface import DatabaseInterface

        # Get all abstract methods from the interface
        abstract_methods = [
            name for name, method in inspect.getmembers(DatabaseInterface, predicate=inspect.isfunction)
            if getattr(method, "__isabstractmethod__", False)
        ]

        for method_name in abstract_methods:
            assert hasattr(Database, method_name), (
                f"Database missing implementation of: {method_name}"
            )
            method = getattr(Database, method_name)
            # Should NOT be abstract in the concrete class
            assert not getattr(method, "__isabstractmethod__", False), (
                f"Database.{method_name} is still abstract"
            )

    def test_database_can_be_instantiated(self, tmp_path):
        """Database class can be instantiated with a path."""
        from services.database import Database

        db_path = str(tmp_path / "test.db")
        db = Database(db_path)
        assert db.db_path == db_path

    def test_database_init_and_verify(self, tmp_path):
        """Database class init_db and verify_db_integrity work."""
        from services.database import Database

        db_path = str(tmp_path / "test.db")
        db = Database(db_path)
        db.init_db()
        assert db.verify_db_integrity() is True

    def test_database_crud_round_trip(self, tmp_path):
        """Database class supports basic CRUD via the interface."""
        from services.database import Database

        db_path = str(tmp_path / "test.db")
        db = Database(db_path)
        db.init_db()

        # Annotation round-trip
        ann_id = db.save_annotation("building", {"type": "Point", "coordinates": [0, 0]})
        assert isinstance(ann_id, int)
        assert db.get_annotation_count() == 1

        features = db.get_all_annotations()
        assert len(features) == 1
        assert features[0]["properties"]["category_name"] == "building"

        db.clear_annotations()
        assert db.get_annotation_count() == 0

        # Layer round-trip
        geojson = {"type": "FeatureCollection", "features": []}
        db.save_layer("test_layer", geojson)
        result = db.get_layer("test_layer")
        assert result is not None
        assert result["type"] == "FeatureCollection"

        layers = db.get_all_layers()
        assert len(layers) == 1

        assert db.delete_layer("test_layer") is True
        assert db.get_layer("test_layer") is None

        # Chat session round-trip
        db.save_chat_session("sess1", [{"role": "user", "content": "hi"}])
        messages = db.get_chat_session("sess1")
        assert len(messages) == 1

        db.delete_chat_session("sess1")
        assert db.get_chat_session("sess1") is None


class TestPostgresDatabaseStub:
    """Test that PostgresDatabase raises NotImplementedError."""

    def test_postgres_is_subclass_of_interface(self):
        """PostgresDatabase must be a subclass of DatabaseInterface."""
        from services.postgres_db import PostgresDatabase
        from services.db_interface import DatabaseInterface

        assert issubclass(PostgresDatabase, DatabaseInterface)

    def test_postgres_raises_not_implemented(self):
        """PostgresDatabase constructor raises NotImplementedError."""
        from services.postgres_db import PostgresDatabase

        with pytest.raises(NotImplementedError) as exc_info:
            PostgresDatabase("postgresql://user:pass@localhost/testdb")

        error_msg = str(exc_info.value)
        assert "not yet implemented" in error_msg
        assert "SQLite" in error_msg or "sqlite" in error_msg

    def test_postgres_requires_url(self):
        """PostgresDatabase raises ValueError for empty URL."""
        from services.postgres_db import PostgresDatabase

        with pytest.raises(ValueError) as exc_info:
            PostgresDatabase("")

        assert "DATABASE_URL" in str(exc_info.value)

    def test_postgres_implements_all_abstract_methods(self):
        """PostgresDatabase must implement every abstract method."""
        from services.postgres_db import PostgresDatabase
        from services.db_interface import DatabaseInterface

        abstract_methods = [
            name for name, method in inspect.getmembers(DatabaseInterface, predicate=inspect.isfunction)
            if getattr(method, "__isabstractmethod__", False)
        ]

        for method_name in abstract_methods:
            assert hasattr(PostgresDatabase, method_name), (
                f"PostgresDatabase missing implementation of: {method_name}"
            )


class TestDatabaseFactory:
    """Test the database factory function."""

    def test_factory_returns_sqlite_by_default(self, tmp_path, monkeypatch):
        """Default config returns SQLite Database."""
        monkeypatch.setattr("config.Config.DATABASE_BACKEND", "sqlite")
        monkeypatch.setattr("config.Config.DATABASE_PATH", str(tmp_path / "test.db"))

        from app import _create_database
        db = _create_database()

        from services.database import Database
        assert isinstance(db, Database)

    def test_factory_returns_sqlite_explicitly(self, tmp_path, monkeypatch):
        """Explicit sqlite config returns SQLite Database."""
        monkeypatch.setattr("config.Config.DATABASE_BACKEND", "sqlite")
        monkeypatch.setattr("config.Config.DATABASE_PATH", str(tmp_path / "test.db"))

        from app import _create_database
        db = _create_database()

        from services.database import Database
        assert isinstance(db, Database)

    def test_factory_raises_for_postgres(self, monkeypatch):
        """Postgres config raises NotImplementedError."""
        monkeypatch.setattr("config.Config.DATABASE_BACKEND", "postgres")
        monkeypatch.setattr("config.Config.DATABASE_URL", "postgresql://user:pass@localhost/test")

        from app import _create_database
        with pytest.raises(NotImplementedError):
            _create_database()

    def test_factory_raises_for_unknown_backend(self, monkeypatch):
        """Unknown backend raises ValueError."""
        monkeypatch.setattr("config.Config.DATABASE_BACKEND", "mongodb")

        from app import _create_database
        with pytest.raises(ValueError) as exc_info:
            _create_database()

        assert "mongodb" in str(exc_info.value)
