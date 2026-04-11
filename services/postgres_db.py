"""PostgreSQL/PostGIS database backend for SpatialApp.

This is a STUB implementation that defines the migration path from SQLite
to PostgreSQL/PostGIS. The actual implementation will be completed when
the project is ready to scale beyond SQLite.

Requires: psycopg2-binary (or psycopg2), PostgreSQL 14+, PostGIS 3.3+
Install:  pip install psycopg2-binary
Config:   DATABASE_URL=postgresql://user:pass@host:5432/spatialapp
          DATABASE_BACKEND=postgres
"""

import logging
from typing import Optional

from services.db_interface import DatabaseInterface

logger = logging.getLogger(__name__)


class PostgresDatabase(DatabaseInterface):
    """PostgreSQL/PostGIS implementation of DatabaseInterface.

    This stub raises NotImplementedError for all methods, with docstrings
    showing the PostGIS SQL that each method will use. This serves as
    both documentation and a development guide for the full implementation.

    Connection pooling will use psycopg2.pool.ThreadedConnectionPool
    for thread-safe concurrent access.
    """

    def __init__(self, database_url: str):
        """Initialize PostgreSQL connection.

        Args:
            database_url: PostgreSQL connection string, e.g.
                postgresql://user:pass@localhost:5432/spatialapp

        Raises:
            NotImplementedError: Always, until implementation is complete.
        """
        if not database_url:
            raise ValueError(
                "DATABASE_URL is required for PostgreSQL backend. "
                "Example: postgresql://user:pass@localhost:5432/spatialapp"
            )
        self.database_url = database_url
        raise NotImplementedError(
            "PostgreSQL/PostGIS support is planned but not yet implemented. "
            "Set DATABASE_BACKEND=sqlite (default) to use SQLite. "
            "See docs/POSTGRES_MIGRATION.md for the migration roadmap."
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init_db(self):
        """Create tables with PostGIS geometry columns and spatial indexes.

        PostGIS SQL:
            CREATE EXTENSION IF NOT EXISTS postgis;

            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                api_token TEXT UNIQUE NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS annotations (
                id SERIAL PRIMARY KEY,
                user_id TEXT DEFAULT 'anonymous',
                category_name TEXT NOT NULL,
                color TEXT DEFAULT '#3388ff',
                source TEXT DEFAULT 'manual',
                geometry_json JSONB NOT NULL,
                geom GEOMETRY(Geometry, 4326),
                properties_json JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_annotations_geom
                ON annotations USING GIST (geom);

            CREATE TABLE IF NOT EXISTS layers (
                name TEXT NOT NULL,
                user_id TEXT DEFAULT 'anonymous',
                geojson JSONB NOT NULL,
                geom GEOMETRY(Geometry, 4326),
                feature_count INTEGER DEFAULT 0,
                style_json JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (name, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_layers_geom
                ON layers USING GIST (geom);

            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT DEFAULT 'anonymous',
                messages_json JSONB DEFAULT '[]',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS query_metrics (
                id SERIAL PRIMARY KEY,
                user_id TEXT DEFAULT 'anonymous',
                session_id TEXT,
                message TEXT,
                tool_calls INTEGER DEFAULT 0,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0,
                error BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

        Key differences from SQLite:
        - JSONB columns for structured data (faster queries, indexable)
        - GEOMETRY columns with SRID 4326 for spatial indexing
        - GIST indexes for spatial queries (ST_Within, ST_Intersects, etc.)
        - SERIAL instead of AUTOINCREMENT
        - TIMESTAMPTZ instead of TEXT timestamps
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def close_connection(self):
        """Return connection to pool.

        Uses psycopg2.pool.ThreadedConnectionPool.putconn() instead of
        closing the connection, for efficient connection reuse.
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def verify_db_integrity(self):
        """Check database connectivity and table existence.

        PostGIS SQL:
            SELECT tablename FROM pg_tables WHERE schemaname = 'public';
            SELECT PostGIS_Version();
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    # ------------------------------------------------------------------
    # User CRUD
    # ------------------------------------------------------------------

    def create_user(self, username, api_token=None):
        """Create a new user.

        PostGIS SQL:
            INSERT INTO users (user_id, username, api_token)
            VALUES (%s, %s, %s) RETURNING user_id;
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def get_user_by_token(self, api_token):
        """Look up user by token hash.

        PostGIS SQL:
            SELECT user_id, username, created_at FROM users
            WHERE api_token = %s;
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def get_user_by_id(self, user_id):
        """Look up user by ID.

        PostGIS SQL:
            SELECT user_id, username, created_at FROM users
            WHERE user_id = %s;
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def list_users(self):
        """List all users.

        PostGIS SQL:
            SELECT user_id, username, created_at FROM users
            ORDER BY created_at;
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    # ------------------------------------------------------------------
    # Annotation CRUD
    # ------------------------------------------------------------------

    def save_annotation(self, category_name, geometry, color="#3388ff",
                        source="manual", properties=None, user_id="anonymous"):
        """Save annotation with spatial geometry column.

        PostGIS SQL:
            INSERT INTO annotations
                (user_id, category_name, color, source, geometry_json, geom, properties_json)
            VALUES
                (%s, %s, %s, %s, %s::jsonb, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s::jsonb)
            RETURNING id;

        The `geom` column enables spatial queries like:
            SELECT * FROM annotations WHERE ST_Within(geom, ST_MakeEnvelope(...));
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def get_all_annotations(self, user_id=None, limit=None, offset=0):
        """Get annotations with optional spatial filtering.

        PostGIS SQL:
            SELECT id, category_name, color, source, geometry_json,
                   properties_json, created_at
            FROM annotations
            WHERE user_id = %s
            ORDER BY id
            LIMIT %s OFFSET %s;

        Future: add bbox parameter for spatial filtering:
            WHERE ST_Intersects(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def get_annotation_count(self, user_id=None):
        """Get annotation count.

        PostGIS SQL:
            SELECT COUNT(*) FROM annotations WHERE user_id = %s;
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def clear_annotations(self, user_id=None):
        """Delete annotations.

        PostGIS SQL:
            DELETE FROM annotations WHERE user_id = %s;
            -- or DELETE FROM annotations; (all)
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    # ------------------------------------------------------------------
    # Layer CRUD
    # ------------------------------------------------------------------

    def save_layer(self, name, geojson, style=None, user_id="anonymous"):
        """Save layer with spatial column.

        PostGIS SQL:
            INSERT INTO layers (name, user_id, geojson, geom, feature_count, style_json, created_at)
            VALUES (%s, %s, %s::jsonb,
                    ST_Collect(
                        ARRAY(SELECT ST_SetSRID(ST_GeomFromGeoJSON(f->>'geometry'), 4326)
                              FROM jsonb_array_elements(%s::jsonb->'features') AS f)
                    ),
                    %s, %s::jsonb, NOW())
            ON CONFLICT (name, user_id) DO UPDATE SET
                geojson = EXCLUDED.geojson,
                geom = EXCLUDED.geom,
                feature_count = EXCLUDED.feature_count,
                style_json = EXCLUDED.style_json,
                created_at = EXCLUDED.created_at;

        The `geom` column stores a GeometryCollection of all features,
        enabling spatial indexing and server-side spatial queries like:
            SELECT * FROM layers WHERE ST_Intersects(geom, ST_MakeEnvelope(...));
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def get_layer(self, name, user_id=None):
        """Get layer GeoJSON by name.

        PostGIS SQL:
            SELECT geojson FROM layers WHERE name = %s AND user_id = %s;
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def get_all_layers(self, user_id=None):
        """Get layer metadata.

        PostGIS SQL:
            SELECT name, feature_count, created_at,
                   ST_AsGeoJSON(ST_Envelope(geom)) as bbox
            FROM layers
            WHERE user_id = %s
            ORDER BY created_at DESC;

        Note: bbox is a bonus from PostGIS — spatial extent without
        deserializing the full GeoJSON.
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def delete_layer(self, name, user_id=None):
        """Delete a layer.

        PostGIS SQL:
            DELETE FROM layers WHERE name = %s AND user_id = %s;
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    # ------------------------------------------------------------------
    # Chat Session CRUD
    # ------------------------------------------------------------------

    def save_chat_session(self, session_id, messages, user_id="anonymous"):
        """Save or update chat session.

        PostGIS SQL:
            INSERT INTO chat_sessions (session_id, user_id, messages_json, updated_at)
            VALUES (%s, %s, %s::jsonb, NOW())
            ON CONFLICT (session_id) DO UPDATE SET
                messages_json = EXCLUDED.messages_json,
                updated_at = NOW();
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def get_chat_session(self, session_id):
        """Get chat session messages.

        PostGIS SQL:
            SELECT messages_json FROM chat_sessions WHERE session_id = %s;
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def delete_chat_session(self, session_id):
        """Delete a chat session.

        PostGIS SQL:
            DELETE FROM chat_sessions WHERE session_id = %s;
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def get_chat_session_with_owner(self, session_id):
        """Get chat session with owner info.

        PostGIS SQL:
            SELECT session_id, user_id, messages_json, created_at, updated_at
            FROM chat_sessions WHERE session_id = %s;
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def delete_chat_session_for_user(self, session_id, user_id):
        """Delete chat session only if owned by user.

        PostGIS SQL:
            DELETE FROM chat_sessions
            WHERE session_id = %s AND user_id = %s;
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def get_user_sessions(self, user_id):
        """Get all sessions for a user.

        PostGIS SQL:
            SELECT session_id, messages_json, created_at, updated_at
            FROM chat_sessions WHERE user_id = %s
            ORDER BY updated_at DESC;
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    # ------------------------------------------------------------------
    # Layer convenience
    # ------------------------------------------------------------------

    def get_user_layers(self, user_id):
        """Get all layers for a user. Delegates to get_all_layers.

        PostGIS SQL: same as get_all_layers(user_id=user_id)
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    # ------------------------------------------------------------------
    # Query Metrics
    # ------------------------------------------------------------------

    def log_query_metric(self, user_id="anonymous", session_id=None,
                         message="", tool_calls=0, input_tokens=0,
                         output_tokens=0, duration_ms=0, error=False):
        """Log a query metric.

        PostGIS SQL:
            INSERT INTO query_metrics
                (user_id, session_id, message, tool_calls,
                 input_tokens, output_tokens, duration_ms, error)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def get_metrics_summary(self, user_id=None):
        """Get aggregated metrics.

        PostGIS SQL:
            SELECT COUNT(*) as total_queries,
                   SUM(tool_calls) as total_tool_calls,
                   SUM(input_tokens) as total_input_tokens,
                   SUM(output_tokens) as total_output_tokens,
                   AVG(duration_ms) as avg_duration_ms,
                   SUM(CASE WHEN error THEN 1 ELSE 0 END) as total_errors,
                   MAX(created_at) as last_query_at
            FROM query_metrics
            WHERE user_id = %s;

        Note: PostgreSQL uses BOOLEAN natively instead of INTEGER 0/1.
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def cleanup_old_metrics(self, days=180):
        """Delete old metrics.

        PostGIS SQL:
            DELETE FROM query_metrics
            WHERE created_at < NOW() - INTERVAL '%s days';

        Note: PostgreSQL interval syntax differs from SQLite's datetime().
        """
        raise NotImplementedError("PostgreSQL implementation pending")

    def get_user_stats(self, user_id):
        """Get aggregated user stats for dashboard.

        Delegates to get_metrics_summary and reshapes the result.
        """
        raise NotImplementedError("PostgreSQL implementation pending")
