"""Dashboard blueprint: user dashboard page and API endpoints."""

import logging

from flask import Blueprint, jsonify, render_template, g

import state
from blueprints.auth import require_api_token

dashboard_bp = Blueprint('dashboard', __name__)


# ------------------------------------------------------------------
# Page route
# ------------------------------------------------------------------

@dashboard_bp.route('/dashboard')
@require_api_token
def dashboard_page():
    """Serve the dashboard HTML page."""
    return render_template('dashboard.html')


# ------------------------------------------------------------------
# API routes
# ------------------------------------------------------------------

@dashboard_bp.route('/api/dashboard')
@require_api_token
def api_dashboard():
    """Return dashboard data for the authenticated user."""
    if not state.db:
        return jsonify(error='Database not available'), 500

    user_id = getattr(g, 'user_id', 'anonymous')

    # User info
    user_info = {"username": "anonymous", "created_at": None}
    if user_id != 'anonymous':
        user = state.db.get_user_by_id(user_id)
        if user:
            user_info = {"username": user["username"], "created_at": user["created_at"]}

    # Sessions
    sessions = state.db.get_user_sessions(user_id)

    # Layers
    layers = state.db.get_user_layers(user_id)

    # Stats
    stats = state.db.get_user_stats(user_id)

    # Tool usage breakdown
    try:
        tool_stats = state.db.get_tool_stats(user_id if user_id != 'anonymous' else None)
    except Exception:
        logging.debug("Failed to get tool stats", exc_info=True)
        tool_stats = {"most_used": [], "failure_rate": {}, "avg_chain_length": 0.0}

    return jsonify(
        user=user_info,
        sessions=sessions,
        layers=layers,
        stats=stats,
        tool_stats=tool_stats,
    )


@dashboard_bp.route('/api/sessions/<session_id>', methods=['DELETE'])
@require_api_token
def api_delete_session(session_id):
    """Delete a specific chat session. Requires ownership."""
    if not state.db:
        return jsonify(error='Database not available'), 500

    user_id = getattr(g, 'user_id', 'anonymous')

    # Verify ownership before deleting
    session = state.db.get_chat_session_with_owner(session_id)
    if not session:
        return jsonify(error='Session not found'), 404
    if session['user_id'] != user_id:
        return jsonify(error='Forbidden'), 403

    deleted = state.db.delete_chat_session_for_user(session_id, user_id)
    if not deleted:
        return jsonify(error='Delete failed'), 500

    # Also remove from in-memory cache if present
    with state.session_lock:
        state.chat_sessions.pop(session_id, None)

    return jsonify(success=True)


@dashboard_bp.route('/api/sessions/<session_id>/messages')
@require_api_token
def api_session_messages(session_id):
    """Get messages for a specific session. Requires ownership."""
    if not state.db:
        return jsonify(error='Database not available'), 500

    user_id = getattr(g, 'user_id', 'anonymous')

    session = state.db.get_chat_session_with_owner(session_id)
    if not session:
        return jsonify(error='Session not found'), 404
    if session['user_id'] != user_id:
        return jsonify(error='Forbidden'), 403

    return jsonify(
        session_id=session_id,
        messages=session['messages'],
        message_count=len(session['messages']),
    )
