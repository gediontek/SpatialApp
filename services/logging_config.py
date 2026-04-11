"""Structured logging configuration for SpatialApp.

When LOG_FORMAT=json is set, all log output uses JSON format with request IDs.
Otherwise, uses standard human-readable format for development.
"""

import json
import logging
import os
import uuid

from flask import g, has_request_context


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        if has_request_context():
            log_entry["request_id"] = getattr(g, 'request_id', None)
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def configure_logging(app):
    """Configure logging for the app.

    Uses JSON format when LOG_FORMAT=json env var is set.
    Otherwise uses standard format for development readability.
    """
    from config import Config

    log_format = os.environ.get('LOG_FORMAT', 'standard')
    log_level = logging.DEBUG if Config.DEBUG else logging.INFO

    if log_format == 'json':
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
    else:
        # Standard format: log to file for development
        log_file = os.path.join(Config.LOG_FOLDER, 'app.log')
        handler = logging.FileHandler(log_file)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))

    # Set on root logger
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Add request ID middleware
    @app.before_request
    def add_request_id():
        g.request_id = str(uuid.uuid4())[:8]
