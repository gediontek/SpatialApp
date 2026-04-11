# Plan 5: Error Recovery and Graceful Degradation

**Objective**: Replace raw tracebacks and silent failures with user-friendly error messages, result size guards, retry logic with circuit breaker, and graceful degradation when external services are unavailable.

**Scope**: ~350 lines of code | 2 days | Files: `nl_gis/handlers/navigation.py`, `nl_gis/handlers/routing.py`, `nl_gis/handlers/analysis.py`, `nl_gis/handlers/__init__.py`, `services/circuit_breaker.py` (new), `nl_gis/chat.py`, `tests/test_error_recovery.py` (new)

**Current State**:
- `handle_geocode()` (navigation.py line 56-58): catches all exceptions, returns `{"error": f"Geocoding failed: {str(e)}"}` -- leaks exception details to users
- `handle_fetch_osm()` (navigation.py line 141): catches `requests.Timeout` separately but `requests.RequestException` leaks `str(e)`
- `handle_search_nearby()` (navigation.py line 380): same pattern -- timeout vs generic exception with leaked details
- `handle_find_route()` (routing.py): delegates to `valhalla_client.get_route()` which returns `None` on failure; handler returns `{"error": "Routing failed"}` but no retry or fallback
- `_request_with_retry()` (valhalla_client.py line 83): retries on 5xx and connection errors, but no circuit breaker -- keeps hammering a dead service
- No result size guards: `fetch_osm` caps at `MAX_FEATURES_PER_LAYER` (5000) via `_osm_to_geojson()` (handlers/__init__.py line 157), but returns the full payload without warning the user about memory impact
- `dispatch_tool()` (handlers/__init__.py line 419): catches `ValueError` but all other exceptions propagate to `_process_message_inner()` which logs and returns generic error

---

## M1: Catalog Every Error Path

**Goal**: Document every error path in the 5 handler modules to establish a baseline for improvement.

### Epic 1.1: Error Path Audit

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.1.1 | Audit `nl_gis/handlers/navigation.py`: list every `return {"error": ...}` and `except` block. Document: (1) what triggers it, (2) what message the user sees, (3) whether exception details leak. Functions: `handle_geocode` (lines 14-58), `handle_fetch_osm` (lines 61-162), `handle_map_command` (lines 165-217), `handle_reverse_geocode` (lines 220-271), `handle_batch_geocode` (lines 274-307), `handle_search_nearby` (lines 310-393) | Audit document (inline code comments) lists all error paths with leak assessment. Count: expect ~15 error paths | S |
| T1.1.2 | Audit `nl_gis/handlers/analysis.py`: same assessment for `handle_buffer`, `handle_spatial_query`, `handle_aggregate`, `handle_filter_layer`, `handle_calculate_area`, `handle_measure_distance`, and all geometry/advanced analysis handlers | Audit document lists all error paths. Count: expect ~25 error paths | S |
| T1.1.3 | Audit `nl_gis/handlers/routing.py`: assess `handle_find_route`, `handle_isochrone`, `handle_closest_facility`, `handle_optimize_route`, `handle_service_area`, `handle_od_matrix`, `handle_heatmap` | Audit document lists all error paths. Count: expect ~15 error paths | S |
| T1.1.4 | Audit `nl_gis/handlers/layers.py` and `nl_gis/handlers/annotations.py`: assess import/export handlers and annotation handlers | Audit document lists all error paths. Count: expect ~10 error paths | S |
| T1.1.5 | Summarize audit as a comment block at the top of each handler file: `# ERROR PATHS: {count} total, {leak_count} leak details, {silent_count} silent failures` | Each handler file has summary comment; total error paths documented | XS |

---

## M2: Graceful Degradation for External Services

**Goal**: When Nominatim returns 429, Valhalla is down, or Overpass returns too many features, provide helpful user messages and fallback behavior instead of raw errors.

### Epic 2.1: Nominatim (Geocoding) Degradation

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.1.1 | In `handle_geocode()` (navigation.py line 37-58), replace the generic `except Exception` with specific catches: `requests.HTTPError` for 429 (rate limit), `requests.Timeout`, `requests.ConnectionError`, and generic `Exception`. For 429: return `{"error": "Geocoding rate limit reached. Please wait a few seconds and try again."}`. For timeout: return `{"error": "Geocoding service is slow. Try again shortly."}`. For connection error: return `{"error": "Cannot reach geocoding service. Check your internet connection."}`. For generic: log with `exc_info=True`, return `{"error": "Geocoding encountered an unexpected issue. Try a different search term."}` | Each error type produces a distinct, user-friendly message; no exception details leaked; all logged with `exc_info=True` | S |
| T2.1.2 | Apply the same specific-catch pattern to `handle_reverse_geocode()` (navigation.py lines 248-271) and `handle_search_nearby()` (navigation.py lines 370-382) | Both functions have specific error handling; messages are user-friendly; no details leaked | S |
| T2.1.3 | In `handle_batch_geocode()` (navigation.py lines 274-307), if more than 50% of addresses fail geocoding, return a summary warning: `"Geocoded {n}/{total} addresses. {len(failed)} failed (service may be rate-limiting). Failed: {first_5_failed}..."`. Currently silently accumulates failures into `failed` list without warning the user about the pattern | Batch geocode with >50% failure rate includes warning message in result; existing `failed` list still returned | S |

