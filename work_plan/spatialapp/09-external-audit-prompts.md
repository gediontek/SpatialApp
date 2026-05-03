# External Audit Prompts — v2 Close-out Plan Review

**Purpose:** Six targeted prompts for an independent reviewer (different LLM model, human reviewer, or a fresh agent session) to adversarially audit the two plan documents:

- **Audit doc:** [`07-v2-audit-findings.md`](07-v2-audit-findings.md) — 12 findings + 3 cross-cutting test gaps
- **Strategy plan:** [`08-v2-bugfree-plan.md`](08-v2-bugfree-plan.md) — Acceptance-First Hardening (Strategy B+A)

**How to use:** Paste each prompt verbatim into your reviewer of choice. Each prompt is self-contained — does not assume the reviewer has read prior context. Run them **in parallel** (different reviewers / different sessions) so their findings are independent. Aggregate findings by class (strategy, completeness, assumptions, etc.) before deciding what to revise in the plan.

**Recommended reviewer mix:**
- Prompts 1, 2, 4, 6 → use a **different model family** than the one that wrote the plan (e.g., if Claude wrote it, audit with Gemini 2.5 Pro or GPT-5).
- Prompts 3, 5 → use a **fresh agent session** (cold context) — these need codebase access to verify, not opinion.
- For maximum signal, run all 6. For budget run, prioritize **1 + 3 + 5** (strategy + completeness + pre-mortem).

---

## Prompt 1 — Strategy Critique (the meta-decision)

```
You are a Principal Software Engineer doing an adversarial review of a remediation
strategy for a security audit. You are NOT here to validate; you are here to find
the strategy's flaws.

Context: A web application (Flask + SQLite + Anthropic/OpenAI/Gemini providers,
Python 3.13, ~132 modules, ~34 routes, 1,435 tests passing) received an external
security audit returning 12 findings (4 Critical RCE/CSRF/multi-user-isolation,
4 High auth/state, 4 Medium UX/format) plus 3 cross-cutting test-infrastructure
gaps (CSRF disabled in fixtures, single-user DB tests, 49 skipped tests).

Read these two files (paths relative to the SpatialApp repo root, or use the
absolute paths /Users/gedionteklemariam/Documents/projects/SpatialApp/work_plan/spatialapp/...):
- work_plan/spatialapp/07-v2-audit-findings.md  (the audit)
- work_plan/spatialapp/08-v2-bugfree-plan.md    (the proposed remediation strategy)

The plan selects "Acceptance-First Hardening" — build an adversarial test harness
(PR #0) before fixing anything, then drive fixes against the red harness. It
rejects three alternatives: (A) PR-by-PR per audit doc, (C) replace scattered
enforcement with one new security_layer.py, (D) freeze v2 and rebuild as v3.

Your task — produce a structured critique:

1. SELECTION CHALLENGE
   - Is the rejection of Strategy A defensible? What concrete scenario makes A
     superior to B+A?
   - Is the rejection of Strategy C defensible? Could the harness + a layered
     refactor be done in parallel rather than serial?
   - Is the rejection of Strategy D defensible? Identify specific v2 components
     where retrofit is genuinely impossible.
   - Is there a Strategy E the plan missed? (e.g., contract-driven development,
     formal verification of the security boundary, dependency injection of an
     auth context.) Name it and argue for it.

2. OBJECTIVE-FUNCTION CHALLENGE
   - The plan reframes "bug-free" as "zero re-detected C/H + 30 nightly harness
     greens." Is this honest, or does it enable shipping with known bugs the
     harness happens not to test?
   - What's a falsifiable contract the plan is NOT enforcing?

3. SCOPE-SPLIT CHALLENGE
   - The plan defers the *un-rescoped portions* of plans 07/09/11/12/13 to v2.2
     with "same harness gate." (The rescoped portions of those plans already
     shipped per docs/v2/README.md — DO NOT re-flag that as deferred.) Is
     deferral of the un-rescoped portions genuinely safe, or does it accumulate
     technical debt that makes v2.2 harder than v2 was?
   - Specifically: plan 09's deferred frontend (WebSocket UI), plan 11's
     deferred JS (chart/dashboard rendering), plan 13's deferred load test —
     is it correct to defer these *after* security fixes, or do they overlap
     with the security work in ways the deferral hides?

4. EFFORT-ESTIMATE CHALLENGE
   - The plan budgets 11 engineering days (1.5d harness + 7-9d fixes + 1d
     audit-rerun). Identify the 3 most likely overrun causes. For each, estimate
     the realistic worst case in days.

Output format:
- One section per task (1-4).
- Each finding labeled S1, S2, ... with severity (Critical/High/Medium/Low) and
  one-sentence justification.
- End with: "STRATEGY VERDICT: APPROVE / APPROVE-WITH-REVISIONS / REJECT"
  plus a 3-sentence rationale.

Be exacting. Do not be polite. If a section finds nothing, say so explicitly
("No findings — the plan handles this correctly because [reason].").
```

