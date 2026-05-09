# tests/golden/ — user-experience workflow eval

These tests mimic the user's actual experience: type a NL message, get
features rendered on the map. They sit between the unit suite (which
verifies handler internals) and `tests/test_golden_path.py` (which drives
a real browser, gated for live runs).

## Why this exists

The unit suite is large (1,500+) but all green doesn't mean the user-
visible experience works. A 2026-05 manual check turned up basic OSM
queries that returned features no one could see on the map — the kind
of regression a unit test won't catch because it doesn't exercise the
chat→tool→SSE→layer_store contract end to end.

These workflow tests close that gap with mocked LLM + mocked Overpass,
so they're CI-safe and fast (~13s).

## Run

```bash
make golden        # this suite only
make eval          # this suite + harness + tool-selection eval
```

## What's covered

**Server-side workflow** (`test_user_workflows.py`, in-process Flask client + mocked LLM/Overpass):

| # | Scenario | Bug class it would catch |
|---|----------|--------------------------|
| W1 | `fetch_osm` single tool | Layer never reaches `state.layer_store` |
| W2 | geocode → fetch_osm chain | Bbox lost between two-tool calls |
| W3 | Empty Overpass result | Phantom features fabricated by converter |
| W4 | Overpass timeout | Partial layer leaked from failed request |
| W5 | 3-polygon realistic payload | Some features dropped silently |
| W6 | Coordinate order invariant | `[lat,lng]` vs `[lng,lat]` swap |

**Browser-render** (`test_browser_render.py`, real Chromium + Playwright route-fulfilled SSE):

| # | Scenario | Bug class it would catch |
|---|----------|--------------------------|
| B1 | Canned `layer_add` → polygon paints in Leaflet overlay pane | Frontend layer wiring (LayerManager, addTo(map)) silently broken |
| B2 | Chunked layer (`layer_init` + N×`layer_chunk`) paints all features | Big-OSM-query path silently fails (separate frontend handler from layer_add) |
| B3 | `map_command pan_and_zoom` actually moves the map | "Zoom to X" workflow regresses; map-command coord swap |
| B4 | `layer_command remove` unmounts the layer + clears polygons | Tool reports "removed" but polygon stays painted |
| B5 | Two `layer_add` events in one turn → both render independently | Second layer overwrites or silently drops the first |
| B6 | `layer_style` event flips polygon stroke color on existing layer | Style changes silently fail; user sees wrong color |
| B7 | Tool failure surfaces in chat UI; chat input stays usable | Silent tool failure — user sees a dead chat with no explanation |
| B8 | `highlight` event recolors only the matching feature(s) | Highlight predicate matches everything or nothing |
| B9 | Quick-action button click fills input + dispatches /api/chat | Convenience-button wiring regresses |
| B10 | Plan mode renders `<ol>` of steps + Execute Plan / Cancel buttons | Plan mode silently degrades to a text message |
| B11 | Stop button mid-stream aborts fetch + re-enables input | User wedged with frozen 'Stop' button (M2 audit) |
| B12 | Second chat aborts the first via AbortController | Ghost-layer race when user retries impatiently (M2 audit) |
| B13 | Malformed `layer_add` (geometry: null) does not crash chat | Defensive frontend regression — page wedges on bad data |
| B14 | `heatmap` event creates a Leaflet.heat canvas on the overlay pane | Leaflet.heat removed from `index.html` → all heatmap tools silently no-op |
| B15 | `chart` tool result renders an actual Chart.js chart in the chat | Chart.js removed → chart results fall back to raw-JSON dumps |
| B16 | `animate` tool result does not crash the page (resilience) | Half-built feature regression — should fail loud when a real player UI lands |
| B17 | `visualize_3d` tool result does not crash the page (resilience) | Same — half-built 3D feature should fail loud when a real renderer lands |
| B18 | Wide-area many-polygon layer renders as cluster bubbles at low zoom | "Show hospitals in Chicago" looks blank because polygons are sub-pixel |
| B19 | Layers ≥ 500 features emit a chat hint about zoom-in | User assumes blank map = broken when actually data spans wide area |

**Frontend auth** (`test_frontend_auth.py`, real Chromium + Playwright route-captured headers):

| # | Scenario | Bug class it would catch |
|---|----------|--------------------------|
| A1 | CSRF token from `<meta>` attached on POST/PUT/DELETE | CSRF protection silently bypassed for state-mutating fetch calls |
| A2 | CSRF token NOT attached on GET/HEAD/OPTIONS | False-positive CSRF traffic / log noise |
| A3 | Bearer token from `localStorage.api_token` attached on every call | Authenticated calls regress to anonymous |
| A4 | No `Authorization` header when localStorage is empty | "Bearer " (empty) masking the unauthenticated 401 observable |
| A5 | `window.SpatialAuth` helpers exposed (`authedFetch`, `getCsrfToken`, etc.) | H1 centralization broken; main/chat/layers fall back to bare fetch |
| A6 | jQuery `$.ajax` beforeSend wires same CSRF + Bearer headers | Legacy `$.ajax` callers silently lose auth (audit H1 parity gap) |
| A7 | `auth.js` loads BEFORE `main.js` / `chat.js` / `layers.js` | Init-time race: dependent scripts can't see `window.authedFetch` |
| A2-corollary | Caller-supplied Authorization is preserved (not overwritten) | Future admin-on-behalf tooling silently downgraded to localStorage user |

The browser tests use Playwright's `page.route()` to fulfill the
`/api/chat` POST with canned SSE bytes; no live LLM/Overpass keys
needed. Socket.IO is intentionally blocked at the route layer so the
chat falls back to the SSE transport (the WebSocket flag is closure-
private and can't be flipped from outside without this trick).

## How to add a scenario

```python
def test_my_workflow(
    self, golden_client, scripted_llm, mock_overpass,
    tool_use, final_text,
):
    scripted_llm([
        tool_use("fetch_osm", {...}),     # what the LLM "would" emit
        final_text("done"),
    ])
    mock_overpass({
        "overpass": {"elements": [...]},  # what Overpass "would" return
        "nominatim": [...],               # optional, if geocode fires
    })
    status, events = _post_chat(golden_client, "user query here")
    # ...assertions on layer_add events...
```

`scripted_llm` patches `nl_gis.chat.create_provider`; `mock_overpass`
patches `nl_gis.handlers.navigation.requests.get`. Neither touches
production code — they're test-only seams.

## What's NOT covered (use other tools)

- Frontend rendering (does Leaflet actually paint the polygon?)
  → `tests/test_golden_path.py` (Playwright, live mode for the paint check).
- LLM tool-selection accuracy on the 50-query corpus
  → `tests/eval/run_eval.py --mock`.
- Security / isolation contracts
  → `tests/harness/`.
