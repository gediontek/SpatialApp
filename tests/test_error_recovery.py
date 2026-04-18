"""Tests for v2.1 Plan 05: error recovery, size guards, circuit breaker."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest
import requests

from nl_gis.handlers import (
    PAGINATE_FEATURE_COUNT,
    REFUSE_SIZE_BYTES,
    WARN_FEATURE_COUNT,
    check_result_size,
    estimate_geojson_size,
)
from nl_gis.handlers.navigation import (
    handle_fetch_osm,
    handle_geocode,
)
from nl_gis.handlers.routing import handle_find_route
from services.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    nominatim_breaker,
)


# Circuit-breaker reset is handled globally by tests/conftest.py.


def _feature(i: int) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [0, 0]},
        "properties": {"id": i},
    }


def _fc(n: int) -> dict:
    return {"type": "FeatureCollection", "features": [_feature(i) for i in range(n)]}


# ---------------------------------------------------------------------------
# T5.1.1 — handle_geocode() error paths surface user-friendly messages
# ---------------------------------------------------------------------------

class TestGeocodeErrorPaths:
    def test_http_429_surfaces_rate_limit_message(self):
        resp = MagicMock(status_code=429)
        err = requests.HTTPError(response=resp)
        with patch("nl_gis.handlers.navigation.requests.get") as g:
            g.return_value.raise_for_status.side_effect = err
            g.return_value.json.return_value = []
            result = handle_geocode({"query": "uncached-429-query"})
        assert "error" in result
        assert "rate limit" in result["error"].lower()
        assert "str(e)" not in result["error"]

    def test_timeout_surfaces_slow_message(self):
        with patch("nl_gis.handlers.navigation.requests.get", side_effect=requests.Timeout()):
            result = handle_geocode({"query": "uncached-timeout-query"})
        assert "error" in result
        assert "slow" in result["error"].lower()

    def test_connection_error_surfaces_internet_message(self):
        with patch("nl_gis.handlers.navigation.requests.get", side_effect=requests.ConnectionError()):
            result = handle_geocode({"query": "uncached-connerr-query"})
        assert "error" in result
        assert "internet" in result["error"].lower() or "reach" in result["error"].lower()

    def test_generic_exception_does_not_leak_details(self):
        secret = "SECRET_INTERNAL_PATH_/etc/passwd"
        with patch("nl_gis.handlers.navigation.requests.get", side_effect=RuntimeError(secret)):
            result = handle_geocode({"query": "uncached-generic-query"})
        assert "error" in result
        assert secret not in result["error"]


# ---------------------------------------------------------------------------
# T5.1.2 — handle_fetch_osm() error paths
# ---------------------------------------------------------------------------

class TestFetchOsmErrorPaths:
    def _bbox_params(self):
        # Provide an explicit bbox so the handler doesn't geocode first.
        return {"feature_type": "park", "category_name": "test", "bbox": [0, 0, 0.01, 0.01]}

    def test_429_surfaces_rate_limiting_message(self):
        resp = MagicMock(status_code=429)
        err = requests.HTTPError(response=resp)
        with patch("nl_gis.handlers.navigation.requests.get") as g:
            g.return_value.raise_for_status.side_effect = err
            g.return_value.json.return_value = {}
            # Bypass cache for deterministic test
            with patch("nl_gis.handlers.navigation.overpass_cache.get", return_value=None):
                result = handle_fetch_osm(self._bbox_params())
        assert "error" in result
        assert "rate-limit" in result["error"].lower() or "rate limit" in result["error"].lower()

    def test_504_surfaces_area_too_large_message(self):
        resp = MagicMock(status_code=504)
        err = requests.HTTPError(response=resp)
        with patch("nl_gis.handlers.navigation.requests.get") as g:
            g.return_value.raise_for_status.side_effect = err
            g.return_value.json.return_value = {}
            with patch("nl_gis.handlers.navigation.overpass_cache.get", return_value=None):
                result = handle_fetch_osm(self._bbox_params())
        assert "error" in result
        assert "too large" in result["error"].lower() or "smaller" in result["error"].lower()

    def test_timeout_suggests_smaller_area(self):
        with patch("nl_gis.handlers.navigation.requests.get", side_effect=requests.Timeout()):
            with patch("nl_gis.handlers.navigation.overpass_cache.get", return_value=None):
                result = handle_fetch_osm(self._bbox_params())
        assert "error" in result
        assert "smaller" in result["error"].lower() or "specific" in result["error"].lower()


# ---------------------------------------------------------------------------
# T5.1.3 — handle_find_route() degradation
# ---------------------------------------------------------------------------

class TestFindRouteDegradation:
    def test_service_down_produces_temporarily_unavailable(self):
        # Mock successful geocoding so the failure is clearly service-side.
        good = {"lat": 1.0, "lon": 1.0, "display_name": "x", "bbox": None}
        with patch("services.valhalla_client.get_route", return_value=None), \
             patch("nl_gis.handlers.navigation.handle_geocode", return_value=good):
            result = handle_find_route({
                "from_location": "A",
                "to_location": "B",
                "profile": "driving",
            })
        assert "error" in result
        assert "temporarily unavailable" in result["error"].lower()

    def test_unsupported_profile_produces_profile_specific_message(self):
        good = {"lat": 1.0, "lon": 1.0, "display_name": "x", "bbox": None}
        with patch("services.valhalla_client.get_route", return_value=None), \
             patch("nl_gis.handlers.navigation.handle_geocode", return_value=good):
            result = handle_find_route({
                "from_location": "A",
                "to_location": "B",
                "profile": "teleport",
            })
        assert "error" in result
        assert "teleport" in result["error"].lower()


# ---------------------------------------------------------------------------
# T5.1.4 — CircuitBreaker state machine + concurrency
# ---------------------------------------------------------------------------

class TestCircuitBreakerStateMachine:
    def test_five_failures_transitions_to_open(self):
        now = [0.0]
        cb = CircuitBreaker("test", failure_threshold=5, recovery_timeout_s=10, clock=lambda: now[0])
        for _ in range(5):
            with pytest.raises(RuntimeError):
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        assert cb.state == "open"

    def test_open_state_rejects_calls_with_circuit_open_error(self):
        now = [0.0]
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout_s=10, clock=lambda: now[0])
        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        # Next call: should raise CircuitOpenError immediately without running fn.
        called = {"count": 0}

        def tracker():
            called["count"] += 1
            return "ok"

        with pytest.raises(CircuitOpenError) as exc:
            cb.call(tracker)
        assert called["count"] == 0
        assert "test" in str(exc.value)

    def test_after_recovery_timeout_transitions_to_half_open_on_probe(self):
        now = [0.0]
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout_s=10, clock=lambda: now[0])
        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        assert cb.state == "open"
        # Advance past cooldown.
        now[0] = 11.0
        # The next successful call probes — state should be CLOSED after it.
        result = cb.call(lambda: "ok")
        assert result == "ok"
        assert cb.state == "closed"

    def test_success_in_half_open_transitions_to_closed(self):
        # Covered by the previous test's final assertion; keeping this as a
        # dedicated test for clarity.
        now = [0.0]
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout_s=5, clock=lambda: now[0])
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        now[0] = 6.0
        cb.call(lambda: "ok")
        assert cb.state == "closed"

    def test_failure_in_half_open_reopens_circuit(self):
        now = [0.0]
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout_s=5, clock=lambda: now[0])
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        now[0] = 6.0  # cooldown elapsed — next call probes
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        assert cb.state == "open"

    def test_success_in_closed_resets_failure_count(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout_s=10)
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        assert cb._failure_count == 2  # noqa: SLF001 (test-only introspection)
        cb.call(lambda: "ok")
        assert cb._failure_count == 0  # noqa: SLF001
        assert cb.state == "closed"

    def test_concurrent_calls_do_not_corrupt_state(self):
        cb = CircuitBreaker("test", failure_threshold=100, recovery_timeout_s=10)

        def worker():
            try:
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
            except RuntimeError:
                pass

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 10 failures recorded — no races, no duplicates.
        assert cb._failure_count == 10  # noqa: SLF001
        assert cb.state == "closed"  # threshold is 100


# ---------------------------------------------------------------------------
# T5.1.5 — check_result_size() threshold behavior
# ---------------------------------------------------------------------------

class TestCheckResultSize:
    def test_below_warn_threshold_no_warning(self):
        r = check_result_size({"geojson": _fc(100), "layer_name": "x"})
        assert "size_warning" not in r
        assert "truncated" not in r
        assert "error" not in r
        assert len(r["geojson"]["features"]) == 100

    def test_above_warn_below_paginate_adds_warning_but_keeps_features(self):
        r = check_result_size({"geojson": _fc(WARN_FEATURE_COUNT + 1), "layer_name": "x"})
        assert "size_warning" in r
        assert "truncated" not in r
        assert len(r["geojson"]["features"]) == WARN_FEATURE_COUNT + 1

    def test_above_paginate_truncates(self):
        r = check_result_size({"geojson": _fc(PAGINATE_FEATURE_COUNT + 1), "layer_name": "x"})
        assert r.get("truncated") is True
        assert r.get("original_count") == PAGINATE_FEATURE_COUNT + 1
        assert len(r["geojson"]["features"]) == PAGINATE_FEATURE_COUNT

    def test_above_refuse_bytes_empties_and_adds_error(self):
        # Construct a result whose estimated size exceeds REFUSE_SIZE_BYTES.
        # Use a handful of features with massive property payloads to keep the
        # test fast while forcing the size threshold.
        bloated_props = {"blob": "x" * 20_000_000}  # ~20MB per feature
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": bloated_props,
            }
            for _ in range(6)
        ]
        fc = {"type": "FeatureCollection", "features": features}
        result = {"geojson": fc, "layer_name": "x"}
        out = check_result_size(result)
        assert "error" in out
        assert "too large" in out["error"].lower()
        assert out["geojson"]["features"] == []
        assert out["refused_size_bytes"] > REFUSE_SIZE_BYTES


# ---------------------------------------------------------------------------
# T5.1.6 — estimate_geojson_size() accuracy
# ---------------------------------------------------------------------------

class TestEstimateGeojsonSize:
    def test_empty_collection_returns_zero(self):
        assert estimate_geojson_size({"type": "FeatureCollection", "features": []}) == 0

    def test_point_features_within_2x_of_actual(self):
        import json
        fc = _fc(100)
        actual = len(json.dumps(fc))
        est = estimate_geojson_size(fc)
        assert 0.5 * actual <= est <= 2.0 * actual

    def test_complex_polygon_features_within_2x_of_actual(self):
        import json
        ring = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {"id": i, "name": f"poly_{i}", "note": "x" * 50},
            }
            for i in range(100)
        ]
        fc = {"type": "FeatureCollection", "features": features}
        actual = len(json.dumps(fc))
        est = estimate_geojson_size(fc)
        assert 0.5 * actual <= est <= 2.0 * actual


# ---------------------------------------------------------------------------
# T5.1.7 — circuit breaker integrates with handle_geocode
# ---------------------------------------------------------------------------

class TestGeocodeCircuitBreakerIntegration:
    def test_three_failures_opens_circuit_then_short_circuits(self):
        """Three upstream failures should open Nominatim's breaker so the
        fourth call returns the 'temporarily unavailable' message without
        making a further HTTP request."""
        http_calls = {"count": 0}

        def _failing(*args, **kwargs):
            http_calls["count"] += 1
            raise requests.ConnectionError("dead")

        # nominatim_breaker has threshold=3. Three consecutive failures should
        # open the circuit; the fourth call should short-circuit.
        with patch("nl_gis.handlers.navigation.requests.get", side_effect=_failing), \
             patch("nl_gis.handlers.navigation.geocode_cache.get", return_value=None):
            for i in range(3):
                out = handle_geocode({"query": f"distinct-query-{i}"})
                assert "error" in out
            # Fourth call — should short-circuit without invoking requests.get.
            out = handle_geocode({"query": "distinct-query-short-circuit"})
            assert "error" in out
            assert "temporarily unavailable" in out["error"].lower()

        # HTTP was called 3 times, not 4.
        assert http_calls["count"] == 3