---

## Prompt 2 — Harness Adequacy (the technical core)

```
You are a Principal Test Engineer with deep expertise in property-based testing
(Hypothesis), security test design, and Flask/Python test infrastructure. You
are auditing whether a proposed test harness will actually catch the bugs it
claims to catch.

Read work_plan/spatialapp/08-v2-bugfree-plan.md (relative to SpatialApp repo
root), especially section 6.1
("PR #0 — Adversarial harness scaffold") and 6.2 (the 10 fix PRs and the
harness tests they target).

The harness components are:

| Component | Bugs it claims to catch |
|---|---|
| test_csrf_enforcement.py | C2, M1 (broken Flask-WTF exemptions; UI delete fails) |
| test_multi_user_isolation.py (Hypothesis state machine) | C3, C4 (chat-session ownership bypass; layer/annotation isolation) |
| test_rce_sandbox.py (AST allow + deny corpus + AST fuzzer) | C1 (execute_code RCE) |
| test_secret_validation.py | H3 (default SECRET_KEY in prod) |
| test_layer_store_identity.py | H2 (layer_store falsy-empty bug) |
| test_provider_mixed_content.py | M4 (OpenAI text-block dropping) |
| test_classify_timeout.py | H4 (ThreadPoolExecutor timeout doesn't release) |
| test_frontend_auth.py (Playwright) | H1, M1, M2 (bearer auth, delete UI, Stop button abort) |
| test_env_isolation.py | N1 (test process must have no live LLM provider keys / no live network calls to providers — `pytest-socket` recommended) |
| test_raster_pipeline.py (rasterio.MemoryFile) | M3 (24 raster tests skip) |

Your task — for EACH harness component above, answer:

1. CONTRACT FIDELITY
   - Does this harness test the CONTRACT (the invariant that must hold) or just
     the symptom of the audit finding? Show the difference with a specific bug
     variant the test would and would NOT catch.

2. ESCAPE BYPASSES
   - Name 2 concrete inputs / scenarios where the test passes green but the
     production bug still exists. (e.g., for the AST sandbox: a frame-walking
     escape via a generator's gi_frame.f_globals chain — would the AST whitelist
     catch this?)

3. FLAKINESS RISK
   - For Hypothesis state-machine tests: estimate failure-reproducibility
     probability. Are seeds pinned? Are failing examples persisted to
     .hypothesis/examples/? What's the false-flake rate at max_examples=100?

4. INFRASTRUCTURE GAPS
   - The plan says the multi-user isolation harness needs `multi_user_clients`
     fixture (2 authed clients with distinct DBs). What other module-level
     globals (besides state.layer_store and state.geo_coco_annotations) might
     contaminate cross-test isolation? List them by `grep`-able pattern.

5. GAP — MISSING HARNESS COMPONENTS
   - Identify 2-3 audit findings that the proposed harness does NOT adequately
     cover (give specific file:line and explain why).

Then write a SINGLE NEW HARNESS COMPONENT not in the plan that you believe
should be added. Specify: filename, fixtures used, properties/contracts asserted,
and which audit finding(s) it would catch.

Output format:
- Per-component table (component × tasks 1-5).
- Final section: "MISSING COMPONENT" with concrete spec.
- Severity flags inline: 🔴 Critical, 🟡 High, 🟢 Low.

Do not give a passing grade if any component fails task 1 or 2. State the
failures bluntly.
```

---

## Prompt 3 — Findings Completeness Re-Audit

