"""SQLite database for annotations, layers, and chat sessions.

Uses plain SQLite (no SpatiaLite dependency) with GeoJSON stored as TEXT.
Spatial indexing deferred until PostGIS migration.

This module provides both module-level functions (legacy API) and a
Database class that implements DatabaseInterface for the new abstraction layer.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import datetime
import threading
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DATABASE_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "spatialapp.db"))

_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """Get or create a thread-local SQLite connection.

    Reuses the same connection within a thread to avoid excessive
    connection churn. Call close_connection() at request end to release.
    """
    conn = getattr(_local, 'conn', None)
    db_path = getattr(_local, 'db_path', None)
    if conn is not None and db_path == DB_PATH:
        try:
            # Verify the connection is still usable
            conn.execute("SELECT 1")
            return conn
        except Exception:
            _local.conn = None
            _local.db_path = None
    elif conn is not None:
        # DB_PATH changed (e.g. tests), close old connection
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    _local.conn = conn
    _local.db_path = DB_PATH
    return conn


def close_connection():
    """Close the thread-local connection (call at request end)."""
    conn = getattr(_local, 'conn', None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            logger.debug("Error closing thread-local connection", exc_info=True)
        _local.conn = None


def init_db():
    """Create database tables if they don't exist.

    Handles migration from older schemas gracefully:
    - Adds user_id columns to existing tables
    - Creates new tables (users, query_metrics) if missing
    - Layers table keeps original PK on existing DBs
    """
    conn = get_connection()
    # Create tables individually to handle existing DBs gracefully
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            api_token TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT DEFAULT 'anonymous',
            category_name TEXT NOT NULL,
            color TEXT DEFAULT '#3388ff',
            source TEXT DEFAULT 'manual',
            geometry_json TEXT NOT NULL,
            properties_json TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Layers table: on fresh DBs use composite PK (name, user_id).
    # On existing DBs, the table already exists with name TEXT PRIMARY KEY
    # and user_id gets added via migration below.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS layers (
            name TEXT NOT NULL,
            user_id TEXT DEFAULT 'anonymous',
            geojson TEXT NOT NULL,
            feature_count INTEGER DEFAULT 0,
            style_json TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (name, user_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT DEFAULT 'anonymous',
            messages_json TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Real-time collaboration sessions (v2.1 Plan 09)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS collab_sessions (
            session_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            session_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_state TEXT DEFAULT '{}'
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS query_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT DEFAULT 'anonymous',
            session_id TEXT,
            message TEXT,
            tool_calls INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            error INTEGER DEFAULT 0,
            tool_details_json TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create indexes (IF NOT EXISTS handles idempotency)
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_annotations_category ON annotations(category_name)",
        "CREATE INDEX IF NOT EXISTS idx_annotations_source ON annotations(source)",
        "CREATE INDEX IF NOT EXISTS idx_metrics_created ON query_metrics(created_at)",
    ]:
        conn.execute(idx_sql)

    # Migration: add user_id columns to existing tables if missing
    _migrate_add_column(conn, "annotations", "user_id", "TEXT DEFAULT 'anonymous'")
    _migrate_add_column(conn, "layers", "user_id", "TEXT DEFAULT 'anonymous'")
    _migrate_add_column(conn, "chat_sessions", "user_id", "TEXT DEFAULT 'anonymous'")
    # Migration: add tool_details_json column to query_metrics if missing
    _migrate_add_column(conn, "query_metrics", "tool_details_json", "TEXT DEFAULT '[]'")

    # Create user_id indexes (only after migration ensures columns exist)
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_annotations_user ON annotations(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_user ON chat_sessions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_metrics_user ON query_metrics(user_id)",
    ]:
        try:
            conn.execute(idx_sql)
        except Exception:
            logger.debug("Index creation skipped (column may not exist): %s", idx_sql, exc_info=True)

    # layers.user_id index — only if column was added successfully
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_layers_user ON layers(user_id)")
    except Exception:
        logger.debug("layers.user_id index creation skipped", exc_info=True)

    conn.commit()
    logger.info("Database initialized at %s", DB_PATH)


_ALLOWED_TABLES = {"users", "annotations", "layers", "chat_sessions", "query_metrics", "collab_sessions"}
_ALLOWED_COLUMNS = {"user_id", "username", "api_token", "category_name", "color",
                    "source", "geometry_json", "properties_json", "geojson",
                    "feature_count", "style_json", "messages_json", "session_id",
                    "message", "tool_calls", "input_tokens", "output_tokens",
                    "duration_ms", "error", "tool_details_json",
                    "created_at", "updated_at", "name"}


def _migrate_add_column(conn, table: str, column: str, definition: str):
    """Add a column to a table if it doesn't already exist."""
    if table not in _ALLOWED_TABLES:
        logger.warning(f"Migration refused: unknown table '{table}'")
        return
    if column not in _ALLOWED_COLUMNS:
        logger.warning(f"Migration refused: unknown column '{column}'")
        return
    try:
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            logger.info(f"Migrated: added {column} to {table}")
    except Exception as e:
        logger.warning(f"Migration check failed for {table}.{column}: {e}")