### Epic 2.2: Valhalla (Routing) Degradation

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.2.1 | In `handle_find_route()` (routing.py), when `get_route()` returns `None`, provide a more helpful error. Currently returns `{"error": "Routing failed. Check locations and try again."}`. Change to detect the likely cause: if both points geocoded successfully, say `"Routing service is temporarily unavailable. Try again in a minute."`. If the profile is unusual, say `"Routing not available for '{profile}' mode between these locations."` | Error message is context-specific; distinguishes service-down from unsupported-route | S |
| T2.2.2 | In `handle_isochrone()` (routing.py), when `get_isochrone()` returns `None`, provide specific error: `"Could not compute {time_minutes}-minute {profile} reachability from this location. The routing service may be temporarily unavailable."` | Isochrone failure includes the requested parameters in the error message | XS |
| T2.2.3 | In `handle_closest_facility()` (routing.py), if the Overpass query for facilities succeeds but subsequent distance calculations fail, return partial results with a note: `"Found {n} facilities but could not compute distances for {m} of them. Showing results without distance sorting."` instead of failing entirely | Partial results returned on partial failure; user informed about limitations | S |

### Epic 2.3: Overpass (OSM) Degradation

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.3.1 | In `handle_fetch_osm()` (navigation.py lines 131-142), add specific handling for HTTP 429 (Overpass rate limit): `"OpenStreetMap data service is rate-limiting requests. Wait 30 seconds and try again, or use a smaller area."`. For HTTP 504 (gateway timeout on large queries): `"The area is too large for this query. Try zooming in or searching a smaller region."` | 429 and 504 produce distinct, actionable error messages; other HTTP errors still use generic message | S |
| T2.3.2 | In `_osm_to_geojson()` (handlers/__init__.py lines 144-266), when feature count reaches `MAX_FEATURES_PER_LAYER` (5000), the result already includes `capped=True` and a `note`. Enhance: also include `"suggestion": "Try a smaller area or more specific feature type (e.g., 'hospital' instead of 'building')"` in the result dict | Capped results include actionable suggestion; existing `note` field preserved | XS |

---

## M3: Result Size Guards

**Goal**: Warn users about large results (>5K features), auto-paginate very large results (>10K), and refuse results that would cause memory issues (>100MB estimated).

### Epic 3.1: Size Estimation and Guards

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T3.1.1 | Add `estimate_geojson_size(geojson: dict) -> int` to `nl_gis/handlers/__init__.py`. Estimates byte size without full serialization: `feature_count * avg_feature_size`. Compute `avg_feature_size` from first 10 features via `len(json.dumps(feature))`. Returns estimated bytes | Function returns size estimate within 2x of actual `len(json.dumps(geojson))` for test data; handles empty FeatureCollections (returns 0) | S |
| T3.1.2 | Add `SIZE_THRESHOLDS` constants to `nl_gis/handlers/__init__.py`: `WARN_FEATURE_COUNT = 5000`, `PAGINATE_FEATURE_COUNT = 10000`, `REFUSE_SIZE_BYTES = 100 * 1024 * 1024` (100MB) | Constants defined and documented | XS |
| T3.1.3 | Add `check_result_size(result: dict) -> dict` to `nl_gis/handlers/__init__.py`. Checks `result["geojson"]` if present. If feature count > `WARN_FEATURE_COUNT`: add `result["size_warning"] = "Large result: {n} features. Map performance may be affected."`. If > `PAGINATE_FEATURE_COUNT`: truncate features to `PAGINATE_FEATURE_COUNT`, add `result["truncated"] = True`, `result["original_count"] = n`. If estimated size > `REFUSE_SIZE_BYTES`: replace geojson with empty FeatureCollection, add `result["error"] = "Result too large ({size_mb:.0f} MB). Narrow your query."` | Warning at 5K, truncation at 10K with note, refusal at 100MB with error; each threshold tested | M |

