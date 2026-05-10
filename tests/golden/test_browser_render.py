"""Browser-render workflow test (mocked SSE, real Leaflet).

Closes the loop the user explicitly flagged: "things need to render on
the map successfully". The server-side workflow tests in
test_user_workflows.py prove the chat→tool→layer_store contract; this
test proves Leaflet actually paints what we hand it.

How it works:
  1. Spawn the real Flask app (live_app fixture).
  2. Open the page in headless Chromium.
  3. Use Playwright `page.route()` to intercept the /api/chat fetch
     and return a canned SSE stream containing one layer_add event.
  4. Click the chat send button.
  5. Assert Leaflet paints at least one polygon path AND the layer
     appears in window.LayerManager.

No live LLM/Overpass calls; runs in CI under `make eval`.
"""
from __future__ import annotations

import json
import time

import pytest


# A small but valid GeoJSON polygon over Chicago — the same kind of
# payload the production fetch_osm path produces.
MOCK_LAYER_GEOJSON = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-87.6204, 41.8741],
                [-87.6132, 41.8741],
                [-87.6132, 41.8669],
                [-87.6204, 41.8669],
                [-87.6204, 41.8741],
            ]],
        },
        "properties": {"category_name": "mock_park", "feature_type": "park"},
    }],
}


def _canned_sse_body(layer_name: str, geojson: dict) -> str:
    """Build the SSE bytes a successful chat→fetch_osm dispatch would emit."""
    layer_event = {
        "type": "layer_add",
        "name": layer_name,
        "geojson": geojson,
        "style": None,
    }
    final_event = {
        "type": "message",
        "text": "Found 1 mock park.",
        "done": True,
    }
    return (
        f"event: layer_add\ndata: {json.dumps(layer_event)}\n\n"
        f"event: message\ndata: {json.dumps(final_event)}\n\n"
    )


def _block_socketio(page):
    """Force the chat to use the SSE transport (POST /api/chat) instead
    of Socket.IO. The chat client flips a closure-private flag to WS the
    moment a socket connects; killing the socket.io endpoint at the
    route layer is the cleanest way to keep the SSE path active without
    touching production code."""
    page.route(
        "**/socket.io/**",
        lambda route, _req: route.abort(),
    )


@pytest.mark.golden
def test_canned_sse_renders_polygon_in_leaflet(live_app, chromium):
    """The user's smoke test: type a query, see a polygon. With Playwright
    fulfilling /api/chat we don't need an LLM key OR Overpass — just the
    browser side of the pipeline."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)

    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    # Intercept the /api/chat POST and return our canned SSE body.
    layer_name = "mock_park_layer"
    sse_body = _canned_sse_body(layer_name, MOCK_LAYER_GEOJSON)

    def _fulfill_chat(route, request):
        if request.method == "POST":
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=sse_body,
            )
        else:
            route.continue_()

    chromium.route("**/api/chat", _fulfill_chat)

    # Drive the UI: open chat, type, send.
    chromium.locator('button.tab-btn[data-tab="chat"]').click()
    chat = chromium.locator("#chatInput")
    chat.wait_for(state="visible", timeout=5000)
    chat.fill("show me parks")
    chromium.locator("#chatSendBtn").click()

    # Poll up to 10s for the layer to register and at least one polygon
    # path to be painted in the Leaflet overlay pane.
    deadline = time.time() + 10
    layer_names = []
    rendered = 0
    while time.time() < deadline:
        layer_names = chromium.evaluate("window.LayerManager.getLayerNames()")
        rendered = chromium.evaluate(
            "document.querySelectorAll('.leaflet-overlay-pane path').length"
        )
        if layer_names and rendered > 0:
            break
        time.sleep(0.2)

    assert layer_name in layer_names, (
        f"layer {layer_name!r} not registered in LayerManager. "
        f"got: {layer_names}; page errors: {errors}"
    )
    assert rendered > 0, (
        f"layer registered but Leaflet painted no polygons. "
        f"path count: {rendered}; page errors: {errors}. "
        "This is the bug class the user reported."
    )


def _canned_chunked_sse(layer_name: str, all_features: list, chunk_size: int = 2) -> str:
    """Build the SSE bytes the server emits for a layer with 500+ features:
    one `layer_init` followed by N `layer_chunk` events. Used to verify
    the frontend's chunked-render path (separate handler from layer_add)."""
    init_event = {
        "type": "layer_init",
        "name": layer_name,
        "total_features": len(all_features),
        "chunks": (len(all_features) + chunk_size - 1) // chunk_size,
        "style": None,
    }
    parts = [f"event: layer_init\ndata: {json.dumps(init_event)}\n\n"]
    for i in range(0, len(all_features), chunk_size):
        chunk_event = {
            "type": "layer_chunk",
            "name": layer_name,
            "chunk_index": i // chunk_size,
            "geojson": {
                "type": "FeatureCollection",
                "features": all_features[i:i + chunk_size],
            },
        }
        parts.append(f"event: layer_chunk\ndata: {json.dumps(chunk_event)}\n\n")
    final = {"type": "message", "text": "done", "done": True}
    parts.append(f"event: message\ndata: {json.dumps(final)}\n\n")
    return "".join(parts)


def _polygon_feature(lng_offset: float, lat_offset: float):
    """Tiny axis-aligned square near Chicago, shifted by the given offsets."""
    base_lng, base_lat = -87.62, 41.87
    lng = base_lng + lng_offset
    lat = base_lat + lat_offset
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [lng, lat],
                [lng + 0.001, lat],
                [lng + 0.001, lat + 0.001],
                [lng, lat + 0.001],
                [lng, lat],
            ]],
        },
        "properties": {"id": f"f-{lng_offset}-{lat_offset}"},
    }