```
You are a Principal Security Engineer doing an INDEPENDENT re-audit of a Flask
web application. The previous external audit returned 12 findings but
self-reported ~85% surface coverage. Your job is to find what the previous
auditor MISSED.

Repository to audit: /Users/gedionteklemariam/Documents/projects/SpatialApp

Stack: Flask + SQLite (WAL) + Anthropic/OpenAI/Gemini LLM providers + Valhalla
(routing) + rasterio (raster ops) + Playwright (e2e). Python 3.13. ~132
modules, ~34 routes, ~1,905 functions.

Previous audit findings (DO NOT repeat these — find NEW ones):
- C1: execute_code AST sandbox bypass
- C2: Flask-WTF CSRF exemptions broken
- C3: chat-session DB-restore ownership bypass
- C4: multi-user layer + annotation isolation broken
- H1: frontend bearer-token gaps
- H2: layer_store falsy-empty bug
- H3: default SECRET_KEY accepted in prod
- H4: ThreadPoolExecutor timeout doesn't release
- M1: layer-delete UI fails (no CSRF/auth)
- M2: Stop button doesn't abort WebSocket / plan-execute
- M3: 24 raster tests skip (sample_rasters/ missing + gitignored at .gitignore:82)
- M4: OpenAI text-block dropping in mixed-content tool messages
- N1: test env contamination — tests/test_chat_api.py:11 clears ANTHROPIC_API_KEY only, so tests with a live GEMINI_API_KEY make real Gemini calls

Your task — find findings the prior audit MISSED. Focus areas (because the
prior audit's coverage gaps were noted in these regions):

1. SURFACE THE PRIOR AUDIT EXPLICITLY UNDER-COVERED
   - Raster tools (24 raster handlers) — what bugs hide under skipped tests?
   - WebSocket / SSE chat path — what state can desync?
   - LLM provider abstraction (nl_gis/llm_provider.py) — only one OpenAI bug
     was found; check Anthropic + Gemini paths for symmetric bugs.
   - Valhalla routing (services/valhalla_client.py) — input validation,
     timeout, error propagation.
   - Database (services/database.py) — SQL injection, missing indexes,
     migration race, WAL checkpoint behavior under concurrent writes.

2. UNAUDITED ATTACK SURFACES
   - File upload paths: any endpoint that takes a file? Path traversal?
     ZIP/Shapefile bombs? GeoTIFF zip-slip?
   - URL / referer parsing: any endpoint that fetches a user-provided URL?
     SSRF to localhost:5000 (own server) or cloud metadata (169.254.169.254)?
   - LLM prompt-injection: the chat tool-dispatch loop trusts LLM tool-call
     arguments. Where do tool args become SQL/shell/file-path inputs?
   - Geospatial coordinate parsing: ValidatedPoint enforcement actually applied
     everywhere user-supplied coords flow?

3. STATE-MACHINE BUGS
   - Concurrency: is `annotation_lock` and `layer_lock` actually held everywhere
     they should be? Find a missing lock acquisition.
   - Idempotency: any endpoint that mutates state and isn't safe to retry?
   - Race windows: TOCTTOU on layer-name uniqueness, session-id collision,
     file-path resolution.

4. CRYPTO + AUTH HYGIENE
   - Token storage: how are bearer tokens persisted? Plaintext? Salted hash?
   - Session timeout: do sessions expire? Are revoked tokens rejected?
   - Password policy (if any user passwords exist).
   - JWT signing keys, refresh token handling, CORS/Origin checks.

5. SUPPLY CHAIN
   - requirements.txt: any pinned package with a known CVE in 2025-2026?
   - Dockerfile: base image age, root user, secret leakage in layers.
   - .github/workflows: any workflow that takes user input (PR title/body) into
     a shell command (workflow injection)?

6. CONFIGURATION
   - .env handling: any default value that is a security risk?
   - Logging: are LLM prompts/responses logged? PII redaction?
   - Error messages: any 500 response that leaks stack traces or path info?

For EACH new finding:
- ID: N19, N20, ... (N1-N18 are already taken — see `12-next-audit-input.md` §1.1 for the full list; start from N19)
- Severity: Critical / High / Medium / Low
- File:line
- Symptom (one sentence)
- Reproduction (one paragraph or shell command)
- Recommended fix shape (one paragraph)
- Whether the proposed harness in 08-v2-bugfree-plan.md would catch it (yes/no
  + which test or "not covered")

Output format: one block per finding. End with:
- "NEW FINDINGS: <count> Critical, <count> High, <count> Medium, <count> Low"
- "PRIOR-AUDIT COVERAGE ESTIMATE (revised): X%"
- "HARNESS COVERAGE OF NEW FINDINGS: X / total"

Reject the temptation to re-list prior findings. Find NEW ones or report
"surface clean" with explicit reasoning per focus area (1-6).
```

---

## Prompt 4 — Adversarial Assumption Audit

