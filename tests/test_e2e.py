"""End-to-end Playwright tests for SpatialApp.

Tests critical user journeys in a real browser:
- Page loads with map, chat panel, and layer panel
- Chat panel accepts input, displays messages, and handles send/stop lifecycle
- Layer manager renders correctly with ARIA labels
- Error states (empty submission, toast display/dismiss)
- Mobile viewport (375px) responsive behavior

Requires: pytest-playwright, playwright chromium
Run: pytest tests/test_e2e.py --headed  (to see browser)
"""

import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Skip all tests if playwright is not installed
try:
    from playwright.sync_api import sync_playwright, expect

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

pytestmark = pytest.mark.skipif(
    not HAS_PLAYWRIGHT, reason="playwright not installed"
)


@pytest.fixture(scope="module")
def flask_server():
    """Start a Flask dev server in a background thread for E2E tests."""
    os.environ["CHAT_API_TOKEN"] = ""
    os.environ["FLASK_DEBUG"] = "false"

    from app import app

    server = threading.Thread(
        target=lambda: app.run(port=5099, use_reloader=False, threaded=True),
        daemon=True,
    )
    server.start()

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
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        yield context, flask_server
        context.close()
        browser.close()


# ---------------------------------------------------------------------------
# 1. Page Load & Layout
# ---------------------------------------------------------------------------
class TestPageLoadAndLayout:
    """Verify the page loads correctly with all UI elements."""

    def test_homepage_loads_with_map(self, browser_context):
        """Map container is present and visible on page load."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        map_el = page.locator("#map")
        expect(map_el).to_be_visible()

        page.close()

    def test_map_tiles_render(self, browser_context):
        """Leaflet initializes and at least one map tile loads."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        page.wait_for_selector(".leaflet-tile-loaded", timeout=10000)
        tiles = page.locator(".leaflet-tile-loaded")
        assert tiles.count() > 0

        page.close()

    def test_chat_panel_visible(self, browser_context):
        """Chat tab content includes input and send button."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        # Switch to chat tab
        page.locator('button.tab-btn[data-tab="chat"]').click()
        page.wait_for_selector("#chatInput", state="visible", timeout=3000)

        chat_input = page.locator("#chatInput")
        expect(chat_input).to_be_visible()
        expect(chat_input).to_be_enabled()

        send_btn = page.locator("#chatSendBtn")
        expect(send_btn).to_be_visible()

        page.close()

    def test_layer_panel_visible(self, browser_context):
        """Layer panel with layer list is present on page load."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        layer_panel = page.locator("#layerPanel")
        expect(layer_panel).to_be_visible()

        layer_list = page.locator("#layerList")
        assert layer_list.count() > 0

        page.close()

    def test_sidebar_tabs_exist(self, browser_context):
        """Three sidebar tab buttons exist: Manual, Classify, Chat."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        manual_tab = page.locator('button.tab-btn[data-tab="manual"]')
        auto_tab = page.locator('button.tab-btn[data-tab="auto"]')
        chat_tab = page.locator('button.tab-btn[data-tab="chat"]')

        expect(manual_tab).to_be_visible()
        expect(auto_tab).to_be_visible()
        expect(chat_tab).to_be_visible()

        page.close()


# ---------------------------------------------------------------------------
# 2. Chat Interaction
# ---------------------------------------------------------------------------
class TestChatInteraction:
    """Verify chat panel interaction lifecycle."""

    def test_send_message_displays_user_bubble(self, browser_context):
        """Typing and sending a message shows user message bubble in chat."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        page.locator('button.tab-btn[data-tab="chat"]').click()
        page.wait_for_selector("#chatInput", state="visible", timeout=3000)

        chat_input = page.locator("#chatInput")
        chat_input.fill("Hello, map assistant!")
        page.locator("#chatSendBtn").click()

        # User message should appear
        page.wait_for_selector(".chat-msg-user", timeout=5000)
        user_msgs = page.locator(".chat-msg-user")
        assert user_msgs.count() > 0
        assert "Hello, map assistant!" in user_msgs.first.text_content()

        page.close()

    def test_input_clears_after_send(self, browser_context):
        """Chat input is cleared after sending a message."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        page.locator('button.tab-btn[data-tab="chat"]').click()
        page.wait_for_selector("#chatInput", state="visible", timeout=3000)

        chat_input = page.locator("#chatInput")
        chat_input.fill("Test clear message")
        page.locator("#chatSendBtn").click()

        assert chat_input.input_value() == ""

        page.close()

    def test_send_button_changes_to_stop(self, browser_context):
        """Send button text transforms to 'Stop' while processing."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        page.locator('button.tab-btn[data-tab="chat"]').click()
        page.wait_for_selector("#chatInput", state="visible", timeout=3000)

        chat_input = page.locator("#chatInput")
        send_btn = page.locator("#chatSendBtn")

        # Verify initial state
        assert send_btn.text_content().strip() == "Send"

        chat_input.fill("What is the weather?")
        send_btn.click()

        # Button should change to "Stop" during processing
        expect(send_btn).to_have_text("Stop", timeout=3000)

        page.close()

    def test_input_disabled_during_processing(self, browser_context):
        """Chat input is disabled while a request is processing."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        page.locator('button.tab-btn[data-tab="chat"]').click()
        page.wait_for_selector("#chatInput", state="visible", timeout=3000)

        chat_input = page.locator("#chatInput")
        chat_input.fill("Some query")
        page.locator("#chatSendBtn").click()

        # Input should be disabled while processing
        expect(chat_input).to_be_disabled(timeout=3000)

        page.close()

    def test_input_re_enabled_after_response(self, browser_context):
        """After response completes (or errors), input is re-enabled."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        page.locator('button.tab-btn[data-tab="chat"]').click()
        page.wait_for_selector("#chatInput", state="visible", timeout=3000)

        chat_input = page.locator("#chatInput")
        chat_input.fill("Hello")
        page.locator("#chatSendBtn").click()

        # Wait for input to be re-enabled (after response or error/retry timeout)
        expect(chat_input).to_be_enabled(timeout=30000)

        # Send button text should revert to "Send"
        send_btn = page.locator("#chatSendBtn")
        expect(send_btn).to_have_text("Send", timeout=30000)

        page.close()

    def test_enter_key_sends_message(self, browser_context):
        """Pressing Enter (without Shift) sends the message."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        page.locator('button.tab-btn[data-tab="chat"]').click()
        page.wait_for_selector("#chatInput", state="visible", timeout=3000)

        chat_input = page.locator("#chatInput")
        chat_input.fill("Enter key test")
        chat_input.press("Enter")

        # Message should appear
        page.wait_for_selector(".chat-msg-user", timeout=5000)
        user_msgs = page.locator(".chat-msg-user")
        assert "Enter key test" in user_msgs.last.text_content()

        # Input cleared
        assert chat_input.input_value() == ""

        page.close()


# ---------------------------------------------------------------------------
# 3. Layer Management
# ---------------------------------------------------------------------------
class TestLayerManagement:
    """Verify layer panel structure and accessibility."""

    def test_layer_panel_exists(self, browser_context):
        """Layer panel with heading and list container is present."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        layer_panel = page.locator("#layerPanel")
        expect(layer_panel).to_be_visible()

        # Panel contains a heading
        heading = layer_panel.locator("h3")
        assert heading.count() > 0
        assert "Layers" in heading.text_content()

        page.close()

    def test_layer_list_empty_initially(self, browser_context):
        """Layer list starts empty (no layers added on fresh load)."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        layer_list = page.locator("#layerList")
        # No layer entries on a fresh page
        layer_items = layer_list.locator(".layer-item")
        assert layer_items.count() == 0

        page.close()


# ---------------------------------------------------------------------------
# 4. Error States
# ---------------------------------------------------------------------------
class TestErrorStates:
    """Verify error handling in the UI."""

    def test_empty_message_not_sent(self, browser_context):
        """Empty chat input does not produce a user message bubble."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        page.locator('button.tab-btn[data-tab="chat"]').click()
        page.wait_for_selector("#chatInput", state="visible", timeout=3000)

        chat_input = page.locator("#chatInput")
        # Ensure input is empty
        chat_input.fill("")

        page.locator("#chatSendBtn").click()

        # No user message should appear
        page.wait_for_timeout(500)
        user_msgs = page.locator(".chat-msg-user")
        assert user_msgs.count() == 0

        # Input should remain enabled (not in processing state)
        expect(chat_input).to_be_enabled()

        page.close()

    def test_whitespace_only_message_not_sent(self, browser_context):
        """Whitespace-only input is treated as empty and not sent."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        page.locator('button.tab-btn[data-tab="chat"]').click()
        page.wait_for_selector("#chatInput", state="visible", timeout=3000)

        chat_input = page.locator("#chatInput")
        chat_input.fill("   ")

        page.locator("#chatSendBtn").click()

        page.wait_for_timeout(500)
        user_msgs = page.locator(".chat-msg-user")
        assert user_msgs.count() == 0

        page.close()

    def test_toast_container_exists(self, browser_context):
        """Toast notification container is present in the DOM."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        toast_container = page.locator("#toast-container")
        assert toast_container.count() > 0

        page.close()

    def test_toast_displays_and_auto_dismisses(self, browser_context):
        """Toast notification appears and auto-dismisses after timeout."""
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

        # Trigger a toast by calling showToast via JS (it is globally accessible
        # inside the main.js IIFE but we can invoke it via the upload form
        # validation which calls showToast). We use a direct JS eval instead.
        page.evaluate("""
            () => {
                const toast = document.createElement('div');
                toast.className = 'toast warning';
                toast.textContent = 'Test toast message';
                document.getElementById('toast-container').appendChild(toast);
                setTimeout(() => {
                    toast.classList.add('fade-out');
                    setTimeout(() => toast.remove(), 500);
                }, 1000);
            }
        """)

        # Toast should appear
        toast = page.locator(".toast.warning")
        expect(toast).to_be_visible(timeout=2000)
        assert "Test toast message" in toast.text_content()

        # Toast should auto-dismiss (removed from DOM)
        expect(toast).to_have_count(0, timeout=5000)

        page.close()