# ============================================================
# User CRUD
# ============================================================

def _hash_token(token: str) -> str:
    """SHA-256 hash of an API token for secure storage."""
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


def create_user(username: str, api_token: str = None) -> dict:
    """Create a new user. Returns dict with user_id, username, api_token.

    The raw token is returned ONLY at creation time. The database stores
    a SHA-256 hash + the first 8 characters as a display prefix.
    """
    import uuid
    user_id = str(uuid.uuid4())
    if not api_token:
        api_token = f"sk-spa-{uuid.uuid4().hex}"
    token_hash = _hash_token(api_token)
    token_prefix = api_token[:12] + "..."
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (user_id, username, api_token) VALUES (?, ?, ?)",
            (user_id, username, token_hash)
        )
        conn.commit()
        return {"user_id": user_id, "username": username, "api_token": api_token, "token_prefix": token_prefix}
    except Exception:
        conn.rollback()
        raise


def get_user_by_token(api_token: str) -> Optional[dict]:
    """Look up a user by API token hash. Returns dict or None."""
    token_hash = _hash_token(api_token)
    conn = get_connection()
    row = conn.execute("SELECT user_id, username, created_at FROM users WHERE api_token = ?", (token_hash,)).fetchone()
    if not row:
        return None
    return {"user_id": row["user_id"], "username": row["username"], "created_at": row["created_at"]}


