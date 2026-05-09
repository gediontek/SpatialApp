"""Frontend auth-on-fetch harness — pins the contracts that
`static/js/auth.js` (the H1+M1+M2 audit centralization) is supposed to
guarantee for every state-mutating call from the browser.

Pins:
  A1 — CSRF token from `<meta name="csrf-token">` is attached to POST/PUT/DELETE
  A2 — CSRF token is NOT attached to GET/HEAD/OPTIONS (no false positives)
  A3 — Bearer token from localStorage is attached when present
  A4 — No Authorization header when localStorage has no token
  A5 — `window.SpatialAuth` exposes the public helpers
  A6 — jQuery `$.ajax` beforeSend wires CSRF + Bearer for state-mutating
       (the legacy code path; H1 audit required parity with fetch)
  A7 — auth.js loads BEFORE main.js / chat.js / layers.js so they can
       call `window.authedFetch` synchronously at init

These are observable contracts. The harness intercepts the requests the
browser actually emits and asserts on the headers — same approach as the
Playwright route-level mocks in test_browser_render.py.
"""
from __future__ import annotations

import time

import pytest


# Bearer the test will plant in localStorage (must look like a real token
# to satisfy any client-side format check; sk- prefix matches register).
_TEST_BEARER = "sk-spa-frontend-auth-harness-token"


def _block_socketio(page):
    page.route(
        "**/socket.io/**",
        lambda route, _req: route.abort(),
    )


# ---------------------------------------------------------------------------
# A5 + A7 — script loaded, helpers exposed
# ---------------------------------------------------------------------------

@pytest.mark.golden
def test_spatialauth_helpers_exposed_on_window(live_app, chromium):
    """auth.js must define `window.SpatialAuth` and `window.authedFetch`
    (alias). Without these, every other audit-H1 fix collapses because
    main.js/chat.js/layers.js look them up synchronously."""
    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    assert chromium.evaluate(
        "typeof window.SpatialAuth === 'object' && "
        "typeof window.SpatialAuth.authedFetch === 'function' && "
        "typeof window.SpatialAuth.getCsrfToken === 'function' && "
        "typeof window.SpatialAuth.getBearerToken === 'function' && "
        "typeof window.SpatialAuth.authedAjaxBeforeSend === 'function'"
    ), "window.SpatialAuth missing or incomplete — H1 centralization broken"

    assert chromium.evaluate(
        "typeof window.authedFetch === 'function' && "
        "window.authedFetch === window.SpatialAuth.authedFetch"
    ), "window.authedFetch alias missing — chat.js will fall back to fetch"


@pytest.mark.golden
def test_auth_js_loads_before_dependents(live_app, chromium):
    """Order matters: auth.js MUST execute before main.js / chat.js /
    layers.js otherwise their init code can't see `window.authedFetch`.
    We assert the contract at runtime via DOM order — cheap and stable."""
    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    script_srcs = chromium.evaluate(
        "Array.from(document.querySelectorAll('script[src]'))"
        ".map(s => s.getAttribute('src'))"
    )
    auth_idx = next(
        (i for i, s in enumerate(script_srcs) if s and s.endswith("auth.js")),
        None,
    )
    main_idx = next(
        (i for i, s in enumerate(script_srcs) if s and s.endswith("main.js")),
        None,
    )
    chat_idx = next(
        (i for i, s in enumerate(script_srcs) if s and s.endswith("chat.js")),
        None,
    )
    layers_idx = next(
        (i for i, s in enumerate(script_srcs) if s and s.endswith("layers.js")),
        None,
    )

    assert auth_idx is not None, "auth.js <script> not found in DOM"
    for name, idx in (("main.js", main_idx), ("chat.js", chat_idx),
                      ("layers.js", layers_idx)):
        assert idx is not None, f"{name} <script> not found in DOM"
        assert auth_idx < idx, (
            f"auth.js (index {auth_idx}) must load before {name} "
            f"(index {idx}) so window.authedFetch is defined at init time"
        )


# ---------------------------------------------------------------------------
# A1 — CSRF on state-mutating
# ---------------------------------------------------------------------------

