"""Fixtures for the golden-path workflow suite.

Provides:
  - `golden_client`: Flask test client with CSRF off and clean state.
  - `scripted_llm`: factory that scripts a sequence of LLM responses
        the chat loop will receive, in order.
  - `mock_overpass`: factory that intercepts Overpass HTTP calls and
        returns canned OSM payloads.
  - `mock_nominatim`: factory that intercepts Nominatim geocode HTTP
        calls and returns canned location payloads.
"""
from __future__ import annotations

import os

# Provider keys cleared at process start by the parent conftest. Re-clear
# defensively in case this module is imported in isolation.
for _k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY",
           "GEMINI_API_KEY", "GOOGLE_API_KEY"):
    os.environ[_k] = ""
os.environ.setdefault("FLASK_DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "golden-workflow-secret")

from unittest.mock import MagicMock, patch

import pytest

from nl_gis.llm_provider import LLMResponse, TextBlock, ToolUseBlock


# ---------------------------------------------------------------------------
# Flask test client
# ---------------------------------------------------------------------------

@pytest.fixture
def golden_client():
    """Test client with CSRF disabled and per-test state isolation."""
    from app import app
    import state

    prior_csrf = app.config.get("WTF_CSRF_ENABLED")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with state.layer_lock:
        state.layer_store.clear()
        state.layer_owners.clear()
    state.chat_sessions.clear()

    try:
        with app.test_client() as client:
            yield client
    finally:
        with state.layer_lock:
            state.layer_store.clear()
            state.layer_owners.clear()
        state.chat_sessions.clear()
        if prior_csrf is not None:
            app.config["WTF_CSRF_ENABLED"] = prior_csrf


# ---------------------------------------------------------------------------
# Scripted LLM provider
# ---------------------------------------------------------------------------

class _ScriptedProvider:
    """LLM provider stub that returns scripted responses in FIFO order.

    When the script is exhausted, returns an `end_turn` text response so
    the chat loop terminates cleanly even if a test under-specifies.
    """

    def __init__(self, responses):
        self._queue = list(responses)
        self.calls = []

    def create_message(self, **kwargs):
        self.calls.append(kwargs)
        if self._queue:
            return self._queue.pop(0)
        return LLMResponse(
            content=[TextBlock(text="done")],
            stop_reason="end_turn",
        )


def _make_tool_use(name, params, tool_id=None):
    return ToolUseBlock(id=tool_id or f"toolu_{name}", name=name, input=params)


def _tool_response(name, params, tool_id=None):
    return LLMResponse(
        content=[_make_tool_use(name, params, tool_id)],
        stop_reason="tool_use",
        input_tokens=10,
        output_tokens=10,
    )


def _final_text(text="OK"):
    return LLMResponse(
        content=[TextBlock(text=text)],
        stop_reason="end_turn",
        input_tokens=5,
        output_tokens=5,
    )


@pytest.fixture
def scripted_llm():
    """Yield a factory that installs a scripted LLM for a test.

    Usage:
        provider = scripted_llm([
            tool_use("fetch_osm", {...}),
            final_text("Found 3 parks."),
        ])
        # ...exercise the chat endpoint...
        assert provider.calls  # was actually called
    """
    patches = []

    def _install(responses):
        provider = _ScriptedProvider(responses)
        # Patch the factory that ChatSession._init_client calls.
        p1 = patch("nl_gis.chat.create_provider", return_value=provider)
        # Force the API-key check to pass (conftest clears all keys).
        p2 = patch("nl_gis.chat.Config.get_llm_api_key",
                   return_value="test-only-key")
        p1.start()
        p2.start()
        patches.append(p1)
        patches.append(p2)
        return provider

    yield _install

    for p in patches:
        try:
            p.stop()
        except Exception:
            pass


# Re-export builders so test files can compose scripts succinctly.
@pytest.fixture
def tool_use():
    return _tool_response


@pytest.fixture
def final_text():
    return _final_text


# ---------------------------------------------------------------------------
# Overpass + Nominatim HTTP mocks
# ---------------------------------------------------------------------------

def _mock_response(payload, status=200):
    m = MagicMock()
    m.json.return_value = payload
    m.status_code = status
    m.raise_for_status = MagicMock()
    return m


@pytest.fixture
def mock_overpass():
    """Patch nl_gis.handlers.navigation.requests.get with a router that
    returns the right canned payload for Overpass / Nominatim based on URL.

    Caller passes a dict:
        {
            "overpass": <osm-payload-dict-or-Exception>,
            "nominatim": <list-of-results>,
        }
    Either key is optional. If a request hits an unmocked URL, the test
    fails loudly so silent live calls cannot happen.
    """
    p = patch("nl_gis.handlers.navigation.requests.get")
    mock_get = p.start()

    def _install(payloads):
        overpass_payload = payloads.get("overpass")
        nominatim_payload = payloads.get("nominatim")

        def _router(url, *args, **kwargs):
            if "overpass-api.de" in url:
                if overpass_payload is None:
                    raise AssertionError(
                        "Test invoked Overpass but did not configure a payload"
                    )
                if isinstance(overpass_payload, Exception):
                    raise overpass_payload
                return _mock_response(overpass_payload)
            if "nominatim.openstreetmap.org" in url:
                if nominatim_payload is None:
                    raise AssertionError(
                        "Test invoked Nominatim but did not configure a payload"
                    )
                if isinstance(nominatim_payload, Exception):
                    raise nominatim_payload
                return _mock_response(nominatim_payload)
            raise AssertionError(
                f"Unmocked outbound HTTP in golden test: {url}"
            )

        mock_get.side_effect = _router
        return mock_get

    yield _install

    p.stop()


# ---------------------------------------------------------------------------
# SSE parsing helper
# ---------------------------------------------------------------------------

def parse_sse(body: str):
    """Parse an SSE response body into a list of (event_type, data_obj).

    Skips empty frames. `data` is JSON-decoded when valid; otherwise the
    raw string is returned (handy when a test wants to assert on raw text).
    """
    import json

    events = []
    for frame in body.split("\n\n"):
        if not frame.strip():
            continue
        event_type = None
        data_str = None
        for line in frame.splitlines():
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_str = line[len("data:"):].strip()
        if event_type is None and data_str is None:
            continue
        try:
            data_obj = json.loads(data_str) if data_str else {}
        except (ValueError, TypeError):
            data_obj = data_str
        events.append((event_type or "message", data_obj))
    return events


@pytest.fixture
def sse_parser():
    return parse_sse


# ---------------------------------------------------------------------------
# Subprocess Flask + chromium for browser-render tests
#
# These fixtures spawn a real Flask process and a headless Chromium so we
# can assert Leaflet actually paints what the SSE stream describes.
# Mocked-mode browser tests use Playwright's `page.route()` to intercept
# the /api/chat fetch call; no live LLM/Overpass calls are required.
# ---------------------------------------------------------------------------

import socket
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


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
    """Boot a flask process for the test module and tear down after.
    Module-scoped so multiple browser tests share one server boot.
    """
    port = _free_port()
    env = os.environ.copy()
    env.update({
        "FLASK_APP": "app.py",
        "FLASK_DEBUG": "false",
        "SECRET_KEY": "golden-render-test-secret",
        "PORT": str(port),
        # Force the rule-based fallback so the live Gemini/Overpass paths
        # are unreachable even if a key leaks into the test env.
        "LLM_PROVIDER": "gemini",
        "GEMINI_API_KEY": "",
    })
    proc = subprocess.Popen(
        [sys.executable, "-m", "flask", "run",
         "--port", str(port), "--host", "127.0.0.1"],
        cwd=_PROJECT_ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    if not _wait_for_health(f"{base}/api/health", timeout_s=20):
        proc.terminate()
        proc.wait(timeout=5)
        pytest.fail("Flask app failed to start within 20s for browser test")
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def chromium():
    """Headless Chromium page. Skips the test if Playwright/chromium are
    not installed rather than failing — keeps `make eval` green on a
    machine that doesn't have the browser yet."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"chromium not available: {exc}")
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            yield page
        finally:
            browser.close()