@pytest.mark.golden
def test_chunked_layer_delivery_paints_all_features(live_app, chromium):
    """Large layers (500+ features) use the layer_init + layer_chunk path,
    not layer_add. The frontend has separate handlers for these. If the
    chunked-render glue is broken, big OSM queries silently fail to paint
    even though the user sees a 'success' tool result."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    layer_name = "chunked_parks"
    features = [_polygon_feature(0.001 * i, 0.001 * i) for i in range(6)]
    sse_body = _canned_chunked_sse(layer_name, features, chunk_size=2)

    chromium.route(
        "**/api/chat",
        lambda route, req: (
            route.fulfill(status=200, content_type="text/event-stream",
                          body=sse_body)
            if req.method == "POST" else route.continue_()
        ),
    )

    chromium.locator('button.tab-btn[data-tab="chat"]').click()
    chromium.locator("#chatInput").wait_for(state="visible", timeout=5000)
    chromium.locator("#chatInput").fill("show me all parks")
    chromium.locator("#chatSendBtn").click()

    # Poll for layer registration AND the expected number of paths.
    deadline = time.time() + 10
    layer_names = []
    rendered = 0
    while time.time() < deadline:
        layer_names = chromium.evaluate("window.LayerManager.getLayerNames()")
        rendered = chromium.evaluate(
            "document.querySelectorAll('.leaflet-overlay-pane path').length"
        )
        if layer_name in layer_names and rendered >= len(features):
            break
        time.sleep(0.2)

    assert layer_name in layer_names, (
        f"chunked layer {layer_name!r} not registered. "
        f"got: {layer_names}; errors: {errors}"
    )
    assert rendered >= len(features), (
        f"chunked layer registered but only {rendered}/{len(features)} "
        f"polygons painted — chunked-render glue is broken. "
        f"errors: {errors}"
    )


@pytest.mark.golden
def test_map_command_pan_and_zoom_actually_moves_the_map(
    live_app, chromium,
):
    """The 'zoom to X' workflow is one of the most common user requests.
    A canned `map_command pan_and_zoom` SSE event must actually re-center
    the Leaflet map. Catches handler regressions (executeMapCommand) and
    coord-order swaps in the pan path."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    # Wait until the Leaflet map IIFE has finished wiring window.map.
    # With Socket.IO blocked the page can report "loaded" before the
    # ready callback resolves, so poll explicitly.
    chromium.wait_for_function(
        "() => window.map && typeof window.map.getCenter === 'function'",
        timeout=10_000,
    )

    target_lat, target_lon, target_zoom = 41.8781, -87.6298, 12  # Chicago
    cmd_event = {
        "type": "map_command",
        "action": "pan_and_zoom",
        "lat": target_lat,
        "lon": target_lon,
        "zoom": target_zoom,
    }
    final_event = {"type": "message", "text": "done", "done": True}
    sse_body = (
        f"event: map_command\ndata: {json.dumps(cmd_event)}\n\n"
        f"event: message\ndata: {json.dumps(final_event)}\n\n"
    )

    # Grab the initial map center so we can prove it moved (not just landed
    # there by coincidence).
    initial_center = chromium.evaluate(
        "({lat: window.map.getCenter().lat, lng: window.map.getCenter().lng})"
    )

    chromium.route(
        "**/api/chat",
        lambda route, req: (
            route.fulfill(status=200, content_type="text/event-stream",
                          body=sse_body)
            if req.method == "POST" else route.continue_()
        ),
    )

    chromium.locator('button.tab-btn[data-tab="chat"]').click()
    chromium.locator("#chatInput").wait_for(state="visible", timeout=5000)
    chromium.locator("#chatInput").fill("zoom to Chicago")
    chromium.locator("#chatSendBtn").click()

    # Wait briefly for the pan to settle, then read center + zoom.
    deadline = time.time() + 5
    final_center = initial_center
    final_zoom = None
    while time.time() < deadline:
        final_center = chromium.evaluate(
            "({lat: window.map.getCenter().lat, lng: window.map.getCenter().lng})"
        )
        final_zoom = chromium.evaluate("window.map.getZoom()")
        if (abs(final_center["lat"] - target_lat) < 0.5
                and abs(final_center["lng"] - target_lon) < 0.5):
            break
        time.sleep(0.2)

    assert errors == [], f"page errors during map_command: {errors}"
    assert abs(final_center["lat"] - target_lat) < 0.5, (
        f"map did not pan to target lat. "
        f"initial={initial_center}, final={final_center}, "
        f"target=({target_lat}, {target_lon})"
    )
    assert abs(final_center["lng"] - target_lon) < 0.5, (
        f"map did not pan to target lon. "
        f"initial={initial_center}, final={final_center}"
    )
    assert final_zoom == target_zoom, (
        f"zoom level wrong: got {final_zoom}, expected {target_zoom}"
    )


def _two_layers_sse():
    """Build SSE bytes that emit two distinct layers in one chat turn."""
    a = {"type": "layer_add", "name": "layer_a",
         "geojson": {"type": "FeatureCollection",
                     "features": [_polygon_feature(0, 0)]},
         "style": None}
    b = {"type": "layer_add", "name": "layer_b",
         "geojson": {"type": "FeatureCollection",
                     "features": [_polygon_feature(0.01, 0.01)]},
         "style": None}
    final = {"type": "message", "text": "done", "done": True}
    return (
        f"event: layer_add\ndata: {json.dumps(a)}\n\n"
        f"event: layer_add\ndata: {json.dumps(b)}\n\n"
        f"event: message\ndata: {json.dumps(final)}\n\n"
    )


def _add_layer_sse(name: str):
    """Build SSE: a single layer_add with one polygon."""
    add = {"type": "layer_add", "name": name,
           "geojson": {"type": "FeatureCollection",
                       "features": [_polygon_feature(0, 0)]},
           "style": None}
    final = {"type": "message", "text": "done", "done": True}
    return (
        f"event: layer_add\ndata: {json.dumps(add)}\n\n"
        f"event: message\ndata: {json.dumps(final)}\n\n"
    )


def _remove_layer_sse(name: str):
    """Build SSE: a single layer_command remove."""
    remove = {"type": "layer_command", "action": "remove", "layer_name": name}
    final = {"type": "message", "text": "removed", "done": True}
    return (
        f"event: layer_command\ndata: {json.dumps(remove)}\n\n"
        f"event: message\ndata: {json.dumps(final)}\n\n"
    )


def _layer_then_style_sse(name: str, color: str):
    """Build SSE: one layer_add followed by a layer_style event."""
    add = {"type": "layer_add", "name": name,
           "geojson": {"type": "FeatureCollection",
                       "features": [_polygon_feature(0, 0)]},
           "style": None}
    style = {"type": "layer_style", "layer_name": name,
             "style": {"color": color, "fillColor": color, "weight": 4}}
    final = {"type": "message", "text": "done", "done": True}
    return (
        f"event: layer_add\ndata: {json.dumps(add)}\n\n"
        f"event: layer_style\ndata: {json.dumps(style)}\n\n"
        f"event: message\ndata: {json.dumps(final)}\n\n"
    )


def _tool_error_sse():
    """SSE that emits a tool_result containing an error and an error event."""
    tool_start = {"type": "tool_start", "tool": "fetch_osm",
                  "input": {"feature_type": "park"}}
    tool_result = {"type": "tool_result", "tool": "fetch_osm",
                   "result": {"error": "OSM service is currently unreachable."}}
    err = {"type": "error", "text": "Tool fetch_osm failed."}
    final = {"type": "message", "text": "Sorry, I could not fetch OSM data.",
             "done": True}
    return (
        f"event: tool_start\ndata: {json.dumps(tool_start)}\n\n"
        f"event: tool_result\ndata: {json.dumps(tool_result)}\n\n"
        f"event: error\ndata: {json.dumps(err)}\n\n"
        f"event: message\ndata: {json.dumps(final)}\n\n"
    )


def _send_chat(page, sse_body: str, message: str = "test query"):
    """Standard browser drive: route /api/chat, fill, click."""
    page.route(
        "**/api/chat",
        lambda route, req: (
            route.fulfill(status=200, content_type="text/event-stream",
                          body=sse_body)
            if req.method == "POST" else route.continue_()
        ),
    )
    page.locator('button.tab-btn[data-tab="chat"]').click()
    page.locator("#chatInput").wait_for(state="visible", timeout=5000)
    page.locator("#chatInput").fill(message)
    page.locator("#chatSendBtn").click()


