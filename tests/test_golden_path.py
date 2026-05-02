"""Golden-path test: the user's real experience.

This test is the bar I should have set on day one. It does NOT verify
each handler in isolation; it verifies that the user can:

  1. Open the app
  2. Type a natural-language query
  3. See features render on the map

Two modes:

- **default (mocked)**: Gemini and Overpass are stubbed so the test runs
  fast and offline; this catches frontend regressions, SSE wiring,
  CSP breakage, tab/panel visibility, LayerManager wiring.

- **live**: set `SPATIALAPP_GOLDEN_LIVE=1` to run against real Gemini +
  real Overpass. Use locally; do not run in CI without an API key
  budget. Catches regressions in the LLM provider config, tool schemas,
  Overpass User-Agent, etc.

Why this test matters: the unit suite has 1,400+ tests but missed both
(a) Gemini's thinking-budget swallowing the entire output budget under
the v2.1 system prompt, and (b) Overpass returning 406 to the default
`python-requests` User-Agent. Only an end-to-end browser test catches
those.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Skip if Playwright + chromium aren't available
playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_health(url: str, timeout_s: float = 15.0) -> bool:
    import urllib.request
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


@pytest.fixture(scope="module")
def live_app():
    """Boot a flask process and tear down after the test."""
    port = _free_port()
    env = os.environ.copy()
    env.update({
        "FLASK_APP": "app.py",
        "FLASK_DEBUG": "false",
        "SECRET_KEY": "golden-path-test-secret",
        "PORT": str(port),
        # Default to a no-op LLM key; live mode overrides via env.
        "LLM_PROVIDER": env.get("LLM_PROVIDER", "gemini"),
        "GEMINI_API_KEY": env.get("GEMINI_API_KEY", "test-only"),
    })
    cmd = [
        sys.executable, "-m", "flask", "run",
        "--port", str(port), "--host", "127.0.0.1",
    ]
    proc = subprocess.Popen(
        cmd, cwd=PROJECT_ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    if not _wait_for_health(f"{base}/api/health", timeout_s=20):
        proc.terminate()
        proc.wait(timeout=5)
        pytest.fail("App failed to start within 20s")
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def chromium():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium not available: {exc}")
        ctx = browser.new_context()
        page = ctx.new_page()
        yield page
        browser.close()


def _is_live() -> bool:
    return os.environ.get("SPATIALAPP_GOLDEN_LIVE") == "1"


@pytest.mark.golden
def test_user_can_load_app_without_errors(live_app, chromium):
    """The page loads, every JS global is set, no CSP violation, no failed request."""
    errors, failed = [], []
    chromium.on("pageerror", lambda e: errors.append(str(e)))
    chromium.on("requestfailed", lambda r: failed.append((r.url, r.failure)))

    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    # JS globals the app needs
    assert chromium.evaluate("typeof L !== 'undefined'"), "Leaflet not loaded"
    assert chromium.evaluate("typeof jQuery !== 'undefined'"), "jQuery not loaded"
    assert chromium.evaluate(
        "typeof window.LayerManager !== 'undefined' && "
        "typeof window.LayerManager.getLayerNames === 'function'"
    ), "LayerManager not initialized"
    assert chromium.evaluate("typeof window.map !== 'undefined'"), "map global missing"

    # Map tiles actually rendered
    tiles = chromium.evaluate("document.querySelectorAll('.leaflet-tile').length")
    assert tiles > 0, "No Leaflet tiles rendered (map is blank)"

    # No JS errors, no failed network requests, no CSP violations
    assert errors == [], f"Page errors: {errors}"
    assert failed == [], f"Failed requests: {failed}"


@pytest.mark.golden
def test_chat_tab_opens_and_input_is_visible(live_app, chromium):
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)
    chromium.locator('button.tab-btn[data-tab="chat"]').click()
    chat = chromium.locator("#chatInput")
    chat.wait_for(state="visible", timeout=5000)
    chromium.locator("#chatSendBtn").wait_for(state="visible", timeout=5000)


@pytest.mark.golden
@pytest.mark.skipif(
    not _is_live(),
    reason="Set SPATIALAPP_GOLDEN_LIVE=1 with a real GEMINI_API_KEY to run.",
)
def test_buildings_query_renders_polygons_live(live_app, chromium):
    """The whole user journey, with the real LLM and the real Overpass.

    Catches Gemini thinking-budget regressions, Overpass UA rejections,
    tool schema drift, SSE+layer wiring, CSP-on-Leaflet-images.
    """
    errors, failed = [], []
    chromium.on("pageerror", lambda e: errors.append(str(e)))
    chromium.on("requestfailed", lambda r: failed.append((r.url, r.failure)))

    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)
    chromium.locator('button.tab-btn[data-tab="chat"]').click()
    chat = chromium.locator("#chatInput")
    chat.wait_for(state="visible", timeout=5000)
    chat.fill("show me buildings in The Loop, Chicago")
    chromium.locator("#chatSendBtn").click()

    # Poll up to 90s for a layer + rendered polygons
    deadline = time.time() + 90
    layer_names: list[str] = []
    rendered = 0
    while time.time() < deadline:
        names = chromium.evaluate("window.LayerManager.getLayerNames()")
        if names:
            layer_names = names
            rendered = chromium.evaluate(
                "document.querySelectorAll('.leaflet-overlay-pane path').length"
            )
            if rendered > 0:
                break
        time.sleep(0.5)

    assert layer_names, f"No layer in LayerManager. Errors: {errors}; failed: {failed}"
    assert rendered > 0, (
        f"Layer added but no polygons painted. "
        f"layers={layer_names}, errors={errors}, failed={failed}"
    )