### Epic 3.2: Integration with Dispatch

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T3.2.1 | In `dispatch_tool()` (handlers/__init__.py line 419), after calling the handler, call `check_result_size(result)` for tools in `LAYER_PRODUCING_TOOLS`. Return the modified result | All layer-producing tool results pass through size check; non-layer tools unaffected | S |
| T3.2.2 | In `ChatSession._process_message_inner()` (chat.py), when a tool result contains `size_warning`, yield it as a separate message event: `{"type": "message", "text": result["size_warning"], "done": false}` before the `layer_add` event | User sees size warning in chat before the layer appears on the map | S |
| T3.2.3 | In `static/js/chat.js` `handleEvent()`, handle a `truncated` flag on `layer_add` events. If `data.truncated`, append a note to the chat: `"Showing first {data.feature_count} of {data.original_count} features. Use filter_layer to narrow results."` | Truncation note appears in chat UI; layer still renders with truncated features | S |

---

## M4: Circuit Breaker Pattern

**Goal**: Stop hammering external services that are down. After N consecutive failures, open the circuit for a cooldown period, then probe with a single request.

### Epic 4.1: Circuit Breaker Implementation

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.1.1 | Create `services/circuit_breaker.py` with `CircuitBreaker` class. States: `CLOSED` (normal), `OPEN` (rejecting calls), `HALF_OPEN` (probing). Constructor: `CircuitBreaker(name: str, failure_threshold: int = 5, recovery_timeout_s: float = 60)`. Methods: `call(fn, *args, **kwargs)` -- wraps a function call with circuit breaker logic; `record_success()`, `record_failure()`, `is_open() -> bool`, `state -> str` | Class implements standard circuit breaker pattern; state transitions: CLOSED->OPEN after N failures, OPEN->HALF_OPEN after timeout, HALF_OPEN->CLOSED on success, HALF_OPEN->OPEN on failure | M |
| T4.1.2 | In `CircuitBreaker.call()`: if OPEN and recovery timeout not elapsed, raise `CircuitOpenError(name, remaining_seconds)` without calling the function. If OPEN and timeout elapsed, transition to HALF_OPEN, call function -- on success transition to CLOSED, on failure transition back to OPEN. If CLOSED, call function -- on success reset failure count, on failure increment count | State transitions are correct; OPEN state rejects calls immediately; HALF_OPEN probes correctly | S |
| T4.1.3 | Add `CircuitOpenError` exception class to `services/circuit_breaker.py`: `"Service '{name}' is temporarily unavailable. Try again in {remaining_s:.0f} seconds."` | Exception has user-friendly message; includes service name and remaining cooldown time | XS |
| T4.1.4 | Add thread safety to `CircuitBreaker`: use `threading.Lock` for state transitions and failure count updates. The `call()` method must be safe for concurrent access | Thread-safe; concurrent calls don't corrupt state; lock scope is minimal (state check + transition, not the actual function call) | S |

### Epic 4.2: Circuit Breaker Integration

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.2.1 | Create three circuit breaker instances in `services/circuit_breaker.py` as module-level singletons: `nominatim_breaker = CircuitBreaker("Nominatim", failure_threshold=3, recovery_timeout_s=30)`, `overpass_breaker = CircuitBreaker("Overpass", failure_threshold=3, recovery_timeout_s=60)`, `valhalla_breaker = CircuitBreaker("Valhalla", failure_threshold=5, recovery_timeout_s=60)` | Three instances created; thresholds reflect service characteristics (Nominatim is stricter, Valhalla more tolerant) | XS |
| T4.2.2 | In `handle_geocode()` (navigation.py), wrap the `requests.get()` call with `nominatim_breaker.call()`. Catch `CircuitOpenError` and return `{"error": str(e)}`. On success, `record_success()`. On request failure, `record_failure()` before returning the error dict | Circuit breaker protects Nominatim; after 3 failures, subsequent calls return "temporarily unavailable" without making HTTP requests; recovery probe after 30s | M |
| T4.2.3 | In `handle_fetch_osm()` and `handle_search_nearby()` (navigation.py), wrap Overpass `requests.get()` calls with `overpass_breaker.call()`. Same pattern as T4.2.2 | Circuit breaker protects Overpass; after 3 failures, circuit opens for 60s | S |
| T4.2.4 | In `_request_with_retry()` (valhalla_client.py line 83), integrate `valhalla_breaker`. Check `valhalla_breaker.is_open()` before attempting request. On final retry failure, call `valhalla_breaker.record_failure()`. On success, call `valhalla_breaker.record_success()`. When circuit is open, return `None` immediately (existing callers already handle `None`) | Circuit breaker protects Valhalla; integrates with existing retry logic; after 5 total failures (not 5 retried calls), circuit opens | M |

