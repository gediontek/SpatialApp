# SpatialApp v2 Close-out — Acceptance-First Hardening Plan

**Author:** Principal Research AI Engineer (deep-think protocol)
**Date:** 2026-05-02 (v1.0); 2026-05-03 (v1.1, v1.2)
**Revision:** v1.2 (2026-05-03) — doc cleanup pass on v1.1 (revision metadata, raster fixture name, exit-criteria precision, prompt de-duplication, schedule consistency in prompts). v1.1 (2026-05-02) — folded external audit verdict (plan 78→86, app 31/100 unchanged). Changes flagged inline as **[v1.1]** or **[v1.2]**.
**Supersedes:** the unstructured "PR-by-PR" hint in `07-v2-audit-findings.md` (Recommended order section). The 12 findings remain unchanged; the **execution strategy** is replaced.
**Cross-refs:** [`07-v2-audit-findings.md`](07-v2-audit-findings.md), [`06-execution-plan.md`](06-execution-plan.md), [`05-workflow-inventory.md`](05-workflow-inventory.md), [`docs/v2/README.md`](../../docs/v2/README.md). Thought log `docs/context/thought-logs/2026-05-02-v2-audit-fix-deep-think.md` lives in the cognitive-skill-agent skill repo, not this checkout — only resolvable via the cognitive-skills MCP, not file path.

---

## 0. External audit verdict (added v1.1; refreshed v1.2)

External reviewer scoring trajectory across three rounds (2026-05-02 → 2026-05-03):

| Round | Plan (08) | Prompts (09) | App readiness | Verdict |
|---|---|---|---|---|
| Pre-v1.1 | 78/100 | 84/100 | 31/100 | APPROVE-WITH-REVISIONS |
| Post-v1.1 | 86/100 | 78/100 | 31/100 | APPROVE-WITH-REVISIONS (small doc cleanup) |
| Post-v1.2 | **91/100** | **92/100** | **31/100 unchanged** | proceed to PR #0 |

The reviewer **confirmed via direct probe** that all 4 Critical findings (C1 RCE, C2 CSRF, C3 chat-session bypass, C4 isolation) plus H3 (default SECRET_KEY warns only), H2 (`layer_store or {}`), H4 (ThreadPoolExecutor timeout), M3 (raster skip), M4 (OpenAI text-block drop), and N1 (test env contamination) are still present on `main`. The audit doc + plan are accepted as input; **the application code is not changed and remains deploy-blocked**. App readiness only moves when PR #0 lands and fixes begin.

Reviewer-surfaced corrections folded into the v1.1/v1.2 revisions:

1. **Scope conflict with `docs/v2/README.md`.** That dashboard claims plans 07/09/11/12/13 are ✅ Done (rescoped). The deferral language in §1.2 ("v2.1 deferred features") was wrong — those plans **shipped rescoped**; what is actually deferred is the **un-rescoped portions** (plan 09 frontend, plan 11 JS, plan 13 load test). §1.2 corrected below.
2. **Raster fixture decision (D6) blocked by `.gitignore:82`** — `sample_rasters/` is git-ignored. Recommended: commit fixture as `tests/fixtures/raster/geog_wgs84.tif` (matching the filename `tests/test_raster.py:29` already expects) AND add a session-scoped `conftest.py` that sets `RASTER_DIR` env var to that path BEFORE `config.Config` is imported. See PR #9 row in §6.2 for the wire-up. Alternative: keep `sample_rasters/` and add `!sample_rasters/geog_wgs84.tif` exception with `git add -f` — simpler but pollutes repo root.
3. **New finding N1 — test env contamination.** `tests/test_chat_api.py:11` clears `ANTHROPIC_API_KEY` only. With a Gemini key in env, the test made a real Gemini call and failed an old fallback expectation. Add to PR #0 harness as `test_env_isolation.py`: assert all LLM provider keys are cleared in test environments, or assert `responses`-style mocking blocks live calls.
4. **Schedule realism.** The 11-day budget is optimistic. Reviewer's pressure-test (Prompt 6 result not yet run) likely revises upward. Treat 11 d as P50, plan to 16 d P80.

5. **v1.2 doc cleanup** — revision metadata bumped, stale `dem_30m_1km.tif` removed, PR #0 exit criteria sharpened ("each finding has at least one red assertion" rather than "all harness tests fail"), `pytest-socket` dependency call-out added, prompt-3 duplicate findings de-duplicated, prompt-3 finding-ID seed shifted to N2 (N1 reserved), prompt-6 schedule line aligned to P50=11/P80=16.

