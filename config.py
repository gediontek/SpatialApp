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

    @staticmethod
    def validate():
        """Validate critical configuration. Call at startup."""
        if not Config.DEBUG and Config.SECRET_KEY == 'dev-secret-key-change-in-production':
            raise RuntimeError(
                "SECRET_KEY must be set in production. "
                "Set the SECRET_KEY environment variable to a random string."
            )

    # Folders
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join('static', 'uploads'))
    LABELS_FOLDER = os.environ.get('LABELS_FOLDER', 'labels')
    LOG_FOLDER = os.environ.get('LOG_FOLDER', 'logs')

    # Upload limits
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_UPLOAD_SIZE', 50 * 1024 * 1024))  # 50 MB

    # OSM / Overpass API
    OSM_REQUEST_TIMEOUT = int(os.environ.get('OSM_REQUEST_TIMEOUT', 30))

    # NL-to-GIS (LLM provider)
    LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'anthropic')  # anthropic, gemini, openai
    LLM_MODEL = os.environ.get('LLM_MODEL', '')  # Empty = use provider default
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
    OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', '')  # For compatible APIs
    CLAUDE_MODEL = os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-20250514')  # Legacy compat
    MAX_TOOL_CALLS_PER_MESSAGE = int(os.environ.get('MAX_TOOL_CALLS', 10))
    MAX_FEATURES_PER_LAYER = int(os.environ.get('MAX_FEATURES_PER_LAYER', 5000))

    @staticmethod
    def get_llm_api_key():
        """Return the API key for the configured LLM provider."""
        provider = Config.LLM_PROVIDER.lower()
        if provider == "anthropic":
            return Config.ANTHROPIC_API_KEY
        elif provider == "gemini":
            return Config.GEMINI_API_KEY
        elif provider == "openai":
            return Config.OPENAI_API_KEY
        return ""

    @staticmethod
    def get_llm_model():
        """Return the model name, falling back to provider defaults."""
        from nl_gis.llm_provider import DEFAULT_MODELS
        if Config.LLM_MODEL:
            return Config.LLM_MODEL
        # Legacy compat: if CLAUDE_MODEL was set and provider is anthropic
        if Config.LLM_PROVIDER.lower() == "anthropic" and Config.CLAUDE_MODEL:
            return Config.CLAUDE_MODEL
        return DEFAULT_MODELS.get(Config.LLM_PROVIDER.lower(), "claude-sonnet-4-20250514")

    # Chat API auth (simple bearer token)
    CHAT_API_TOKEN = os.environ.get('CHAT_API_TOKEN', '')

    # Session and memory limits
    MAX_ANNOTATIONS_STARTUP = int(os.environ.get('MAX_ANNOTATIONS_STARTUP', 10000))
    SESSION_TTL_SECONDS = int(os.environ.get('SESSION_TTL_SECONDS', 3600))
    MAX_LAYERS_IN_MEMORY = int(os.environ.get('MAX_LAYERS_IN_MEMORY', 100))

    # LLM cost budget
    MAX_TOKENS_PER_SESSION = int(os.environ.get('MAX_TOKENS_PER_SESSION', 100000))

    # Database
    DATABASE_PATH = os.environ.get('DATABASE_PATH',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'spatialapp.db'))
