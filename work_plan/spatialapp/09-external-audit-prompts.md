# External Audit Prompts — SpatialApp v2 Re-Audit Pack

**Purpose:** Adversarial prompts for an independent reviewer (different LLM model, human reviewer, or a fresh agent session) to re-audit the SpatialApp v2 implementation after 4 audit rounds + 30 closed findings.

**Status (2026-05-10):**
- The remediation plan in `08-v2-bugfree-plan.md` has fully shipped (all 12 audit findings + 18 self-discovered N-findings closed; see `12-next-audit-input.md` §1.1 for the audit log).
- 4 external audit rounds completed: 31 → 81 → 93 → 86. Each round produced fresh findings the prior round missed.
- **Next finding ID: N31.** IDs N1-N30 are taken (N25 was consumed by the auditor at audit-4 as already-fixed).

**How to use:** Paste each prompt verbatim into your reviewer of choice. Each prompt is self-contained — does not assume the reviewer has read prior context. Run them **in parallel** (different reviewers / different sessions) so their findings are independent.

**Prompt status map:**

| Prompt | Status | When to run |
|---|---|---|
| **Prompt 3 — Findings Completeness Re-Audit** | **PRIMARY** — run every audit | Always. This is the prompt that has produced almost all real findings across audits 2-4. |
| **Prompt 7 — Capability-Honesty Sweep** (NEW post audit-4) | **PRIMARY** — run every audit | Always. Targets the doc-vs-runtime drift class that produced N26/N28/N30. |
| **Prompt 8 — Auth-Mode Parity Sweep** (NEW post audit-4) | **PRIMARY** — run every audit | Always. Targets the prod-vs-dev parity class that produced N27/N29. |
| Prompt 5 — Pre-mortem | Optional | Run as cold-context probe before any major release. |
| Prompts 1, 2, 4, 6 — Plan-review prompts | **ARCHIVED** | The plan they review has shipped. Re-run only if a new strategic plan is being drafted. Kept below for historical context. |

**Recommended reviewer mix:**
- Prompts 3, 7, 8 → use a **fresh agent session** (cold context) with codebase access — these need to verify against actual files, not opinion.
- For maximum signal, run all 3 primary prompts in parallel. For budget run, prioritize **Prompt 3 + Prompt 7** (most leverage per hour).
- Use a **different model family** than the one currently maintaining the codebase (e.g., if Claude is maintaining, audit with Gemini 2.5 Pro or GPT-5) for independence.

---

## Prompt 1 — Strategy Critique (the meta-decision)  *[ARCHIVED]*

> **Archived 2026-05-10.** The plan in `08-v2-bugfree-plan.md` has fully shipped (all 12 audit findings + 18 self-discovered N-findings closed). This prompt reviews a strategic decision that no longer needs reviewing. Kept verbatim below for the audit trail. Skip unless drafting a new strategic plan.


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

## Prompt 2 — Harness Adequacy (the technical core)  *[ARCHIVED]*