**Decision boundary triggered:** the plan now has 0 reviewer-Critical / 0 reviewer-High / 0 REJECT verdicts → **proceed to PR #0**. v1.1 + v1.2 corrections are applied; no further planning revision required before harness work begins.

---

## 1. Problem Definition (reframed)

### 1.1 Stated request
> "Properly address the audit findings and things which have yet to be implemented. Plan with the intention of building something bug-free."

### 1.2 Reframe — the request is ill-posed; fix it before solving

**(a) "Bug-free" is unfalsifiable.** No software is bug-free. The principled translation is **acceptance-test-green on a falsifiable adversarial harness AND zero re-detected Critical/High findings on independent audit re-run AND the harness suite stays green for a 30-day soak.** This plan is built to that target. Anything looser is theater.

**(b) "Things which have yet to be implemented" conflates two non-overlapping work classes.** They are separated below and **must remain separated**:

| Class | Scope | Disposition |
|---|---|---|
| **v2 close-out** (negative work — defect removal) | 12 audit findings (4 Critical, 4 High, 4 Medium) + 3 cross-cutting (X1 CSRF-disabled fixture, X2 single-user DB tests, X3 49 skipped tests) + new finding N1 (test env contamination) | **This plan** |
| **v2.1 rescoped portions deferred to v2.2** [v1.1 corrected] | Plans 07/09/11/12/13 **shipped rescoped** per `docs/v2/README.md`. The originally-scoped portions that were SKIPPED are: plan 09 frontend (WebSocket UI), plan 11 frontend JS (chart/dashboard rendering), plan 13 load test, plan 07 live provider bake-off, plan 06 58-query expansion. | **Deferred to v2.2** — must clear the same harness gate before merge. Do **not** mix with close-out work. |

Adding new surface before the security baseline is proven guarantees the next audit finds the same bug-class on the new tools. This separation is non-negotiable.

**[v1.1] Note on `docs/v2/README.md`:** the dashboard's "✅ Done (rescoped)" status for plans 07/09/11/12/13 is correct for the **rescoped slice**. This plan does not undo that. What this plan defers is the originally-planned-but-skipped portions, which become v2.2 candidates only after v2 close-out passes the harness.

### 1.3 Objective function (formal)

