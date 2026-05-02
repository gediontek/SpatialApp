# SpatialApp — Execution plan

How to move from current state (matrix mostly gapped) to covered, in
prioritized order per
[`framework/08-rollout-and-governance.md`](../../../cognitive-skill-agent/eval-framework/docs/08-rollout-and-governance.md).

## Phase 0 — Bootstrap (today)

- [x] `work_plan/framework/` written.
- [x] `work_plan/spatialapp/01-profile.md` drafted.
- [x] `work_plan/spatialapp/02-capability-catalog.md` drafted (rows for top capabilities; rest stubbed).
- [x] `work_plan/spatialapp/03-domain-criteria.md` written (12 GIS-C, 5 LLM-C, 4 UX-C).
- [x] `work_plan/spatialapp/04-coverage-matrix.md` filled with current state.
- [x] `work_plan/spatialapp/05-workflow-inventory.md` (38 workflows).
- [ ] Build `tests/workflows/` skeleton + pytest markers per [`framework/07`](../../../cognitive-skill-agent/eval-framework/docs/07-tooling.md).
- [ ] Build `tests/api/`, `tests/integration/`, `tests/property/`, `tests/visual/`, `tests/security/`, `tests/chaos/`, `tests/load/` skeletons.
- [ ] Wire CI lanes (one job per `tests/<folder>/`).
- [ ] Auto-extractor stub (`scripts/extract_catalog.py`) — reads routes / handlers / UI handlers and emits a draft.

## Phase 1 — P0 cells (week 1)

Order matters: every workflow in the inventory before any unit test.

### Day 1 — Q1 / M5 happy paths (R5.1)

- [ ] `tests/workflows/test_manual_tab.py` covering W01–W06.
- [ ] `tests/workflows/test_auto_tab.py` covering W10–W14.
- [ ] `tests/workflows/test_chat_tab.py` covering W20–W30.
- [ ] `tests/workflows/test_layer_panel.py` covering W40–W44.
- [ ] `tests/workflows/test_routing.py` covering routing-quick-action subset of W24–W25.
- [ ] `tests/workflows/test_health.py` covering W90–W92.

Pass criteria: every workflow asserts on **what the user sees**
(rendered polygons / lines / markers / file downloads / toast text /
`LayerManager.getLayerNames()`) — not on response JSON.

### Day 2 — Q7 / M3 (R3.3 + R3.4)

- [ ] `tests/api/test_csrf_matrix.py` — every state-mutating route returns 403 without a CSRF token.
- [ ] `tests/api/test_auth_matrix.py` — every authenticated route returns 401/403 under missing/wrong token.

### Day 3 — Q3 / M5 (R5.3) — error recovery for top 5 workflows

- [ ] Playwright `route()` interception that mocks Overpass / Nominatim / Valhalla / Gemini failures.
- [ ] One error-recovery test per: W01, W10, W20, W24, W90.
- [ ] Assertion: error toast names the failed service AND a retry path.

### Day 4 — Token-budget hygiene (LLM-C5, today's bug)

- [ ] `tests/workflows/test_token_budget.py::test_one_query_under_budget` — drives the chat path, asserts `MAX_TOKENS_PER_SESSION` not exceeded by any single query.
- [ ] Backend mitigation: trim large geojson tool_results before re-feeding to the LLM (separate PR; covered by Q1 tests).

### Day 5 — Wire the matrix coverage badge

- [ ] `scripts/coverage_matrix.py` — reads pytest markers + `02-capability-catalog.md` + `test-inventory.yaml`; emits the numbers in `04-coverage-matrix.md`.
- [ ] Post coverage delta on every PR.

End of Phase 1: every P0 cell shows `covered`. CI red on regression.

## Phase 2 — P1 cells (weeks 2–3)

### Q1 / M3 (R3.1 + R3.2 + R3.6)

- [ ] One `tests/api/test_<route>.py` per blueprint; happy + bad-input matrix.
- [ ] Wire `geojson` schema validator — every route returning GeoJSON validates with `geojson-validation` or `jsonschema` against `tests/schemas/geojson.schema.json`.

### Q1 / M2 — purge duplicate / orphan tests

- [ ] Audit current 1,400 tests against `test-inventory.yaml`.
- [ ] Tag orphans (tests not derived from any rule).
- [ ] Delete or remap each. Target: zero orphans, ~500 unit tests.

### Q1 / M4 — real-dependency integration (R4.1)

- [ ] `tests/integration/test_overpass_canary.py` — one query per top OSM `feature_type`; asserts `_osm_to_geojson` parses both formats; runs nightly, not on PR.
- [ ] `tests/integration/test_valhalla_canary.py` — one route per supported mode.
- [ ] `tests/integration/test_rasterio_sample.py` — sample raster open + read at known coord.

### Q2 / M3 — completeness

- [ ] Cross-check: every entry in `02-capability-catalog.md` resolves to at least one route or handler. Test fails if a capability has no source mapping.

## Phase 3 — P2 cells (weeks 3–4)

### Q1 / M6 — property tests for GIS-C and LLM-C criteria (R6.2)

- [ ] `tests/property/test_geometry_invariants.py` — Hypothesis generators for points, polygons, multipolygons; assert GIS-C1, C2, C4, C5, C10.
- [ ] `tests/property/test_metric_invariants.py` — buffer, route distance, area conversions (GIS-C6).
- [ ] `tests/property/test_round_trip.py` — every (import, export) pair is a round-trip (GIS-C12).

### Q5 / M5 — mobile viewport (R5.4)

- [ ] Re-run top-10 workflow tests at 375px viewport.

### Q6 / M5 — UX-C assertions inside workflow tests (R5.1 second-pass)

- [ ] Each workflow test gains a `usability` assertion block: error toasts name service (UX-C1), no hung spinners (UX-C2), map fits to bounds (UX-C3).

### Q5 / M5 — visual regression (T8 / R8)

- [ ] Baseline screenshots for the success state of W01, W10, W20, W24, W60.

### Q8 / M3 + M5 — observability (R10)

- [ ] `/metrics` exposure verified.
- [ ] Dashboard live-update verified.

## Phase 4 — P3 / P4 cells (continuous)

### Q3 / M7 — chaos (R7.2 / T10)

- [ ] One chaos scenario per external dependency (Nominatim, Overpass, Valhalla, LLM provider, DB).
- [ ] Run nightly.

### Q4 / M7 — load (R7.1 / T9)

- [ ] Locust profile for: `fetch_osm`, `chat`, `route`, `classify_area`.
- [ ] Asserts p95 / p99 / error-rate / memory budgets.
- [ ] Run weekly + on release.

### Q7 / M5 + M7 — security (R9 / T11)

- [ ] Overpass-QL injection attempts on `feature_type`, `osm_key`, `osm_value`.
- [ ] XSS attempts on layer names, chat messages, annotation labels.
- [ ] Auth bypass attempts: try to GET another user's session.

## Definition of done for the framework rollout

- All 38 workflows in [`05-workflow-inventory.md`](05-workflow-inventory.md) have a committed Playwright test.
- Coverage badge ≥ 80% (covered cells / required cells).
- Zero orphan tests in the suite.
- Auto-extractor runs in CI; drift > 5 capabilities opens an audit ticket.
- Every external dependency has a chaos test in `tests/chaos/`.
- A new contributor can run `pytest tests/workflows/` and see the app's full user surface validated in a real browser within 5 minutes.
