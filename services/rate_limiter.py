"""Simple rate limiter for external API calls."""

import logging
import time
import threading

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token bucket rate limiter. Thread-safe.

    Enforces a minimum interval between requests to an external service.
    """

    def __init__(self, name: str, min_interval_seconds: float = 1.0):
        """Initialize rate limiter.

        Args:
            name: Service name (for logging).
            min_interval_seconds: Minimum seconds between requests.
        """
        self.name = name
        self.min_interval = min_interval_seconds
        self.last_request_time = 0.0
        self._lock = threading.Lock()

    def wait(self):
        """Block until it's safe to make a request."""
        with self._lock:
            now = time.time()
            elapsed = now - self.last_request_time
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
                logger.debug(f"Rate limiter [{self.name}]: waiting {sleep_time:.2f}s")
                time.sleep(sleep_time)
            self.last_request_time = time.time()

    def can_proceed(self) -> bool:
        """Check if a request can proceed without blocking."""
        with self._lock:
            return (time.time() - self.last_request_time) >= self.min_interval


# Pre-configured limiters
nominatim_limiter = RateLimiter("nominatim", min_interval_seconds=1.0)  # Nominatim policy
overpass_limiter = RateLimiter("overpass", min_interval_seconds=2.0)    # Be gentle
valhalla_limiter = RateLimiter("valhalla_public", min_interval_seconds=1.0)  # FOSSGIS policy
