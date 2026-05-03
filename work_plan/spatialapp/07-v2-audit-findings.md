# SpatialApp v2 — External audit findings

**Source:** External audit pass conducted 2026-05-02. Auditor stopped
the local audit server after verification.

**Auditor's caveat (important):** the full test suite is green
(1,435 passed, 30 skipped) but **several bugs are hidden** because
tests disable CSRF and all raster tests skip. Green CI does not mean
"v2 is correct."

**Status:** v2 is **buggy and not yet fixed**. All 12 findings below
are scoped under v2 (continuation of the v2.1 line — closing v2 out,
not opening a new version).

---

## Critical (4) — block deploy

### C1 — `execute_code` sandbox is bypassable; remote code execution risk

- **File:** `services/code_executor.py:20`
- **Symptom:** Substring blacklist + `ALLOWED_MODULES` is never
  enforced. Auditor verified this payload passes validation and
  executes a shell command:
  ```python
  import importlib; importlib.import_module('os').system(...)
  ```
- **Also:** `max_memory_mb` is documented but **not enforced**.
- **Risk:** Remote code execution if the LLM (or anything proxied
  to it) can call `execute_code`.

**Fix shape**
- Replace substring scan with **AST walk** that rejects any `Import`,
  `ImportFrom`, or `Call` whose target resolves to `__import__`,
  `importlib.*`, `eval`, `exec`, `open`, `compile`, `globals`,
  `__builtins__`.
- Enforce `ALLOWED_MODULES` as the **only allowlist** (not a blacklist).
- Wrap execution in `resource.setrlimit(RLIMIT_AS, ...)` for memory.
- Run in `multiprocessing.Process` with `terminate()` after timeout.
- Drop the in-process exec entirely.

---

### C2 — CSRF exemptions are broken; API clients + UI actions return 400

- **Files:** `app.py:79` (wrong env flag) and `app.py:168` (wrong
  endpoint key shape)
- **Two bugs:**
  1. `request.environ['csrf.exempt']` is **not** what Flask-WTF reads.
  2. The exemptions in `app.py:168` use endpoint-like strings such as
     `chat.api_chat`, while Flask-WTF checks **module paths** like
     `blueprints.chat.api_chat`.
- **Auditor verified:** `/api/register`, `/api/chat`,
  `/api/chat/execute-plan`, and `DELETE /api/layers/test_layer`
  return **400 without CSRF**.

**Fix shape**
- Drop the env-flag hook entirely.
- Use `csrf.exempt(view_function)` at blueprint registration time,
  passing the actual **function object** — not a string.
- Re-test every state-mutating route under both bearer-only and
  CSRF-only flows.

---

### C3 — Chat session ownership can be bypassed on DB restore

- **File:** `blueprints/chat.py:89` (restore by `session_id` only)
  → `blueprints/chat.py:94` (in-memory owner becomes the attacker)
- **Symptom:** A second user who knows or guesses a session id can
  load another user's saved messages; the in-memory owner record then
  becomes the attacker. Auditor reproduced with a temp DB.

**Fix shape**
- Restore must honor the saved `owner_user_id` column
  (`get_chat_session_with_owner` already returns it; the path that
  calls `get_chat_session` must be replaced).
- On restore, if `owner != g.user_id`, return **403** instead of
  taking ownership.

---

### C4 — Multi-user layer + annotation isolation is broken

- **Layers (global in memory):**
  - Restored without user filtering at `app.py:293`.
  - `/api/layers` returns the global store at `blueprints/layers.py:47`.
  - Delete removes from memory even if the DB delete did not delete
    the current user's row at `blueprints/layers.py:100`.
- **Annotations (also global):**
  - Loaded without user filtering at `blueprints/annotations.py:37`.
  - Saved without passing `g.user_id` at `blueprints/annotations.py:205`.
  - Public via `/get_annotations` and `/export_annotations` at
    `blueprints/annotations.py:275`.

**Fix shape (two paths)**
- **(A) Restructure** `state.layer_store` to
  `dict[user_id, OrderedDict[name, geojson]]` and gate every read /
  write on `g.user_id`. **Correct but invasive.**
- **(B) Keep global in-memory** but require every public API to
  filter by `g.user_id` before serving. **Faster, lower-risk.**
- **Recommendation:** ship (B) now with a tracked TODO to migrate to
  (A) post-v2. Mirror for annotations: pass `user_id=g.user_id`
  everywhere `state.geo_coco_annotations` is touched, filter on read.

---

## High (4) — fix before declaring v2 done

