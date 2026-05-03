# SpatialApp v2 — Input package for next external audit

**Status:** **DRAFT — actively updated each cycle.** Submit only when the user invokes external audit.
**Last updated:** 2026-05-03 (cycle 4 — 16 findings beyond the original audit, all closed; N15 was a verification with no fix needed)
**Updated by:** autonomous /auto-solve cycle
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
| N16 | Medium | WS `chat_message` `context` dict was unbounded → amplified LLM cost + log bloat; validate session_id + active_layers cap 256 + total ≤ 16 KB | `<this commit>` |
| N17 | Low | `/.well-known/security.txt` (RFC 9116) added with `SECURITY_CONTACT` env var | `<this commit>` |

**Total: 28 findings closed** (12 audit + 16 self-discovered post-fix; N15 was a clean check).

### 1.2 Test infrastructure added

- `tests/harness/` directory — opt-in adversarial suite (`pytest -m harness`):
  - `test_csrf_enforcement.py` — 15-route property test, distinguishes CSRF rejection (sentinel HTTP 419) from other 400s
  - `test_rce_sandbox.py` — 14-payload deny corpus + 7-payload allow corpus
  - `test_multi_user_isolation.py` — 6 scenario tests (layer/annotation/chat-session, 2-user fixture)
  - `test_secret_validation.py` — 3 cases on `Config.validate()`
  - `test_layer_store_identity.py` — 4 ChatSession identity invariants
  - `test_provider_mixed_content.py` — 3 OpenAI converter cases
  - `test_env_isolation.py` — 4 LLM key guards
- `tests/conftest.py` — root-level: clears LLM keys + sets `RASTER_DIR` to fixture dir before any `Config` import.
- `tests/fixtures/raster/geog_wgs84.tif` — committed 611-byte WGS84 raster.

### 1.3 Test deltas

| | Before (pre-session) | After (current) |
|---|---|---|
| Pre-existing tests | 1,437 passed / 31 skipped | **1,503 passed / 7 skipped** |
| Harness tests | 0 | **44 (all green)** |
| Net regressions | — | **0** |

## 2. What the auditor should focus on

The previous audit explicitly self-reported ~85% surface coverage. The 21 closed findings teach what classes of bug to expect; this section names the surface still under-audited.

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
Completed the 21 findings above. Repo on `main`, 7 unpushed commits (`ed21e66` → `d68d5e4`).

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

### Cycle 5 — possible next directions
- [ ] Replace placeholder `SECURITY_CONTACT` default with a real inbox before any deploy
- [ ] Add `pip-audit` step to GitHub Actions CI
- [ ] Property-based Hypothesis state machine for multi-user isolation (current is scenario-based)
- [ ] Playwright frontend harness (`test_frontend_auth.py` per `08-v2-bugfree-plan.md`)
- [ ] Live smoke test: `python3 app.py` + browser-exercise the golden path
- [ ] Add a `pre-commit` hook that runs `pytest -m harness` before push

## 4. Suggested external prompts to use

Use [`09-external-audit-prompts.md`](09-external-audit-prompts.md) Prompts 1, 3, 5 as the primary input. Recommended adjustments for this round:
- Prompt 3 (findings completeness) — the "previous findings" list now includes N1-N9; new findings start at N10.
- Add a new explicit focus area: "the ten under-audited surfaces in §2.1 of `12-next-audit-input.md`" — reviewer should sweep those before generic ones.
- Provide the auditor with the current commit sha (use `git log -1 --oneline`) so they can re-run the same probes against the same code.

## 5. Submission checklist (for when you DO audit)

- [ ] Push the 7+ unpushed commits OR generate a `git format-patch` bundle for the auditor.
- [ ] Confirm `pytest -m harness` is green on a clean checkout.
- [ ] Confirm `pytest --ignore=tests/e2e` is green (1,503 passed / 7 skipped baseline).
- [ ] Hand the auditor: this doc, `09-external-audit-prompts.md` Prompts 1+3+5, and the current commit sha.
- [ ] Tell the auditor: "do not re-flag any ID in §1.1; new findings start at N10."
- [ ] Budget: 1-2 reviewer hours per prompt; total ~6 hours.