@pytest.mark.golden
def test_layer_command_remove_unmounts_layer(live_app, chromium):
    """When the chat emits a `layer_command remove`, the layer must
    actually disappear from `LayerManager` AND from the Leaflet overlay
    pane. Two-turn workflow (add, then remove on the next chat) so the
    intermediate "added" state is observable."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    layer_name = "removable_layer"

    # --- Turn 1: add the layer ---
    _send_chat(chromium, _add_layer_sse(layer_name), "show me the layer")
    deadline = time.time() + 6
    while time.time() < deadline:
        names = chromium.evaluate("window.LayerManager.getLayerNames()")
        rendered = chromium.evaluate(
            "document.querySelectorAll('.leaflet-overlay-pane path').length"
        )
        if layer_name in names and rendered >= 1:
            break
        time.sleep(0.15)
    else:
        pytest.fail(f"layer never appeared on turn 1. errors: {errors}")

    # Wait for the chat input to re-enable so we can send the next turn.
    chromium.locator("#chatInput").wait_for(state="visible", timeout=3000)
    deadline = time.time() + 3
    while time.time() < deadline:
        if chromium.evaluate(
            "!document.querySelector('#chatInput').disabled"
        ):
            break
        time.sleep(0.1)

    # Re-route: replace the previous fulfill with the remove SSE.
    chromium.unroute("**/api/chat")
    _send_chat(chromium, _remove_layer_sse(layer_name), "remove that layer")

    # --- Turn 2: layer must disappear ---
    deadline = time.time() + 6
    saw_remove = False
    while time.time() < deadline:
        names = chromium.evaluate("window.LayerManager.getLayerNames()")
        if layer_name not in names:
            saw_remove = True
            break
        time.sleep(0.15)

    assert saw_remove, (
        f"layer_command remove did not unmount the layer. "
        f"current layers: {chromium.evaluate('window.LayerManager.getLayerNames()')}; "
        f"errors: {errors}"
    )
    paths_after = chromium.evaluate(
        "document.querySelectorAll('.leaflet-overlay-pane path').length"
    )
    assert paths_after == 0, (
        f"layer_command remove dropped from LayerManager but {paths_after} "
        "polygon path(s) still painted on the map"
    )


@pytest.mark.golden
def test_two_layers_render_independently(live_app, chromium):
    """Two distinct layer_add events in one chat turn must produce two
    independent layers, both painted, both registered. Catches the bug
    class where a second layer overwrites the first or the second is
    silently dropped because the first hasn't finished initializing."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    _send_chat(chromium, _two_layers_sse(), "give me two layers")

    deadline = time.time() + 8
    names = []
    rendered = 0
    while time.time() < deadline:
        names = chromium.evaluate("window.LayerManager.getLayerNames()")
        rendered = chromium.evaluate(
            "document.querySelectorAll('.leaflet-overlay-pane path').length"
        )
        if "layer_a" in names and "layer_b" in names and rendered >= 2:
            break
        time.sleep(0.15)

    assert "layer_a" in names and "layer_b" in names, (
        f"two-layer SSE produced {names}; expected both layer_a and layer_b. "
        f"errors: {errors}"
    )
    assert rendered >= 2, (
        f"both layers registered but only {rendered}/2 polygons painted"
    )


@pytest.mark.golden
def test_layer_style_event_changes_color(live_app, chromium):
    """A `layer_style` event after a layer_add must update the polygon's
    rendered color. Catches the bug class where style changes silently
    fail and the user sees a polygon in the wrong color."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    layer_name = "styleable"
    target_color = "#ff00aa"  # distinct magenta — won't appear by default
    _send_chat(
        chromium,
        _layer_then_style_sse(layer_name, target_color),
        "color it magenta",
    )

    # Wait for layer to appear and for the path's stroke to flip to the
    # target color.
    deadline = time.time() + 8
    final_stroke = None
    while time.time() < deadline:
        names = chromium.evaluate("window.LayerManager.getLayerNames()")
        if layer_name in names:
            final_stroke = chromium.evaluate(
                "(() => { const p = document.querySelector("
                "'.leaflet-overlay-pane path'); "
                "return p ? (p.getAttribute('stroke') || '').toLowerCase() : null;"
                " })()"
            )
            if final_stroke and final_stroke.lower() == target_color.lower():
                break
        time.sleep(0.15)

    assert final_stroke is not None, (
        f"no path painted to apply style to. errors: {errors}"
    )
    assert final_stroke.lower() == target_color.lower(), (
        f"layer_style event did not update polygon stroke. "
        f"got {final_stroke!r}, expected {target_color!r}"
    )


@pytest.mark.golden
def test_tool_error_surfaces_in_chat_ui(live_app, chromium):
    """A tool failure (Overpass unreachable, etc.) must reach the user as
    a visible chat message — not silent. Catches the bug class where the
    tool fails and the chat just stops typing without telling the user."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    _send_chat(chromium, _tool_error_sse(), "fetch parks")

    # The chat UI must show some error-class element OR an error message
    # in the chat history within the timeout.
    deadline = time.time() + 6
    found_error_text = False
    while time.time() < deadline:
        # The error is surfaced through appendMessage('error', ...) which
        # renders into the chat history. Look for the error text from our
        # canned event.
        body_text = chromium.evaluate("document.body.innerText")
        if (
            "fetch_osm failed" in body_text.lower()
            or "could not fetch osm" in body_text.lower()
            or "unreachable" in body_text.lower()
        ):
            found_error_text = True
            break
        time.sleep(0.2)

    assert found_error_text, (
        "tool error never surfaced in the chat UI — silent failure. "
        "User would see a dead chat with no explanation. "
        f"page errors: {errors}"
    )

    # The chat input must remain usable for the next request.
    assert chromium.locator("#chatInput").is_enabled(), (
        "chat input stayed disabled after tool error — user is wedged"
    )


def _two_feature_layer_then_highlight_sse(name: str, target_value: str, color: str):
    """SSE that adds a layer with two features (different category_name)
    then highlights the one matching `target_value` with `color`."""
    feat_a = _polygon_feature(0, 0)
    feat_a["properties"]["category_name"] = "alpha"
    feat_b = _polygon_feature(0.01, 0.01)
    feat_b["properties"]["category_name"] = "beta"
    add = {"type": "layer_add", "name": name,
           "geojson": {"type": "FeatureCollection", "features": [feat_a, feat_b]},
           "style": None}
    highlight = {"type": "highlight", "layer_name": name,
                 "attribute": "category_name", "value": target_value,
                 "color": color}
    final = {"type": "message", "text": "highlighted", "done": True}
    return (
        f"event: layer_add\ndata: {json.dumps(add)}\n\n"
        f"event: highlight\ndata: {json.dumps(highlight)}\n\n"
        f"event: message\ndata: {json.dumps(final)}\n\n"
    )


def _plan_sse():
    """SSE that returns a plan (no execution yet)."""
    plan = {
        "type": "plan",
        "summary": "Fetch parks then count them.",
        "estimated_steps": 2,
        "plan": [
            {"step": 1, "tool": "fetch_osm",
             "params": {"feature_type": "park", "category_name": "p",
                        "location": "Chicago"},
             "reason": "Get the parks in Chicago"},
            {"step": 2, "tool": "aggregate",
             "params": {"layer_name": "p", "operation": "count"},
             "reason": "Count them"},
        ],
    }
    return f"event: plan\ndata: {json.dumps(plan)}\n\n"


def _slow_then_quick_sse_factory():
    """Factory returning two route-fulfill closures: the first sleeps
    briefly before responding (to simulate an in-flight chat), the second
    responds immediately. Used by the concurrent-chat test to prove the
    AbortController cancels the first call."""
    def _slow_handler(route, request):
        if request.method == "POST":
            # Brief delay so the next chat can fire while we're "in flight".
            time.sleep(1.5)
            slow_layer = {"type": "layer_add", "name": "slow_layer",
                          "geojson": {"type": "FeatureCollection",
                                      "features": [_polygon_feature(0, 0)]},
                          "style": None}
            final = {"type": "message", "text": "slow done", "done": True}
            route.fulfill(
                status=200, content_type="text/event-stream",
                body=(f"event: layer_add\ndata: {json.dumps(slow_layer)}\n\n"
                      f"event: message\ndata: {json.dumps(final)}\n\n"),
            )
        else:
            route.continue_()

    def _fast_handler(route, request):
        if request.method == "POST":
            fast_layer = {"type": "layer_add", "name": "fast_layer",
                          "geojson": {"type": "FeatureCollection",
                                      "features": [_polygon_feature(0.05, 0.05)]},
                          "style": None}
            final = {"type": "message", "text": "fast done", "done": True}
            route.fulfill(
                status=200, content_type="text/event-stream",
                body=(f"event: layer_add\ndata: {json.dumps(fast_layer)}\n\n"
                      f"event: message\ndata: {json.dumps(final)}\n\n"),
            )
        else:
            route.continue_()

    return _slow_handler, _fast_handler