@pytest.mark.golden
def test_csrf_token_attached_to_post(live_app, chromium):
    """authedFetch must attach `X-CSRFToken` from the meta tag on POST."""
    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    # Capture the request the page makes.
    captured = {}

    def _capture(route, request):
        captured["headers"] = dict(request.headers)
        # Return a trivial 200 so the page doesn't error.
        route.fulfill(status=200, content_type="application/json", body="{}")

    chromium.route("**/api/_capture_csrf", _capture)

    # Read the meta token, then fire authedFetch and wait for the call.
    expected_csrf = chromium.evaluate(
        "document.querySelector('meta[name=\"csrf-token\"]').getAttribute('content')"
    )
    assert expected_csrf, "csrf-token meta tag missing or empty — server-side bug"

    chromium.evaluate(
        "window.authedFetch('/api/_capture_csrf', "
        "{method: 'POST', body: JSON.stringify({})})"
    )

    deadline = time.time() + 4
    while time.time() < deadline and "headers" not in captured:
        time.sleep(0.05)
    assert "headers" in captured, "POST never fired — authedFetch broken"

    headers = captured["headers"]
    csrf = headers.get("x-csrftoken") or headers.get("X-CSRFToken")
    assert csrf == expected_csrf, (
        f"X-CSRFToken on POST mismatched. expected={expected_csrf!r}, "
        f"got={csrf!r}, all headers: {headers}"
    )


# ---------------------------------------------------------------------------
# A2 — No CSRF on GET (false-positive guard)
# ---------------------------------------------------------------------------

@pytest.mark.golden
def test_csrf_token_not_attached_to_get(live_app, chromium):
    """authedFetch must NOT attach `X-CSRFToken` on GET — adding it for
    safe methods would mask real bugs and pollute server logs."""
    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    captured = {}

    def _capture(route, request):
        captured["headers"] = dict(request.headers)
        route.fulfill(status=200, content_type="application/json", body="{}")

    chromium.route("**/api/_capture_get", _capture)
    chromium.evaluate("window.authedFetch('/api/_capture_get')")  # method defaults to GET

    deadline = time.time() + 4
    while time.time() < deadline and "headers" not in captured:
        time.sleep(0.05)
    assert "headers" in captured, "GET never fired"

    headers = captured["headers"]
    assert "x-csrftoken" not in {k.lower() for k in headers}, (
        f"X-CSRFToken should NOT appear on GET; headers: {headers}"
    )


# ---------------------------------------------------------------------------
# A3 — Bearer token attached when localStorage has one
# ---------------------------------------------------------------------------

@pytest.mark.golden
def test_bearer_token_attached_from_local_storage(live_app, chromium):
    """When `localStorage.api_token` is set, Authorization: Bearer <token>
    must be attached to outbound calls."""
    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    chromium.evaluate(
        f"localStorage.setItem('api_token', '{_TEST_BEARER}')"
    )

    captured = {}

    def _capture(route, request):
        captured["headers"] = dict(request.headers)
        route.fulfill(status=200, content_type="application/json", body="{}")

    chromium.route("**/api/_capture_bearer", _capture)
    chromium.evaluate("window.authedFetch('/api/_capture_bearer')")

    deadline = time.time() + 4
    while time.time() < deadline and "headers" not in captured:
        time.sleep(0.05)
    assert "headers" in captured, "request never fired"

    headers = captured["headers"]
    auth = headers.get("authorization") or headers.get("Authorization")
    assert auth == f"Bearer {_TEST_BEARER}", (
        f"Authorization header mismatch. expected='Bearer {_TEST_BEARER}', "
        f"got={auth!r}"
    )


# ---------------------------------------------------------------------------
# A4 — No Authorization header when localStorage is empty
# ---------------------------------------------------------------------------

