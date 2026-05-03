"""Real-time collaboration blueprint (v2.1 Plan 09).

REST endpoints for creating, inspecting, resuming, and exporting
collaboration sessions. The actual real-time fan-out happens over
WebSocket events (registered in `blueprints/websocket.py`).
"""

from __future__ import annotations

import logging
import time
import uuid

from flask import Blueprint, jsonify, request, g

import state
from blueprints.auth import require_api_token
from config import Config

logger = logging.getLogger(__name__)

collab_bp = Blueprint('collab', __name__)


# 10 distinct user colors (ColorBrewer Set3-inspired). Cycled by user-join order.
COLOR_PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#bcbd22", "#17becf", "#7f7f7f",
]


def _generate_session_id() -> str:
    return f"collab_{uuid.uuid4().hex[:16]}"


def _new_session_record(owner_user_id: str, session_name: str | None) -> dict:
    now = time.time()
    return {
        "owner": owner_user_id,
        "name": session_name,
        "users": {},
        "layer_history": [],
        "chat_messages": [],
        "created_at": now,
        "last_active": now,
    }


def _evict_expired_locked() -> int:
    """Drop in-memory sessions older than COLLAB_SESSION_TTL_SECONDS.

    Caller must hold state.collab_lock. Returns count evicted.
    """
    ttl = float(Config.COLLAB_SESSION_TTL_SECONDS)
    cutoff = time.time() - ttl
    expired = [
        sid for sid, s in state.collab_sessions.items()
        if s.get("last_active", 0) < cutoff and not s.get("users")
    ]
    for sid in expired:
        state.collab_sessions.pop(sid, None)
    return len(expired)


# ---------------------------------------------------------------------------
# REST routes
# ---------------------------------------------------------------------------

@collab_bp.route('/api/collab/create', methods=['POST'])
@require_api_token
def api_collab_create():
    """Create a new collaboration session."""
    from flask import g

    payload = request.get_json(silent=True) or {}
    session_name = payload.get("session_name")
    if session_name is not None and not isinstance(session_name, str):
        return jsonify(error="session_name must be a string"), 400
    if isinstance(session_name, str):
        session_name = session_name.strip()[:200] or None

    sid = _generate_session_id()
    record = _new_session_record(g.user_id, session_name)

    with state.collab_lock:
        _evict_expired_locked()
        state.collab_sessions[sid] = record

    if state.db is not None:
        try:
            state.db.save_collab_session(sid, record, owner_user_id=g.user_id,
                                         session_name=session_name)
        except Exception:
            logger.warning("Failed to persist new collab session %s", sid, exc_info=True)

    join_url = f"{request.host_url.rstrip('/')}/?collab={sid}"
    return jsonify({
        "session_id": sid,
        "join_url": join_url,
        "owner": g.user_id,
        "session_name": session_name,
    })


@collab_bp.route('/api/collab/<session_id>/info', methods=['GET'])
@require_api_token
def api_collab_info(session_id: str):
    """Read of session metadata. Audit N6: requires auth so a UUID-guess
    cannot enumerate session owners + chat counts."""
    if not session_id.startswith("collab_"):
        return jsonify(error="Invalid session id"), 400

    with state.collab_lock:
        record = state.collab_sessions.get(session_id)
        if record is None:
            # Try DB
            in_db = None
            if state.db is not None:
                try:
                    in_db = state.db.get_collab_session(session_id)
                except Exception:
                    logger.debug("collab info DB lookup failed", exc_info=True)
            if not in_db:
                return jsonify(error="Session not found"), 404
            return jsonify({
                "session_id": session_id,
                "owner": in_db.get("owner_user_id", "anonymous"),
                "session_name": in_db.get("session_name"),
                "user_count": 0,
                "users": [],
                "created_at": in_db.get("created_at"),
                "last_active": in_db.get("last_active"),
                "active": False,
            })

        users = [
            {
                "user_id": uid,
                "name": u.get("name") or uid,
                "color": u.get("color"),
                "joined_at": u.get("joined_at"),
            }
            for uid, u in record.get("users", {}).items()
        ]
        return jsonify({
            "session_id": session_id,
            "owner": record.get("owner"),
            "session_name": record.get("name"),
            "user_count": len(users),
            "users": users,
            "created_at": record.get("created_at"),
            "last_active": record.get("last_active"),
            "active": True,
        })