### H1 — Frontend auth is inconsistent

- `static/js/main.js:5` — main jQuery setup only sends CSRF, not
  Authorization.
- `static/js/chat.js:730` — Chat SSE and plan execution also omit
  bearer tokens.
- **Consequence:** if `CHAT_API_TOKEN` is set, much of the UI fails;
  if only per-user tokens exist and no shared token is set, many
  actions silently run as anonymous.

**Fix shape**
- Add `Authorization: Bearer ${token}` to the jQuery `beforeSend`.
- Centralise into `static/js/auth.js` exporting `authedFetch()` and
  `authedAjax()` so all sites share one source of truth.
- Migrate every `fetch()` / `$.ajax()` call site to the helper.

---

### H2 — Chat sessions can detach from the real layer store

- **File:** `nl_gis/chat.py:316` uses `layer_store or {}`.
- **Bug:** an empty shared `OrderedDict` is **falsy**, so new chat
  sessions get a private dict. Imported layers added later to
  `state.layer_store` are invisible to that chat session.

**Fix shape**
- Replace `layer_store or {}` with
  `layer_store if layer_store is not None else {}`.
- Add a regression test: create chat session → import layer → next
  chat tool call sees the imported layer.

---

### H3 — Production can run with the default development secret

- **File:** `app.py:62`
- **Bug:** `Config.validate()` raises, but the call site catches the
  exception and only logs a warning. That allows insecure Flask
  sessions / CSRF secrets in production.

**Fix shape**
- Re-raise `RuntimeError` when `FLASK_DEBUG` is **false** (production).
- Keep the warning path only when `DEBUG=true`.

---

### H4 — Auto-classify timeout does not actually release the request

- **File:** `blueprints/osm.py:414`
- **Bug:** `with ThreadPoolExecutor(...)` waits for the worker on
  context exit; if `future.result(timeout=300)` raises, the context
  manager still blocks. Route can hang past the intended 504.

**Fix shape**
- Use a module-level executor or
  `concurrent.futures.ThreadPoolExecutor()` with explicit
  `future.cancel()` + thread cleanup.
- Better: run via `subprocess.run(timeout=...)` so the OS kills the
  worker.
- Or: refactor classify to be cancellable via a `threading.Event`
  checked in the inner loop.

---

## Medium (4) — track in v2 close-out

### M1 — Layer delete UI fails server-side

- **File:** `static/js/layers.js:153`
- **Bug:** sends `fetch(... DELETE ...)` without CSRF or auth.
  Auditor verified server returns 400, so client-side removal can
  leave server-side ghost layers.

**Fix:** migrate to `authedFetch()` (created for H1); same module
fixes this in one go.

---

### M2 — The "Stop" button does not stop WebSocket chat or plan execution

- `static/js/chat.js:150` — click handler only aborts
  `currentAbortController`.
- **WebSocket sends have no abort path.**
- **Plan execution creates no abort controller** at
  `static/js/chat.js:730`.

**Fix shape**
- WebSocket: emit a `chat_abort` event with the session id; server
  cancels the in-flight tool-dispatch loop.
- Plan execute: thread an `AbortController` through `fetch(..., {signal})`
  like the SSE path does.

---

### M3 — Raster feature coverage is effectively absent

- All 24 raster tests skip because `sample_rasters/` is missing.
- `rasterio` is installed, but the app has no sample raster data, so
  raster tools are not meaningfully exercised.

**Fix shape**
- Commit a tiny GeoTIFF fixture (1km × 1km, 30m DEM-like, < 50 KB)
  under `sample_rasters/`.
- Or: fabricate one in a fixture via `rasterio.MemoryFile()`.

---

### M4 — OpenAI tool-limit summarization can lose instructions

- **File:** `nl_gis/llm_provider.py:376`
- **Bug:** when tool results and text are mixed, only `tool_result`
  blocks are converted; **text blocks are dropped**.
- The tool-limit instruction appended at `nl_gis/chat.py:938` can
  disappear for OpenAI.

**Fix shape**
- When the assistant content list contains both text and tool_use,
  emit **both** into the OpenAI message format (text into `content`,
  tool_use into `tool_calls`).
- Mirror what the Anthropic path already does.

---

## Cross-cutting findings (implied by the audit)

### X1 — Tests disable CSRF, so CSRF tests don't catch CSRF bugs

`app.config['WTF_CSRF_ENABLED'] = False` in fixtures means **every
existing test passes regardless of whether CSRF works in production**
— which is why C2 ships green.

