"""Circuit breaker for protecting external service calls.

When an external service (Nominatim, Overpass, Valhalla) starts failing,
we stop hammering it: after N consecutive failures the breaker opens,
rejecting calls instantly until a cooldown elapses. The first call after
the cooldown probes the service — if it succeeds the breaker closes, if
it fails the cooldown resets.

Design constraints:
- Thread-safe: the handlers package is used by Flask request workers that
  each may invoke the same breaker concurrently.
- Lock scope is minimal — the wrapped function call runs OUTSIDE the lock
  so a slow external service can't serialize other request threads.
- State is in-memory only; breakers reset to CLOSED on process restart.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class _State(Enum):
    CLOSED = "closed"      # normal operation
    OPEN = "open"          # rejecting calls
    HALF_OPEN = "half_open"  # probing after cooldown


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the breaker is open."""

    def __init__(self, name: str, remaining_seconds: float):
        self.name = name
        self.remaining_seconds = remaining_seconds
        super().__init__(
            f"Service '{name}' is temporarily unavailable. "
            f"Try again in {remaining_seconds:.0f} seconds."
        )


class CircuitBreaker:
    """Standard three-state circuit breaker.

    Transitions:
        CLOSED    --N failures-->       OPEN
        OPEN      --timeout elapsed-->  HALF_OPEN   (on next call())
        HALF_OPEN --success-->          CLOSED
        HALF_OPEN --failure-->          OPEN         (cooldown resets)
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self._clock = clock
        self._lock = threading.Lock()
        self._state = _State.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None

    # --- introspection ---------------------------------------------------

    @property
    def state(self) -> str:
        with self._lock:
            return self._state.value

    def is_open(self) -> bool:
        """Return True if the breaker is currently rejecting calls.

        A breaker whose cooldown has elapsed is reported as NOT open — the
        caller's next call() will transition it to HALF_OPEN and probe.
        """
        with self._lock:
            if self._state == _State.CLOSED:
                return False
            if self._state == _State.HALF_OPEN:
                return False
            # OPEN: still open only while cooldown remains
            return self._remaining_cooldown() > 0

    # --- recording ops (public for callers that don't wrap via call()) ---

    def record_success(self) -> None:
        with self._lock:
            if self._state in (_State.CLOSED, _State.HALF_OPEN):
                if self._state == _State.HALF_OPEN:
                    logger.info("Circuit '%s' closed after successful probe", self.name)
                self._state = _State.CLOSED
                self._failure_count = 0
                self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            if self._state == _State.HALF_OPEN:
                # Probe failed — reopen with fresh cooldown.
                self._state = _State.OPEN
                self._opened_at = self._clock()
                logger.warning(
                    "Circuit '%s' reopened after failed probe", self.name
                )
                return
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                if self._state != _State.OPEN:
                    logger.warning(
                        "Circuit '%s' opened after %d failures",
                        self.name, self._failure_count,
                    )
                self._state = _State.OPEN
                self._opened_at = self._clock()

    # --- the main API ----------------------------------------------------

    def call(self, fn: Callable[..., T], *args, **kwargs) -> T:
        """Invoke fn() under circuit-breaker protection.

        Raises:
            CircuitOpenError: if the breaker is open and cooldown hasn't elapsed.
            Exception: whatever fn raises (re-raised after recording failure).
        """
        self._check_and_transition()
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result

    # --- internals -------------------------------------------------------

    def _remaining_cooldown(self) -> float:
        if self._opened_at is None:
            return 0.0
        elapsed = self._clock() - self._opened_at
        return max(0.0, self.recovery_timeout_s - elapsed)

    def _check_and_transition(self) -> None:
        """Before a call: if OPEN + cooldown elapsed, move to HALF_OPEN.
        If OPEN + cooldown remaining, raise CircuitOpenError.
        """
        with self._lock:
            if self._state == _State.OPEN:
                remaining = self._remaining_cooldown()
                if remaining > 0:
                    raise CircuitOpenError(self.name, remaining)
                # Cooldown elapsed — transition to probing.
                self._state = _State.HALF_OPEN
                logger.info(
                    "Circuit '%s' half-opened for probe", self.name
                )


# ---------------------------------------------------------------------------
# Module-level singletons — one breaker per external service.
# Thresholds reflect service characteristics:
#   Nominatim aggressively rate-limits (3 / short cooldown)
#   Overpass tolerates more failures (3 / long cooldown — recovery is slow)
#   Valhalla is usually local or self-hosted (5 / long cooldown)
# ---------------------------------------------------------------------------

nominatim_breaker = CircuitBreaker("Nominatim", failure_threshold=3, recovery_timeout_s=30.0)
overpass_breaker = CircuitBreaker("Overpass", failure_threshold=3, recovery_timeout_s=60.0)
valhalla_breaker = CircuitBreaker("Valhalla", failure_threshold=5, recovery_timeout_s=60.0)
