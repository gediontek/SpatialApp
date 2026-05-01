"""Auth blueprint: registration, user info, health check, and the
``require_api_token`` decorator used across other blueprints.
"""

import hmac
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, jsonify, request, g

from config import Config
import state

auth_bp = Blueprint('auth', __name__)

# Process start time for uptime reporting (v2.1 Plan 13 M4.3.1)
_PROCESS_START_TIME = time.time()


def _read_version() -> str:
    """Resolve a version string. Tries (1) VERSION file, (2) env, (3) git."""
    version_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION"
    )
    try:
        with open(version_file, "r", encoding="utf-8") as fh:
            v = fh.read().strip()
            if v:
                return v
    except OSError:
        pass
    env_v = os.environ.get("APP_VERSION")
    if env_v:
        return env_v
    return "dev"


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
        from services.metrics import metrics as _prom
        g.user_id = 'anonymous'

        auth = request.headers.get('Authorization', '')
        token = auth[7:] if auth.startswith('Bearer ') else ''

        if token:
            # Try per-user token lookup first
            if state.db:
                user = state.db.get_user_by_token(token)
                if user:
                    g.user_id = user['user_id']
                    _prom.inc("auth_requests_total", {"status": "success"})
                    return f(*args, **kwargs)

            # Fall back to shared token check
            if Config.CHAT_API_TOKEN and hmac.compare_digest(token, Config.CHAT_API_TOKEN):
                _prom.inc("auth_requests_total", {"status": "success"})
                return f(*args, **kwargs)

            # Token provided but invalid
            _prom.inc("auth_requests_total", {"status": "failure"})
            return jsonify(error='Unauthorized'), 401

        elif Config.CHAT_API_TOKEN:
            # Token required but not provided
            _prom.inc("auth_requests_total", {"status": "failure"})
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
        return jsonify({
            "status": "ok",
            "timestamp": timestamp,
            "uptime_seconds": round(time.time() - _PROCESS_START_TIME, 1),
            "version": _read_version(),
        })

    # Full details for authenticated requests
    health = {
        "status": "ok",
        "timestamp": timestamp,
        "uptime_seconds": round(time.time() - _PROCESS_START_TIME, 1),
        "version": _read_version(),
        "checks": {},
    }

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

    # Readiness flag — true if DB + LLM provider both initialized.
    db_ok = health["checks"]["database"]["status"] == "ok"
    llm_ok = health["checks"]["llm"]["status"] == "configured"
    health["ready"] = db_ok and llm_ok

    return jsonify(health)


@auth_bp.route('/api/health/ready')
def api_health_ready():
    """Kubernetes-style readiness probe.

    Returns 200 only when DB is initialized and the LLM provider key is
    configured. Otherwise 503 — load balancer should not route traffic.
    """
    db_ok = state.db is not None
    llm_ok = bool(Config.get_llm_api_key())
    body = {
        "ready": db_ok and llm_ok,
        "checks": {"database": db_ok, "llm": llm_ok},
        "uptime_seconds": round(time.time() - _PROCESS_START_TIME, 1),
    }
    code = 200 if body["ready"] else 503
    return jsonify(body), code