**Fix:** add `tests/security/test_csrf_enforcement.py` that runs with
CSRF *enabled* and asserts every state-mutating endpoint returns 403
without a token, 200 with one. (This is also derivation rule R3.4 in
the V11 framework — but is an immediate v2 need too.)

### X2 — Test infrastructure mocks `state.db` inconsistently

The fact that **C3 ships green** strongly suggests the test that
*would* catch it either uses a single user or skips the DB-restore
path entirely.

**Fix:** add a test fixture where:
1. session A is created and persisted by user A,
2. the in-memory cache is cleared,
3. user B requests session A's id,
4. assert 403.

10-line test. Its absence today is itself a finding.

### X3 — Raster + e2e test gaps mean the audit could only cover ~85% of the surface

24 raster tests skip + 25 e2e tests skip (no Playwright chromium
baseline). That's roughly 49 tests that don't run on a "green" CI
build. M3 fixes the rasters; should also commit a chromium-cache-friendly
Dockerfile so e2e tests run on every PR.

---

## Recommended order of attack (one PR per row)

| # | PR | Severity | Effort | Why this order |
|---|---|---|---|---|
| 1 | **C2 — Real CSRF exemptions + X1 enabled-CSRF test suite** | Critical | S | Until CSRF works, no other security finding can be regression-tested. Also unblocks fixing M1 + H1 cleanly. |
| 2 | **C1 — `execute_code` AST sandbox + RLIMIT** | Critical | M | RCE class. Highest blast radius if the LLM is ever proxied to an attacker. |
| 3 | **C3 — Owner-aware chat-session restore + X2 regression test** | Critical | XS | Three-line fix; large privacy impact. |
| 4 | **C4 — Per-user layer + annotation isolation** | Critical | M | Largest code surface; touches `state.py`, `blueprints/layers`, `blueprints/annotations`, `app.py` restore path. Schedule after C1–C3 because the test infra those produce makes C4 verifiable. |
| 5 | **H3 — Refuse default SECRET_KEY in production** | High | XS | One-line fix; deploy-blocker. |
| 6 | **H1 + M1 + M2 — Centralized authedFetch + WebSocket abort + plan-execute abort** | High + Medium | M | All three are JS auth/transport gaps; one shared `auth.js` module fixes them together. |
| 7 | **H2 — ChatSession layer_store identity fix + regression test** | High | XS | One-line fix; verifies via a workflow test. |
| 8 | **H4 — Auto-classify cancellable timeout** | High | S | Subprocess refactor; isolated to `blueprints/osm.py`. |
| 9 | **M3 — Sample raster fixture committed** | Medium | XS | Unblocks 24 skipped tests. |
| 10 | **M4 — OpenAI text+tool_use mixed-content emit** | Medium | S | One-provider fix; mirrors existing Anthropic path. |

**Total estimated effort:** ~7–9 focused engineering days.

## Decisions still required from the user (before any code)

1. **Approve the v2 scope** — all 12 findings as listed, no expansion?
2. **Approve the order** — or rearrange? In particular, fix C4 *after*
   C2/C1/C3 (smaller ones land first to clear the path), or C4 before
   everything because of multi-user impact?
3. **Confirm path-A-vs-B for C4** — global with per-user filters (B,
   recommended), or restructure to `dict[user_id, OrderedDict]` (A)?
4. **Approve committing a small raster fixture** (≤ 50 KB GeoTIFF)
   under `sample_rasters/`, or generate at fixture time via
   `rasterio.MemoryFile`?
5. **Approve adding `tests/security/test_csrf_enforcement.py` with
   CSRF actually enabled** — this changes one fixture's behavior and
   may turn currently-green tests yellow. Acceptable?

Once 1–5 are answered, start with PR #1 (C2 + X1), run the existing
suite, run the new CSRF-enforced suite, and only then move to the
next PR. **No commits until each PR is green on its own.**

## Cross-references

- Plan dashboard: [`../../docs/v2/README.md`](../../docs/v2/README.md)
- Project status: [`../../.project_plan/STATUS.md`](../../.project_plan/STATUS.md)
- Workflow inventory: [`05-workflow-inventory.md`](05-workflow-inventory.md)
  — auditor's findings cross-reference workflows W01 (fetch_osm),
  W11 (auto-classify), W42 (delete layer), W20+W30 (chat), W90 (health).
- Execution plan: [`06-execution-plan.md`](06-execution-plan.md) —
  these v2 fixes precede the framework rollout's Phase 1 P0 work.