> **Archived 2026-05-10.** The harness was built (PR #0 then iterated across 17 cycles) and has caught real bugs across 4 audit rounds. This prompt's "will the harness work?" framing is now answered by the closed-finding count. Skip unless a new harness component is being designed.


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
web application. Four prior external audit rounds have closed 30 findings
(scores: 31 → 81 → 93 → 86). Each round produced fresh findings the prior
rounds missed. Your job is to find what audits 1-4 MISSED.

Repository to audit: /Users/gedionteklemariam/Documents/projects/SpatialApp
Read first: work_plan/spatialapp/12-next-audit-input.md (handoff doc, header
is the source of truth for repo state, test counts, and next-finding-ID).

Stack: Flask + SQLite (WAL) + Flask-SocketIO + Anthropic/OpenAI/Gemini LLM
providers + Valhalla (routing) + rasterio (raster ops) + Leaflet/deck.gl
(frontend) + Playwright (e2e). Python 3.13. ~132 modules, ~34 routes, 82
LLM-callable tools.

Previous findings (DO NOT repeat — see 12-next-audit-input.md §1.1 for the
authoritative list with commit shas. Summary by class):
- Sandbox / RCE: C1, N18 (AST allowlist + RLIMIT + env-strip regression)
- CSRF / auth: C2, H1, M1, N6, N19, N27, N29
- Multi-user isolation: C3, C4, N2, N3, N7, N13, H2
- LLM provider: M4, N12, N16, N28, N30
- Rate limit / DoS: N11, N12, N14, BL1
- Input validation / size cap: N8, N9, N14, N16
- Info-leak: N10, M3
- Frontend / UX: H1, M1, M2, N20, N22, N26, N27
- Doc / capability honesty: N23, N24, N28, N30
- Operational: H3, H4, N1, N4, N17

Your task — find findings audits 1-4 MISSED. Focus areas (audit-4 surfaced
several user-facing bugs in these regions; audits 1-3 had under-covered them):

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

## Prompt 4 — Adversarial Assumption Audit  *[ARCHIVED]*

> **Archived 2026-05-10.** Reviews the 10 assumptions A1-A10 in the shipped plan. Useful as a teaching exercise; not load-bearing for ongoing audit work.


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

## Prompt 5 — Pre-mortem (T+2 weeks post-deploy)

```
You are a Principal Engineer running a pre-mortem on a Flask web application
that just shipped to production after 4 audit rounds + 30 closed findings.
Today is fictional date: 2 weeks after first real-user traffic. Something has
gone wrong. Your job is to write three distinct post-incident reports
describing what failed.

Read first (relative to repo root, absolute under /Users/gedionteklemariam/Documents/projects/SpatialApp/):
- work_plan/spatialapp/12-next-audit-input.md (audit log + closed findings)
- work_plan/spatialapp/14-pre-deploy-dryrun.md (operator-side residuals)
- CLAUDE.md (architecture decisions)

Constraints:
- 30 findings (12 audit + 18 self-discovered, IDs C1-C4 / H1-H4 / M1-M4 /
  N1-N30) are closed with regression tests in tests/harness/, tests/golden/,
  tests/test_*.py. The full unit suite is green.
- 4 external audit rounds returned 31 → 81 → 93 → 86. Audit-4 surfaced 5
  fresh findings (N26-N30) that audits 1-3 missed — meaning the audit pipeline
  itself has a known false-negative rate.
- gunicorn dry-run (Cycle 16) was green; SECURITY_CONTACT was set for
  production; the operator-checklist 8 items in 14-pre-deploy-dryrun.md were
  all completed.
- Then, 2 weeks into real-user traffic, something failed.

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
- INCIDENT 1: A bug-class the test suite (unit + harness + golden) missed
  because every test scenario uses small fixtures (1-6 features in tight
  bboxes). Example precedents: the Cycle 12 wide-area-render bug, the N22
  cluster-bubble miss. What's the next "many features over wide area"
  pathology? What about scale: 10k features? 100MB GeoJSON? 1k concurrent
  users? Pick one realistic scale boundary and walk the failure.
- INCIDENT 2: A second-order failure caused by a fix's side-effect — the
  audit-log shows several of these (N18 was the C1 sandbox env-strip
  breaking macOS user-site imports; N26 was the N7 isolation contract breaking
  the raster URL serve route). Pick a closed finding from §1.1 of
  12-next-audit-input.md and write a plausible second-order failure where
  THAT fix's defensive behavior broke something else.
- INCIDENT 3: A failure of the *meta-process* — e.g., the audit pipeline
  reaches a fixed point where successive audits stop finding new bugs because
  they probe the same surfaces; or the operator updated SECURITY_CONTACT in
  the env but a stale .env in a second deployment env still pointed at the
  placeholder; or the user merged a feature PR that added a new route bypassing
  every harness gate; or the make-eval ritual was skipped under deadline
  pressure.

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

## Prompt 6 — Quantitative Realism Check  *[ARCHIVED]*

> **Archived 2026-05-10.** Pressure-tests the plan's 11-day budget. The plan shipped over 17 cycles; the budget question is moot. Skip unless a new estimate is needed.


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

## Prompt 7 — Capability-Honesty Sweep  *[NEW post audit-4]*

```
You are a Principal Software Engineer doing a doc-vs-runtime drift audit on a
Flask + LLM application. Your job is to find every place where the app
ADVERTISES a capability that it does not actually have, or where the docs
state a number/contract/behavior that no longer matches the code.

This bug class produced 3 of audit-4's 5 findings (N26 raster URL, N28
Shapefile/GeoPackage advertised but error-only, N30 stale tool counts).
History suggests every audit round will find one or two more.

Repository to audit: /Users/gedionteklemariam/Documents/projects/SpatialApp
Read first: work_plan/spatialapp/12-next-audit-input.md (header has the
authoritative test counts and commit sha for cross-checking).

The 4 surfaces to sweep:

