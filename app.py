"""SpatialApp — NL-to-GIS web application.

Application factory pattern. All routes live in blueprints/.
Shared mutable state lives in state.py.
"""

import logging
import os
import secrets

from flask import Flask, jsonify, request, g
from flask_wtf.csrf import CSRFProtect

from config import Config
import state


def _create_database():
    """Database factory: returns the configured database backend.

    Returns a DatabaseInterface implementation based on DATABASE_BACKEND config:
    - 'sqlite' (default): SQLite via services.database.Database
    - 'postgres': PostgreSQL/PostGIS via services.postgres_db.PostgresDatabase

    Raises:
        NotImplementedError: If postgres backend is selected (not yet implemented).
        ValueError: If an unknown backend is configured.
    """
    backend = Config.DATABASE_BACKEND.lower()
    if backend == 'postgres':
        from services.postgres_db import PostgresDatabase
        return PostgresDatabase(Config.DATABASE_URL)
    elif backend == 'sqlite':
        from services.database import Database
        return Database(Config.DATABASE_PATH)
    else:
        raise ValueError(
            f"Unknown DATABASE_BACKEND: {backend!r}. "
            f"Supported values: 'sqlite', 'postgres'"
        )


def create_app(testing=False):
    """Application factory.

    Creates and configures the Flask application, registers blueprints,
    initializes database, loads annotations, and restores layers.

    Parameters
    ----------
    testing : bool
        When True, skips background timers and sets TESTING config.
    """
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER

    if testing:
        app.config['TESTING'] = True
        os.environ['TESTING'] = '1'

    # Validate critical config
    try:
        Config.validate()
    except RuntimeError as e:
        logging.warning(f"Config warning: {e}")

    # Initialize CSRF protection
    csrf = CSRFProtect(app)
    # Store csrf on app for blueprint access
    app.extensions['csrf'] = csrf

    # ------------------------------------------------------------------
    # CSP nonce (v2.1 Plan 13 follow-up — removes 'unsafe-inline' from
    # script-src). Nonce is generated per request and exposed to Jinja
    # templates so each <script> tag (and nonce'd handlers) can carry
    # the nonce attribute.
    # ------------------------------------------------------------------
    @app.before_request
    def _generate_csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def _inject_csp_nonce():
        # `g` is request-bound; only meaningful inside a request.
        try:
            return {"csp_nonce": getattr(g, "csp_nonce", "")}
        except RuntimeError:
            return {"csp_nonce": ""}

    # Ensure directories exist
    os.makedirs(Config.LABELS_FOLDER, exist_ok=True)
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(Config.LOG_FOLDER, exist_ok=True)

    # Configure logging
    from services.logging_config import configure_logging
    configure_logging(app)

    # ------------------------------------------------------------------
    # Database connection teardown
    # ------------------------------------------------------------------
    @app.teardown_appcontext
    def close_db_connection(exception):
        if state.db is not None:
            state.db.close_connection()
        else:
            # Fallback: close module-level connection if db not initialized
            from services.database import close_connection
            close_connection()

    # ------------------------------------------------------------------
    # Initialize database
    # ------------------------------------------------------------------
    try:
        db_instance = _create_database()
        db_instance.init_db()
        if db_instance.verify_db_integrity():
            state.db = db_instance
            try:
                db_instance.cleanup_old_metrics(days=180)
            except Exception:
                logging.debug("Metrics cleanup failed on startup", exc_info=True)
        else:
            logging.error("Database integrity check failed — running without DB persistence")
    except NotImplementedError as e:
        logging.warning(f"Database backend not available: {e}")
    except Exception as e:
        logging.warning(f"Database init skipped: {e}")

    # ------------------------------------------------------------------
    # Register blueprints
    # ------------------------------------------------------------------
    from blueprints.auth import auth_bp
    from blueprints.annotations import annotation_bp
    from blueprints.osm import osm_bp
    from blueprints.chat import chat_bp
    from blueprints.layers import layers_bp
    from blueprints.dashboard import dashboard_bp
    from blueprints.collab import collab_bp  # v2.1 Plan 09

    app.register_blueprint(auth_bp)
    app.register_blueprint(annotation_bp)
    app.register_blueprint(osm_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(layers_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(collab_bp)

    # CSRF exemptions for API endpoints
    csrf.exempt(osm_bp.name + '.api_auto_classify')
    csrf.exempt(chat_bp.name + '.api_chat')
    csrf.exempt(layers_bp.name + '.api_import_layer')
    csrf.exempt(layers_bp.name + '.api_delete_layer')
    csrf.exempt(auth_bp.name + '.api_register')
    csrf.exempt(dashboard_bp.name + '.api_delete_session')
    csrf.exempt(collab_bp.name + '.api_collab_create')

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify(error="Bad request"), 400

    @app.errorhandler(404)
    def not_found(e):
        return jsonify(error="Not found"), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify(error="Method not allowed"), 405

    @app.errorhandler(413)
    def too_large(e):
        return jsonify(message='File is too large. Maximum size is 50MB.'), 413

    @app.errorhandler(429)
    def too_many_requests(e):
        return jsonify(error="Too many requests, please try again later"), 429

    @app.errorhandler(500)
    def internal_error(e):
        app.logger.error(f"Internal server error: {str(e)}")
        return jsonify(message='An internal error occurred.'), 500

    # ------------------------------------------------------------------
    # Prometheus metrics endpoint
    # ------------------------------------------------------------------
    @app.route('/metrics')
    def prometheus_metrics():
        """Expose Prometheus-compatible metrics."""
        from services.metrics import metrics as _metrics
        # Update session gauge on each scrape
        with state.session_lock:
            _metrics.set_gauge("active_sessions", len(state.chat_sessions))
        with state.layer_lock:
            _metrics.set_gauge("active_layers", len(state.layer_store))
        return _metrics.format_prometheus(), 200, {'Content-Type': 'text/plain; charset=utf-8'}

    # ------------------------------------------------------------------
    # CORS + security headers (v2.1 Plan 13 M2.3)
    # ------------------------------------------------------------------
    @app.after_request
    def add_cors_headers(response):
        """Set CORS + security headers."""
        from services.metrics import metrics as _metrics
        # Record HTTP request metrics (skip the /metrics endpoint itself)
        if request.path != '/metrics':
            _metrics.inc("http_requests_total", {
                "method": request.method,
                "status": str(response.status_code),
            })
        origin = request.headers.get('Origin')
        if origin:
            request_host = request.host
            allowed_origin = f"{request.scheme}://{request_host}"
            if origin == allowed_origin:
                response.headers['Access-Control-Allow-Origin'] = origin
                response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
                response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-CSRFToken'
                response.headers['Access-Control-Allow-Credentials'] = 'true'
                response.headers['Access-Control-Max-Age'] = '600'

        # Security headers — applied to ALL responses, not just CORS.
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('X-XSS-Protection', '0')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        # CSP allows the CDNs the existing templates already use.
        # Nonce-based script-src + 'strict-dynamic' replaces 'unsafe-inline'.
        # Modern browsers honor the nonce and ignore both 'unsafe-inline'
        # and the host allowlist; older browsers fall back to the hosts.
        nonce = getattr(g, "csp_nonce", "")
        nonce_token = f" 'nonce-{nonce}' 'strict-dynamic'" if nonce else ""
        response.headers.setdefault(
            'Content-Security-Policy',
            "default-src 'self'; "
            f"script-src 'self'{nonce_token} cdn.jsdelivr.net unpkg.com; "
            "style-src 'self' 'unsafe-inline' unpkg.com cdn.jsdelivr.net; "
            "img-src 'self' data: blob: https://*.tile.openstreetmap.org "
            "https://server.arcgisonline.com https://*.basemaps.cartocdn.com; "
            "connect-src 'self' ws: wss:; "
            "font-src 'self' data:;",
        )
        # HSTS only if behind HTTPS reverse proxy.
        if request.headers.get('X-Forwarded-Proto') == 'https':
            response.headers.setdefault(
                'Strict-Transport-Security',
                'max-age=31536000; includeSubDomains',
            )
        return response

    # ------------------------------------------------------------------
    # Load annotations
    # ------------------------------------------------------------------
    from blueprints.annotations import load_annotations
    load_annotations()

    # ------------------------------------------------------------------
    # Restore layers from database
    # ------------------------------------------------------------------
    if state.db:
        try:
            from blueprints.layers import _evict_layers_if_needed
            for layer_meta in state.db.get_all_layers():
                geojson = state.db.get_layer(layer_meta['name'])
                if geojson:
                    state.layer_store[layer_meta['name']] = geojson
            if state.layer_store:
                _evict_layers_if_needed()
                logging.info(f"Restored {len(state.layer_store)} layers from database")
        except Exception as e:
            logging.warning(f"Layer restore from DB failed: {e}")

    # ------------------------------------------------------------------
    # Start cleanup timer (guarded)
    # ------------------------------------------------------------------
    from blueprints.chat import _start_session_cleanup_timer
    _start_session_cleanup_timer()

    # ------------------------------------------------------------------
    # Initialize WebSocket support (optional — requires flask-socketio)
    # ------------------------------------------------------------------
    try:
        from flask_socketio import SocketIO
        from blueprints.websocket import register_websocket_events

        socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
        register_websocket_events(socketio)
        state.socketio = socketio
        logging.info("WebSocket support enabled (flask-socketio)")
    except ImportError:
        logging.info("WebSocket support disabled (flask-socketio not installed)")

    return app


# ------------------------------------------------------------------
# Backward-compatibility: module-level app instance
# ------------------------------------------------------------------
# This lets `from app import app` and `python app.py` keep working.
app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    if state.socketio is not None:
        state.socketio.run(app, debug=Config.DEBUG, host='0.0.0.0', port=port)
    else:
        app.run(debug=Config.DEBUG, host='0.0.0.0', port=port)
