"""Auth blueprint: registration, user info, health check, and the
``require_api_token`` decorator used across other blueprints.
"""

import hmac
import logging
import os
import shutil
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, jsonify, request, g

from config import Config
import state

auth_bp = Blueprint('auth', __name__)


# ------------------------------------------------------------------
# Decorator (importable by other blueprints)
# ------------------------------------------------------------------

def require_api_token(f):
    """Decorator: enforce bearer token auth. Resolves user_id onto flask.g.

    Supports two modes:
    - Single shared token (CHAT_API_TOKEN env var) -> user_id = 'anonymous'
    - Per-user tokens (stored in users table) -> user_id from DB lookup
    - No token configured -> open access, user_id = 'anonymous'
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        g.user_id = 'anonymous'

        auth = request.headers.get('Authorization', '')
        token = auth[7:] if auth.startswith('Bearer ') else ''

        if token:
            # Try per-user token lookup first
            if state.db:
                user = state.db.get_user_by_token(token)
                if user:
                    g.user_id = user['user_id']
                    return f(*args, **kwargs)

            # Fall back to shared token check
            if Config.CHAT_API_TOKEN and hmac.compare_digest(token, Config.CHAT_API_TOKEN):
                return f(*args, **kwargs)

            # Token provided but invalid
            return jsonify(error='Unauthorized'), 401

        elif Config.CHAT_API_TOKEN:
            # Token required but not provided
            return jsonify(error='Unauthorized'), 401

        # No token required -- open access
        return f(*args, **kwargs)
    return decorated


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@auth_bp.route('/api/register', methods=['POST'])
def api_register():
    """Register a new user. Returns user_id and API token."""
    from flask import current_app
    if not state.db:
        return jsonify(error='Database not available'), 500

    data = request.get_json(silent=True)
    if not data or not data.get('username'):
        return jsonify(error='username is required'), 400

    username = data['username'].strip()
    if not username or len(username) > 100:
        return jsonify(error='Invalid username'), 400

    try:
        user = state.db.create_user(username)
        return jsonify(success=True, **user), 201
    except Exception as e:
        if 'UNIQUE' in str(e):
            return jsonify(error='Username or token already exists'), 409
        current_app.logger.error(f"Registration error: {e}")
        return jsonify(error='Registration failed'), 500


@auth_bp.route('/api/me')
@require_api_token
def api_me():
    """Get current user info."""
    user_id = getattr(g, 'user_id', 'anonymous')
    if user_id == 'anonymous':
        return jsonify(user_id='anonymous', username='anonymous')
    if state.db:
        user = state.db.get_user_by_id(user_id)
        if user:
            return jsonify(user_id=user['user_id'], username=user['username'], created_at=user['created_at'])
    return jsonify(user_id=user_id, username='unknown')


@auth_bp.route('/api/health')
def api_health():
    """Health check endpoint.

    Unauthenticated: returns minimal {"status": "ok", "timestamp": ...}.
    Authenticated (valid bearer token): returns full subsystem details.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # Check if a valid token is provided for detailed view
    auth = request.headers.get('Authorization', '')
    token = auth[7:] if auth.startswith('Bearer ') else ''
    authenticated = False
    if token:
        # Per-user token lookup
        if state.db:
            user = state.db.get_user_by_token(token)
            if user:
                authenticated = True
        # Shared token check
        if not authenticated and Config.CHAT_API_TOKEN and hmac.compare_digest(token, Config.CHAT_API_TOKEN):
            authenticated = True
    elif not Config.CHAT_API_TOKEN:
        # No token configured -- open access, show details
        authenticated = True

    if not authenticated:
        return jsonify({"status": "ok", "timestamp": timestamp})

    # Full details for authenticated requests
    health = {"status": "ok", "timestamp": timestamp, "checks": {}}

    # Database check
    if state.db:
        try:
            count = state.db.get_annotation_count()
            health["checks"]["database"] = {"status": "ok", "annotation_count": count}
        except Exception as e:
            health["checks"]["database"] = {"status": "error", "detail": str(e)}
            health["status"] = "degraded"
    else:
        health["checks"]["database"] = {"status": "unavailable"}
        health["status"] = "degraded"

    # Disk space check
    try:
        usage = shutil.disk_usage(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        free_mb = usage.free / (1024 * 1024)
        health["checks"]["disk"] = {"status": "ok" if free_mb > 100 else "warning", "free_mb": round(free_mb)}
    except Exception:
        logging.debug("Disk space check failed", exc_info=True)
        health["checks"]["disk"] = {"status": "unknown"}

    # LLM provider check
    llm_key = Config.get_llm_api_key()
    health["checks"]["llm"] = {
        "provider": Config.LLM_PROVIDER,
        "status": "configured" if llm_key else "not_configured",
    }

    # Layer store
    with state.layer_lock:
        layer_count = len(state.layer_store)
    health["checks"]["layers"] = {"count": layer_count, "max": state.MAX_LAYERS_IN_MEMORY}

    # Sessions
    with state.session_lock:
        session_count = len(state.chat_sessions)
    health["checks"]["sessions"] = {"count": session_count}

    return jsonify(health)
