"""Unified configuration for SpatialApp."""

import logging
import os
import tempfile
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

_config_logger = logging.getLogger(__name__)

# N35: SECURITY_CONTACT values that are clearly the unconfigured default.
# Refusing these in prod prevents shipping a security.txt that points
# at a non-functional inbox — i.e., reports that vanish silently.
_PLACEHOLDER_SECURITY_CONTACTS = {
    "mailto:security@example.com",
    "mailto:security@example.org",
    "mailto:placeholder@example.com",
    "mailto:test@example.com",
    "",
    "TODO",
    "CHANGEME",
}


def _int_env(key: str, default: int) -> int:
    """Read an integer from an environment variable with safe fallback.

    If the env var is set to a non-numeric string, logs a warning and
    returns the default value instead of crashing at import time.
    """
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        _config_logger.warning(
            f"Environment variable {key}={raw!r} is not a valid integer, "
            f"using default {default}"
        )
        return default


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
        # N35: refuse to start in prod with a placeholder SECURITY_CONTACT.
        # The /.well-known/security.txt route would otherwise advertise a
        # non-functional inbox to any researcher trying to disclose a
        # vulnerability — the highest-friction way to lose a report.
        if not Config.DEBUG:
            sc = (Config.SECURITY_CONTACT or "").strip()
            if sc in _PLACEHOLDER_SECURITY_CONTACTS:
                raise RuntimeError(
                    "SECURITY_CONTACT must be set in production. "
                    "Set the SECURITY_CONTACT environment variable to a real "
                    "contact channel (e.g., 'mailto:security@yourdomain.com' "
                    "or 'https://yourdomain.com/security'). The placeholder "
                    "default would publish a dead inbox in /.well-known/security.txt."
                )
        # N37: probe-write each writable folder so a misconfigured prod
        # deploy fails loud at startup instead of throwing 500s on the
        # first user upload. Skipped in DEBUG so dev sandboxes that
        # haven't materialized the folders yet don't block startup.
        if not Config.DEBUG:
            for folder_name in ("UPLOAD_FOLDER", "LABELS_FOLDER", "LOG_FOLDER"):
                folder = getattr(Config, folder_name, None)
                if not folder:
                    continue
                try:
                    os.makedirs(folder, exist_ok=True)
                    with tempfile.NamedTemporaryFile(
                        dir=folder, prefix=".writeprobe_", delete=True
                    ) as fh:
                        fh.write(b"probe")
                        fh.flush()
                except OSError as exc:
                    raise RuntimeError(
                        f"{folder_name}={folder!r} is not writable: {exc.strerror or exc}. "
                        f"Fix folder permissions or set {folder_name} to a "
                        f"writable path. (Probe failed at startup; would have "
                        f"surfaced as an opaque 500 on first upload.)"
                    ) from exc

    # Folders
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join('static', 'uploads'))
    LABELS_FOLDER = os.environ.get('LABELS_FOLDER', 'labels')
    LOG_FOLDER = os.environ.get('LOG_FOLDER', 'logs')

    # Security disclosure (RFC 9116 — /.well-known/security.txt).
    # Default is a placeholder that Config.validate() rejects in prod.
    SECURITY_CONTACT = os.environ.get(
        'SECURITY_CONTACT', 'mailto:security@example.com'
    )

    # Upload limits
    MAX_CONTENT_LENGTH = _int_env('MAX_UPLOAD_SIZE', 50 * 1024 * 1024)  # 50 MB

    # OSM / Overpass API
    OSM_REQUEST_TIMEOUT = _int_env('OSM_REQUEST_TIMEOUT', 30)

    # NL-to-GIS (LLM provider)
    LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'anthropic')  # anthropic, gemini, openai
    LLM_MODEL = os.environ.get('LLM_MODEL', '')  # Empty = use provider default
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
    OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', '')  # For compatible APIs
    CLAUDE_MODEL = os.environ.get('CLAUDE_MODEL', '')  # Legacy compat; empty = use DEFAULT_MODELS
    MAX_TOOL_CALLS_PER_MESSAGE = _int_env('MAX_TOOL_CALLS', 10)
    MAX_FEATURES_PER_LAYER = _int_env('MAX_FEATURES_PER_LAYER', 5000)

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
    MAX_ANNOTATIONS_STARTUP = _int_env('MAX_ANNOTATIONS_STARTUP', 10000)
    SESSION_TTL_SECONDS = _int_env('SESSION_TTL_SECONDS', 3600)
    MAX_LAYERS_IN_MEMORY = _int_env('MAX_LAYERS_IN_MEMORY', 100)

    # LLM cost budget
    MAX_TOKENS_PER_SESSION = _int_env('MAX_TOKENS_PER_SESSION', 100000)

    # Raster (v2.1 Plan 08)
    RASTER_DIR = os.environ.get(
        'RASTER_DIR',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sample_rasters'),
    )
    MAX_RASTER_SIZE_MB = _int_env('MAX_RASTER_SIZE_MB', 500)

    # Data pipeline (v2.1 Plan 10)
    IMPORT_MAX_FEATURES = _int_env('IMPORT_MAX_FEATURES', 10_000)
    PIPELINE_MAX_STEPS = _int_env('PIPELINE_MAX_STEPS', 10)

    # Database
    DATABASE_PATH = os.environ.get('DATABASE_PATH',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'spatialapp.db'))
    DATABASE_BACKEND = os.environ.get('DATABASE_BACKEND', 'sqlite')  # 'sqlite' or 'postgres'
    DATABASE_URL = os.environ.get('DATABASE_URL', '')  # PostgreSQL connection string

    # Real-time collaboration (v2.1 Plan 09)
    COLLAB_MAX_USERS_PER_SESSION = _int_env('COLLAB_MAX_USERS_PER_SESSION', 10)
    COLLAB_CURSOR_THROTTLE_MS = _int_env('COLLAB_CURSOR_THROTTLE_MS', 100)
    COLLAB_SESSION_TTL_SECONDS = _int_env('COLLAB_SESSION_TTL_SECONDS', 86400)  # 24h
    COLLAB_LAYER_HISTORY_CAP = _int_env('COLLAB_LAYER_HISTORY_CAP', 1000)