```
You are a Principal Research Engineer reviewing the assumption set behind a
remediation plan. Your specialty is finding fragile assumptions that the plan
authors took for granted.

Read work_plan/spatialapp/08-v2-bugfree-plan.md (relative to SpatialApp repo
root) section 2 ("Assumption Audit
(Adversarial)") which lists 10 assumptions A1-A10 with confidence levels.

Your task:

1. CHALLENGE EACH ASSUMPTION
   For each of A1-A10, do one of:
   (a) AGREE — and add a *deeper* assumption hidden inside it that the author
       missed.
   (b) DISAGREE — name the counter-evidence and a concrete scenario where the
       assumption fails in production.
   (c) RECLASSIFY — argue the confidence level is wrong (e.g., A8 is marked
       Medium but should be Low; or A2 is marked Medium but should be High).

2. ASSUMPTIONS NOT IN THE LIST
   Identify 3 unstated assumptions the plan depends on but didn't surface.
   Examples to look for:
   - Assumptions about the development environment (Python version, OS,
     dependency versions).
   - Assumptions about the auditor's incentive alignment (will they actually
     re-run? will they re-run thoroughly?).
   - Assumptions about test-runner behavior (Hypothesis defaults,
     pytest-xdist isolation, asyncio test loops).
   - Assumptions about how the plan's "30-night soak" interacts with normal
     development (will main change during the soak? does each change reset
     the clock?).
   - Assumptions about the user's behavior (will the user actually answer
     D1-D8? what if D1 is rejected?).

3. CASCADE ANALYSIS
   Pick the assumption you believe is *most fragile*. Trace the cascade if it
   fails: which fix PRs become invalid? Which harness tests become wrong?
   What's the recovery cost?

4. COUNTERFACTUAL
   "If exactly one assumption in the plan turned out to be wrong, which would
   I least want it to be?" Justify in 4 sentences.

Output format:
- Per-assumption (A1-A10): one block with verdict (AGREE+ / DISAGREE / RECLASSIFY)
  and 2-4 sentences.
- "UNSTATED ASSUMPTIONS": 3 numbered findings.
- "CASCADE ANALYSIS": chosen assumption + dependency walk.
- "COUNTERFACTUAL": 1-paragraph answer.

Be ruthless about "high confidence" assumptions — those are where confirmation
bias hides.
```

---

## Prompt 5 — Pre-mortem (T+2 weeks)

```
You are a Principal Engineer running a pre-mortem on a security remediation
plan that just shipped. Today is fictional date: PR #11 merged 2 weeks ago.
Something has gone wrong in production. Your job is to write three distinct
post-incident reports describing what failed.

Read the full plan (relative to SpatialApp repo root, or absolute under
/Users/gedionteklemariam/Documents/projects/SpatialApp/):
work_plan/spatialapp/08-v2-bugfree-plan.md

Constraints:
- The harness was built (PR #0).
- All 10 fix PRs landed and were green per the plan's gating criteria.
- The audit re-run (PR #11 part 1) reported zero new C/H.
- The 30-night soak (PR #11 part 2) was green for 22 nights.
- Then something failed.

Write THREE post-incident reports, each describing a fundamentally different
failure mode (not three flavors of the same bug). For each:

INCIDENT N (Date: ~2 weeks post-merge)
- TITLE: one line
- SEVERITY: P0 / P1 / P2
- DETECTION: who/what noticed first, and how late it was caught
- IMPACT: what broke, who was affected, blast radius
- ROOT CAUSE: 5-whys chain ending at a design decision in the plan that enabled
  this failure
- WHY THE PLAN'S SAFEGUARDS DIDN'T CATCH IT: name the specific harness component
  or gating check that should have caught it but didn't, and explain why it was
  blind to this scenario
- WHAT THE PLAN SHOULD HAVE INCLUDED: a concrete addition (test, gate, design
  change) that would have prevented this incident

Required failure-mode diversity (one report per category):
- INCIDENT 1: A bug variant the harness type-class missed (e.g., harness tests
  isolation between 2 users, but the bug shows up at 3+ users; or harness tests
  CSRF on routes the audit listed, but a route added during the fix work has no
  CSRF).
- INCIDENT 2: A second-order failure caused by a fix's side-effect on something
  the plan considered out-of-scope (e.g., the per-user filter in C4 broke the
  Gemini eval framework's batch operations; or the new authedFetch broke an
  in-flight admin script).
- INCIDENT 3: A failure of the *meta-process* — e.g., the audit re-run was
  done by Claude on the same conversation context as the plan author and just
  agreed with itself; or the soak's "no regression" was technically true but a
  warning was downgraded to silent; or the user merged plan 09 (deferred) into
  v2 close-out under deadline pressure.

Then write a META section:

PATTERN ACROSS INCIDENTS
- What's the common failure class across all three?
- Is there a single safeguard the plan could add that would catch all three?

FINAL VERDICT
- "If you had to ship this plan as written today, what's your P(at least one
  C/H bug in production within 30 days)?" Express as a percentage with
  reasoning.
- "What's the single highest-leverage modification to the plan that drops that
  probability the most?"

Write at the technical depth of a real post-incident report. No hand-waving.
Specific file paths, line numbers, attack scenarios.
```