Minimize residual security/correctness risk subject to:
- **Hard constraint:** zero re-detected Critical or High findings on an independent audit re-run.
- **Hard constraint:** every fix lands with (a) a regression test that fails on `main` before the fix, (b) the existing 1,435-test suite still green, (c) line coverage on the touched module ≥ 10pp higher than before the fix.
- **Soft criterion:** prefer fixes whose test machinery generalizes (property tests > example tests).
- **Cost ceiling:** Gemini-only LLM spend (no Claude API live calls — key rotated).
- **Effort ceiling:** P50 = 11 engineering days, P80 = 16 engineering days (audit's 7-9 day fix estimate + 2 day harness budget + reviewer-confirmed schedule realism). Strategy revisit if actual > P80 + 25% = 20 days. **[v1.1 — see §6.3 row "Total engineering time"]**

### 1.4 Underspecification flagged for user
1. **Audit re-run mechanism:** original audit was external. Re-run options: (a) same external auditor (cost?), (b) `/critical-review` with `--adversarial`, (c) different LLM running the audit doc as a checklist. Default: (b) + (c) chained, only escalate to (a) if both pass and you want a third opinion.
2. **30-day soak:** is this calendar time after PR #11 lands, or 30 days of the harness running nightly without regression? Default: latter — concrete, measurable, unambiguous.
3. **C4 isolation path A vs B:** the harness validates the contract regardless of implementation, so this becomes an implementation choice. Default to B (per-user filter on global) for v2 close-out; track A (restructure to `dict[user_id, OrderedDict]`) as v2.2 hardening.

---

## 2. Assumption Audit (Adversarial)

| # | Assumption | Stated? | Confidence | Why it could be wrong | Failure mode if wrong |
|---|---|---|---|---|---|
| A1 | Audit doc is exhaustive for Critical/High findings | implicit in audit | **Low** | Auditor explicitly noted ~85% surface coverage (X3). 49 tests skip on green CI. Raster + e2e surfaces unaudited. | Ship the 12 fixes, next audit finds 5 more. Same bug class. |
| A2 | Each finding's PR boundary is independent of others' | implicit in audit's "one PR per row" | **Medium** | C2 (CSRF fixture) changes test infrastructure, breaking other tests' implicit reliance on disabled CSRF. C4 (per-user state) touches `app.py:293` restore path also touched by C3 (owner-aware restore). | PRs serialize artificially; merge conflicts; one PR's regression test fails on the next. |
| A3 | "Green CI" reflects production correctness | implicit | **Wrong (already)** | Audit proved CSRF is disabled, raster tests skip, e2e tests skip. 49 tests don't run. | Already realized — that's why we need the harness. |
| A4 | The auditor's PR effort estimates (XS/S/M) are accurate | doc | **Low** | C4 marked M but spans `state.py`, `blueprints/layers`, `blueprints/annotations`, `app.py` restore — and now also depends on the multi-user DB fixture (X2). Likely L. | Schedule slips; under-tested fixes ship. |
| A5 | `state.layer_store` is the only global mutable user-scoped state | implicit | **Unknown — must verify** | `state.geo_coco_annotations` confirmed; what about `chat_sessions`, `layer_metadata`, valhalla cache, raster cache? Each is a potential C4-class bug. | C4 fix is incomplete; isolation bypass survives in unaudited globals. |
| A6 | Existing `g.user_id` plumbing is reliable when present | implicit | **Medium** | Frontend bearer-token gaps (H1) mean `g.user_id` may be None/anonymous on routes the audit didn't explicitly test. | Per-user filter on global (C4 path B) returns empty for anonymous-but-supposedly-authenticated requests. |
| A7 | Hypothesis state-machine testing is tractable for multi-user isolation | this plan | **High** | State space is small (2 users × N operations × M routes). Hypothesis Stateful is the textbook tool for this. | If wrong, fall back to scripted scenario tests; don't lose value. |
| A8 | RCE AST sandbox is safe if it rejects all `Import`, `ImportFrom`, attribute access to `__*` | this plan | **Medium** | Python sandbox escapes are a research-grade adversarial domain. Even with AST whitelist, `getattr`-based reflection, generator tricks, and frame inspection have escapes. | Sandbox marked safe; live RCE persists. |
| A9 | Gemini 2.5 Flash will not regress on accuracy when CSRF is enforced in tests | implicit | **N/A** | CSRF fix is server-side; LLM provider unaffected. | (none — separating concern correctly) |
| A10 | The user has authority + intent to defer the **un-rescoped portions** of plans 07/09/11/12/13 to v2.2 (the rescoped portions already shipped per `docs/v2/README.md`) **[v1.1]** | this plan | **Must confirm** | User said "things yet to be implemented" — may want full-scope versions in v2 close-out. | Plan rejected, scope re-expands. |

**Highest-leverage assumption to verify before starting: A5** — enumerate every module-level mutable in the codebase. Two minutes with `grep -nE "^[a-z_]+ *= *(\{|\[|OrderedDict)" services/ blueprints/ nl_gis/`. If any are user-scoped and unfiltered, C4 expands.

**Highest-risk assumption: A8** — sandbox safety. Mitigation in §6 PR #2: don't claim safety from AST alone; layer it (AST whitelist + `RestrictedPython` library + `multiprocessing.Process` with `RLIMIT_AS` + `subprocess` with `seccomp` if available + zero network egress in the worker). Defense in depth.

---

## 3. Candidate Approaches

| | A. PR-by-PR | B. Acceptance-first harness | C. Security-boundary rewrite | D. Freeze v2, restart as v3 |
|---|---|---|---|---|
| **Mechanism** | Audit's checklist; one regression test per finding | Build adversarial harness first (red), drive fixes against red suite | Cluster all auth/isolation/sandbox findings into one new module; migrate 34 routes | Banner v2 "no deploy"; restart on Flask-Security |
| **Test discipline** | Example tests | Property tests + e2e + adversarial fuzzing | Same as A but on new code | New project, new tests |
| **Bug-class coverage** | Single instances | The class (catches variants) | The class (architecturally) | N/A (rewrite) |
| **Blast radius** | Per-PR (small) | PR #0 large but isolated; PRs #1-#10 small | Single big-bang or weeks of bimodal state | Total |
| **Time** | 7-9 d | 9-11 d | 14-21 d | 30+ d |
| **Salvages existing v2.1 work?** | Yes | Yes | Yes (minus auth layer) | No |
| **Catches *next* audit's findings?** | No | Yes (within harness scope) | Maybe (depends on layer design) | Yes (different code) |

---

## 4. Critical Evaluation (Reviewer Mode — no politeness)

### A. PR-by-PR — REJECTED
- **Failure modes:** Audit-completeness assumption (A1) is already known wrong. Single-instance regression tests miss adjacent variants — e.g., a CSRF fix on `/api/chat` may not cover `/api/chat/execute-plan` if test exercises only one route. Each fix can introduce a new finding the audit didn't see.
- **Falsified by:** Audit re-run finds *any* new C/H. Or: a property-based test catches a bug outside the audit list.
- **Why rejected:** Symptom-fixing. Ships *this* audit's findings; doesn't address the *next* audit. Direct match to "done-ness inflation" anti-pattern (knowledge base, 2026-04-28).

### B. Acceptance-first harness — SELECTED (with A's prioritized findings as the queue)
- **Failure modes:** (1) Harness calibrated to known bugs, not contracts → tests pass once bugs are fixed but contract-violating variants ship. **Mitigation:** harness derived from CONTRACTS (`CSRF MUST be enforced on every state-mutating route`; `user A MUST NOT see user B data on any read`; `sandbox MUST refuse arbitrary `Import` and reflection`), not from finding text. (2) Hypothesis flakiness → seed-pinned, failing examples persisted to `.hypothesis/examples/` as durable regressions. (3) PR #0 lands *red* → contradicts always-green CI norm. **Mitigation:** harness in `tests/harness/` marked `pytest.mark.harness`; CI runs `pytest -m "not harness"` until PR #11 promotes it.
- **Scaling:** Hypothesis state-machine for 2 users × ~10 operations × 34 routes is tractable (`max_examples=100` CI / `1000` nightly). RCE fuzzer corpus is bounded.
- **Falsified by:** Harness completes but catches < 8/12 audit findings → harness design wrong (not strategy). Fix harness; re-test. If after iteration still < 11/12, fall back to A.
- **Why selected:** Subsumes A. Aligns with the v9-reframe lesson — "eval-framework on the critical path because every other claim depends on it" (knowledge base, 2026-04-25).

### C. Security-boundary rewrite — REJECTED for v2 close-out
- **Failure modes:** Refactor on a buggy codebase amplifies bugs. 34-route migration in one PR is unreviewable; staged migration leaves bimodal state for weeks. New layer has systemic-bug risk.
- **Verdict:** Architecturally tempting, operationally hostile. **Track for v2.2** — once harness exists, the refactor can be validated continuously.

### D. Freeze v2, restart as v3 — REJECTED
- **Failure modes:** Discards 8 plans of completed work (raster pipeline, data validation, eval framework) that have **zero** audit findings. The 12 findings cluster in web/auth/state — 11 of 12 are in `app.py`, `blueprints/`, `static/js/`, plus one in OpenAI provider. Tools/raster/geo logic is unaffected. v3 will hit identical issues unless framework choice is correct day-1; track record (12 findings without it) suggests it won't be.
- **Verdict:** Premature pessimism; misdiagnoses the failure surface.

---

## 5. Selected Approach — "Acceptance-First Hardening"

### 5.1 Three-stage sequence

**Stage 0 — PR #0: Adversarial harness (1.5 days)**
Build the test machinery the audit revealed as missing. Lands with all-red expected. Quantifies the bug surface as a number, not a guess.

**Stage 1 — PRs #1-#10: Drive fixes against red harness (7-9 days)**
Order: C2+X1 → C1 → C3+X2 → C4 → H3 → H1+M1+M2 → H2 → H4 → M3 → M4 (audit's order; rationale: CSRF unblock first, then RCE, then isolation, then UX). Each PR's gate:
1. Targeted harness test was red on `main` (proves fix is needed).
2. Targeted harness test goes green after fix (proves fix works).
3. No other harness test regresses (proves fix is scoped).
4. Pre-existing 1,435-test suite stays green (proves no collateral damage).
5. Coverage on touched module +10pp (proxy for adequate testing).

**Stage 2 — PR #11: Audit re-run + soak (1 day + 30-day calendar)**
- Run `/critical-review --adversarial` on the v2 branch.
- Run an LLM-driven re-audit using `07-v2-audit-findings.md` as a checklist with explicit instruction "find findings the original audit MISSED."
- Promote `tests/harness/` to required CI gate.
- Soak: 30 calendar days with nightly harness run; zero regressions allowed.

### 5.2 Trade-offs accepted

- **+2 day upfront harness cost.** Accepted because (a) harness becomes the v2.2 acceptance gate, amortizing the cost, (b) catches bug variants beyond the audit's checklist.
- **Defer the un-rescoped portions of plans 07/09/11/12/13 to v2.2** (rescoped portions already shipped per `docs/v2/README.md`). **[v1.1]** Accepted because (a) adding the un-rescoped surface before baseline is proven invites the same bug class on new code, (b) the un-rescoped portions (plan 07 live bake-off, plan 09 frontend, plan 11 JS, plan 13 load test) each touch `chat.py` SYSTEM_PROMPT, frontend, or production config — the exact regions the audit found broken or unverified.
- **C4 ships with path B (per-user filter), not path A (restructure).** Accepted because path B is faster + lower-risk and the harness enforces the contract regardless of implementation. Path A becomes a v2.2 hardening item.
- **No frontend rewrite.** Accepted; H1 + M1 + M2 share one centralized `authedFetch` module, not a rewrite.

### 5.3 What this approach explicitly does NOT do

- Does **not** introduce Flask-Security, FastAPI migration, or per-user database (deferred to v2.2 if at all).
- Does **not** rewrite the chat tool-dispatch loop.
- Does **not** add new geospatial features.
- Does **not** change LLM provider mix.
- Does **not** ship until 30-day soak passes.

---

## 6. Experimental Plan (Mandatory)

### 6.1 PR #0 — Adversarial harness scaffold

**Files created:**

| Path | Purpose | Bugs it catches |
|---|---|---|
| `tests/harness/conftest.py` | `csrf_enforced_client`, `multi_user_clients` (2 authed clients, distinct DBs), `rce_corpus` fixtures | infrastructure for X1, X2 |
| `tests/harness/test_csrf_enforcement.py` | Iterate Flask URL map; for each state-mutating route assert 400 without CSRF token, 200 with | C2, M1 |
| `tests/harness/test_multi_user_isolation.py` | Hypothesis `RuleBasedStateMachine` with rules: `user_a_creates_layer`, `user_b_lists_layers`, `user_b_deletes_layer`. Invariant: `set(user_b_visible) ∩ set(user_a_only) == ∅`. Same for annotations and chat sessions. | C3, C4 (full class) |
| `tests/harness/test_rce_sandbox.py` | (a) Allow corpus: 50 example safe snippets. (b) Deny corpus: 30 escapes from `gist.github.com/escape-collection`-style references — `importlib`, `getattr` chains, `__class__.__bases__`, frame walks, generator-based escapes. Hypothesis fuzzer over Python AST sampling `Import`, `Attribute`, `Call`. | C1 |
| `tests/harness/test_secret_validation.py` | `FLASK_DEBUG=false` + default `SECRET_KEY` MUST raise `RuntimeError` at startup | H3 |
| `tests/harness/test_layer_store_identity.py` | Create `ChatSession`; verify it shares the same `dict` object as `state.layer_store` (not a copy) | H2 |
| `tests/harness/test_provider_mixed_content.py` | Golden assistant message with text + tool_use blocks; assert OpenAI converter emits both | M4 |
| `tests/harness/test_classify_timeout.py` | Mock classifier worker that sleeps 600s; assert request returns within timeout + worker is killed | H4 |
| `tests/harness/test_env_isolation.py` **[v1.1 — new finding N1]** | Assert no test process has live `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY` set unless using a sanctioned `responses`-style mock; assert no test in `tests/` makes a real network call to LLM providers (use `pytest-socket` to disable network and re-enable per-test for explicit live tests). **Dependency note:** `pytest-socket` is NOT in `requirements.txt:29` — PR #0 must add it (and `pytest-recording` or `responses` if mock-based assertion is preferred). | N1 |
| `tests/harness/test_frontend_auth.py` | Playwright: login → click "Delete layer" → assert request includes both `X-CSRF-Token` and `Authorization: Bearer`; click "Stop" mid-chat → assert SSE/WebSocket connection closes within 1s | H1, M1, M2 |
| `tests/harness/test_raster_pipeline.py` | Use `rasterio.MemoryFile` to fabricate 10×10 GeoTIFF fixture; exercise `raster_info`, `raster_value`, `slope`, `aspect`, `hillshade`, all 24 raster tools | M3 |
| `tests/harness/RED_BASELINE.md` | Snapshot expected red-test count after PR #0 lands. Used to detect tampering. | meta |

**Exit criteria for PR #0:**
- Harness contains tests for all 12 audit findings + N1 (13 total).
- **Each finding has at least one red assertion on `main`** that maps 1:1 to its finding ID (not "all harness tests fail" — some assertions in a multi-assertion test may pass on `main` because the bug is partial; what matters is that for every finding ID at least one assertion is red).
- Number of finding-IDs with at least one red assertion matches `RED_BASELINE.md` (no finding silently 100% green due to a bug-canceling-bug).
- CI gate is `pytest -m "not harness"` — green.
- Harness is opt-in: `pytest -m harness` runs the red suite locally.
- New runtime deps added to `requirements.txt`: `hypothesis`, `pytest-socket`, `pytest-playwright` (already-installed `playwright` browser binaries assumed; if not, `python -m playwright install chromium` is part of PR #0 setup).

### 6.2 PRs #1-#10 — Fix queue

(Order is audit's recommended sequence; rationale unchanged but each row gains its harness gate.)

| # | PR | Audit ID(s) | Harness test that flips green | Implementation skeleton | Effort |
|---|---|---|---|---|---|
| 1 | Real CSRF exemptions + secret-validation startup gate | C2, X1 partial | `test_csrf_enforcement.py` | `app.py:79` → drop env-flag hook. Register `csrf.exempt(view_function)` at blueprint registration in `blueprints/__init__.py`. Add `flask_wtf.csrf.CSRFError` handler returning JSON. | S |
| 2 | Hardened RCE sandbox | C1 | `test_rce_sandbox.py` allow + deny corpora | Replace `services/code_executor.py:20` substring scan with: (a) `ast.walk` whitelist (no `Import`, `ImportFrom`, `Call` to `__import__`/`importlib`/`eval`/`exec`/`open`/`compile`/`globals`/`__builtins__`/`getattr` with dunder strings); (b) execute in `multiprocessing.Process(target=worker, args=(code, queue))` with `resource.setrlimit(RLIMIT_AS, (memory_mb*MB, ...))` and `RLIMIT_CPU`; (c) `process.terminate()` after timeout; (d) network blocked via `socket.socket = lambda *a: raise PermissionError`; (e) optionally layer `RestrictedPython` for defense in depth. **Audit corpus before claiming safe.** | M |
| 3 | Owner-aware chat-session restore | C3, X2 | `test_multi_user_isolation.py` chat-session invariant | `blueprints/chat.py:89` — replace `get_chat_session(session_id)` with `get_chat_session_with_owner(session_id)`; if `owner_user_id != g.user_id` return 403. Don't take ownership on restore. | XS |
| 4 | Per-user layer + annotation isolation (path B) | C4 | `test_multi_user_isolation.py` layer + annotation invariants | Add `_filter_by_user(state.layer_store, g.user_id)` helper; gate `app.py:293` restore + `blueprints/layers.py:47,100` + `blueprints/annotations.py:37,205,275`. Tag `state.layer_store` entries with `owner_user_id` at insert time. **Track `state.geo_coco_annotations` and any other globals discovered during A5 verification.** | M |
| 5 | Refuse default SECRET_KEY in production | H3 | `test_secret_validation.py` | `app.py:62` — `Config.validate()` re-raises when `not FLASK_DEBUG`. Warning path only when DEBUG=true. | XS |
| 6 | Centralized `authedFetch` + WebSocket abort + plan-execute abort | H1, M1, M2 | `test_frontend_auth.py` (Playwright) | New `static/js/auth.js` exporting `authedFetch(url, opts)` and `authedAjax(opts)` — both attach `X-CSRF-Token` from `<meta>` tag and `Authorization: Bearer` from session storage. Migrate `static/js/main.js:5`, `static/js/chat.js:730`, `static/js/layers.js:153`. WebSocket: emit `chat_abort` event with session id; server cancels in-flight tool-dispatch loop. Plan execute: thread `AbortController` through `fetch(..., {signal})`. | M |
| 7 | ChatSession `layer_store` identity fix | H2 | `test_layer_store_identity.py` | `nl_gis/chat.py:316` — `layer_store if layer_store is not None else {}`. | XS |
| 8 | Auto-classify cancellable timeout | H4 | `test_classify_timeout.py` | `blueprints/osm.py:414` — replace `with ThreadPoolExecutor(...)` with `subprocess.run(["python", "-m", "nl_gis.classify_worker", input], timeout=300)`. OS kills worker on timeout. | S |
| 9 | Sample raster fixture | M3 | `test_raster_pipeline.py` (already in harness) | **[v1.1 — wire-up explicit]** Existing `tests/test_raster.py:29` expects filename `geog_wgs84.tif` and reads `Config.RASTER_DIR` (default `sample_rasters/` per `config.py:105`). Two coupled changes required: **(i)** commit fixture at `tests/fixtures/raster/geog_wgs84.tif` (≤ 50 KB, real GeoTIFF), keeping the filename the test already expects; **(ii)** add a session-scoped `conftest.py` fixture that sets `os.environ['RASTER_DIR']` to the absolute fixtures path BEFORE `config.Config` is imported, OR monkeypatches `Config.RASTER_DIR`. Without (ii), tests still read `sample_rasters/` and stay skipped. Alternative path: keep `sample_rasters/` and add `!sample_rasters/geog_wgs84.tif` exception to `.gitignore` with `git add -f` — simpler but pollutes the repo root. Recommended: option (i)+(ii). | XS |
| 10 | OpenAI text+tool_use mixed-content emit | M4 | `test_provider_mixed_content.py` | `nl_gis/llm_provider.py:376` — when assistant content contains both text + tool_use, emit text into `content` and tool_use into `tool_calls`. Mirror Anthropic path. | S |

### 6.3 Metrics + success criteria

| Metric | How measured | Pass threshold | Decision boundary |
|---|---|---|---|
| **Harness coverage of audit findings** | After PR #0, count harness tests that fail; map each to audit ID | ≥ 11/12 (allow 1 untestable) | < 8/12 → harness design wrong; iterate before PR #1 |
| **Per-PR regression-test pass after fix** | Targeted harness test was red on `main`, green after PR | 100% | Any miss → PR is incomplete; do not merge |
| **Per-PR cross-test stability** | All other harness tests + 1,435 pre-existing tests | No regressions | Any new failure → fix scope wrong; back to design |
| **Per-PR coverage delta** | `pytest --cov=<touched_module>` before vs after | +10pp on touched module | < +10pp → tests insufficient; add cases |
| **Audit re-run findings** | `/critical-review --adversarial` + LLM-driven re-audit | Zero new C/H | Any new C/H → fix-of-fix loop with new harness rule |
| **Soak duration** | Nightly `pytest -m harness` runs after PR #11 | 30 consecutive nights green | Any failure resets the clock |
| **Total engineering time** | Time from PR #0 start to PR #11 merge | P50 ≤ 11 d, P80 ≤ 16 d **[v1.1]** | > 20 days (P80 + 25%) → revisit selection (consider Strategy A pure or scope reduction) |

### 6.4 Expected outcomes per hypothesis

- **H1 (harness catches all audit findings):** PR #0 lands with ≥ 11 red tests. Each PR #1-#10 turns one red → green; PR #11 audit re-run finds zero new C/H. Plan succeeds.
- **H2 (harness misses some findings):** PR #0 lands with 7-10 red tests. Add missing harness rules (e.g., if frontend race conditions are missed → add Playwright concurrency tests). Re-run.
- **H3 (audit re-run finds new C/H not in original 12):** Treat as expected — that's the harness's value. Add harness rule for new finding, fix, re-audit. Iteration time bounded by harness build cost (already paid in PR #0).

---

## 7. Iteration Strategy (when something fails)

| Failure mode | Detection | First action | Escalation |
|---|---|---|---|
| Harness catches < 8/12 findings after PR #0 | RED_BASELINE.md doesn't match audit IDs | Inspect missed findings; identify missing harness layer (e.g., Playwright not installed → install). Add layer; re-baseline. | If still < 8/12 after 2 iterations → fall back to Strategy A pure for those findings; document gap. |
| A PR turns its red test green but breaks another harness test | CI failure on PR's harness suite | The fix's scope is wrong — likely a shared dependency. Trace; reduce scope. | If 3 attempts fail → split the PR; sequence with stricter contract isolation. |
| A PR breaks the pre-existing 1,435-test suite | CI failure on `not harness` suite | Diagnose the regression. If hidden coupling (e.g., test relied on disabled CSRF), update that test to use `csrf_enforced_client`. | If > 5 pre-existing tests break → the audit assumption A2 (independent PR boundaries) is failing; re-sequence remaining PRs. |
| Hypothesis test is flaky | Same test fails on different seeds across runs | Persist failing example via `.hypothesis/examples/`; harden invariant (likely a real race condition). | If race is in production code → escalate to a real bug, file as new finding. |
| Audit re-run finds a new C/H | PR #11 critical-review surfaces it | Add harness rule capturing the contract; fix; re-run audit. Budget: 0.5-1 day per new finding. | If > 3 new C/H surface → halt; the codebase has a class problem this plan hasn't caught. Consider Strategy C (security-boundary rewrite) targeted at the failure cluster. |
| Soak fails (regression in 30-day window) | Nightly harness CI red | Reset soak clock; bisect via `git bisect run pytest -m harness`. | If regression source is upstream (Flask, Anthropic, etc.) → pin version in `requirements.txt`. |

**Fastest path to reducing uncertainty:**
1. **Hour 1:** Enable CSRF in fixtures. Run existing 1,435-test suite. Number of currently-green tests that turn red is the *exact* proxy for hidden-bug risk in the codebase. This is the single highest-information experiment in the plan.
2. **Hour 2-4:** Build the multi-user isolation Hypothesis state machine. Run on `main`. Count violations. This calibrates the C4 effort estimate.
3. **Hour 4-12:** Build remaining harness components.

If hour-1 result shows 0-2 newly-red tests, the codebase is in better shape than the audit suggests; consider Strategy A pure to save 1-2 days. If hour-1 result shows ≥ 20 newly-red tests, the harness investment pays for itself many times over — proceed with full Strategy B+A.

---

## 8. Decisions Required from User Before Code

(Replaces the 5 decisions in `07-v2-audit-findings.md` §"Decisions still required" — those remain valid; the new ones below are additional.)

| # | Decision | Default | Why this default |
|---|---|---|---|
| D1 | Approve scope split: v2 close-out = 12 audit findings + N1 only; **un-rescoped portions** of plans 07/09/11/12/13 deferred to v2.2 (rescoped portions already shipped) **[v1.1]** | **Approve** | Adding new surface before baseline is proven invites bug recurrence on new code. |
| D2 | Approve "Acceptance-First Hardening" (Strategy B+A) over pure A | **Approve** | A is symptom-fixing; harness catches the bug *class*, including findings the original audit missed. |
| D3 | Audit re-run mechanism for "done" gate | `/critical-review --adversarial` + LLM re-audit | External re-audit costly; chained internal/LLM is reproducible and re-runnable. |
| D4 | Soak interpretation | 30 nightly harness runs without regression after PR #11 | Calendar 30 days post-merge is unobservable; nightly-green is concrete. |
| D5 | C4 implementation path | Path B (per-user filter on global) | Faster, lower risk; harness validates contract regardless of impl. Path A as v2.2 item. |
| D6 | Raster fixture mode | Committed ≤50 KB GeoTIFF at `tests/fixtures/raster/geog_wgs84.tif` (matching name expected at `tests/test_raster.py:29`) + `conftest.py` sets `RASTER_DIR` env var to that path before `config.Config` import (default `config.py:105` is `sample_rasters/` which is gitignored at `.gitignore:82`) **[v1.1]** | Reproducible, no per-test fabrication overhead. `MemoryFile` fallback acceptable. Without the conftest wire-up the fixture commit alone is invisible to tests. |
| D7 | RED_BASELINE.md tampering check | Required | Prevents accidental test that passes on main due to a bug-canceling-bug. |
| D8 | Harness in CI | Opt-in until PR #11 (`pytest -m "not harness"`); required after | Avoids breaking always-green CI norm during the 9-day fix window. |

**Pending from `07-v2-audit-findings.md` (still need answers):**
1. ✅ Approve all 12 findings as v2 scope? — preserved as-is.
2. Order — superseded by §6.2.
3. ✅ C4 path A or B? — answered above as D5.
4. ✅ Raster fixture mode — answered above as D6.
5. ✅ CSRF-enabled test suite OK to add? — built into PR #0 harness.

---

## 9. Cross-references

- **Audit source:** [`07-v2-audit-findings.md`](07-v2-audit-findings.md) — canonical finding text, line numbers, fix shapes.
- **Workflow inventory:** [`05-workflow-inventory.md`](05-workflow-inventory.md) — auditor's findings cross-reference workflows W01, W11, W20, W30, W42, W90.
- **Execution context:** [`06-execution-plan.md`](06-execution-plan.md) — phased framework rollout; v2 fixes precede Phase 1 P0.
- **Status board:** [`docs/v2/README.md`](../../docs/v2/README.md), [`.project_plan/STATUS.md`](../../.project_plan/STATUS.md).
- **Thought log (this analysis):** `docs/context/thought-logs/2026-05-02-v2-audit-fix-deep-think.md` **— stored in the cognitive-skill-agent skill repo, NOT in this SpatialApp checkout. Resolvable only via the cognitive-skills MCP tools (`search_knowledge`, file read against the skill repo path). Not auditable from this filesystem.** **[v1.1]**
- **Knowledge priors leveraged:**
  - SpatialApp v9 reframe (2026-04-25) — eval-framework on critical path.
  - Done-ness inflation anti-pattern (2026-04-28) — never claim "shipped" without acceptance evidence.
  - Gemini 2.5 Flash prompt-bloat fragility (2026-04-18) — relevant to any chat.py touchpoint.

---

## 10. Open residual risks (knowingly accepted)

1. **Hypothesis can prove violations exist; cannot prove violations don't exist.** A green Hypothesis run with 1000 examples does not prove the contract holds — only that no counterexample was found in 1000 attempts. Documented in test docstrings.
2. **AST sandbox is hard.** Python sandboxing is a research-grade adversarial domain. Even with AST whitelist + RLIMIT + subprocess, sophisticated escapes are possible. Defense in depth (§6.2 PR #2) makes it hard but not impossible. Recommendation in v2.2: replace with WASM-based sandbox (Pyodide-in-worker) if `execute_code` becomes important.
3. **Frontend tests via Playwright are slow.** Adds 30-60s to CI. Acceptable cost.
4. **Cost of LLM re-audit (PR #11):** 1 model call against full audit doc. ~$0.02 per Gemini run; budget noise.
5. **30-day soak window.** Calendar time. If urgent ship needed, can compress to 7 nights with explicit ack of residual risk.