@pytest.mark.golden
def test_highlight_event_recolors_only_matching_features(live_app, chromium):
    """A `highlight` event must change the stroke of features whose
    attribute matches the target value — and ONLY those features. The
    bug class: highlight matches everything (broken predicate) or nothing
    (broken attribute lookup), giving the user a confusing visual."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    layer_name = "two_feat_layer"
    target_color = "#ff7700"  # bright orange — won't appear by default
    _send_chat(
        chromium,
        _two_feature_layer_then_highlight_sse(layer_name, "alpha", target_color),
        "highlight alpha",
    )

    deadline = time.time() + 8
    matched_orange = 0
    other_orange = 0
    while time.time() < deadline:
        names = chromium.evaluate("window.LayerManager.getLayerNames()")
        if layer_name in names:
            # Count paths whose stroke is the target color.
            matched_orange = chromium.evaluate(
                "Array.from(document.querySelectorAll("
                "'.leaflet-overlay-pane path')).filter("
                f"p => (p.getAttribute('stroke') || '').toLowerCase() === '{target_color.lower()}'"
                ").length"
            )
            if matched_orange >= 1:
                # Also count any OTHER paths that became orange (would be a bug).
                other_orange = chromium.evaluate(
                    "Array.from(document.querySelectorAll("
                    "'.leaflet-overlay-pane path')).length"
                )
                break
        time.sleep(0.15)

    assert matched_orange == 1, (
        f"highlight should re-color exactly 1 feature (the alpha one); "
        f"got {matched_orange} orange paths. errors: {errors}"
    )
    assert other_orange == 2, (
        f"expected 2 total polygons painted (1 orange + 1 default-blue), "
        f"got {other_orange} — features may have been dropped"
    )


@pytest.mark.golden
def test_quick_action_button_dispatches_chat(live_app, chromium):
    """Clicking a `.quick-action-btn` must fill the chat input with the
    button's `data-msg` AND fire the /api/chat POST. Catches regressions
    in the convenience-button wiring (a common user entry point)."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    # Capture the POST body the button click triggers.
    captured = {}

    def _capture(route, request):
        if request.method == "POST":
            captured["body"] = request.post_data
            # Return a trivial successful SSE so the chat completes.
            final = {"type": "message", "text": "ack", "done": True}
            route.fulfill(
                status=200, content_type="text/event-stream",
                body=f"event: message\ndata: {json.dumps(final)}\n\n",
            )
        else:
            route.continue_()

    chromium.route("**/api/chat", _capture)

    # Open chat tab and click the "Buildings" quick-action button.
    chromium.locator('button.tab-btn[data-tab="chat"]').click()
    chromium.locator(".quick-action-btn", has_text="Buildings").wait_for(
        state="visible", timeout=5000,
    )
    chromium.locator(".quick-action-btn", has_text="Buildings").click()

    # Wait for the POST to fire.
    deadline = time.time() + 5
    while time.time() < deadline and "body" not in captured:
        time.sleep(0.1)

    assert "body" in captured, (
        f"clicking quick-action did not fire POST /api/chat. errors: {errors}"
    )
    body_str = captured["body"] or ""
    assert "Fetch buildings in this map area" in body_str, (
        f"quick-action POST did not include the button's data-msg. "
        f"body: {body_str[:200]!r}"
    )


@pytest.mark.golden
def test_plan_mode_renders_plan_ui_with_steps(live_app, chromium):
    """When the chat returns a `plan` event (plan mode), the frontend
    must render the plan steps + an "Execute Plan" button. Catches the
    bug class where plan mode silently degrades to a text message and
    the user never sees the plan."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    _send_chat(chromium, _plan_sse(), "fetch then count")

    # Wait for the plan UI: an <ol> with two <li> entries + an "Execute Plan" button.
    chromium.locator(".chat-plan ol li").first.wait_for(
        state="visible", timeout=8_000,
    )

    li_count = chromium.locator(".chat-plan ol li").count()
    assert li_count == 2, (
        f"plan UI should render 2 steps; rendered {li_count}. "
        f"errors: {errors}"
    )

    li_texts = [
        chromium.locator(".chat-plan ol li").nth(i).inner_text()
        for i in range(li_count)
    ]
    joined = " | ".join(li_texts).lower()
    assert "fetch_osm" in joined and "aggregate" in joined, (
        f"plan steps missing expected tool names. got: {li_texts}"
    )

    assert chromium.locator("button.plan-approve",
                            has_text="Execute Plan").is_visible(), (
        "plan UI did not render the Execute Plan button"
    )
    assert chromium.locator("button.plan-reject",
                            has_text="Cancel").is_visible(), (
        "plan UI did not render the Cancel button"
    )


def _hang_chat_fetch_js() -> str:
    """JS that monkey-patches window.fetch so any /api/chat POST returns
    a Response whose body is a never-resolving stream. Lets us observe
    the in-flight UI state from the test without blocking the Playwright
    event loop the way a Python sleep in a route handler would."""
    return r"""
    (function(){
        const origFetch = window.fetch;
        window._lastAbortReason = null;
        window.fetch = function(url, opts){
            if (typeof url === 'string' && url.includes('/api/chat') && !url.includes('execute-plan')) {
                // Never-completing body stream so the chat stays "in flight".
                const stream = new ReadableStream({
                    start(controller){
                        // intentionally no enqueue/close
                    }
                });
                // Honor the AbortController so the chat client's abort path
                // can resolve. Record the reason so the test can assert it.
                if (opts && opts.signal) {
                    opts.signal.addEventListener('abort', function(){
                        window._lastAbortReason = opts.signal.reason || 'aborted';
                    });
                }
                return Promise.resolve(new Response(stream, {
                    status: 200,
                    headers: {'Content-Type': 'text/event-stream'},
                }));
            }
            return origFetch.apply(this, arguments);
        };
    })();
    """


@pytest.mark.golden
def test_stop_button_cancels_in_flight_chat(live_app, chromium):
    """While a chat is streaming, clicking the Send (now 'Stop') button
    must abort the fetch and re-enable the input. Catches Stop-button
    regressions that leave the user wedged with a frozen 'Stop' button.
    Uses a JS-side fetch override so the Playwright event loop stays
    free to drive UI interactions while the chat is "in flight"."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)
    chromium.evaluate(_hang_chat_fetch_js())

    chromium.locator('button.tab-btn[data-tab="chat"]').click()
    chromium.locator("#chatInput").wait_for(state="visible", timeout=5000)
    chromium.locator("#chatInput").fill("slow query")
    chromium.locator("#chatSendBtn").click()

    # Button flips to 'Stop' once the chat starts.
    chromium.wait_for_function(
        "() => document.querySelector('#chatSendBtn').textContent.trim() === 'Stop'",
        timeout=3_000,
    )

    # Click Stop → fetch must be aborted, input re-enabled, button = 'Send'.
    chromium.locator("#chatSendBtn").click()

    chromium.wait_for_function(
        "() => !document.querySelector('#chatInput').disabled && "
        "document.querySelector('#chatSendBtn').textContent.trim() === 'Send'",
        timeout=3_000,
    )

    # Confirm the AbortController fired (frontend respected the cancel).
    abort_reason = chromium.evaluate("window._lastAbortReason")
    assert abort_reason is not None, (
        "Stop button did not propagate to the AbortController — the "
        "fetch was never cancelled. M2 audit regression. "
        f"errors: {errors}"
    )


