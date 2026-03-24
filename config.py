"""Unified configuration for SpatialApp."""

import os
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""

    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'

    # Folders
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join('static', 'uploads'))
    LABELS_FOLDER = os.environ.get('LABELS_FOLDER', 'labels')
    LOG_FOLDER = os.environ.get('LOG_FOLDER', 'logs')

    # Upload limits
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_UPLOAD_SIZE', 50 * 1024 * 1024))  # 50 MB

    # OSM / Overpass API
    OSM_REQUEST_TIMEOUT = int(os.environ.get('OSM_REQUEST_TIMEOUT', 30))

    # NL-to-GIS (Claude API)
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
    CLAUDE_MODEL = os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-20250514')
    MAX_TOOL_CALLS_PER_MESSAGE = int(os.environ.get('MAX_TOOL_CALLS', 10))
    MAX_FEATURES_PER_LAYER = int(os.environ.get('MAX_FEATURES_PER_LAYER', 5000))

    # Chat API auth (simple bearer token)
    CHAT_API_TOKEN = os.environ.get('CHAT_API_TOKEN', '')

    # Database
    DATABASE_PATH = os.environ.get('DATABASE_PATH',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'spatialapp.db'))
