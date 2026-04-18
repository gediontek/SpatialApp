"""Shared pytest fixtures for the SpatialApp test suite."""

import pytest


@pytest.fixture(autouse=True)
def _reset_circuit_breakers():
    """Reset all module-level circuit breakers before every test.

    The breakers in services/circuit_breaker.py are process-wide singletons.
    Without this fixture, a test that deliberately trips a breaker (e.g., the
    Plan 05 M4 state-machine tests) leaves the breaker OPEN, causing every
    subsequent geocode/overpass/valhalla test to short-circuit with a
    "temporarily unavailable" error.
    """
    from services.circuit_breaker import (
        nominatim_breaker, overpass_breaker, valhalla_breaker, _State,
    )
    for b in (nominatim_breaker, overpass_breaker, valhalla_breaker):
        with b._lock:
            b._state = _State.CLOSED
            b._failure_count = 0
            b._opened_at = None
    yield