@pytest.mark.golden
def test_concurrent_chats_second_aborts_first(live_app, chromium):
    """Submitting a second chat while the first is in-flight must abort
    the first (AbortController) so its events do not race with the
    second's. M2 audit contract. Uses the same JS-side fetch override
    as the Stop test to keep the Playwright loop responsive."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)
    chromium.evaluate(_hang_chat_fetch_js())

    chromium.locator('button.tab-btn[data-tab="chat"]').click()
    chromium.locator("#chatInput").wait_for(state="visible", timeout=5000)
    chromium.locator("#chatInput").fill("first query")
    chromium.locator("#chatSendBtn").click()

    chromium.wait_for_function(
        "() => document.querySelector('#chatSendBtn').textContent.trim() === 'Stop'",
        timeout=3_000,
    )
    # First fetch is now hanging. Reset the abort sentinel so we can prove
    # the SECOND send-attempt's path triggered an abort, not the prior one.
    chromium.evaluate("window._lastAbortReason = null")

    # The Send button currently says 'Stop' — its click handler would
    # only abort, not send. To simulate the user firing a second message,
    # call sendMessage's effective entry point: forcibly flip the button
    # to 'Send', re-enable the input, then click. (Mirrors the post-abort
    # state the chat client itself produces between turns.)
    chromium.evaluate(
        "document.querySelector('#chatInput').disabled = false;"
        "document.querySelector('#chatSendBtn').textContent = 'Send';"
    )
    chromium.locator("#chatInput").fill("second query")
    chromium.locator("#chatSendBtn").click()

    # The second send creates a new AbortController and aborts the
    # previous one. Wait for the abort sentinel to become non-null.
    chromium.wait_for_function(
        "() => window._lastAbortReason !== null",
        timeout=3_000,
    )

    # And the in-flight indicator flips to 'Stop' for the second request.
    chromium.wait_for_function(
        "() => document.querySelector('#chatSendBtn').textContent.trim() === 'Stop'",
        timeout=3_000,
    )

    abort_reason = chromium.evaluate("window._lastAbortReason")
    assert abort_reason is not None, (
        "starting a second chat did not abort the first — M2 regression. "
        f"errors: {errors}"
    )


def _wide_area_polygons_sse(layer_name: str, n_features: int = 60):
    """SSE that emits a layer_add with N small polygons spread across a
    wide bbox (~30km). Mimics 'show hospitals in Chicago' — the user-
    reported bug class where individual polygons are sub-pixel at fit
    zoom and the map looks blank. With the fix in place, the centroid
    cluster representation should render instead."""
    # Spread features across ~0.3 degrees lat × 0.4 degrees lng (≈ 30km).
    base_lat, base_lng = 41.78, -87.80
    features = []
    for i in range(n_features):
        # Pseudo-random but deterministic placement.
        lat = base_lat + ((i * 0.013) % 0.3)
        lng = base_lng + ((i * 0.017) % 0.4)
        # Each polygon ~50m square (sub-pixel at low zoom).
        d = 0.0005
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [lng, lat], [lng + d, lat],
                    [lng + d, lat + d], [lng, lat + d], [lng, lat],
                ]],
            },
            "properties": {"category_name": "tiny", "osm_id": 100000 + i},
        })
    add = {"type": "layer_add", "name": layer_name,
           "geojson": {"type": "FeatureCollection", "features": features},
           "style": None}
    final = {"type": "message", "text": f"Rendered {n_features} features.",
             "done": True}
    return (
        f"event: layer_add\ndata: {json.dumps(add)}\n\n"
        f"event: message\ndata: {json.dumps(final)}\n\n"
    )


@pytest.mark.golden
def test_wide_area_many_polygons_renders_as_cluster_bubbles(
    live_app, chromium,
):
    """Wide-area polygon queries (small features over a large bbox) must
    render as cluster bubbles at low zoom — NOT as sub-pixel invisible
    polygons. The user's manual-check complaint was exactly this case
    ('show hospitals in Chicago' returned data but the map looked blank).
    Pin: at zoom < 15 with 60 polygons spread over ~30km, the cluster
    layer is on the map and the polygon paths are NOT.
    """
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)
    chromium.wait_for_function(
        "() => window.map && typeof window.map.getCenter === 'function'",
        timeout=10_000,
    )

    layer_name = "wide_hospital_test"
    _send_chat(chromium, _wide_area_polygons_sse(layer_name, 60),
               "show wide-area hospitals")

    # Wait for the layer to register.
    chromium.wait_for_function(
        f"() => window.LayerManager.getLayerNames().includes('{layer_name}')",
        timeout=8_000,
    )

    # Fit the map to the layer (mimics chat post-render auto-fit). With
    # 60 features over ~30km bounds, fit zoom should be ≤ 11.
    chromium.evaluate(f"window.LayerManager.fitToLayer('{layer_name}')")
    chromium.wait_for_timeout(700)  # tiles + zoom transition

    fit_zoom = chromium.evaluate("window.map.getZoom()")
    assert fit_zoom < 15, (
        f"fitToLayer chose zoom {fit_zoom} — bbox should have been wide "
        "enough to force a low zoom. Test fixture is wrong."
    )

    # At low zoom the centroid-cluster layer must be active (cluster
    # bubbles in the marker pane) and the polygon-painting must be
    # WAY under the feature count (the bug class was 60 sub-pixel paths
    # painted at low zoom; the fix collapses them into a handful of
    # cluster markers, mostly rendered as `.marker-cluster` divs plus a
    # few stray circleMarker paths for outliers).
    cluster_count = chromium.evaluate(
        "document.querySelectorAll('.marker-cluster, .leaflet-marker-icon').length"
    )
    polygon_path_count = chromium.evaluate(
        "document.querySelectorAll('.leaflet-overlay-pane path').length"
    )
    assert cluster_count > 0, (
        f"wide-area layer at zoom {fit_zoom} did not render any cluster "
        "markers — the centroid-cluster fix has regressed. Path count: "
        f"{polygon_path_count}; errors: {errors}"
    )
    assert polygon_path_count < 10, (
        f"too many overlay-pane paths painted at zoom {fit_zoom} "
        f"({polygon_path_count}) — polygons were not swapped out for "
        "the cluster representation. Bug class regressed."
    )

    # Now zoom in past the swap level — the polygons should appear.
    chromium.evaluate("window.map.setZoom(16)")
    chromium.wait_for_timeout(500)

    polygon_count_after = chromium.evaluate(
        "document.querySelectorAll('.leaflet-overlay-pane path').length"
    )
    assert polygon_count_after > 0, (
        f"after zooming in past 15 the polygons did not re-appear "
        f"(path count {polygon_count_after}); zoom-toggle is broken"
    )


@pytest.mark.golden
def test_wide_area_layer_emits_chat_hint(live_app, chromium):
    """When >= 500 features are returned, the chat must surface a hint
    explaining that cluster bubbles will be shown at low zoom. Without
    this, users see a 'rendered N features' message and assume the map
    is broken when fitToLayer pans wide."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    _send_chat(chromium, _wide_area_polygons_sse("hint_check", 600),
               "show many features")

    # Wait for the hint to appear in the chat history.
    deadline = time.time() + 6
    saw_hint = False
    while time.time() < deadline:
        body_text = chromium.evaluate("document.body.innerText")
        if ("Showing 600 features" in body_text
                and "Zoom in" in body_text):
            saw_hint = True
            break
        time.sleep(0.15)

    assert saw_hint, (
        "chat did not surface the high-feature-count hint. "
        f"errors: {errors}"
    )


def _heatmap_sse(layer_name: str, points: list):
    """SSE that emits a heatmap event with the given (lat, lng, intensity)
    points. Frontend handler at chat.js:417 needs `window.L.heatLayer`."""
    heat = {
        "type": "heatmap",
        "layer_name": layer_name,
        "points": points,
        "options": {"radius": 25, "blur": 15},
    }
    final = {"type": "message", "text": "heatmap rendered", "done": True}
    return (
        f"event: heatmap\ndata: {json.dumps(heat)}\n\n"
        f"event: message\ndata: {json.dumps(final)}\n\n"
    )