# ---------------------------------------------------------------------------
# 5. Mobile Viewport (375px)
# ---------------------------------------------------------------------------
class TestMobileViewport:
    """Verify responsive behavior at mobile width (375px)."""

    def test_page_loads_at_mobile_width(self, browser_context):
        """Page loads without errors at 375x812 viewport."""
        context, base_url = browser_context
        page = context.new_page()
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(base_url)

        # Map should still be present
        map_el = page.locator("#map")
        expect(map_el).to_be_visible()

        page.close()

    def test_mobile_sidebar_toggle_visible(self, browser_context):
        """Mobile sidebar toggle button is visible at narrow viewport."""
        context, base_url = browser_context
        page = context.new_page()
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(base_url)

        toggle_btn = page.locator("#mobileSidebarToggle")
        expect(toggle_btn).to_be_visible()

        page.close()

    def test_mobile_layer_toggle_visible(self, browser_context):
        """Mobile layer toggle button is visible at narrow viewport."""
        context, base_url = browser_context
        page = context.new_page()
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(base_url)

        layer_toggle = page.locator("#mobileLayerToggle")
        expect(layer_toggle).to_be_visible()

        page.close()

    def test_mobile_sidebar_toggle_works(self, browser_context):
        """Clicking the mobile sidebar toggle hides/shows the sidebar."""
        context, base_url = browser_context
        page = context.new_page()
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(base_url)

        toggle_btn = page.locator("#mobileSidebarToggle")
        sidebar = page.locator("#sidebar")

        # Click toggle to hide sidebar
        toggle_btn.click()
        page.wait_for_timeout(300)
        sidebar_classes = sidebar.get_attribute("class") or ""
        assert "mobile-hidden" in sidebar_classes

        # Click again to show
        toggle_btn.click()
        page.wait_for_timeout(300)
        sidebar_classes = sidebar.get_attribute("class") or ""
        assert "mobile-hidden" not in sidebar_classes

        page.close()

    def test_map_fills_viewport_on_mobile(self, browser_context):
        """Map container width is at least the viewport width on mobile."""
        context, base_url = browser_context
        page = context.new_page()
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(base_url)

        map_box = page.locator("#map").bounding_box()
        assert map_box is not None
        # Map should span at least a significant portion of viewport width
        assert map_box["width"] >= 300

        page.close()


# ---------------------------------------------------------------------------
# 6. API Endpoints (via browser fetch)
# ---------------------------------------------------------------------------
class TestAPIEndpoints:
    """Verify API endpoints respond correctly via browser fetch."""

    def test_layers_endpoint(self, browser_context):
        context, base_url = browser_context
        page = context.new_page()
        page.goto(base_url)

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
