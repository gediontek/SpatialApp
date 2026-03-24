"""SQLite database for annotations, layers, and chat sessions.

Uses plain SQLite (no SpatiaLite dependency) with GeoJSON stored as TEXT.
Spatial indexing deferred until PostGIS migration.
"""

import json
import logging
import os
import sqlite3
import datetime
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DATABASE_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "spatialapp.db"))


def get_connection() -> sqlite3.Connection:
    """Get a SQLite connection with row factory."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create database tables if they don't exist."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_name TEXT NOT NULL,
                color TEXT DEFAULT '#3388ff',
                source TEXT DEFAULT 'manual',
                geometry_json TEXT NOT NULL,
                properties_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS layers (
                name TEXT PRIMARY KEY,
                geojson TEXT NOT NULL,
                feature_count INTEGER DEFAULT 0,
                style_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                messages_json TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_annotations_category
                ON annotations(category_name);
            CREATE INDEX IF NOT EXISTS idx_annotations_source
                ON annotations(source);
        """)
        conn.commit()
        logger.info("Database initialized at %s", DB_PATH)
    finally:
        conn.close()


# ============================================================
# Annotation CRUD
# ============================================================

def save_annotation(category_name: str, geometry: dict, color: str = "#3388ff",
                    source: str = "manual", properties: dict = None) -> int:
    """Save an annotation to the database. Returns the new ID."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO annotations (category_name, color, source, geometry_json, properties_json) VALUES (?, ?, ?, ?, ?)",
            (category_name, color, source, json.dumps(geometry), json.dumps(properties or {}))
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_all_annotations() -> list:
    """Get all annotations as GeoJSON features."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM annotations ORDER BY id").fetchall()
        features = []
        for row in rows:
            features.append({
                "type": "Feature",
                "id": row["id"],
                "geometry": json.loads(row["geometry_json"]),
                "properties": {
                    "category_name": row["category_name"],
                    "color": row["color"],
                    "source": row["source"],
                    "created_at": row["created_at"],
                    **json.loads(row["properties_json"]),
                },
            })
        return features
    finally:
        conn.close()


def get_annotation_count() -> int:
    """Get total annotation count."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM annotations").fetchone()
        return row["cnt"]
    finally:
        conn.close()


def clear_annotations():
    """Delete all annotations."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM annotations")
        conn.commit()
    finally:
        conn.close()


# ============================================================
# Layer CRUD
# ============================================================

def save_layer(name: str, geojson: dict, style: dict = None):
    """Save or update a named layer."""
    feature_count = len(geojson.get("features", [])) if isinstance(geojson, dict) else 0
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO layers (name, geojson, feature_count, style_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, json.dumps(geojson), feature_count, json.dumps(style or {}), datetime.datetime.now().isoformat())
        )
        conn.commit()
    finally:
        conn.close()


def get_layer(name: str) -> Optional[dict]:
    """Get a layer by name. Returns GeoJSON dict or None."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT geojson FROM layers WHERE name = ?", (name,)).fetchone()
        return json.loads(row["geojson"]) if row else None
    finally:
        conn.close()


def get_all_layers() -> list:
    """Get all layer metadata."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT name, feature_count, created_at FROM layers ORDER BY created_at DESC").fetchall()
        return [{"name": r["name"], "feature_count": r["feature_count"], "created_at": r["created_at"]} for r in rows]
    finally:
        conn.close()


def delete_layer(name: str) -> bool:
    """Delete a layer. Returns True if deleted."""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM layers WHERE name = ?", (name,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ============================================================
# Chat Session CRUD
# ============================================================

def save_chat_session(session_id: str, messages: list):
    """Save or update a chat session."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO chat_sessions (session_id, messages_json, updated_at) VALUES (?, ?, ?)",
            (session_id, json.dumps(messages, default=str), datetime.datetime.now().isoformat())
        )
        conn.commit()
    finally:
        conn.close()


def get_chat_session(session_id: str) -> Optional[list]:
    """Get chat session messages. Returns list or None."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT messages_json FROM chat_sessions WHERE session_id = ?", (session_id,)).fetchone()
        return json.loads(row["messages_json"]) if row else None
    finally:
        conn.close()


def delete_chat_session(session_id: str):
    """Delete a chat session."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()