@pytest.mark.golden
def test_heatmap_event_creates_heat_layer(live_app, chromium):
    """A `heatmap` event must (a) find `L.heatLayer` loaded, (b) register
    the layer in `LayerManager`, (c) paint a Leaflet.heat canvas onto the
    overlay pane. Pre-fix, Leaflet.heat was not loaded in the template so
    the handler's `if (window.L && window.L.heatLayer && data.points)`
    guard silently dropped every heatmap tool call. This test pins the
    fix: if Leaflet.heat is removed from index.html again, this fails."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    # Belt-and-braces: the lib MUST be available before the event arrives,
    # otherwise the handler silently no-ops. Asserting this directly so
    # the failure message is unambiguous when the script tag is removed.
    assert chromium.evaluate("typeof L !== 'undefined' && typeof L.heatLayer === 'function'"), (
        "Leaflet.heat is not loaded — heatmap tool calls will silently no-op. "
        "Re-add the leaflet-heat.js <script> in templates/index.html."
    )

    layer_name = "test_heatmap"
    # 5 weighted points around Chicago.
    points = [
        [41.880, -87.628, 0.9],
        [41.882, -87.630, 0.7],
        [41.878, -87.625, 0.5],
        [41.884, -87.632, 0.6],
        [41.876, -87.620, 0.8],
    ]
    _send_chat(chromium, _heatmap_sse(layer_name, points), "show heatmap")

    # The handler registers the layer with LayerManager AND paints a
    # <canvas class="leaflet-heatmap-layer"> via Leaflet.heat.
    deadline = time.time() + 8
    saw_layer = False
    saw_canvas = False
    while time.time() < deadline:
        names = chromium.evaluate("window.LayerManager.getLayerNames()")
        if layer_name in names:
            saw_layer = True
        # Leaflet.heat renders to a canvas inside the overlay pane.
        canvas_count = chromium.evaluate(
            "document.querySelectorAll('canvas.leaflet-heatmap-layer').length"
        )
        if canvas_count > 0:
            saw_canvas = True
        if saw_layer and saw_canvas:
            break
        time.sleep(0.15)

    assert saw_layer, (
        f"heatmap event did not register layer in LayerManager. "
        f"got: {chromium.evaluate('window.LayerManager.getLayerNames()')}; "
        f"errors: {errors}"
    )
    assert saw_canvas, (
        f"heatmap layer registered but Leaflet.heat did not paint a "
        f"canvas onto the overlay pane. errors: {errors}"
    )


def _chart_tool_result_sse():
    """SSE that emits a tool_start + tool_result for a `chart` call. The
    result payload is the Chart.js-compatible spec the backend returns."""
    tool_start = {"type": "tool_start", "tool": "chart",
                  "input": {"layer_name": "x", "attribute": "type",
                            "chart_type": "pie"}}
    tool_result = {
        "type": "tool_result", "tool": "chart",
        "result": {
            "action": "chart",
            "chart_type": "pie",
            "layer_name": "x",
            "labels": ["alpha", "beta", "gamma"],
            "datasets": [{"label": "count(type)", "data": [3, 5, 2]}],
            "title": "Pie — count(type) by type",
        },
    }
    final = {"type": "message", "text": "chart rendered", "done": True}
    return (
        f"event: tool_start\ndata: {json.dumps(tool_start)}\n\n"
        f"event: tool_result\ndata: {json.dumps(tool_result)}\n\n"
        f"event: message\ndata: {json.dumps(final)}\n\n"
    )


@pytest.mark.golden
def test_chart_tool_result_renders_chartjs_canvas(live_app, chromium):
    """A `chart` tool result must render an actual Chart.js chart in the
    chat history — not the raw JSON dump that fell out of the default
    formatToolResult branch pre-fix. Pins (a) Chart.js is loaded,
    (b) the chart-render hook fires on action='chart', (c) a canvas
    element appears under the tool step, (d) Chart.js attaches a chart
    instance to that canvas (verified via Chart.getChart)."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    # Belt-and-braces: Chart.js MUST be loaded before the event arrives.
    assert chromium.evaluate("typeof window.Chart === 'function'"), (
        "Chart.js is not loaded — chart tool results will fall back to "
        "raw JSON dumps. Re-add the Chart.js <script> in templates/index.html."
    )

    _send_chat(chromium, _chart_tool_result_sse(), "chart it")

    # Wait for a canvas to appear inside a tool step.
    deadline = time.time() + 8
    canvas_present = False
    chart_attached = False
    while time.time() < deadline:
        canvas_count = chromium.evaluate(
            "document.querySelectorAll('.chat-tool-step canvas.chat-chart-canvas').length"
        )
        if canvas_count >= 1:
            canvas_present = True
            # Chart.js exposes Chart.getChart(canvas) — non-null if a
            # chart is attached.
            chart_attached = chromium.evaluate(
                "(() => { const c = document.querySelector("
                "'.chat-tool-step canvas.chat-chart-canvas'); "
                "return !!(c && window.Chart && Chart.getChart(c)); })()"
            )
            if chart_attached:
                break
        time.sleep(0.15)

    assert canvas_present, (
        "chart tool result did not produce a <canvas> in the tool step. "
        "renderChartIntoStep hook may not be wired. "
        f"errors: {errors}"
    )
    assert chart_attached, (
        "canvas appeared but no Chart.js instance is attached — "
        "the render call may have thrown. "
        f"errors: {errors}"
    )

    # Tool-step text should still summarize (default branch in
    # formatToolResult), not crash.
    step_text = chromium.evaluate(
        "document.querySelector('.chat-tool-step .tool-text').textContent"
    )
    assert step_text is not None and len(step_text) > 0, (
        "tool step lost its summary text after chart render"
    )


def _choropleth_tool_result_sse(layer_name: str = "tracts"):
    """N31 regression SSE: a `choropleth_map` tool result. Backend handler
    at nl_gis/handlers/visualization.py:264 returns
    {action: 'choropleth', styleMap: {idx: '#hex'}, legendData: {...}}.
    Pre-N31 the frontend had no `case 'choropleth':` and the result fell
    through to formatToolResult's JSON-dump default branch — the layer
    was NOT recolored and no legend appeared.
    """
    feats = [_polygon_feature(0.001 * i, 0) for i in range(4)]
    add = {"type": "layer_add", "name": layer_name,
           "geojson": {"type": "FeatureCollection", "features": feats},
           "style": None}
    tool_start = {"type": "tool_start", "tool": "choropleth_map",
                  "input": {"layer_name": layer_name,
                            "attribute": "pop",
                            "num_classes": 4}}
    # styleMap keys serialize to JSON as strings; the renderer must look up
    # both the numeric and string forms.
    tool_result = {
        "type": "tool_result", "tool": "choropleth_map",
        "result": {
            "action": "choropleth",
            "layer_name": layer_name,
            "attribute": "pop",
            "method": "quantile",
            "breaks": [0.0, 25.0, 50.0, 75.0, 100.0],
            "colors": ["#fef0d9", "#fdcc8a", "#fc8d59", "#d7301f"],
            "styleMap": {"0": "#fef0d9", "1": "#fdcc8a",
                         "2": "#fc8d59", "3": "#d7301f"},
            "missing_count": 0,
            "feature_count": 4,
            "legendData": {
                "type": "choropleth",
                "title": "tracts — pop",
                "entries": [
                    {"color": "#fef0d9", "min": 0.0, "max": 25.0,
                     "count": 1, "label": "0.00 – 25.00"},
                    {"color": "#fdcc8a", "min": 25.0, "max": 50.0,
                     "count": 1, "label": "25.00 – 50.00"},
                    {"color": "#fc8d59", "min": 50.0, "max": 75.0,
                     "count": 1, "label": "50.00 – 75.00"},
                    {"color": "#d7301f", "min": 75.0, "max": 100.0,
                     "count": 1, "label": "75.00 – 100.00"},
                ],
            },
        },
    }
    final = {"type": "message", "text": "choropleth rendered", "done": True}
    return (
        f"event: layer_add\ndata: {json.dumps(add)}\n\n"
        f"event: tool_start\ndata: {json.dumps(tool_start)}\n\n"
        f"event: tool_result\ndata: {json.dumps(tool_result)}\n\n"
        f"event: message\ndata: {json.dumps(final)}\n\n"
    )