---

## Prompt 6 — Quantitative Realism Check

```
You are a Principal Engineering Manager reviewing the effort estimate and
acceptance criteria of a remediation plan for budget approval.

Read work_plan/spatialapp/08-v2-bugfree-plan.md (relative to SpatialApp repo
root), focus on:
- Section 6.2 (per-PR effort estimates: XS/S/M)
- Section 6.3 (metrics + success criteria table)
- Section 7 (iteration strategy)
- Section 10 (residual risks)

Your task — pressure-test the numbers:

1. EFFORT ESTIMATE BREAKDOWN
   Convert XS/S/M to days using your own scale and produce a Gantt-style
   bottom-up estimate. Include:
   - PR #0 (harness): broken into per-component days
   - Each PR #1-#10: dev + review + revision + merge time
   - PR #11 audit re-run: realistic time including any fix-of-fix loops
   - 30-night soak: include the variance — what's the probability of 0
     regressions in 30 nights given a 1,435-test suite + harness?
   Total estimate vs the plan's P50=11 / P80=16 day budget (revisit threshold > 20 d). Show your own variance.

2. ACCEPTANCE CRITERIA HONESTY
   The plan claims:
   - "≥ 11/12 audit findings caught by harness" — what's the realistic count?
   - "+10pp coverage on touched module" — is this measurable cleanly given
     branch coverage edge cases (try/except, unreachable defensive code)?
   - "30 consecutive nights without regression" — what's the upstream-pin
     strategy if a Flask security release lands during the soak and shifts
     behavior?
   For each criterion, say: ACHIEVABLE / OPTIMISTIC / UNREALISTIC and revise.

3. HIDDEN COSTS
   Identify costs the plan didn't budget:
   - Reviewer time (PR review hours not in dev days).
   - CI compute increase (Hypothesis with max_examples=1000 nightly + Playwright).
   - Maintenance burden of the harness post-merge (who updates it when routes
     change?).
   - The opportunity cost of deferring the un-rescoped portions of plans
     07/09/11/12/13 (the rescoped portions already shipped per
     docs/v2/README.md; deferred slice is plan 07 live bake-off, plan 09
     frontend, plan 11 JS, plan 13 load test) — quantify lost value.

4. METRIC GAMING
   For each "pass threshold" metric in §6.3, name how a developer under
   deadline pressure could game it without violating the letter:
   - "+10pp coverage" → write tests that hit lines without asserting behavior.
   - "30 consecutive nights green" → relax flaky-test reruns; mark hard tests
     as expected-fail.
   - "Zero re-detected C/H" → re-audit instructions that nudge toward
     confirmation.
   For each, propose a counter-measure.

5. FALSIFIABILITY GRADE
   Score the plan's falsifiability on 5 dimensions, 1-5 each:
   - Are the success criteria measurable without judgment? __/5
   - Could a hostile reviewer prove the plan failed using only the plan's own
     metrics? __/5
   - Are failure modes named in advance with named recovery? __/5
   - Are the experiments (hour-1 spike, harness count, audit re-run) genuinely
     informative or ceremonial? __/5
   - Could results be challenged a year from now with new evidence and the
     plan still rule on them? __/5
   Total: __/25. Anything below 18 means the plan needs revision.

Output format:
- Per-task structured response.
- Final section: "REVISED ESTIMATE" — your bottom-up number with confidence
  interval, e.g., "16 days [12-22]."
- "RECOMMEND: APPROVE / APPROVE-WITH-REVISIONS / REJECT" with one paragraph.
```

---

## Aggregating findings

When the prompts return:

1. **Group by class:** strategy gaps (P1) | harness gaps (P2) | new findings (P3) | wrong assumptions (P4) | new failure modes (P5) | estimate revisions (P6).
2. **Severity-rank** every finding.
3. **For each Critical/High finding** — decide: revise the plan, add a harness component, or accept as documented residual risk.
4. **Write back** the revisions to `08-v2-bugfree-plan.md` as a v2 of that doc; preserve the v1 as `08-v2-bugfree-plan-v1.md` for the audit trail.
5. **Re-run prompts 1, 3, 5** against the revised plan. Three rounds max — if findings keep growing, the plan has a structural problem that needs a different deep-think pass.

**Decision boundary:** if the aggregate review finds **≥ 3 Critical** or **≥ 5 High** or any **REJECT verdict** from a prompt that supplies coherent rationale → revise the plan before any code. If findings are **< 3 Critical and < 5 High and all verdicts are APPROVE / APPROVE-WITH-REVISIONS** → proceed to the hour-1 CSRF spike.