def get_user_by_id(user_id: str) -> Optional[dict]:
    """Look up a user by ID. Does not return the token hash."""
    conn = get_connection()
    row = conn.execute("SELECT user_id, username, created_at FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return None
    return {"user_id": row["user_id"], "username": row["username"], "created_at": row["created_at"]}


def list_users() -> list:
    """List all users (without tokens)."""
    conn = get_connection()
    rows = conn.execute("SELECT user_id, username, created_at FROM users ORDER BY created_at").fetchall()
    return [{"user_id": r["user_id"], "username": r["username"], "created_at": r["created_at"]} for r in rows]


# ============================================================
# Annotation CRUD
# ============================================================

def save_annotation(category_name: str, geometry: dict, color: str = "#3388ff",
                    source: str = "manual", properties: dict = None,
                    user_id: str = "anonymous") -> int:
    """Save an annotation to the database. Returns the new ID."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO annotations (user_id, category_name, color, source, geometry_json, properties_json) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, category_name, color, source, json.dumps(geometry), json.dumps(properties or {}))
        )
        conn.commit()
        return cursor.lastrowid
    except Exception:
        conn.rollback()
        raise


def get_all_annotations(user_id: str = None, limit: int = None, offset: int = 0) -> list:
    """Get annotations as GeoJSON features. Supports pagination and user filtering."""
    conn = get_connection()
    query = "SELECT * FROM annotations"
    params = []
    if user_id:
        query += " WHERE user_id = ?"
        params.append(user_id)
    query += " ORDER BY id"
    if limit:
        query += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    rows = conn.execute(query, params).fetchall()
    features = []
    for row in rows:
        try:
            geom = json.loads(row["geometry_json"])
            props = json.loads(row["properties_json"]) if row["properties_json"] else {}
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Skipping corrupt annotation id={row['id']}")
            continue
        features.append({
            "type": "Feature",
            "id": row["id"],
            "geometry": geom,
            "properties": {
                "category_name": row["category_name"],
                "color": row["color"],
                "source": row["source"],
                "created_at": row["created_at"],
                **props,
            },
        })
    return features


def get_annotation_count(user_id: str = None) -> int:
    """Get annotation count, optionally filtered by user."""
    conn = get_connection()
    if user_id:
        row = conn.execute("SELECT COUNT(*) as cnt FROM annotations WHERE user_id = ?", (user_id,)).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) as cnt FROM annotations").fetchone()
    return row["cnt"]


def clear_annotations(user_id: str = None):
    """Delete annotations. If user_id given, only that user's annotations."""
    conn = get_connection()
    try:
        if user_id:
            conn.execute("DELETE FROM annotations WHERE user_id = ?", (user_id,))
        else:
            conn.execute("DELETE FROM annotations")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ============================================================
# Layer CRUD
# ============================================================

def save_layer(name: str, geojson: dict, style: dict = None, user_id: str = "anonymous"):
    """Save or update a named layer."""
    feature_count = len(geojson.get("features", [])) if isinstance(geojson, dict) else 0
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO layers (name, user_id, geojson, feature_count, style_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name, user_id, json.dumps(geojson), feature_count, json.dumps(style or {}), datetime.datetime.now().isoformat())
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def get_layer(name: str, user_id: str = None) -> Optional[dict]:
    """Get a layer by name. Returns GeoJSON dict or None."""
    conn = get_connection()
    if user_id:
        row = conn.execute("SELECT geojson FROM layers WHERE name = ? AND user_id = ?", (name, user_id)).fetchone()
    else:
        row = conn.execute("SELECT geojson FROM layers WHERE name = ?", (name,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["geojson"])
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"Corrupt layer data for '{name}'")
        return None


def get_all_layers(user_id: str = None) -> list:
    """Get layer metadata, optionally filtered by user."""
    conn = get_connection()
    if user_id:
        rows = conn.execute("SELECT name, feature_count, created_at FROM layers WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
    else:
        rows = conn.execute("SELECT name, feature_count, created_at FROM layers ORDER BY created_at DESC").fetchall()
    return [{"name": r["name"], "feature_count": r["feature_count"], "created_at": r["created_at"]} for r in rows]


def delete_layer(name: str, user_id: str = None) -> bool:
    """Delete a layer. Returns True if deleted."""
    conn = get_connection()
    try:
        if user_id:
            cursor = conn.execute("DELETE FROM layers WHERE name = ? AND user_id = ?", (name, user_id))
        else:
            cursor = conn.execute("DELETE FROM layers WHERE name = ?", (name,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        conn.rollback()
        raise


# ============================================================
# Chat Session CRUD
# ============================================================

def save_chat_session(session_id: str, messages: list, user_id: str = "anonymous"):
    """Save or update a chat session."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO chat_sessions (session_id, user_id, messages_json, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, user_id, json.dumps(messages, default=str), datetime.datetime.now().isoformat())
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def get_chat_session(session_id: str) -> Optional[list]:
    """Get chat session messages. Returns list or None."""
    conn = get_connection()
    row = conn.execute("SELECT messages_json FROM chat_sessions WHERE session_id = ?", (session_id,)).fetchone()
    return json.loads(row["messages_json"]) if row else None


def delete_chat_session(session_id: str):
    """Delete a chat session."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ============================================================
# Query Metrics
# ============================================================

def log_query_metric(user_id: str = "anonymous", session_id: str = None,
                     message: str = "", tool_calls: int = 0,
                     input_tokens: int = 0, output_tokens: int = 0,
                     duration_ms: int = 0, error: bool = False,
                     tool_details: list = None):
    """Log a single query metric.

    Args:
        tool_details: Optional list of per-tool-call dicts with keys:
            tool (str), success (bool), chain_position (int), retry (bool).
    """
    conn = get_connection()
    tool_details_json = json.dumps(tool_details or [])
    try:
        conn.execute(
            "INSERT INTO query_metrics (user_id, session_id, message, tool_calls, input_tokens, output_tokens, duration_ms, error, tool_details_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, session_id, message[:200], tool_calls, input_tokens, output_tokens, duration_ms, 1 if error else 0, tool_details_json)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def cleanup_old_metrics(days: int = 180):
    """Delete query metrics older than N days."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM query_metrics WHERE created_at < datetime('now', ?)",
            (f"-{days} days",)
        )
        conn.commit()
        deleted = cursor.rowcount
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} query metrics older than {days} days")
        return deleted
    except Exception:
        conn.rollback()
        raise


def verify_db_integrity() -> bool:
    """Check that the database file exists and has expected tables."""
    if not os.path.exists(DB_PATH):
        logger.error(f"Database file missing: {DB_PATH}")
        return False
    try:
        conn = get_connection()
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        expected = {"users", "annotations", "layers", "chat_sessions", "query_metrics"}
        missing = expected - set(tables)
        if missing:
            logger.error(f"Database missing tables: {missing}")
            return False
        return True
    except Exception as e:
        logger.error(f"Database integrity check failed: {e}")
        return False


def get_user_sessions(user_id: str) -> list:
    """Get all chat sessions for a user, with message counts."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT session_id, messages_json, created_at, updated_at FROM chat_sessions WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,)
    ).fetchall()
    result = []
    for r in rows:
        try:
            messages = json.loads(r["messages_json"]) if r["messages_json"] else []
        except (json.JSONDecodeError, TypeError):
            messages = []
        result.append({
            "session_id": r["session_id"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "message_count": len(messages),
        })
    return result


def get_user_layers(user_id: str) -> list:
    """Get all layers for a user with metadata."""
    return get_all_layers(user_id=user_id)


def get_user_stats(user_id: str) -> dict:
    """Get aggregated query stats for a user (for dashboard)."""
    summary = get_metrics_summary(user_id=user_id)
    return {
        "total_queries": summary["total_queries"],
        "total_tokens_used": summary["total_input_tokens"] + summary["total_output_tokens"],
        "avg_response_time_ms": summary["avg_duration_ms"],
        "total_tool_calls": summary["total_tool_calls"],
    }


def get_chat_session_with_owner(session_id: str) -> Optional[dict]:
    """Get a chat session with its owner user_id. Returns dict or None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT session_id, user_id, messages_json, created_at, updated_at FROM chat_sessions WHERE session_id = ?",
        (session_id,)
    ).fetchone()
    if not row:
        return None
    try:
        messages = json.loads(row["messages_json"]) if row["messages_json"] else []
    except (json.JSONDecodeError, TypeError):
        messages = []
    return {
        "session_id": row["session_id"],
        "user_id": row["user_id"],
        "messages": messages,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def delete_chat_session_for_user(session_id: str, user_id: str) -> bool:
    """Delete a chat session only if owned by user_id. Returns True if deleted."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM chat_sessions WHERE session_id = ? AND user_id = ?",
            (session_id, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        conn.rollback()
        raise


def get_tool_stats(user_id: str = None) -> dict:
    """Aggregate per-tool usage statistics from tool_details_json.

    Returns dict with:
        most_used: list of {tool, count} sorted by count desc (top 10)
        failure_rate: dict of tool -> failure rate (0.0-1.0)
        avg_chain_length: average number of tool calls per query
    """
    conn = get_connection()
    where = "WHERE user_id = ?" if user_id else ""
    params = (user_id,) if user_id else ()

    rows = conn.execute(
        f"SELECT tool_details_json, tool_calls FROM query_metrics {where}",
        params
    ).fetchall()

    tool_counts = {}  # tool -> total count
    tool_failures = {}  # tool -> failure count
    total_chains = 0
    total_chain_length = 0

    for row in rows:
        tc = row["tool_calls"] or 0
        if tc > 0:
            total_chains += 1
            total_chain_length += tc

        details_raw = row["tool_details_json"]
        if not details_raw:
            continue
        try:
            details = json.loads(details_raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for entry in details:
            tool = entry.get("tool", "unknown")
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
            if not entry.get("success", True):
                tool_failures[tool] = tool_failures.get(tool, 0) + 1

    most_used = sorted(
        [{"tool": t, "count": c} for t, c in tool_counts.items()],
        key=lambda x: x["count"], reverse=True
    )[:10]

    failure_rate = {}
    for tool, count in tool_counts.items():
        failures = tool_failures.get(tool, 0)
        failure_rate[tool] = round(failures / count, 3) if count > 0 else 0.0

    avg_chain = round(total_chain_length / total_chains, 1) if total_chains > 0 else 0.0

    return {
        "most_used": most_used,
        "failure_rate": failure_rate,
        "avg_chain_length": avg_chain,
    }


def get_metrics_summary(user_id: str = None) -> dict:
    """Get aggregated metrics. Optionally filter by user."""
    conn = get_connection()
    where = "WHERE user_id = ?" if user_id else ""
    params = (user_id,) if user_id else ()

    row = conn.execute(f"""
        SELECT
            COUNT(*) as total_queries,
            SUM(tool_calls) as total_tool_calls,
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            AVG(duration_ms) as avg_duration_ms,
            SUM(error) as total_errors,
            MAX(created_at) as last_query_at
        FROM query_metrics {where}
    """, params).fetchone()

    total = row["total_queries"] or 0
    return {
        "total_queries": total,
        "total_tool_calls": row["total_tool_calls"] or 0,
        "total_input_tokens": row["total_input_tokens"] or 0,
        "total_output_tokens": row["total_output_tokens"] or 0,
        "avg_duration_ms": round(row["avg_duration_ms"] or 0, 1),
        "total_errors": row["total_errors"] or 0,
        "error_rate": round((row["total_errors"] or 0) / total * 100, 1) if total > 0 else 0,
        "last_query_at": row["last_query_at"],
    }


# ============================================================
# Database class (implements DatabaseInterface)
# ============================================================

from services.db_interface import DatabaseInterface


# ============================================================
# Collaboration session CRUD (v2.1 Plan 09)
# ============================================================

def save_collab_session(session_id: str, state_dict: dict, owner_user_id: str = "anonymous",
                        session_name: str | None = None) -> None:
    """Persist a collaboration session's serializable state.

    `state_dict` should be a JSON-safe dict. We strip socket IDs since
    they're transient — they don't help on resume.
    """
    payload = dict(state_dict)
    # Sanitize per-user transient fields
    if "users" in payload and isinstance(payload["users"], dict):
        clean_users = {}
        for uid, u in payload["users"].items():
            if not isinstance(u, dict):
                continue
            clean_users[uid] = {
                k: v for k, v in u.items()
                if k not in {"sid", "last_cursor_ts"}
            }
        payload["users"] = clean_users
    body = json.dumps(payload, default=str)
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO collab_sessions
                (session_id, owner_user_id, session_name, last_active, session_state)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                last_active = CURRENT_TIMESTAMP,
                session_state = excluded.session_state,
                session_name = COALESCE(excluded.session_name, session_name)
            """,
            (session_id, owner_user_id, session_name, body),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def get_collab_session(session_id: str) -> dict | None:
    """Retrieve a persisted collab session by id, or None if missing."""
    conn = get_connection()
    row = conn.execute(
        "SELECT session_id, owner_user_id, session_name, created_at, last_active, session_state "
        "FROM collab_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if not row:
        return None
    try:
        state = json.loads(row["session_state"]) if row["session_state"] else {}
    except (json.JSONDecodeError, TypeError):
        state = {}
    return {
        "session_id": row["session_id"],
        "owner_user_id": row["owner_user_id"],
        "session_name": row["session_name"],
        "created_at": row["created_at"],
        "last_active": row["last_active"],
        "state": state,
    }


def delete_collab_session(session_id: str) -> int:
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM collab_sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        return cur.rowcount or 0
    except Exception:
        conn.rollback()
        raise


def list_collab_sessions(owner_user_id: str | None = None) -> list[dict]:
    conn = get_connection()
    if owner_user_id:
        rows = conn.execute(
            "SELECT session_id, owner_user_id, session_name, created_at, last_active "
            "FROM collab_sessions WHERE owner_user_id = ? ORDER BY last_active DESC",
            (owner_user_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT session_id, owner_user_id, session_name, created_at, last_active "
            "FROM collab_sessions ORDER BY last_active DESC",
        ).fetchall()
    return [dict(r) for r in rows]


class Database(DatabaseInterface):
    """SQLite implementation of DatabaseInterface.

    Wraps the module-level functions above, adding a db_path parameter
    so multiple instances can target different database files (useful
    for testing and multi-tenant deployments).
    """

    def __init__(self, db_path: str = None):
        """Initialize with an optional database path.

        Args:
            db_path: Path to the SQLite database file. If None, uses
                     the module-level DB_PATH default.
        """
        global DB_PATH
        if db_path is not None:
            DB_PATH = db_path
        self.db_path = DB_PATH

    # -- Lifecycle -------------------------------------------------------

    def init_db(self):
        return init_db()

    def close_connection(self):
        return close_connection()

    def verify_db_integrity(self):
        return verify_db_integrity()

    # -- User CRUD -------------------------------------------------------

    def create_user(self, username, api_token=None):
        return create_user(username, api_token)

    def get_user_by_token(self, api_token):
        return get_user_by_token(api_token)

    def get_user_by_id(self, user_id):
        return get_user_by_id(user_id)

    def list_users(self):
        return list_users()

    # -- Annotation CRUD -------------------------------------------------

    def save_annotation(self, category_name, geometry, color="#3388ff",
                        source="manual", properties=None, user_id="anonymous"):
        return save_annotation(category_name, geometry, color, source,
                               properties, user_id)

    def get_all_annotations(self, user_id=None, limit=None, offset=0):
        return get_all_annotations(user_id, limit, offset)

    def get_annotation_count(self, user_id=None):
        return get_annotation_count(user_id)

    def clear_annotations(self, user_id=None):
        return clear_annotations(user_id)

    # -- Layer CRUD ------------------------------------------------------

    def save_layer(self, name, geojson, style=None, user_id="anonymous"):
        return save_layer(name, geojson, style, user_id)

    def get_layer(self, name, user_id=None):
        return get_layer(name, user_id)

    def get_all_layers(self, user_id=None):
        return get_all_layers(user_id)

    def delete_layer(self, name, user_id=None):
        return delete_layer(name, user_id)

    # -- Chat Session CRUD -----------------------------------------------

    def save_chat_session(self, session_id, messages, user_id="anonymous"):
        return save_chat_session(session_id, messages, user_id)

    def get_chat_session(self, session_id):
        return get_chat_session(session_id)

    def delete_chat_session(self, session_id):
        return delete_chat_session(session_id)

    def get_chat_session_with_owner(self, session_id):
        return get_chat_session_with_owner(session_id)

    def delete_chat_session_for_user(self, session_id, user_id):
        return delete_chat_session_for_user(session_id, user_id)

    def get_user_sessions(self, user_id):
        return get_user_sessions(user_id)

    # -- Layer convenience -----------------------------------------------

    def get_user_layers(self, user_id):
        return get_user_layers(user_id)

    # -- Collaboration sessions (v2.1 Plan 09) ---------------------------

    def save_collab_session(self, session_id, state_dict,
                            owner_user_id="anonymous", session_name=None):
        return save_collab_session(session_id, state_dict, owner_user_id, session_name)

    def get_collab_session(self, session_id):
        return get_collab_session(session_id)

    def delete_collab_session(self, session_id):
        return delete_collab_session(session_id)

    def list_collab_sessions(self, owner_user_id=None):
        return list_collab_sessions(owner_user_id)

    # -- Query Metrics ---------------------------------------------------

    def log_query_metric(self, user_id="anonymous", session_id=None,
                         message="", tool_calls=0, input_tokens=0,
                         output_tokens=0, duration_ms=0, error=False,
                         tool_details=None):
        return log_query_metric(user_id, session_id, message, tool_calls,
                                input_tokens, output_tokens, duration_ms, error,
                                tool_details)

    def get_metrics_summary(self, user_id=None):
        return get_metrics_summary(user_id)

    def get_tool_stats(self, user_id=None):
        return get_tool_stats(user_id)

    def cleanup_old_metrics(self, days=180):
        return cleanup_old_metrics(days)

    def get_user_stats(self, user_id):
        return get_user_stats(user_id)
