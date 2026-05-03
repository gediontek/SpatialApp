"""Shared pytest fixtures for the SpatialApp test suite."""

import os
from pathlib import Path

# Audit M3: point RASTER_DIR at the committed test fixture before any
# `from config import Config` import in test files. config.py:105 reads
# RASTER_DIR from env at import time; setting it here makes the bundled
# tests/fixtures/raster/geog_wgs84.tif visible to tests/test_raster.py.
# We also overwrite Config.RASTER_DIR in case Config was already imported.
_FIXTURE_RASTER_DIR = Path(__file__).parent / 'fixtures' / 'raster'
if _FIXTURE_RASTER_DIR.is_dir():
    os.environ['RASTER_DIR'] = str(_FIXTURE_RASTER_DIR)
    try:
        from config import Config as _Config
        _Config.RASTER_DIR = str(_FIXTURE_RASTER_DIR)
    except Exception:
        pass

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
