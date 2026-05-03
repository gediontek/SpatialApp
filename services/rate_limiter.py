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


class PerKeyRateLimiter:
    """Sliding-window per-key rate limiter for inbound requests.

    Tracks recent timestamps per key (typically a client IP) and rejects
    when the window would exceed `max_requests`. Thread-safe. In-memory
    only — counters reset on process restart and are not shared across
    workers; for multi-worker deployments use Redis or nginx limit_req.

    Audit N11: applied to /api/register to prevent bot-creates / token
    exhaustion / username enumeration.
    """

    def __init__(self, name: str, max_requests: int, window_seconds: int):
        self.name = name
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Return True if the key may proceed; record the event when True."""
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            history = self._events.setdefault(key, [])
            # Drop expired
            while history and history[0] < cutoff:
                history.pop(0)
            if len(history) >= self.max_requests:
                return False
            history.append(now)
            # Drop the bucket entirely if it ever empties to bound memory.
            if not history:
                self._events.pop(key, None)
            return True

    def reset(self, key: str = None) -> None:
        """Reset state. Useful in tests."""
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)


# 5 registrations per IP per hour — covers typical UX (forgot-token scenarios)
# while blocking unattended bot-create loops. Tunable via env if needed later.
register_limiter = PerKeyRateLimiter("register", max_requests=5, window_seconds=3600)

# Per-user chat throttle. 60 messages per minute is well above any human
# typing rate but caps automated bursts that would otherwise burn provider
# tokens. Audit N12.
chat_limiter = PerKeyRateLimiter("chat", max_requests=60, window_seconds=60)
