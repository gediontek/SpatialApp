"""Abstract database interface for SpatialApp.

Defines the contract that all database backends (SQLite, PostgreSQL/PostGIS)
must implement. This enables swapping storage backends via configuration
without changing application code.
"""

from abc import ABC, abstractmethod
from typing import Optional


class DatabaseInterface(ABC):
    """Abstract interface for database operations.

    All database backends must implement every method defined here.
    Application code should depend on this interface, not on concrete
    implementations.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def init_db(self) -> None:
        """Create tables and run migrations. Must be idempotent."""
        ...

    @abstractmethod
    def close_connection(self) -> None:
        """Close the current thread-local connection."""
        ...

    @abstractmethod
    def verify_db_integrity(self) -> bool:
        """Check that the database is accessible and has expected tables."""
        ...

    # ------------------------------------------------------------------
    # User CRUD
    # ------------------------------------------------------------------

    @abstractmethod
    def create_user(self, username: str, api_token: str = None) -> dict:
        """Create a new user. Returns dict with user_id, username, api_token."""
        ...

    @abstractmethod
    def get_user_by_token(self, api_token: str) -> Optional[dict]:
        """Look up a user by API token. Returns dict or None."""
        ...

    @abstractmethod
    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        """Look up a user by ID. Returns dict or None."""
        ...

    @abstractmethod
    def list_users(self) -> list:
        """List all users (without tokens)."""
        ...

    # ------------------------------------------------------------------
    # Annotation CRUD
    # ------------------------------------------------------------------

    @abstractmethod
    def save_annotation(self, category_name: str, geometry: dict,
                        color: str = "#3388ff", source: str = "manual",
                        properties: dict = None, user_id: str = "anonymous") -> int:
        """Save an annotation. Returns the new ID."""
        ...

    @abstractmethod
    def get_all_annotations(self, user_id: str = None, limit: int = None,
                            offset: int = 0) -> list:
        """Get annotations as GeoJSON features. Supports pagination and user filtering."""
        ...

    @abstractmethod
    def get_annotation_count(self, user_id: str = None) -> int:
        """Get annotation count, optionally filtered by user."""
        ...

    @abstractmethod
    def clear_annotations(self, user_id: str = None) -> None:
        """Delete annotations. If user_id given, only that user's annotations."""
        ...

    # ------------------------------------------------------------------
    # Layer CRUD
    # ------------------------------------------------------------------

    @abstractmethod
    def save_layer(self, name: str, geojson: dict, style: dict = None,
                   user_id: str = "anonymous") -> None:
        """Save or update a named layer."""
        ...

    @abstractmethod
    def get_layer(self, name: str, user_id: str = None) -> Optional[dict]:
        """Get a layer by name. Returns GeoJSON dict or None."""
        ...

    @abstractmethod
    def get_all_layers(self, user_id: str = None) -> list:
        """Get layer metadata, optionally filtered by user."""
        ...

    @abstractmethod
    def delete_layer(self, name: str, user_id: str = None) -> bool:
        """Delete a layer. Returns True if deleted."""
        ...

    # ------------------------------------------------------------------
    # Chat Session CRUD
    # ------------------------------------------------------------------

    @abstractmethod
    def save_chat_session(self, session_id: str, messages: list,
                          user_id: str = "anonymous") -> None:
        """Save or update a chat session."""
        ...

    @abstractmethod
    def get_chat_session(self, session_id: str) -> Optional[list]:
        """Get chat session messages. Returns list or None."""
        ...

    @abstractmethod
    def delete_chat_session(self, session_id: str) -> None:
        """Delete a chat session."""
        ...

    @abstractmethod
    def get_chat_session_with_owner(self, session_id: str) -> Optional[dict]:
        """Get a chat session with its owner user_id. Returns dict or None."""
        ...

    @abstractmethod
    def delete_chat_session_for_user(self, session_id: str, user_id: str) -> bool:
        """Delete a chat session only if owned by user_id. Returns True if deleted."""
        ...

    @abstractmethod
    def get_user_sessions(self, user_id: str) -> list:
        """Get all chat sessions for a user, with message counts."""
        ...

    # ------------------------------------------------------------------
    # Layer convenience
    # ------------------------------------------------------------------

    @abstractmethod
    def get_user_layers(self, user_id: str) -> list:
        """Get all layers for a user with metadata."""
        ...

    # ------------------------------------------------------------------
    # Query Metrics
    # ------------------------------------------------------------------

    @abstractmethod
    def log_query_metric(self, user_id: str = "anonymous", session_id: str = None,
                         message: str = "", tool_calls: int = 0,
                         input_tokens: int = 0, output_tokens: int = 0,
                         duration_ms: int = 0, error: bool = False,
                         tool_details: list = None) -> None:
        """Log a single query metric.

        Args:
            tool_details: Optional list of per-tool-call dicts with keys:
                tool (str), success (bool), chain_position (int), retry (bool).
        """
        ...

    @abstractmethod
    def get_metrics_summary(self, user_id: str = None) -> dict:
        """Get aggregated metrics. Optionally filter by user."""
        ...

    @abstractmethod
    def cleanup_old_metrics(self, days: int = 180) -> int:
        """Delete query metrics older than N days. Returns count deleted."""
        ...

    @abstractmethod
    def get_user_stats(self, user_id: str) -> dict:
        """Get aggregated query stats for a user (for dashboard)."""
        ...