1. LLM TOOL DESCRIPTIONS vs HANDLER BEHAVIOR
   The chat tool dispatch surface lives in nl_gis/tools.py (schemas) +
   nl_gis/tool_handlers.py (implementations) + nl_gis/handlers/*.py
   (per-domain handlers). For EACH of the ~82 tool definitions, verify:
   - Does the description's claim list match what the handler returns?
   - Does the description name a parameter that the handler ignores?
   - Does the handler raise NotImplementedError / "not yet supported" / "use
     X instead" for any code path the description promises?
   - Does the handler advertise a format (Shapefile, GeoPackage, KML, etc.)
     that the runtime returns an error for?
   - Are required-parameter / optional-parameter splits in the JSON Schema
     consistent with what the handler validates?
   - For tools that produce a layer: does layer_add fire reliably, or does
     the handler sometimes return a payload with no `geojson` / `layer_name`?

   Cross-check the documented tool count: docs/TOOL_CATALOG.md vs the runtime
   `get_tool_definitions()` count vs any number embedded in the system prompt
   in nl_gis/chat.py. They should agree (or the doc/system-prompt should
   defer to the registry as authoritative — which is what N30 fixed).

2. FRONTEND TOOL-RESULT RENDERERS vs TOOL OUTPUTS
   In static/js/chat.js, the `case 'tool_result':` block dispatches on
   `result.action` (chart / animate_layer / show_3d_buildings / heatmap /
   etc.). For EACH action a handler can return, verify there is a
   non-fall-through renderer in chat.js. Fall-through to the JSON dump is
   the symptom Cycle 11 / Cycle 13 fixed (chart no-op, animate JSON dump,
   3D JSON dump). Look for new fall-throughs.

3. README + CLAUDE.md + .project_plan/STATUS.md vs ACTUAL CODE
   - CLAUDE.md "Quick Start" claims 236 tests; the actual test count
     (per `pytest --collect-only -q`) should match within 5%.
   - .project_plan/STATUS.md should not list "in progress" features that
     have shipped, or "shipped" features that are still error-only paths.
   - docs/TOOL_CATALOG.md sections should reflect the runtime registry.
   - Any README at any depth that claims "supports X" — does X work?

4. HEALTH / READINESS ENDPOINTS
   /api/health and /api/health/ready are read by deploy automation. Verify:
   - /api/health/ready returns ready=true ONLY when EVERY guarantee the
     application makes to its callers is met. (N29 was the gap: ready was
     true while paid LLM chat was open without auth.) What other
     guarantees should be in the readiness check that aren't?
   - /api/health does not leak per-user counts, secrets, or stack traces.
   - /metrics (Prometheus) does not expose per-user labels.

For EACH finding:
- ID: starts at N31 (N1-N30 taken)
- Severity: Critical / High / Medium / Low
- Surface: which of (1)-(4) above
- File:line of the description/doc
- File:line of the actual handler/code
- The drift in one sentence ("description says X, handler does Y")
- User-visible symptom (one paragraph, with reproduction if possible)
- Recommended fix shape

Output format: one block per finding. End with:
- "DRIFT FINDINGS: <count> Critical, <count> High, <count> Medium, <count> Low"
- "SURFACE COVERAGE: tools (<N> checked / <total>), renderers (<N>),
  docs (<N>), health (<N>)"
- "TOOL HONESTY GRADE: pass | needs-revision | fail" with a one-paragraph
  rationale.

Do not flag prior closed findings (see 12-next-audit-input.md §1.1).
```

---

## Prompt 8 — Auth-Mode Parity Sweep  *[NEW post audit-4]*

```
You are a Principal Security Engineer doing a prod-vs-dev parity audit on a
Flask + LLM application. Your job is to find every place where a feature
works in DEBUG mode but breaks (or worse: silently bypasses auth) when
deployed with FLASK_DEBUG=false + CHAT_API_TOKEN set.

This bug class produced 2 of audit-4's 5 findings (N27 annotation export
broken under auth, N29 readiness green while chat publicly open). History
suggests this is the highest-leverage class for production-readiness audits.

Repository to audit: /Users/gedionteklemariam/Documents/projects/SpatialApp
Read first:
- work_plan/spatialapp/12-next-audit-input.md
- work_plan/spatialapp/13-smoke-test-2026-05-03.md (live smoke test report)
- work_plan/spatialapp/14-pre-deploy-dryrun.md (gunicorn dry-run report)
- config.py (Config.DEBUG, Config.CHAT_API_TOKEN, Config.validate())

The matrix to sweep — for each of the 4 production-mode invariants, audit
every entry point:

1. AUTH MODE PARITY — every state-mutating route + every fetch site
   When CHAT_API_TOKEN is set:
   - Every fetch in static/js/*.js MUST go through `authedFetch` (or
     `$.ajax` with `authedAjaxBeforeSend`) so the Bearer header attaches.
     Direct `fetch()`, `window.location.href = '/api/...'`, or `<a href>`
     download links break under auth. (N27 was a `window.location.href`
     to /export_annotations/<format>.)
   - Every WebSocket connect MUST send the token in connect args.
   - Every server-side route that returns user data MUST require auth in
     prod. Special attention: routes added during the rolling fix work
     that may not have inherited the @require_api_token decorator.

2. CONFIG.VALIDATE() PROD GATING
   Config.validate() must FAIL-FAST on missing required prod settings.
   Audit-4 closed:
   - SECRET_KEY default is rejected
   - CHAT_API_TOKEN required for ready=true (N29)
   What else SHOULD be in there but isn't? Candidates to consider:
   - SECURITY_CONTACT (currently allowed to be the placeholder)
   - LLM provider key (without one, chat falls back to rule-based — is this
     the documented behavior, or a silent capability downgrade?)
   - DATABASE_PATH writability check
   - LOG_FOLDER + UPLOAD_FOLDER + LABELS_FOLDER writability check
   - CSRF secret key separate from SECRET_KEY (is it?)

3. PER-USER NAMESPACE CONTRACT — every file write site
   N7 + N26 established the contract: every file the request handler writes
   MUST live under a per-user subdir of UPLOAD_FOLDER / LABELS_FOLDER /
   LOG_FOLDER, and every file the response references MUST be reachable via
   the per-user-scoped serve route.
   For EACH `open(... , 'w')` / `write_text()` / `tempfile` / `os.makedirs`
   in app.py, blueprints/*.py, services/*.py, nl_gis/*.py, handlers/*.py:
   - Is the path computed from the request user_id?
   - If the URL of the result is returned to the client, does the serve
     route actually find it?
   - Does the file leak data from one user into another's filesystem
     namespace? (e.g., backup_annotations() in blueprints/annotations.py is
     a known LABELS_FOLDER-root writer per §2.1.)

4. RATE LIMIT + SIZE CAP COVERAGE — every public input
   For EACH route that accepts user input (POST / WebSocket message / SSE
   client → server):
   - Is there a per-user or per-IP rate limit?
   - Is the request body size capped (Flask MAX_CONTENT_LENGTH covers
     uploads but not necessarily JSON / WS messages)?
   - Are individual fields capped (string length, list length, nested dict
     depth)?
   N11/N12/N14/N16 closed several of these; what's still uncapped?

For EACH finding:
- ID: starts at N31 (N1-N30 taken)
- Severity: Critical / High / Medium / Low
- Mode: which of (1)-(4) above
- File:line
- Reproduction: a curl command (or browser interaction) that demonstrates
  the difference between DEBUG=true behavior and DEBUG=false behavior
- Recommended fix shape

To set up the prod-mode environment for testing (run as one shell line):

    FLASK_DEBUG=false  SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")  CHAT_API_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")  ANTHROPIC_API_KEY=sk-ant-...  SECURITY_CONTACT=mailto:security@example.com  .venv/bin/gunicorn -w 4 -k eventlet -b 127.0.0.1:5000 app:app

Output format: one block per finding. End with:
- "PARITY FINDINGS: <count> Critical, <count> High, <count> Medium, <count> Low"
- "MODES SWEPT: auth-fetch (<N>), config-validate (<N>),
  per-user-namespace (<N>), rate-limit-cap (<N>)"
- "PROD-READINESS GRADE: ship | hold | block" with one-paragraph rationale.

Do not flag prior closed findings (see 12-next-audit-input.md §1.1).
```

---

## Aggregating findings

When the prompts return (current workflow — for the active 3-prompt primary set; archived prompts P1/P2/P4/P6 are not part of the standard cycle):

1. **Dedupe by ID and against the closed-finding list.** Cross-check every reported finding against `12-next-audit-input.md` §1.1. If a reviewer re-flags a closed finding, that's a signal to clarify the §1.1 entry's evidence rather than re-fix.
2. **Group by class:** new findings (P3) | capability/doc drift (P7) | prod-mode parity (P8) | failure-mode (P5).
3. **Severity-rank** every new finding (Critical / High / Medium / Low).
4. **Open a new cycle in `12-next-audit-input.md` §3** — name it after the audit round (e.g., "Cycle N (external audit-X close-out)"). For each new finding, log the symptom + fix + commit sha + regression test path.
5. **Update the audit-input header** with the new score, repo state, test counts, and "next finding ID starts at N…" pointer.
6. **Re-run the eval gate** (`make eval` in `--ci` strict mode) before declaring closure.
7. **Re-run the primary prompts** against the same commit only if the score dropped — convergence behavior is the signal that the audit pipeline has reached a fixed point.

**Decision boundary:** if a single audit round produces **≥ 1 Critical** or **≥ 3 High** → fix immediately and re-audit before any deploy work. If findings are **all Medium / Low** → fix in the same week but proceed with deploy planning in parallel. The gate is per-finding-class, not aggregate score; audit-4's 86/100 was acceptable to ship from because every finding had a localized fix and no class signaled systemic regression.