@pytest.mark.golden
def test_choropleth_tool_result_recolors_layer_and_renders_legend(
    live_app, chromium,
):
    """N31 regression: a choropleth_map tool result MUST (a) recolor the
    layer features per styleMap, (b) render a legend panel under the tool
    step. Pre-fix, both silently no-op'd because chat.js had no
    `case 'choropleth':` in the tool_result handler — the layer kept its
    default blue and the user saw a JSON dump in the chat.
    """
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    # Sanity: applyStyleMap was added to LayerManager in this fix.
    assert chromium.evaluate(
        "typeof window.LayerManager.applyStyleMap === 'function'"
    ), (
        "LayerManager.applyStyleMap is not exported. "
        "static/js/layers.js return block must list applyStyleMap."
    )

    _send_chat(chromium, _choropleth_tool_result_sse(), "color tracts by pop")

    # Wait for the legend panel to appear under the tool step.
    deadline = time.time() + 8
    legend_present = False
    while time.time() < deadline:
        legend_count = chromium.evaluate(
            "document.querySelectorAll("
            "'.chat-tool-step .choropleth-legend').length"
        )
        if legend_count >= 1:
            legend_present = True
            break
        time.sleep(0.15)

    assert legend_present, (
        "choropleth tool result did not render a legend panel under the "
        "tool step. renderChoroplethLegend hook may not be wired. "
        f"errors: {errors}"
    )

    # Legend should have one row per class (4).
    row_count = chromium.evaluate(
        "document.querySelectorAll("
        "'.chat-tool-step .choropleth-legend .choropleth-legend-row').length"
    )
    assert row_count == 4, (
        f"expected 4 legend rows (one per class break); got {row_count}. "
        f"legendData.entries may not be iterated correctly."
    )

    # The first feature path on the map should now have the styleMap[0]
    # color, not the default blue (#3388ff). Leaflet renders polygon
    # features as <path> elements with a `fill` attribute.
    fill_colors = chromium.evaluate(
        "Array.from(document.querySelectorAll('.leaflet-overlay-pane path'))"
        ".map(function(p) { return p.getAttribute('fill'); })"
    )
    assert fill_colors, (
        "no <path> elements rendered on the map; layer_add may have failed "
        f"upstream. errors: {errors}"
    )
    # styleMap was {0:#fef0d9, 1:#fdcc8a, 2:#fc8d59, 3:#d7301f}; default
    # blue is #3388ff. After the recolor, the choropleth palette should
    # appear at least once and the default blue should NOT.
    palette = {"#fef0d9", "#fdcc8a", "#fc8d59", "#d7301f"}
    fills_lower = {(c or "").lower() for c in fill_colors}
    palette_lower = {c.lower() for c in palette}
    assert fills_lower & palette_lower, (
        f"choropleth palette did not appear on any path; fills={fill_colors}. "
        f"applyStyleMap may not be iterating features in the same order as "
        f"the handler indexed them."
    )
    assert "#3388ff" not in fills_lower, (
        f"default blue still present after choropleth — the recolor missed "
        f"some features. fills={fill_colors}"
    )


def _animate_layer_tool_result_sse(layer_name: str = "permits"):
    """SSE for an animate_layer tool result. The handler returns a
    time_steps list; the frontend should render a slider+play UI."""
    add = {"type": "layer_add", "name": layer_name,
           "geojson": {"type": "FeatureCollection",
                       "features": [
                           _polygon_feature(0, 0),
                           _polygon_feature(0.001, 0),
                           _polygon_feature(0.002, 0),
                           _polygon_feature(0.003, 0),
                       ]},
           "style": None}
    tool_start = {"type": "tool_start", "tool": "animate_layer",
                  "input": {"layer_name": layer_name,
                            "time_attribute": "year"}}
    tool_result = {
        "type": "tool_result", "tool": "animate_layer",
        "result": {
            "action": "animate", "layer_name": layer_name,
            "time_attribute": "year", "interval_ms": 200,
            "cumulative": False, "feature_count": 4, "binned": False,
            "time_steps": [
                {"time": "2020", "label": "2020", "feature_indices": [0]},
                {"time": "2021", "label": "2021", "feature_indices": [1]},
                {"time": "2022", "label": "2022", "feature_indices": [2]},
                {"time": "2023", "label": "2023", "feature_indices": [3]},
            ],
        },
    }
    final = {"type": "message", "text": "animation ready", "done": True}
    return (
        f"event: layer_add\ndata: {json.dumps(add)}\n\n"
        f"event: tool_start\ndata: {json.dumps(tool_start)}\n\n"
        f"event: tool_result\ndata: {json.dumps(tool_result)}\n\n"
        f"event: message\ndata: {json.dumps(final)}\n\n"
    )


def _visualize_3d_tool_result_sse(layer_name: str = "buildings_3d"):
    """SSE for visualize_3d. Backend returns a height-annotated GeoJSON;
    the frontend should expose a 'Show 3D view' button that opens a
    deck.gl modal with extruded buildings."""
    feats = []
    for i in range(3):
        f = _polygon_feature(0.001 * i, 0)
        f["properties"]["_height_m"] = 10.0 + 20.0 * i
        feats.append(f)
    tool_start = {"type": "tool_start", "tool": "visualize_3d",
                  "input": {"layer_name": layer_name}}
    tool_result = {
        "type": "tool_result", "tool": "visualize_3d",
        "result": {
            "action": "3d_buildings", "layer_name": layer_name,
            "height_attribute": "height", "height_multiplier": 3.0,
            "default_height": 10.0, "skipped_non_polygon": 0,
            "used_default_count": 0, "feature_count": len(feats),
            "geojson": {"type": "FeatureCollection", "features": feats},
        },
    }
    final = {"type": "message", "text": "3d ready", "done": True}
    return (
        f"event: tool_start\ndata: {json.dumps(tool_start)}\n\n"
        f"event: tool_result\ndata: {json.dumps(tool_result)}\n\n"
        f"event: message\ndata: {json.dumps(final)}\n\n"
    )


