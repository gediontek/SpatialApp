# SpatialApp — Workflow inventory

Source list for **M5 / Q1** (workflow tests). Every entry must produce
at least one Playwright test in `tests/workflows/`. Driven by user
clicks; assertions are on **what the user sees**, not on response JSON.

Last refreshed: 2026-05-02. Drift checked by re-running the UI-handler
grep in [`01-profile.md`](01-profile.md) "Profile drift checks".

## Manual tab

| ID | Workflow | Trigger | Capability | Expected user-visible result | Priority |
|---|---|---|---|---|---|
| W01 | Fetch OSM features (building / forest / water / road / amenity / cafe / etc.) | type category, pick `#osm_feature`, click `#fetchOsmBtn` | `fetch_osm` (route `/fetch_osm_data`) | polygons / lines / markers render in the overlay pane; layer appears in `LayerManager.getLayerNames()`; success toast | **P0** |
| W02 | Draw polygon / rectangle / marker (Leaflet.draw) | toolbar | `add_annotation` | annotation row appears in table; counts increment | P1 |
| W03 | Auto-classify a drawn polygon | `#auto-classify-drawn` | `classify_landcover` | classified polygon styled by category | P1 |
| W04 | Export annotations (GeoJSON / GeoPackage) | `#exportGeoJsonBtn` / `#exportGeoPackageBtn` | `export_annotations` | file downloads; valid content; round-trip imports cleanly | P1 |
| W05 | Clear classified data | `#clearClassifiedBtn` | (clear) | table empties; layer removed from map | P2 |
| W06 | Upload an image / shapefile / file | `#uploadInput` | `/upload` | file processed; toast acknowledges | P2 |

## Auto tab

| ID | Workflow | Trigger | Capability | Expected user-visible result | Priority |
|---|---|---|---|---|---|
| W10 | Pan to location | type city, `#panToLocationBtn` | `geocode` (route `/api/geocode`) | map recenters; success toast | **P0** |
| W11 | Auto-classify area (city or current extent) | `#autoClassifyBtn` with classes selected | `classify_area` (autolabel) | classified layer renders with category colors; legend appears | P1 |
| W12 | Use Current Extent toggle | checkbox | (modifier) | classification uses bbox, not city | P2 |
| W13 | Export Classified | `#exportClassifiedBtn` | export | file downloads | P1 |
| W14 | Clear Classified | `#clearClassifiedBtn` | clear | resets state | P2 |

## Chat tab

| ID | Workflow | Trigger | Capability | Expected user-visible result | Priority |
|---|---|---|---|---|---|
| W20 | Free-form NL query: "show me X in Y" | type into `#chatInput`, click `#chatSendBtn` | `ChatSession.process_message` → tool dispatch | matching layer / chart / route renders; assistant message under token budget | **P0** |
| W21 | Quick-action: Buildings | `.quick-action-btn[data-msg="Fetch buildings in this map area"]` | `fetch_osm` | polygons render in current bounds | P0 |
| W22 | Quick-action: Classify | classify quick action | `classify_area` or `classify_landcover` | classified layer renders | P1 |
| W23 | Quick-action: Summarize | summarize quick action | aggregate / `describe_layer` | message with counts | P1 |
| W24 | Quick-action: Route | route quick action | `find_route` | polyline rendered; distance displayed | P0 |
| W25 | Quick-action: Reachable | isochrone quick action | `isochrone` | polygon rendered | P1 |
| W26 | Quick-action: Export | export quick action | `export_*` | file downloads | P1 |
| W27 | Multi-step chain | "buffer parks by 500m and show restaurants nearby" | buffer → search_nearby chain | both layers render; restaurants are inside the buffer | P0 |
| W28 | Plan mode (preview before execute) | toggle plan mode → submit | `validate_plan_chain` + executor | JSON plan visible; click approve → executes | P1 |
| W29 | Stop streaming mid-response | click stop | abort | request cancels; UI re-enables; no half-rendered layer | P2 |
| W30 | Token-budget exhaustion message | many turns in one session | `MAX_TOKENS_PER_SESSION` | clear "session exhausted" message; offer new session | P0 (LLM-C5) |