@collab_bp.route('/api/collab/<session_id>/resume', methods=['GET'])
@require_api_token
def api_collab_resume(session_id: str):
    """Restore an in-memory session record from DB and return its state.

    Audit N6: requires auth and owner-or-creator check. Resume mutates
    state.collab_sessions; a UUID-guesser must not be able to spawn
    in-memory records owned by an arbitrary user.
    """
    if not session_id.startswith("collab_"):
        return jsonify(error="Invalid session id"), 400
    if state.db is None:
        return jsonify(error="Persistence not configured"), 503
    try:
        row = state.db.get_collab_session(session_id)
    except Exception:
        logger.warning("collab resume failed", exc_info=True)
        return jsonify(error="Failed to load session"), 500
    if not row:
        return jsonify(error="Session not found"), 404
    # Audit N6: only the recorded owner may restore.
    requester = getattr(g, 'user_id', 'anonymous')
    owner = row.get("owner_user_id", "anonymous")
    if owner != requester:
        return jsonify(error="Session not found"), 404  # avoid existence leak

    persisted = row.get("state") or {}
    record = _new_session_record(row.get("owner_user_id", "anonymous"),
                                 row.get("session_name"))
    # Merge persisted history but keep users empty (no live SIDs)
    record["layer_history"] = list(persisted.get("layer_history", []) or [])
    record["chat_messages"] = list(persisted.get("chat_messages", []) or [])
    record["users"] = {}  # nobody connected yet on resume

    with state.collab_lock:
        state.collab_sessions[session_id] = record

    return jsonify({
        "session_id": session_id,
        "owner": record["owner"],
        "session_name": record["name"],
        "layer_history": record["layer_history"],
        "chat_messages": record["chat_messages"],
        "restored": True,
    })


@collab_bp.route('/api/collab/<session_id>/export', methods=['GET'])
@require_api_token
def api_collab_export(session_id: str):
    """Export the workflow (NL commands + layer ops) as JSON.

    Audit N6: requires auth and owner check — exporting another user's
    chat history + layer ops without auth was a privacy leak.
    """
    if not session_id.startswith("collab_"):
        return jsonify(error="Invalid session id"), 400

    requester = getattr(g, 'user_id', 'anonymous')
    record = None
    owner = None
    with state.collab_lock:
        live = state.collab_sessions.get(session_id)
        if live is not None:
            record = live
            owner = live.get("owner")

    if record is None and state.db is not None:
        try:
            row = state.db.get_collab_session(session_id)
        except Exception:
            row = None
        if not row:
            return jsonify(error="Session not found"), 404
        record = row.get("state") or {}
        owner = row.get("owner_user_id", "anonymous")

    if record is None:
        return jsonify(error="Session not found"), 404
    if owner is not None and owner != requester:
        return jsonify(error="Session not found"), 404  # avoid existence leak

    chat = record.get("chat_messages", []) or []
    layer_history = record.get("layer_history", []) or []

    workflow = []
    step = 0
    for msg in chat:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "user":
            continue
        text = msg.get("text") or msg.get("message") or ""
        if not text:
            continue
        step += 1
        workflow.append({
            "step": step,
            "user": msg.get("user_name") or msg.get("user_id") or "anonymous",
            "command": text,
            "timestamp": msg.get("timestamp"),
        })

    return jsonify({
        "session_id": session_id,
        "owner": record.get("owner"),
        "session_name": record.get("name"),
        "workflow": workflow,
        "layer_history": layer_history,
        "total_messages": len(chat),
    })


# ---------------------------------------------------------------------------
# Helpers used by websocket.py
# ---------------------------------------------------------------------------

def assign_color(record: dict) -> str:
    """Deterministic-ish color allocation: pick the first palette color
    not currently in use, falling back to round-robin if all 10 are used."""
    in_use = {u.get("color") for u in record.get("users", {}).values()}
    for c in COLOR_PALETTE:
        if c not in in_use:
            return c
    # All taken — cycle by user count
    return COLOR_PALETTE[len(record.get("users", {})) % len(COLOR_PALETTE)]


def append_layer_history(record: dict, entry: dict) -> None:
    """Append a layer-history entry, capping FIFO at COLLAB_LAYER_HISTORY_CAP."""
    cap = int(Config.COLLAB_LAYER_HISTORY_CAP)
    history = record.setdefault("layer_history", [])
    history.append(entry)
    if len(history) > cap:
        del history[: len(history) - cap]


def append_chat_message(record: dict, message: dict) -> None:
    """Append a chat message to the session record."""
    record.setdefault("chat_messages", []).append(message)