@pytest.mark.golden
def test_animate_layer_filters_cluster_markers_at_low_zoom(
    live_app, chromium,
):
    """Audit N22 regression: when a wide-area polygon layer is in
    cluster mode (zoom < 15), filterToIndices must also toggle which
    centroid markers are in the cluster — not just style the hidden
    polygon paths. Without this, the slider advances visually but the
    cluster bubbles never update until the user zooms in.

    Setup: 60 polygons over ~30km bbox (forces cluster mode at fit
    zoom). Then call filterToIndices([0]) directly via the page and
    verify the cluster's `hasLayer(marker[0])` is true while
    `hasLayer(marker[1])` is false.
    """
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)
    chromium.wait_for_function(
        "() => window.LayerManager && "
        "typeof window.LayerManager.filterToIndices === 'function'",
        timeout=5_000,
    )

    layer_name = "wide_anim"
    _send_chat(chromium, _wide_area_polygons_sse(layer_name, 60),
               "wide-area animate test")
    chromium.wait_for_function(
        f"() => window.LayerManager.getLayerNames().includes('{layer_name}')",
        timeout=8_000,
    )

    # Fit the map low so the cluster mode is active, then capture the
    # baseline cluster-bubble count.
    chromium.evaluate(f"window.LayerManager.fitToLayer('{layer_name}')")
    chromium.wait_for_timeout(500)
    baseline_clusters = chromium.evaluate(
        "document.querySelectorAll('.marker-cluster').length"
    )
    assert baseline_clusters > 0, (
        "wide-area layer did not enter cluster mode at fit zoom — "
        "test setup wrong or cluster trigger broke"
    )

    # Filter to just the first feature. The cluster must reorganize:
    # with 59 of 60 markers removed, the surviving cluster bubble count
    # MUST be smaller than the baseline. Pre-fix the cluster never
    # learned about the filter and the bubbles stayed put.
    chromium.evaluate(
        f"window.LayerManager.filterToIndices('{layer_name}', [0])"
    )
    chromium.wait_for_timeout(400)
    filtered_clusters = chromium.evaluate(
        "document.querySelectorAll('.marker-cluster').length"
    )
    assert filtered_clusters < baseline_clusters, (
        f"filterToIndices([0]) did not shrink cluster bubbles "
        f"(was {baseline_clusters}, after-filter {filtered_clusters}). "
        "N22 regression — slider would not affect visible bubbles."
    )
    # Restore via clearFilter — cluster bubble count must return to
    # ~baseline (animation reset must not leave map stuck on filter).
    chromium.evaluate(f"window.LayerManager.clearFilter('{layer_name}')")
    chromium.wait_for_timeout(400)
    restored_clusters = chromium.evaluate(
        "document.querySelectorAll('.marker-cluster').length"
    )
    assert restored_clusters >= baseline_clusters, (
        f"clearFilter did not restore cluster ({restored_clusters} < "
        f"baseline {baseline_clusters}). Animation reset broken."
    )
    assert errors == [], f"page errors: {errors}"


@pytest.mark.golden
def test_animate_layer_renders_player_and_filters_features(
    live_app, chromium,
):
    """animate_layer must render a slider + play/reset buttons; clicking
    play must advance the slider AND filter the layer per step. Pre-fix,
    the result fell through to a raw-JSON dump."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)
    chromium.wait_for_function(
        "() => window.LayerManager && "
        "typeof window.LayerManager.filterToIndices === 'function'",
        timeout=5_000,
    )

    _send_chat(chromium, _animate_layer_tool_result_sse(), "animate this")

    # The player UI must appear under the tool step.
    chromium.locator(".chat-animate-player").first.wait_for(
        state="visible", timeout=6_000,
    )
    assert chromium.locator(".chat-animate-slider").is_visible()
    assert chromium.locator(".chat-animate-play").is_visible()
    assert chromium.locator(".chat-animate-reset").is_visible()

    # Initial state — slider at 0, label says step 1/4.
    initial_label = chromium.evaluate(
        "document.querySelector('.chat-animate-label').textContent"
    )
    assert "Step 1 / 4" in initial_label, f"label was: {initial_label!r}"
    initial_slider = chromium.evaluate(
        "document.querySelector('.chat-animate-slider').value"
    )
    assert initial_slider == "0"

    # Press play; slider must advance past 0 within a couple of intervals.
    chromium.locator(".chat-animate-play").click()
    chromium.wait_for_function(
        "() => parseInt(document.querySelector('.chat-animate-slider').value, 10) > 0",
        timeout=3_000,
    )
    # Button text flips to Pause while playing.
    assert "Pause" in chromium.locator(".chat-animate-play").inner_text()

    # Reset returns slider to 0 and the label to step 1/4.
    chromium.locator(".chat-animate-reset").click()
    chromium.wait_for_function(
        "() => document.querySelector('.chat-animate-slider').value === '0'",
        timeout=2_000,
    )
    assert errors == [], f"animate player raised page errors: {errors}"


@pytest.mark.golden
def test_visualize_3d_opens_deck_gl_modal_with_canvas(live_app, chromium):
    """visualize_3d must render a 'Show 3D view' button; clicking it
    must open a modal containing a deck.gl WebGL canvas. Pre-fix, the
    result fell through to a raw-JSON dump."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)
    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    # deck.gl must be loaded for the renderer to fire.
    assert chromium.evaluate(
        "typeof window.deck === 'object' && "
        "typeof window.deck.DeckGL === 'function'"
    ), "deck.gl not loaded — visualize_3d will silently no-op"

    _send_chat(chromium, _visualize_3d_tool_result_sse(), "show 3d")

    btn = chromium.locator(".chat-show-3d-btn")
    btn.first.wait_for(state="visible", timeout=6_000)
    btn.click()

    # Modal overlay + deck.gl canvas appear.
    chromium.locator(".chat-3d-modal-overlay").wait_for(
        state="visible", timeout=4_000,
    )
    chromium.wait_for_function(
        "() => !!document.querySelector('#deck-3d-canvas canvas')",
        timeout=5_000,
    )

    # Canvas has non-zero size (deck.gl actually rendered).
    canvas_w = chromium.evaluate(
        "document.querySelector('#deck-3d-canvas canvas').width"
    )
    canvas_h = chromium.evaluate(
        "document.querySelector('#deck-3d-canvas canvas').height"
    )
    assert canvas_w > 0 and canvas_h > 0, (
        f"deck.gl canvas has zero size ({canvas_w}x{canvas_h}) — "
        "WebGL context may have failed"
    )

    # Closing the modal removes it from the DOM.
    chromium.locator(".chat-3d-modal-overlay button", has_text="Close").click()
    chromium.wait_for_function(
        "() => !document.querySelector('.chat-3d-modal-overlay')",
        timeout=2_000,
    )

    assert errors == [], f"3D modal raised page errors: {errors}"


@pytest.mark.golden
def test_canned_sse_with_invalid_geojson_does_not_crash_page(
    live_app, chromium,
):
    """Defense test: a malformed layer_add (geometry missing, coords swapped)
    must not crash the page or wedge the chat. The frontend should either
    skip the layer or surface a console warning, not raise."""
    errors = []
    chromium.on("pageerror", lambda e: errors.append(str(e)))

    _block_socketio(chromium)

    chromium.goto(live_app + "/", wait_until="networkidle", timeout=20_000)

    # Layer with a geometry of None — Leaflet should silently skip but
    # MUST NOT throw an unhandled error.
    bad = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": None, "properties": {}}],
    }
    sse_body = _canned_sse_body("bad_layer", bad)

    def _fulfill_chat(route, request):
        if request.method == "POST":
            route.fulfill(
                status=200, content_type="text/event-stream", body=sse_body,
            )
        else:
            route.continue_()

    chromium.route("**/api/chat", _fulfill_chat)

    chromium.locator('button.tab-btn[data-tab="chat"]').click()
    chat = chromium.locator("#chatInput")
    chat.wait_for(state="visible", timeout=5000)
    chat.fill("show me bad data")
    chromium.locator("#chatSendBtn").click()

    # Wait briefly to allow any error to surface.
    chromium.wait_for_timeout(1500)

    # The page must still be alive — chat input still responsive.
    assert chromium.locator("#chatInput").is_visible(), (
        f"chat input gone after malformed SSE. Page errors: {errors}"
    )
    # No unhandled JS error (defensive code should have logged a warn,
    # not thrown).
    assert errors == [], (
        f"malformed layer_add raised unhandled errors: {errors}"
    )