## Layer panel (always visible)

| ID | Workflow | Trigger | Capability | Expected user-visible result | Priority |
|---|---|---|---|---|---|
| W40 | Toggle layer visibility | layer-row checkbox | `show_layer` / `hide_layer` | layer disappears / reappears | P0 |
| W41 | Fit map to layer | click layer name | (fit_bounds) | viewport snaps to layer extent | P0 |
| W42 | Delete layer | delete control | `remove_layer` | layer gone from server + map | P1 |
| W43 | Re-style layer | style control | `style_layer` | color / weight reflected | P1 |
| W44 | Many layers (>50) | open many → eviction | `_evict_layers_if_needed` | older layers evicted; UI reflects | P2 |

## Routing / network analysis (chat-driven, no separate UI surface)

(Covered by W24, W25 above. Listed here so reviewers see they map
to specific catalog entries.)

## Raster (Plan 08)

| ID | Workflow | Trigger | Capability | Expected user-visible result | Priority |
|---|---|---|---|---|---|
| W50 | Load sample raster | "show elevation in <area>" via chat | `raster_info`, `raster_classify` | raster derivative renders or metadata shown | P1 |
| W51 | Pick a value at a point | "elevation at lat,lon" | `raster_value` | numeric value in chat reply | P1 |
| W52 | Slope / aspect / hillshade | "slope at <area>" | `raster_statistics` | derivative layer renders | P2 |

## Visualization (Plan 11)

| ID | Workflow | Trigger | Capability | Expected user-visible result | Priority |
|---|---|---|---|---|---|
| W60 | Choropleth | "color by population density" | `choropleth_map` | graduated colors visible; legend rendered | P1 |
| W61 | Chart | "pie chart of building types" | `chart` | Chart.js panel opens with bars / pie | P1 |
| W62 | Animate layer | "animate permits 2020-2024" | `animate_layer` | controls appear; features cycle through time | P2 |
| W63 | 3D buildings | "show buildings in 3D" | `visualize_3d` | extruded polygons via OSMBuildings | P2 |

## Auto-label (Plan 12)

| ID | Workflow | Trigger | Capability | Priority |
|---|---|---|---|---|
| W70 | classify_area for a small bbox | chat | `classify_area` | P1 |
| W71 | predict_labels on existing layer | chat | `predict_labels` | P1 |
| W72 | evaluate_classifier on labeled layer | chat | `evaluate_classifier` | P2 |

## Collaboration (Plan 09)

| ID | Workflow | Trigger | Capability | Priority |
|---|---|---|---|---|
| W80 | Two clients join the same session | open same `?collab=` URL in two contexts | `join_collab` | P1 |
| W81 | Layer added by A appears for B | A clicks fetch | `layer_add` propagation | P1 |
| W82 | Layer removed by A drops for B | A removes | `layer_remove` | P1 |
| W83 | Cursor of A visible to B | mousemove | `cursor_move` (throttled) | P2 |
| W84 | A leaves; B sees user_left | tab close | disconnect | P2 |

## Production / health (Plan 13)

| ID | Workflow | Trigger | Capability | Priority |
|---|---|---|---|---|
| W90 | Hit `/api/health/ready` with no LLM key | curl | health | P0 |
| W91 | CSP doesn't break the page | full workflow | CSP | P0 |
| W92 | Dashboard renders + updates live | navigate to `/dashboard` | dashboard | P2 |

## Excluded UI elements

| Element | Reason |
|---|---|
| Tab buttons (Manual / Auto / Chat) | UI-only; no server effect. |
| Layer panel collapse on mobile | UI-only. |
| Quick-action buttons that simply prefill `#chatInput` | redundant with W20. |

---

## Total workflows: 38

Each row above maps to **exactly one Playwright test** in
`tests/workflows/`. The current `/tmp/*.py` smoke scripts cover W01,
W10, W20, W21, W24 only (5 of 38).