---

## M5: Test Each Error Condition

**Goal**: Verify every error path produces a user-friendly message, circuit breaker opens/closes correctly, and size guards trigger at thresholds.

### Epic 5.1: Error Recovery Test Suite

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T5.1.1 | Create `tests/test_error_recovery.py`. Test `handle_geocode()` error paths: mock `requests.get` to raise `requests.HTTPError(response=Mock(status_code=429))` -> verify "rate limit" message; mock `requests.Timeout` -> verify "slow" message; mock `requests.ConnectionError` -> verify "internet connection" message; mock generic `Exception` -> verify no exception details in response | 4 test cases; all pass; no test leaks exception details | M |
| T5.1.2 | Test `handle_fetch_osm()` error paths: mock Overpass returning 429 -> verify "rate-limiting" message; mock 504 -> verify "too large" message; mock timeout -> verify "smaller area" suggestion | 3 test cases; all pass | S |
| T5.1.3 | Test `handle_find_route()` degradation: mock `get_route()` returning `None` with both points geocoded -> verify "temporarily unavailable" message; mock with invalid profile -> verify profile-specific message | 2 test cases; all pass | S |
| T5.1.4 | Test `CircuitBreaker` state machine: (1) 5 failures transitions to OPEN; (2) OPEN rejects calls with `CircuitOpenError`; (3) after recovery timeout, transitions to HALF_OPEN; (4) success in HALF_OPEN transitions to CLOSED; (5) failure in HALF_OPEN transitions to OPEN; (6) success in CLOSED resets failure count; (7) thread-safety: 10 concurrent calls don't corrupt state | 7 test cases; all pass; thread-safety test uses `threading.Thread` | M |
| T5.1.5 | Test `check_result_size()`: (1) < 5000 features -> no warning; (2) 5001 features -> warning present, features intact; (3) 10001 features -> truncated to 10000, `truncated=True`; (4) estimated > 100MB -> error, empty features | 4 test cases; all pass | S |
| T5.1.6 | Test `estimate_geojson_size()`: empty collection -> 0; 100 simple point features -> estimate within 2x of actual; 100 complex polygon features -> estimate within 2x of actual | 3 test cases; all pass | S |
| T5.1.7 | Integration test: circuit breaker with `handle_geocode()`. Mock 3 consecutive failures -> verify circuit opens -> verify next call returns "temporarily unavailable" without HTTP call -> mock time advance past recovery -> verify probe call goes through | 1 integration test; passes; uses `unittest.mock.patch` for time | M |

---

## Dependencies and Risks

| Risk | Mitigation |
|------|-----------|
| Circuit breaker opens too aggressively (3 failures on Nominatim) | Threshold is configurable; monitor in production; adjust if needed. 30s recovery is short enough to not block users long |
| `estimate_geojson_size()` inaccurate for layers with highly variable feature sizes | Sample first 10 features; 2x accuracy is sufficient for guard thresholds which are order-of-magnitude decisions |
| Size guard truncation loses data silently | `truncated=True` flag explicitly communicated to user with original count; user can filter to get specific subset |
| Specific error messages reveal service architecture (Nominatim, Overpass, Valhalla names) | Acceptable trade-off; messages use service category ("geocoding service", "routing service") not specific URLs |
| Circuit breaker state not persisted across restarts | Acceptable; circuit resets to CLOSED on restart; services likely recovered during restart window |

## Files Modified

| File | Change |
|------|--------|
| `services/circuit_breaker.py` | **New file** -- `CircuitBreaker` class, `CircuitOpenError`, 3 singleton instances |
| `nl_gis/handlers/navigation.py` | Modify `handle_geocode()`, `handle_reverse_geocode()`, `handle_fetch_osm()`, `handle_search_nearby()`, `handle_batch_geocode()` for specific error handling and circuit breaker integration |
| `nl_gis/handlers/routing.py` | Modify `handle_find_route()`, `handle_isochrone()`, `handle_closest_facility()` for context-specific error messages |
| `nl_gis/handlers/__init__.py` | Add `estimate_geojson_size()`, `check_result_size()`, `SIZE_THRESHOLDS` constants. Modify `dispatch_tool()` for size guard integration. Modify `_osm_to_geojson()` for enhanced capped-result suggestions |
| `services/valhalla_client.py` | Modify `_request_with_retry()` for circuit breaker integration |
| `nl_gis/chat.py` | Modify `_process_message_inner()` to yield size warnings as message events |
| `static/js/chat.js` | Modify `handleEvent()` for truncation notes |
| `tests/test_error_recovery.py` | **New file** -- 24+ test cases for error handling, circuit breaker, and size guards |