@pytest.mark.golden
def test_no_authorization_when_local_storage_empty(live_app, chromium):
    """When no api_token is stored, authedFetch must omit Authorization
    entirely so the server's @require_api_token can return 401 — the
    explicit not-logged-in observable. Adding 'Bearer ' (no token) would
    mask the unauthenticated state."""
    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    chromium.evaluate("localStorage.removeItem('api_token')")

    captured = {}

    def _capture(route, request):
        captured["headers"] = dict(request.headers)
        route.fulfill(status=200, content_type="application/json", body="{}")

    chromium.route("**/api/_capture_no_auth", _capture)
    chromium.evaluate("window.authedFetch('/api/_capture_no_auth')")

    deadline = time.time() + 4
    while time.time() < deadline and "headers" not in captured:
        time.sleep(0.05)
    assert "headers" in captured, "request never fired"

    headers = captured["headers"]
    auth_keys = [k for k in headers if k.lower() == "authorization"]
    assert not auth_keys, (
        f"Authorization header present despite empty localStorage. "
        f"got: {[(k, headers[k]) for k in auth_keys]}"
    )


# ---------------------------------------------------------------------------
# A6 — jQuery $.ajax beforeSend parity with authedFetch
# ---------------------------------------------------------------------------

@pytest.mark.golden
def test_jquery_ajax_beforesend_attaches_csrf_and_bearer(live_app, chromium):
    """The H1 audit required jQuery $.ajax to wire the same headers as
    authedFetch (legacy callers still use $.ajax). main.js sets up
    `$.ajaxSetup({ beforeSend: SpatialAuth.authedAjaxBeforeSend })`."""
    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    chromium.evaluate(
        f"localStorage.setItem('api_token', '{_TEST_BEARER}')"
    )
    expected_csrf = chromium.evaluate(
        "document.querySelector('meta[name=\"csrf-token\"]').getAttribute('content')"
    )

    captured = {}

    def _capture(route, request):
        captured["headers"] = dict(request.headers)
        captured["method"] = request.method
        route.fulfill(status=200, content_type="application/json", body="{}")

    chromium.route("**/api/_capture_jquery", _capture)
    # Fire a $.ajax POST — beforeSend should add both headers.
    chromium.evaluate(
        "jQuery.ajax({url: '/api/_capture_jquery', type: 'POST', "
        "contentType: 'application/json', data: '{}'})"
    )

    deadline = time.time() + 4
    while time.time() < deadline and "headers" not in captured:
        time.sleep(0.05)
    assert "headers" in captured, "$.ajax POST never fired — beforeSend wiring broken"

    headers = captured["headers"]
    csrf = headers.get("x-csrftoken") or headers.get("X-CSRFToken")
    auth = headers.get("authorization") or headers.get("Authorization")
    assert csrf == expected_csrf, (
        f"$.ajax POST missing matching X-CSRFToken. expected={expected_csrf!r}, "
        f"got={csrf!r}"
    )
    assert auth == f"Bearer {_TEST_BEARER}", (
        f"$.ajax POST missing Authorization. expected='Bearer {_TEST_BEARER}', "
        f"got={auth!r}"
    )


# ---------------------------------------------------------------------------
# A2 corollary — caller-supplied Authorization is preserved
# ---------------------------------------------------------------------------

@pytest.mark.golden
def test_caller_supplied_authorization_is_not_overwritten(live_app, chromium):
    """Edge case: if the caller already passes an Authorization header,
    authedFetch must NOT overwrite it. This protects future code that
    needs to make authenticated calls on behalf of another user (e.g.,
    admin tooling) without monkey-patching localStorage."""
    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    # localStorage has a token, but the caller supplies an explicit override.
    chromium.evaluate(
        f"localStorage.setItem('api_token', 'sk-from-localstorage')"
    )
    explicit = "Bearer sk-explicit-override"

    captured = {}

    def _capture(route, request):
        captured["headers"] = dict(request.headers)
        route.fulfill(status=200, content_type="application/json", body="{}")

    chromium.route("**/api/_capture_explicit", _capture)
    chromium.evaluate(
        "window.authedFetch('/api/_capture_explicit', "
        "{method: 'GET', headers: {'Authorization': '" + explicit + "'}})"
    )

    deadline = time.time() + 4
    while time.time() < deadline and "headers" not in captured:
        time.sleep(0.05)
    assert "headers" in captured, "request never fired"

    headers = captured["headers"]
    auth = headers.get("authorization") or headers.get("Authorization")
    assert auth == explicit, (
        f"explicit Authorization was clobbered by localStorage value. "
        f"expected={explicit!r}, got={auth!r}"
    )
