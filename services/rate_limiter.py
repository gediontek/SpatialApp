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
        sleep_time = 0
        with self._lock:
            now = time.time()
            elapsed = now - self.last_request_time
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
                # Set last_request_time to the future target so other threads
                # compute their own wait relative to this reserved slot.
                self.last_request_time = now + sleep_time
            else:
                self.last_request_time = now
        if sleep_time > 0:
            logger.debug(f"Rate limiter [{self.name}]: waiting {sleep_time:.2f}s")
            time.sleep(sleep_time)

    def would_wait(self) -> bool:
        """Check if a call to wait() would block. Informational only — not a reservation.

        WARNING: This is subject to TOCTOU races. Between calling would_wait()
        and calling wait(), another thread may have taken the slot. Do NOT use
        this as a guarantee that wait() won't block. Use it only for
        informational purposes (e.g., returning 429 to clients).
        """
        with self._lock:
            return (time.time() - self.last_request_time) < self.min_interval

    # Backward-compatible alias
    def can_proceed(self) -> bool:
        """Check if a request can proceed without blocking.

        Informational only — subject to TOCTOU races. See would_wait().
        """
        return not self.would_wait()


# Pre-configured limiters
nominatim_limiter = RateLimiter("nominatim", min_interval_seconds=1.0)  # Nominatim policy
overpass_limiter = RateLimiter("overpass", min_interval_seconds=2.0)    # Be gentle
valhalla_limiter = RateLimiter("valhalla_public", min_interval_seconds=1.0)  # FOSSGIS policy
