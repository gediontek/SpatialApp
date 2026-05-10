# SpatialApp v2 — Input package for next external audit

**Status:** **READY for external audit submission.** 17 cycles closed; CI green; audit-4 returned **86/100** (1 High + 3 Medium + 1 Low — N26-N30, all closed in Cycle 17).
**Last updated:** 2026-05-10 (post Cycle 17 — N26-N30 from external audit-4 closed)
**Updated by:** autonomous /auto-solve cycle
**Repo state:** branch `main`, working tree clean, synced with origin. **Next external auditor: new finding IDs MUST start at N31 — IDs N1-N30 are taken** (N25 was consumed by the auditor as already-fixed at the time of audit-4).
**Verified at last update**: `make eval` green (6 workflow + 19 browser + 8 frontend-auth + 65 harness + 30 tool-selection in `--ci` strict mode); CI-mirror `pytest tests/ -k "not e2e"` = **1,577 passed / 10 skipped / 0 failed** (~95s).
**Audit history**: audit-1 (pre-cycles): 31/100 → audit-2 (post Cycle 13): 81/100 → audit-3 (post Cycle 14): 93/100 → audit-4 (post Cycles 15-16): **86/100** (5 fresh findings N26-N30, all closed in Cycle 17). Audit-5 awaits.
**Audit-4 specifics**: N26 was a real user-facing break (raster upload returned a 404 URL); N27 was an auth break (annotation export buttons couldn't attach Bearer); N29 was a security gap (readiness could go green while paid chat was publicly open). Score dropped from 93 → 86 because audit-4 surfaced bugs the prior audits missed — exactly what fresh-eyes audits exist for.
**Companion docs:**
- [`07-v2-audit-findings.md`](07-v2-audit-findings.md) — original external audit (12 findings)
- [`08-v2-bugfree-plan.md`](08-v2-bugfree-plan.md) — Acceptance-First Hardening plan (v1.2)
- [`09-external-audit-prompts.md`](09-external-audit-prompts.md) — six reviewer prompts
- [`10-pr0-csrf-spike-report.md`](10-pr0-csrf-spike-report.md) — first acceptance evidence (C2)
- [`11-all-fixes-applied-report.md`](11-all-fixes-applied-report.md) — per-finding closure for the original 12

## 1. What changed since the last audit

### 1.1 Findings closed

| ID | Severity | One-line | Commit |
|---|---|---|---|
| C1 | Critical | RCE sandbox: AST allowlist + RLIMIT (replaces substring blacklist) | `ed21e66` |
| C2 | Critical | CSRF exemptions: pass view function objects (not endpoint strings) | `ed21e66` |
| C3 | Critical | Chat-session restore honors saved owner; mismatch → 403 | `ed21e66` |
| C4 | Critical | Multi-user layer + annotation isolation via `state.layer_owners` + `properties.owner_user_id` | `ed21e66` |
| H1 | High | Centralized `static/js/auth.js` `authedFetch` + `authedAjaxBeforeSend` | `ed21e66` |
| H2 | High | `nl_gis/chat.py:316` explicit None check (preserve shared layer_store identity) | `ed21e66` |
| H3 | High | `Config.validate()` re-raises in production (FLASK_DEBUG false + not testing) | `ed21e66` |
| H4 | High | Auto-classify drops `with` ThreadPoolExecutor context; `executor.shutdown(wait=False)` + `future.cancel()` | `ed21e66` |
| M1 | Medium | layers.js `removeLayer` uses `authedFetch` (folded into H1) | `ed21e66` |
| M2 | Medium | Stop button aborts SSE + plan-execute + emits `chat_abort` for WS | `ed21e66` |
| M3 | Medium | `tests/fixtures/raster/geog_wgs84.tif` (611-byte WGS84 GeoTIFF) + conftest `RASTER_DIR` override | `ed21e66` |
| M4 | Medium | OpenAI `_convert_messages` emits text alongside tool messages | `ed21e66` |
| N1 | Medium | Test env contamination: clear all 4 LLM provider keys (centralized in `tests/conftest.py`) | `ed21e66` + `57e0457` |
| N2 | **Critical** | WS `layer_remove` ownership check (was C4 bypass via collab path) | `57e0457` |
| N3 | High | WS chat `layer_add` populates `state.layer_owners` (was layer-invisible to owner) | `57e0457` |
| N4 | High | Server-side `chat_abort` WS handler (frontend M2 was emitting into the void) | `57e0457` |
| N6 | **Critical** | Collab REST endpoints (`info`/`resume`/`export`) require `@require_api_token` + owner check | `fe94bda` |
| N7 | Medium | Raster upload per-user namespace under `<UPLOAD_FOLDER>/<user_id>/` | `862182b` |
| N8 | Medium | Shapefile zip-bomb / zip-slip guard (1k entries / 100MB per / 500MB total / path reject) | `862182b` |
| N9 | Medium | `add_osm_annotations` cap at 1k features per request | `d68d5e4` |
| N10 | Medium | `/api/health` leaked `str(e)` from DB checks + global layer/session counts → leak-free + per-user filtered | `8098718` |
| N11 | Medium | `/api/register` had no inbound rate limit → per-IP sliding window (5/hour); `PerKeyRateLimiter` primitive added | `7a92c38` |
| N12 | Medium | `/api/chat`, `/api/chat/execute-plan`, WS `chat_message` had no per-user throttle → 60 msg/min shared bucket across all 3 transports | `f702857` + `9f5bfbd` |
| N13 | Low (pre-emptive) | `LLMCache.make_key` did not include `user_id` → cross-user cache leak risk if/when wired into `nl_gis/chat.py` | `6a78e74` |
| N14 | Medium | WS `layer_style` accepted unbounded `style` dict + had no throttle → broadcast amplification DoS; cap 256 char name, 8 KB style, 10 ev/sec/user/session | `8d72500` |
| N15 | — | `/api/usage` cross-user check — verified clean (already gates by `entry["user_id"]`) | (no fix) |
| N16 | Medium | WS `chat_message` `context` dict was unbounded → amplified LLM cost + log bloat; validate session_id + active_layers cap 256 + total ≤ 16 KB | `737c48d` |
| N17 | Low | `/.well-known/security.txt` (RFC 9116) added with `SECURITY_CONTACT` env var | `737c48d` |
| N18 | High | C1 sandbox child env stripped HOME/PYTHONPATH so harshly that macOS user-site / non-`.venv` layouts could not import shapely+numpy → switch to copy-and-deny env (still strips secrets); RCE harness gains EXECUTE_CORPUS that actually runs each allowed snippet | `336a9ed` |

**Total: 29 findings closed** (12 audit + 17 self-discovered post-fix; N15 was a clean check).

### 1.2 Test infrastructure added

- `tests/harness/` directory — opt-in adversarial suite (`pytest -m harness`), **51 passed / 1 skipped at draft time**:
  - `test_csrf_enforcement.py` — 15-route property test, distinguishes CSRF rejection (sentinel HTTP 419) from other 400s
  - `test_rce_sandbox.py` — 14-payload deny corpus + 7-payload allow corpus + **5 EXECUTE_CORPUS tests** (added after N18; previous AST-only coverage missed an env regression)
  - `test_multi_user_isolation.py` — 6 scenario tests (layer/annotation/chat-session, 2-user fixture)
  - `test_secret_validation.py` — 3 cases on `Config.validate()`
  - `test_layer_store_identity.py` — 4 ChatSession identity invariants
  - `test_provider_mixed_content.py` — 3 OpenAI converter cases
  - `test_env_isolation.py` — 4 LLM key guards
  - `test_register_rate_limit.py` — 4 cases for N11 (per-key limiter primitive + endpoint enforcement + per-IP isolation)
- `tests/conftest.py` — root-level: clears LLM keys + sets `RASTER_DIR` to fixture dir before any `Config` import.
- `tests/fixtures/raster/geog_wgs84.tif` — committed 611-byte WGS84 raster.

### 1.3 Test deltas

| | Before (pre-session) | After (current) |
|---|---|---|
| Full suite (`pytest -q --ignore=tests/e2e`) | 1,437 passed / 31 skipped | **1,526 passed / 10 skipped** (verified 2026-05-03 after gap close-out) |
| Harness suite (`pytest tests/harness/`) | 0 | **65 passed / 3 skipped** (3 intentional: 1 RCE env-leak placeholder, 2 collab DB API not in SQLite) |
| Hypothesis state machine | none | 1 test, 50 random scenarios × 20 steps each (~1,000 ops/run) |
| CI gates | tests only | tests + **harness gate** + **pip-audit (CVE sweep)** |
| Pre-commit | none | **`pre-commit install`** runs harness on every commit |
| Live smoke test | none | **2026-05-03**: golden path verified end-to-end ([`13-smoke-test-2026-05-03.md`](13-smoke-test-2026-05-03.md)) |
| Net regressions | — | **0** |

## 2. What the auditor should focus on

The previous audit explicitly self-reported ~85% surface coverage. The 29 closed findings teach what classes of bug to expect; this section names the surface still under-audited.

### 2.1 High-leverage areas for the next audit

1. **LLM tool-call arg validation.** Tool dispatch in `nl_gis/chat.py` accepts arg dicts from the model. If args reach SQL (database tools), file paths (raster/import tools), or shell (none currently), prompt-injection becomes RCE-adjacent. The defense surface has not been audited.
2. **Provider symmetry.** Audit found M4 in OpenAI converter only. Anthropic + Gemini converters have not been audited for symmetric mixed-content / dropped-block bugs. (Cycle 1 of this session is starting here — see §3 for the live state.)
3. **Database concurrency under load.** SQLite WAL with concurrent writes from Flask + WebSocket background tasks; `_migrate_add_column` runs at every startup; multi-process gunicorn would have init races. No load test exists.
4. **Annotation backup race + leakage.** `backup_annotations()` in `blueprints/annotations.py` writes timestamped `annotations_backup_*.geojson` to `LABELS_FOLDER` with no per-user namespacing. C4-class.
5. **Error handlers info-leak.** `app.py:200-206` 500 handler returns generic message but logs `str(e)` — verify no stack trace / path leaks in 4xx/5xx body or set-cookie.
6. **Frontend Playwright e2e.** Backend property tests cover transport contracts; the Playwright harness for H1+M1+M2 (`test_frontend_auth.py`) is still TODO.
7. **Raster upload size limit.** `secure_filename` blocks path traversal but no MAX_RASTER_BYTES guard — a 50MB Flask MAX_CONTENT_LENGTH applies, but a craftily-compressed GeoTIFF could OOM rasterio on read.
8. **Public `/api/geocode` and `/api/category-colors`** — no auth. Verify they don't enable enumeration / abuse.
9. **`/metrics` (Prometheus)** — unauthenticated by intent. Verify it doesn't leak per-user labels or secrets.
10. **WebSocket `connect` flow** — auth happens in `handle_connect` via `request.args.get('token')`; verify the per-user vs shared-token branches don't allow privilege escalation.

### 2.2 Areas the auditor can SKIP (already covered by harness)

- CSRF enforcement on the 15 state-mutating routes (covered by `test_csrf_enforcement.py`)
- 14 known sandbox-escape payloads (covered by `test_rce_sandbox.py`)
- Cross-user reads/writes on layers + annotations + chat sessions via REST (covered by `test_multi_user_isolation.py`)
- The 7 specific contracts named in §1.1's harness column

### 2.3 Files most-changed since last audit (review priority)

| File | Lines changed | Why |
|---|---|---|
| `services/code_executor.py` | +180 / −80 (full rewrite) | C1 AST sandbox |
| `blueprints/websocket.py` | +85 | N2 + N3 + N4 + chat_abort plumbing |
| `blueprints/annotations.py` | +60 | C4 + N9 |
| `blueprints/layers.py` | +30 | C4 + N8 |
| `blueprints/chat.py` | +20 | C3 + 403 propagation |
| `blueprints/osm.py` | +25 | H4 + N7 |
| `blueprints/collab.py` | +30 | N6 |
| `nl_gis/llm_provider.py` | +15 | M4 |
| `app.py` | +30 / -20 | C2 + H3 |
| `state.py` | +5 | C4 (`layer_owners` map) |

## 3. Live state (this session)

(Updated each cycle as I find/fix more.)

### Cycle 0 — done
Completed the original 12 audit findings + 9 self-discovered (N1-N9). Repo on `main`, started this rolling work on top of those.

### Cycle 1 — done
- ✅ **Anthropic + Gemini provider symmetry of M4 — clean.** Anthropic uses native message format (no converter; passthrough). Gemini's `_convert_messages` already iterates ALL block types (text + tool_use + tool_result) and emits each as a part — so no symmetric drop bug exists. M4 was OpenAI-converter-specific.
- ✅ **LLM tool-arg validation — clean.** Tool dispatch surface checked. `params` from LLM tool-calls flow into typed reads (string layer names, float coordinates, validated paths via `_safe_raster_path`). No path traversal, no shell, no `eval`. SQL throughout is parameterized. Code execution goes through `validate_code()` AST whitelist.
- ✅ **Annotation backup leakage — filesystem-only.** `backup_annotations()` writes to `LABELS_FOLDER` which is NOT web-served. Backup files contain cross-user annotations (per-user filtering happens at READ, not WRITE). Risk surface: filesystem-level (operator/sysadmin) only. Captured in §2.1 as a known gap; not a runtime exposure.
- ✅ **Error-handler info-leak audit — 1 finding (N10), now closed.** `auth.py:182` was the only `str(e)` leak into a response body; fixed in commit `8098718`. No `traceback.format_exc()` calls anywhere. All other exception handlers log + return generic message.

### Cycle 2 — done
- ✅ N10: `/api/health` info-leak — fixed.
- ✅ N11: `/api/register` rate limit — fixed (5/hour per IP).
- ✅ N12: `/api/chat` + execute-plan + WS chat_message rate limit — fixed (60/min per user, shared across transports).
- ✅ Subprocess args validation in code_executor — already clean (AST allowlist + minimal env, no shell=True).
- ✅ CORS+credentials interaction — already clean (only same-origin gets CORS headers; no third-party origin trust).
- ⏭ Database concurrency — documented in §2.1 as known gap (multi-worker startup race on `_migrate_add_column`; not a runtime issue with single-worker dev).

### Cycle 3 — done
- ✅ `services/cache.py` — clean (key hashed; collisions rejected; no traversal).
- ✅ `services/llm_cache.py` — pre-emptive N13 fix; not wired yet.
- ✅ `services/database.py` SQL string-building — `_migrate_add_column` is the only `f""` SQL site and is gated by `_ALLOWED_TABLES`/`_ALLOWED_COLUMNS` whitelist. All other DB ops are parameterized. ✅
- ✅ `/api/dashboard` — already filtered per-user via `get_user_layers(user_id)` etc.; `tool_stats` falls back to `None` for anonymous (cross-user aggregate), which is acceptable when no token is configured. Documented for v2.2 if multi-tenant tightening is needed.
- ✅ N14: WS `layer_style` size + throttle — fixed.

### Cycle 4 — done
- ✅ N15: `/api/usage` cross-user — clean.
- ✅ N16: WS `chat_message` context cap — fixed.
- ✅ N17: `/.well-known/security.txt` — added.
- ⏭ WS `cursor_move` size limit — bounded inputs (lat/lon floats); spec-bounded; no fix needed.
- ⏭ DB concurrency / index races — single-worker dev safe; multi-worker production needs operational fix (gunicorn preload + once-only migration), not a code fix.
- ⏭ Dependency CVE sweep — operational, not code; recommend running `pip-audit` in CI.

### Auditor-1 follow-up (2026-05-03) — done
External reviewer caught 5 issues in the doc + a real C1 regression. All addressed:
- ✅ N18 (the regression) — see §1.1.
- ✅ Stale `<this commit>` placeholders in N16/N17 → real shas (`737c48d`).
- ✅ "next IDs start at N10" → corrected to N18 in header.
- ✅ "44 harness tests" → corrected to 65; `test_register_rate_limit.py` + `test_post_audit_findings.py` + `test_isolation_state_machine.py` added to §1.2 list.
- ✅ "21 closed findings" → corrected to 29 throughout (now 30 with new harness count).
- ✅ "1,503 passed / 7 skipped" → corrected to verified `1,526 passed / 10 skipped`.
- ✅ "7 unpushed commits" → corrected to 24 in header.

### Cycle 5 (deep-think (b)-path) — done
After self-evaluation said "I cannot self-grade to 100; here are the residual gaps," shipped all 5 enumerated gap items:
- ✅ Gap 1: Harness regression guards for 10 unguarded closed findings — `tests/harness/test_post_audit_findings.py` (13 tests covering N6, N7, N8, N9, N10, N12, N13, N14, N16, N17). Caught a real bug in my own N10 fix while writing tests: `api_health` did its own auth check without setting `g.user_id`, so the per-user filter saw 'anonymous' for everyone. Fixed inline.
- ✅ Gap 2: Hypothesis state machine for multi-user isolation — `tests/harness/test_isolation_state_machine.py`. 50 random scenarios × 20 steps each per CI run. First Hypothesis run found a bug in my test (read state AFTER mutating request); fixed and re-ran clean.
- ✅ Gap 3: CI harness gate + `pip-audit` job + pre-commit hook — `.github/workflows/ci.yml` + `.pre-commit-config.yaml`. Local pip-audit run: "No known vulnerabilities found."
- ✅ Gap 4: `09-external-audit-prompts.md` Prompt 3 N-seed: `N2` → `N19`.
- ✅ Gap 5: Live smoke test of `python3 app.py` golden path — full report at `13-smoke-test-2026-05-03.md`. All endpoints, headers, rate limits, and security.txt verified live.

### Outstanding (not in this round)
- Playwright frontend harness (`test_frontend_auth.py`) — needs Playwright chromium install and is the only Critical/High contract without a regression guard
- Replace placeholder `SECURITY_CONTACT` default with a real inbox before any deploy
- Push 24 commits to `origin/main` (deferred per "no auto-push" policy)

### Cycle 13 (real UIs for animate_layer + visualize_3d) — done
Cycle 11 added `animate_layer` and `visualize_3d` as resilience-only tests (`test_unrendered_tool_actions_degrade_gracefully`) — pinning that the page wouldn't crash when those tools returned data with no specialized renderer. The user pushed back: "they should have real UI. I don't understand the purpose of dumping JSON files in the chat." Built both:

- **`animate_layer` → time-step player** (`renderAnimatePlayer` in `static/js/chat.js`): slider + ▶ Play / ⟲ Reset buttons rendered under the tool step. Each step calls a new `LayerManager.filterToIndices(layerName, indices)` that zero-styles non-matching features (no expensive add/remove per frame). Honors `cumulative: true` (union steps 0..N) vs default (just step N). Slider is interactive; play auto-advances by `interval_ms` and stops at the last step. `LayerManager.clearFilter` restores the default style.
- **`visualize_3d` → deck.gl extrusion modal** (`renderShow3DButton` + `open3DModal` in `chat.js`): "🏙 Show 3D view" button under the tool step opens an 80vh / 90vw modal with a `deck.gl PolygonLayer({extruded: true})` painting the building footprints with `getElevation: f._height_m` and a height-binned color ramp (blue <20m → green <50m → yellow <100m → red ≥100m). Basemap is OSM raster via `deck.TileLayer` + `BitmapLayer`. Camera centers on the layer centroid at zoom 16 / pitch 50°; `controller: true` enables drag-to-rotate / scroll-to-zoom. Modal `Close` button calls `deckInstance.finalize()` to release the WebGL context.
- **`templates/index.html`**: added deck.gl 8.9.36 from unpkg (already in CSP via Leaflet).

**Replaced tests B16/B17** with real-UI assertions:
- `test_animate_layer_renders_player_and_filters_features` — asserts slider, play, reset buttons exist; clicking play advances the slider; clicking reset returns to step 0; button text flips to "Pause" while playing.
- `test_visualize_3d_opens_deck_gl_modal_with_canvas` — asserts deck.gl is loaded; clicking the 3D button opens the modal; a `<canvas>` with non-zero dimensions appears (proves the WebGL context initialized); Close removes the overlay.

**Visual evidence** (`tmp/smoke_screenshots/`):
- `deck_3d_modal.png` — real extruded buildings from a Loop OSM query, height-coded colors, controllable camera. Genuinely renders 52 buildings in 3D.
- `animate_player.png` — slider+play+reset rendered under the tool step (also visible in the test DOM assertion).

**Final coverage**: see header for current `make eval` and unit-suite numbers (kept fresh per-cycle).

### Cycle 17 (external audit-4 close-out — N26-N30) — done
External LLM audit-4 returned **86/100** (down from audit-3's 93/100) — a fresh-eyes pass that surfaced bugs prior audits missed. 5 findings, all closed:

- ✅ **N26 High — Raster upload returned a 404 URL.** `render_overlay()` wrote the generated PNG to `UPLOAD_FOLDER` root, but the `/static/uploads/<name>` serve route is scoped to the requesting user's subdir per N7 isolation. The browser's `L.imageOverlay(data.image_url, ...)` got a dead URL → broken image in the map. **Fix**: write the PNG into `os.path.dirname(image_path)` (the per-user TIFF dir) so the serve route resolves it. **Regression test**: `test_n26_upload_returns_image_url_that_actually_resolves` uploads the bundled fixture TIFF, asserts the returned `image_url` actually resolves to a valid PNG (magic bytes check). `blueprints/osm.py:108-115`.

- ✅ **N27 Medium — Annotation export broke under auth.** `static/js/main.js` used `window.location.href = '/export_annotations/<format>'`, which can't attach the Bearer header that `@require_api_token` requires. With `CHAT_API_TOKEN` set in prod, the export endpoint returned 401. **Fix**: switched to `authedFetch` + Blob download via temporary `<a>` element with `URL.createObjectURL` so the Bearer goes with the request. Filename derived from `Content-Disposition` header. `static/js/main.js:301-345`.

- ✅ **N28 Medium — Capability-claim honesty.** `export_layer` advertised Shapefile/GeoPackage but returned an error; `import_auto` advertised Shapefile detection but returned "not yet supported." False-positive capability gates: tool-selection eval still passed, but the actual operation didn't work. **Fix**: tool descriptions in `nl_gis/tools.py` now admit the chat tool is GeoJSON-only and direct callers to the `/export_annotations` HTTP endpoint for Shapefile/GeoPackage; `import_auto` description now explicitly notes that shapefile detection surfaces a clear error message rather than silently failing. (Implementing real shapefile import in the chat path is a feature for later, not an audit closure.)

- ✅ **N29 Medium — Readiness could go green while paid chat was publicly open.** `Config.validate()` blocked default SECRET_KEY but not missing CHAT_API_TOKEN; `require_api_token` falls through to "open access" when CHAT_API_TOKEN is empty; `/api/health/ready` checked only DB + LLM key. With LLM key configured and no chat token, an instance could be marked ready and start serving unauthenticated chat traffic that burns LLM tokens. **Fix**: `/api/health/ready` now requires `CHAT_API_TOKEN` to be set when `Config.DEBUG=False`. Dev mode is unaffected. **3 regression tests**: `test_n29_prod_mode_requires_chat_auth_token` (must 503 without token), `test_n29_prod_mode_with_chat_auth_token_returns_200`, `test_n29_debug_mode_does_not_require_chat_auth`. `blueprints/auth.py:258-298`.

- ✅ **N30 Low — Stale tool counts.** `docs/TOOL_CATALOG.md` said 64 tools, the system prompt in `nl_gis/chat.py` said 50, the actual registry returns 82. **Fix**: both updated to point at `get_tool_definitions()` as the runtime source of truth (registry-authoritative, doc-advisory). Section counts in TOOL_CATALOG.md noted as "may lag the runtime registry."

**Verification**: `make eval` green; full unit suite **1,577 passed / 10 skipped / 0 failed** (~95s, +4 tests from N26+N29 regression suite). Repo verified clean after Cycle 17.

### Cycle 15 (external audit-3 close-out — N24) — done
External LLM audit-3 returned 93/100 (up from 81/100 in audit-2). Only one finding:
- ✅ **N24 Low — audit handoff still contained stale reviewer instructions.** §4 said "new findings MUST start at N19" (old) and §5 still referenced "24+ unpushed commits" with the daa6b36 test counts. Header was already current (Cycle 14 fix), but the per-section handoff text wasn't updated. Refreshed §4 + §5: handoff text now says "new findings start at N24," repo state is "clean and pushed," and verified test counts reflect Cycle 14 numbers (1,573 / 10 / 0).

**Audit-3 spot-checks all confirmed**: N19 (CSRF handler at import time), N20 (golden CI job + chromium install), N21 (`--ci` mode in `make eval`), N22 (`clusterMarkersByIdx` toggle in `filterToIndices`). Repo verified clean at `79dc9cc` after audit-3.

### Cycle 14 (external audit-2 close-out — N19-N23) — done
External LLM auditor reviewed the cycle-13 package and returned 5 findings (initial 84/100; final score 81/100). All closed:

- ✅ **N19 High — CI-mirror suite red on combined run.** `tests/harness/conftest.py:65` registered the CSRFError handler inside the `csrf_enforced_client` fixture; once another test had touched the app first, Flask refuses late `app.errorhandler` registration ("can no longer be called after first request"). Moved the registration to module-import time (`_install_harness_csrf_handler()`); now idempotent and safe regardless of test order. CI-mirror `pytest tests/ -k "not e2e"` was 1571 passed / 1 error → now **1573 passed / 0 errors**.
- ✅ **N20 High — claimed browser-render coverage silently skipped in CI.** `.github/workflows/ci.yml` installed `pytest-playwright` but never ran `playwright install chromium`, so all 27 browser tests hit the `pytest.skip("chromium not available")` guard. Added a dedicated `golden` job that runs `playwright install --with-deps chromium` before `pytest tests/golden/`, AND added the strict-mode `python -m tests.eval.run_eval --ci` step. Added `golden` to `docker.needs` so docker won't build without browser tests passing.
- ✅ **N21 Medium — `make eval` swallowed tool-selection failures.** Was `python -m tests.eval.run_eval --mock || true`. Switched to `--ci` mode (which exists in `tests/eval/run_eval.py:253`, enforces tool/param/chain accuracy thresholds, exits non-zero on regression). Local run: 80/80 / 50/50 / 11/11, `pass: true`.
- ✅ **N22 Medium — animation player didn't update visible cluster bubbles.** `filterToIndices` only styled `entry.leafletLayer`; for wide-area polygon layers in cluster mode (zoom < 15), the visible representation is `clusterLayer` (markerClusterGroup of centroids). Fix: stamp `_origIdx` on each centroid marker at build time and store `clusterMarkersByIdx[]` on the entry; `filterToIndices` now also batches `clusterLayer.removeLayers(toRemove)` + `addLayers(toAdd)` so the cluster reorganizes per animation frame. `clearFilter` re-adds any missing markers. New regression test `test_animate_layer_filters_cluster_markers_at_low_zoom` proves the cluster bubble count drops when filtering and restores on clear.
- ✅ **N23 Low — audit doc was stale.** Header said "24 commits ahead, latest daa6b36" while the repo was at `3124686` clean and synced. Refreshed all metadata; the test counts in this file are now updated per-cycle in the header rather than embedded in cycle notes (which became wrong as cycles added tests).

**Verification**: full pytest run + `make eval` after Cycle 14 — see header for current numbers.

### Cycle 12 (the actual user-reported render bug — fixed) — done
The previous cycles built infrastructure to *catch* render bugs; this cycle reproduced and fixed the user's original manual-check complaint. I drove the live application against real Overpass (free, no LLM cost), captured screenshots, and inspected them visually (multimodal). Two distinct rendering pathologies turned up.

**Findings (with screenshot evidence at `tmp/smoke_screenshots/`)**
- **Finding A — sub-pixel polygons at wide-area zoom**: "hospitals in Chicago" → 59 hospital polygons returned, `fitToLayer` zooms to ~10, every polygon is < 1px wide → user sees a blank map labeled "59 features". Confirmed by zooming to a 700m bbox, where the same hospitals appear as clear blue blocks. Data correct; render unusable.
- **Finding B — overlap-blob at medium zoom**: "buildings in The Loop, Chicago" → 1,582 building polygons returned, `fitToLayer` to zoom 14, all rendered solid `#3388ff` with 0.3 fill → entire Loop becomes one indistinguishable blue blob. Outlines invisible because every feature has the same fill.

**Why the unit suite missed both**: every existing mocked workflow test uses 1–6 features in a tight bbox. None hit the "many features over a wide area" or "many features at the same scale" stress cases. The bug was in the *frontend default rendering policy*, not in any handler — a code surface no test was probing.

**Fix (4 changes in `static/js/layers.js`)**
1. **Density-aware default style**: when feature_count > 200, switch defaults to `weight: 1, fillOpacity: 0.15` (was `weight: 2, fillOpacity: 0.3`). Overlapping outlines stay distinguishable.
2. **Wide-area chat hint** (in `static/js/chat.js`): when ≥ 500 features land, emit an info message — "Showing N features. Zoom in to see individual items; cluster bubbles below zoom 15." Avoids the "blank map looks broken" confusion.
3. **Polygon centroid clustering with zoom-toggle**: when `polygonCount ≥ 100` OR (`polygonCount ≥ 30` AND `bbox_diagonal ≥ 5km`), build a parallel `L.markerClusterGroup` of feature centroids. A `zoomend` handler swaps which layer is on the map: at zoom < 15 show clusters; at zoom ≥ 15 show actual polygons. The wide-area trigger (b) catches the canonical "show hospitals in Chicago" case (59 features, ~30km bounds) that the count-only trigger missed.
4. **Hashed per-feature color**: when `polygonCount ≥ 50` AND no caller-supplied color/styleFunction, pick HSL hue from `osm_id × 137 mod 360`. Adjacent features get distinguishable colors so 1,500-building queries are legible at any zoom.

**Regression tests (B18, B19)**
- `test_wide_area_many_polygons_renders_as_cluster_bubbles` — 60 polygons over ~30km, asserts at zoom < 15 the cluster layer is active AND polygon paths < 10 (they were 60 pre-fix). Zoom in past 15 → polygons re-appear.
- `test_wide_area_layer_emits_chat_hint` — 600 polygons, asserts the "Showing 600 features. Zoom in…" hint reaches the chat history.

**Visual proof** (saved to `tmp/smoke_screenshots/`):
- `user_query_buildings_loop.png` — pre-fix solid blue blob → post-fix orange/yellow/red cluster bubbles with feature counts
- `hospital_chicago.png` — pre-fix blank map → post-fix green/purple cluster bubbles spread across Chicago
- `buildings_small.png` — pre-fix uniform blue → post-fix per-building varied colors (52 distinguishable buildings)

**Final coverage**: `make eval` runs 6 server-side workflow + 19 browser-render + 8 frontend-auth + 65 harness + 30 tool-selection in ~50s. Unit suite: 1,539 passed / 10 skipped / 0 failed.

### Cycle 11 (chart tool fix + animate/3d resilience) — done
While auditing chat.js for more silently-broken UX surfaces (the same hunt that found heatmap), discovered that the `chart` tool returned a Chart.js-compatible spec but no Chart.js was loaded AND no chart-render hook existed in the frontend. Result: chart tool calls fell through to `formatToolResult`'s default branch and rendered as a raw JSON snippet. Two more half-built features (`animate_layer`, `visualize_3d`) had similar gaps but require non-trivial UI work.
- ✅ **Chart fix**: added Chart.js 4.4.1 CDN to `templates/index.html`; added `renderChartIntoStep(stepId, spec)` in `static/js/chat.js`; hooked `case 'tool_result'` to invoke it when `result.action === 'chart'`. Histograms render as bar charts (Chart.js has no native histogram type, but the backend already pre-bins so a bar chart is correct). Pie charts get the legend, others suppress it.
- ✅ **B15 — chart regression test**: `test_chart_tool_result_renders_chartjs_canvas`. Asserts (a) Chart.js loaded, (b) canvas appears under tool step, (c) `Chart.getChart(canvas)` returns a non-null instance (proves the `new Chart(...)` call actually attached), (d) tool-step text summary survives.
- ✅ **B16/B17 — resilience guards for `animate` + `visualize_3d`** (parametrized): both tools currently return structured payloads the frontend has no specialized renderer for. Contract pinned: page MUST NOT crash, chat input MUST stay usable. When/if real animate/3d UIs land, these tests fail informatively and need updating to match the new behavior.

**Known limitation flagged for next round**: `animate_layer` and `visualize_3d` produce backend output but the frontend has no time-slider / 3D extrusion view. They aren't broken (no crash, deterministic output); they're half-built. Either build the UIs (significant scope) or remove the tools from the LLM-visible tool list to stop the LLM from reaching for them.

**Final coverage**: `make eval` runs 6 server-side workflow + 17 browser-render + 8 frontend-auth + 65 harness + 30 tool-selection in ~50s. Unit suite: 1,539 passed / 10 skipped / 0 failed.

### Cycle 10 (heatmap fix + frontend-auth harness) — done
After Cycle 9 the only known UI no-op was heatmap (Leaflet.heat lib missing) and the only un-harnessed frontend contract was auth-on-fetch. Both closed.
- ✅ **Heatmap fix**: added `<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.heat/0.2.0/leaflet-heat.js">` to `templates/index.html` (cdnjs is already in CSP via socket.io). Without this the chat handler at `static/js/chat.js:417` silently dropped every heatmap tool call because `window.L.heatLayer` was undefined.
- ✅ **B14 — heatmap regression test**: `tests/golden/test_browser_render.py::test_heatmap_event_creates_heat_layer`. Asserts (a) `L.heatLayer` is a function (catches the lib being removed from index.html again), (b) the layer registers in `LayerManager`, (c) Leaflet.heat actually paints a `canvas.leaflet-heatmap-layer` onto the overlay pane.
- ✅ **`tests/golden/test_frontend_auth.py`** (8 tests, planned in §6.1): pins every `static/js/auth.js` contract that the H1+M1+M2 audits required. A1 CSRF on POST; A2 no CSRF on GET; A3 Bearer from localStorage; A4 no Authorization when localStorage empty (preserves the unauthenticated 401 observable); A5 `window.SpatialAuth` helpers exposed; A6 jQuery `$.ajax` beforeSend parity with `authedFetch`; A7 auth.js loads before main/chat/layers; plus an A2-corollary that caller-supplied Authorization is not overwritten by localStorage. Uses Playwright `page.route()` to capture the headers each call actually emits — no mocks, real browser, real auth.js.

**Final coverage**: `make eval` runs 6 server-side workflow + 14 browser-render + 8 frontend-auth + 65 harness + 30 tool-selection in ~50s. Unit suite: 1,539 passed / 10 skipped / 0 failed. Still air-gapped from external paid services.

### Cycle 9 (browser-render coverage expansion) — done
After Cycle 8 shipped 4 browser tests (B1–B4), the remaining user-visible code paths got covered. The bar moved from "polygon paints" to "every common UI workflow has a regression guard":
- ✅ B5 — `layer_command remove` two-turn workflow (snapshot the appear state on turn 1, assert removal on turn 2). Caught a polling-resolution bug while building it: SSE'd add+remove in a single fulfillment finishes faster than 150ms polls can witness; restructured as separate chat turns.
- ✅ B6 — two `layer_add` events in one turn render two independent layers + paths
- ✅ B7 — `layer_style` event flips polygon stroke color on an existing layer
- ✅ B8 — `highlight` event re-colors ONLY matching features (predicate guard)
- ✅ B9 — quick-action button click fills input AND fires `/api/chat` with the button's `data-msg`
- ✅ B10 — plan mode renders `<ol>` of steps + Execute/Cancel buttons in `.chat-plan`
- ✅ B11 — Stop button mid-stream aborts fetch + flips input back to `Send` (M2 audit)
- ✅ B12 — second chat call aborts the first's `AbortController` (M2 audit)
- ✅ B13 — malformed `layer_add` (geometry: null) does not crash the page (defensive)

**Architectural finding while building B11/B12**: the Playwright sync Python API serializes everything on one event loop, so a `time.sleep()` in a route handler blocks the test driver too — the in-flight UI states are never observable. Switched both tests to a JS-side fetch override (`window.fetch = ... ReadableStream that never closes`) which keeps the loop free. Pattern documented inline as `_hang_chat_fetch_js`.

**Heatmap deliberately not covered**: the chat handler `case 'heatmap':` checks `window.L && window.L.heatLayer` but `Leaflet.heat` is **not loaded** in `templates/index.html`. So heatmap events silently no-op in the browser today. This is a real finding, but the fix is to load the lib (one CDN script tag), not to write a test against a nonexistent feature.

**Final coverage**: `make eval` runs 6 server-side workflow + 13 browser-render + 65 harness + 30 tool-selection in ~40s. All air-gapped from external paid services (LLM, Overpass, Nominatim, Valhalla); the only opt-in live test (`SPATIALAPP_GOLDEN_LIVE=1`) lives in the pre-existing `tests/test_golden_path.py` and is excluded from `make eval`.

### Cycle 8 (mocked-browser render in CI) — done
The Cycle 6 server-side workflow tests proved the chat→tool→`state.layer_store` contract; what remained unverified deterministically was the browser-side render the user explicitly flagged ("things need to render on the map successfully"). Closed that gap:
- ✅ `tests/golden/test_browser_render.py` — 2 Playwright tests against a real Flask + headless Chromium. B1 fulfills `/api/chat` with a canned SSE stream containing one `layer_add` event and asserts (a) the layer name is registered in `window.LayerManager` and (b) at least one `<path>` exists in the Leaflet overlay pane (i.e., a polygon was actually painted). B2 sends a `layer_add` with `geometry: null` and asserts the page does not crash and the chat input remains responsive.
- ✅ Discovered while writing B1: chat.js flips a closure-private `_useWebSocket` flag the moment Socket.IO connects, bypassing `/api/chat` entirely. Since the flag is not exposed on `window`, the test blocks `**/socket.io/**` at the Playwright route layer to keep the SSE transport active. Documented this trick in `tests/golden/README.md`.
- ✅ `live_app` (module-scoped subprocess) and `chromium` (skip-if-unavailable) fixtures lifted into `tests/golden/conftest.py` so future browser tests reuse them.
- ✅ `Makefile` `golden` target unchanged in scope (still `pytest tests/golden/`) — now picks up browser-render automatically. Total `make eval` cost: 8 golden + 65 harness + 30 tool-selection in ~25s.

**Coverage delta**: the only previously-skipped paint assertion (`test_buildings_query_renders_polygons_live`, `tests/test_golden_path.py:159`) was gated behind `SPATIALAPP_GOLDEN_LIVE=1`. Now there is an equivalent paint assertion in CI mode using mocked SSE — same DOM probe (`document.querySelectorAll('.leaflet-overlay-pane path').length`), no live cost.

### Cycle 7 (close /critical-review BL1+BL2+BL3) — done
After Cycle 6 shipped the golden eval, /critical-review's three remaining blockers were tackled:
- ✅ **BL1 — `PerKeyRateLimiter._events` unbounded**. The dead `if not history: pop()` branch (lines 102-104, pre-fix) never fired because `history.append(now)` happened immediately above. Replaced with: opportunistic GC sweep every `_GC_INTERVAL=1024` allow() calls + a hard `max_keys=50_000` cap that refuses brand-new keys when full while still serving existing ones. Memory now O(active-keys-within-window), not O(distinct-keys-ever-seen). `services/rate_limiter.py:71-130`.
- ✅ **BL2 — direct unit tests for `services/rate_limiter.py` and `blueprints/auth.py`** (both were exercised only indirectly). Added `tests/test_rate_limiter.py` (17 tests) and `tests/test_auth.py` (21 tests). Includes a BL1 regression test (`test_memory_bounded_under_distinct_key_flood`) that proves an attacker rotating through 150 distinct keys cannot grow `_events` past `max_keys=100`. While writing tests I caught one assumption error of my own: I assumed `users.username` had a UNIQUE constraint and thus dupe usernames yielded 409 — actually only `api_token` is UNIQUE in the schema (`services/database.py:85-86`), so dupe usernames currently succeed with new user_ids. Pinned the actual contract in `test_duplicate_username_currently_allowed` rather than masking it.
- ✅ **BL3 — Hypothesis state machine docstring drift**. The header claimed annotation rules were modeled but only layer rules existed. Added 3 annotation rules (`create_annotation`, `list_annotations`, `clear_annotations`) + an annotation cross-user-visibility invariant. Now the state machine genuinely fuzzes both C3 (layer) and C4 (annotation) isolation surfaces. `tests/harness/test_isolation_state_machine.py:175-272`.

**Test count delta**: harness 65 → 65 (state machine still 1 test, just exercises more rules); unit 1,526 → 1,537 (+38 new direct tests in 2 new files; skip count 10 → 9). `make eval` still green: 6 golden + 65 harness + 30 tool-selection.

### Cycle 6 (geospatial workflow eval — user reframe) — done
After /critical-review and /gap-analysis flagged that the security harness covered isolation contracts but NOT the user-visible geospatial experience ("things need to render on the map successfully"), shipped a workflow-level eval:
- ✅ `tests/golden/test_user_workflows.py` — 6 scenarios that exercise chat → LLM tool dispatch → mocked Overpass/Nominatim → SSE stream → `state.layer_store`. Asserts (a) `layer_add` events fire, (b) GeoJSON is `FeatureCollection`-shaped, (c) every coordinate is geographic, (d) polygon rings close, (e) coordinate order is `[lng, lat]` not `[lat, lng]`. ~13s, CI-safe (no live keys).
- ✅ `tests/golden/conftest.py` — `scripted_llm`, `mock_overpass`, `golden_client`, `parse_sse` fixtures. Mock seams patch `nl_gis.chat.create_provider` + `nl_gis.handlers.navigation.requests.get`; no production code touched.
- ✅ `Makefile` with `make eval` — single command bundling golden + harness + tool-selection corpus. The pre-audit ritual the user asked for ("after each implementation I want to be able to run the eval, before an external auditor reviews").
- ✅ `tests/golden/README.md` — bug-class → scenario coverage matrix and how to add new workflows.

**Coverage delta**: `make eval` now runs 6 golden + 65 harness + 30 tool-selection probes deterministically. Catches OSM-query-but-nothing-renders bugs, lat/lng swaps, partial-state-on-timeout regressions, and chained-tool bbox loss — none of which any unit test was checking.

## 4. Suggested external prompts to use

Use [`09-external-audit-prompts.md`](09-external-audit-prompts.md) Prompts 1, 3, 5 as the primary input. Recommended adjustments for this round:
- Prompt 3 (findings completeness) — the "previous findings" list NOW INCLUDES N1-N23. **New findings MUST start at N24** (the header is the source of truth — see top of this file). The `09-external-audit-prompts.md` file's own intro numbering predates the rolling work — override it with this file when handing it to the reviewer.
- Add a new explicit focus area: "the ten under-audited surfaces in §2.1 of `12-next-audit-input.md`" — reviewer should sweep those before generic ones.
- Provide the auditor with the current commit sha (use `git log -1 --oneline`) so they can re-run the same probes against the same code.

## 5. Submission checklist (for when you DO audit)

- [ ] Repo state is clean and pushed; auditor can pull from `origin/main` directly. The header records the latest commit at the time of the most recent cycle.
- [ ] Confirm `pytest tests/harness/` is green on a clean checkout (latest verified: **65 passed / 3 skipped**).
- [ ] Confirm `pytest tests/ -k "not e2e"` is green (latest verified at Cycle 14 close: **1,573 passed / 10 skipped / 0 failed**).
- [ ] Confirm `make eval` is green (latest: 6 workflow + 19 browser-render + 8 frontend-auth + 65 harness + 30 tool-selection in `--ci` strict mode).
- [ ] Hand the auditor: this doc, `09-external-audit-prompts.md` Prompts 1+3+5, the smoke test report `13-smoke-test-2026-05-03.md`, and the current commit sha (`git log -1 --oneline`).
- [ ] Tell the auditor: "do not re-flag any ID in §1.1 or any of N1–N23; **new findings start at N24**."
- [ ] Budget: 1-2 reviewer hours per prompt; total ~6 hours.
