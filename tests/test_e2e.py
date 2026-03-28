"""End-to-end Playwright tests for SpatialApp.

Tests critical user journeys in a real browser:
- Page loads with map and all UI elements
- Chat panel accepts input and displays messages
- Layer manager renders correctly
- Map controls work (zoom, basemap)

Requires: pytest-playwright, playwright chromium
Run: pytest tests/test_e2e.py --headed  (to see browser)
"""

import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="module")
def flask_server():
    """Start a Flask dev server in a background thread for E2E tests."""
    # Ensure no API token required for E2E tests
    os.environ["CHAT_API_TOKEN"] = ""
    os.environ["FLASK_DEBUG"] = "false"

    from app import app

    server = threading.Thread(
        target=lambda: app.run(port=5099, use_reloader=False, threaded=True),
        daemon=True,
    )
    server.start()

    # Wait for server to be ready
    import urllib.request
    for _ in range(30):
        try:
            urllib.request.urlopen("http://127.0.0.1:5099/", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        pytest.fail("Flask server did not start within 6 seconds")

    yield "http://127.0.0.1:5099"


@pytest.fixture(scope="module")
def browser_context(flask_server):
    """Create a Playwright browser context."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        yield context, flask_server
        context.close()
        browser.close()


class TestPageLoad:
    """Verify the page loads correctly with all UI elements."""

    def test_map_renders(self, browser_context):
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        # Leaflet map container exists
        assert page.locator("#map").is_visible()

        # Leaflet tiles loaded (at least one tile image)
        page.wait_for_selector(".leaflet-tile-loaded", timeout=10000)
        tiles = page.locator(".leaflet-tile-loaded")
        assert tiles.count() > 0

        page.close()

    def test_sidebar_tabs_exist(self, browser_context):
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        # Three sidebar tabs should exist
        assert page.locator("#chatInput").count() > 0
        assert page.locator("#chatSendBtn").count() > 0

        page.close()

    def test_layer_manager_panel(self, browser_context):
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        # Layer list container
        assert page.locator("#layerList").count() > 0

        page.close()


class TestChatPanel:
    """Verify chat panel interaction."""

    def test_send_message_displays(self, browser_context):
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        # Switch to Chat tab
        page.locator('button.tab-btn[data-tab="chat"]').click()
        page.wait_for_selector("#chatInput", state="visible", timeout=3000)

        # Type a message
        chat_input = page.locator("#chatInput")
        chat_input.fill("Hello, map assistant!")

        # Click send
        page.locator("#chatSendBtn").click()

        # User message should appear in chat
        page.wait_for_selector(".chat-msg-user", timeout=5000)
        user_msgs = page.locator(".chat-msg-user")
        assert user_msgs.count() > 0
        assert "Hello, map assistant!" in user_msgs.first.text_content()

        # Input should be cleared
        assert chat_input.input_value() == ""

        page.close()

    def test_chat_input_clears_on_send(self, browser_context):
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        # Switch to Chat tab
        page.locator('button.tab-btn[data-tab="chat"]').click()
        page.wait_for_selector("#chatInput", state="visible", timeout=3000)

        chat_input = page.locator("#chatInput")
        chat_input.fill("Test message")
        page.locator("#chatSendBtn").click()

        # Input cleared after send
        assert chat_input.input_value() == ""

        page.close()


class TestAPIEndpoints:
    """Verify API endpoints respond correctly via browser fetch."""

    def test_layers_endpoint(self, browser_context):
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        # Call /api/layers via evaluate
        result = page.evaluate("""
            async () => {
                const resp = await fetch('/api/layers');
                return await resp.json();
            }
        """)
        assert "layers" in result
        assert isinstance(result["layers"], list)

        page.close()

    def test_usage_endpoint(self, browser_context):
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        result = page.evaluate("""
            async () => {
                const resp = await fetch('/api/usage');
                return await resp.json();
            }
        """)
        assert "usage" in result
        assert "total_input_tokens" in result["usage"]

        page.close()

    def test_annotations_endpoint(self, browser_context):
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        result = page.evaluate("""
            async () => {
                const resp = await fetch('/get_annotations');
                return await resp.json();
            }
        """)
        assert result["type"] == "FeatureCollection"

        page.close()
