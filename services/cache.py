"""Caching layer for external API responses (Nominatim, Overpass, Valhalla)."""

import hashlib
import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Default cache directory
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")


class FileCache:
    """Simple file-based cache with TTL support.

    Each cached item is a JSON file named by the hash of the key.
    Metadata (timestamp, TTL) stored alongside the data.
    """

    def __init__(self, namespace: str, ttl_seconds: int = 3600, cache_dir: str = None,
                 max_entries: int = 10000):
        """Initialize file cache.

        Args:
            namespace: Cache namespace (subdirectory name).
            ttl_seconds: Time-to-live in seconds (default: 1 hour).
            cache_dir: Override cache directory.
            max_entries: Maximum number of cache entries (default: 10000).
                Eviction check runs every 100 writes to avoid filesystem scan overhead.
        """
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._write_count = 0
        self._EVICTION_CHECK_INTERVAL = 100
        self.cache_path = os.path.join(cache_dir or CACHE_DIR, namespace)
        os.makedirs(self.cache_path, exist_ok=True)

    def _key_hash(self, key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def _file_path(self, key: str) -> str:
        return os.path.join(self.cache_path, f"{self._key_hash(key)}.json")

    def get(self, key: str) -> Optional[dict]:
        """Get cached value. Returns None if not found or expired."""
        path = self._file_path(key)
        if not os.path.exists(path):
            return None

        try:
            with open(path, "r") as f:
                entry = json.load(f)

            # Check TTL
            if time.time() - entry.get("timestamp", 0) > self.ttl:
                os.remove(path)
                return None

            # Verify full key to detect hash collisions (truncated SHA-256)
            stored_key = entry.get("key")
            if stored_key is not None and stored_key != key:
                logger.debug("Cache hash collision detected: requested key differs from stored key")
                return None

            return entry.get("data")
        except (json.JSONDecodeError, IOError):
            return None

    def set(self, key: str, data: dict):
        """Store value in cache. Uses atomic write (tempfile + rename)."""
        import tempfile
        path = self._file_path(key)
        try:
            entry = {
                "timestamp": time.time(),
                "key": key,
                "data": data,
            }
            # Write to temp file then atomic rename to prevent corruption
            fd, tmp_path = tempfile.mkstemp(dir=self.cache_path, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(entry, f)
                os.replace(tmp_path, path)  # Atomic on POSIX
            except Exception:
                os.unlink(tmp_path)  # Clean up temp file on failure
                raise
        except (IOError, OSError) as e:
            logger.warning(f"Cache write failed: {e}")
            return

        self._write_count += 1
        if self._write_count % self._EVICTION_CHECK_INTERVAL == 0:
            self._evict_if_needed()

    def _evict_if_needed(self):
        """Delete oldest cache files if entry count exceeds max_entries."""
        import glob
        files = glob.glob(os.path.join(self.cache_path, "*.json"))
        if len(files) <= self.max_entries:
            return
        # Sort by modification time (oldest first)
        files.sort(key=lambda f: os.path.getmtime(f))
        to_delete = len(files) - self.max_entries
        for f in files[:to_delete]:
            try:
                os.remove(f)
            except IOError:
                pass
        logger.info("Cache eviction: removed %d entries from %s", to_delete, self.cache_path)

    def clear(self):
        """Clear all cached entries in this namespace."""
        import glob
        for f in glob.glob(os.path.join(self.cache_path, "*.json")):
            try:
                os.remove(f)
            except IOError:
                pass

    def size(self) -> int:
        """Return number of cached entries."""
        import glob
        return len(glob.glob(os.path.join(self.cache_path, "*.json")))


# Pre-configured caches for different services
geocode_cache = FileCache("geocode", ttl_seconds=86400)      # 24 hours
overpass_cache = FileCache("overpass", ttl_seconds=3600)      # 1 hour
osrm_cache = FileCache("osrm", ttl_seconds=3600)             # 1 hour (legacy)
valhalla_cache = FileCache("valhalla", ttl_seconds=3600)     # 1 hour
