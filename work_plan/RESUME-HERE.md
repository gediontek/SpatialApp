# Resume here after restart

**Last session ended:** 2026-05-02. About to start the v2 audit fix
work but stopped because the user is restarting Claude.

## TL;DR for the next session

1. **v2 is buggy.** External audit returned 12 findings (4 critical,
   4 high, 4 medium). Full report:
   [`spatialapp/07-v2-audit-findings.md`](spatialapp/07-v2-audit-findings.md).
2. **No code fixes have been written yet** — only the triage doc.
3. **Five decisions are pending from the user** (listed at the bottom
   of `07-v2-audit-findings.md`). Get those answered before writing
   any code.
4. **Recommended first PR:** C2 (CSRF exemptions) + X1 (CSRF-enabled
   test suite). Until CSRF works, no other security finding can be
   regression-tested.

## Repo state at session end

### SpatialApp
- Branch: `main`. Two new commits, **not pushed**:
  - `10140dd` docs(work_plan): SpatialApp project-specific evaluation plan
  - `a248d09` fix: Manual-tab fetch + Gemini tool calls; add golden-path test
- Working tree clean.
- Test status: 1,435 passed, 30 skipped — but auditor noted CSRF and
  raster tests don't actually run, so green CI is misleading.

### cognitive-skill-agent
- The eval framework (V11) shipped in commit `1844ad9` (already pushed).
- 27 files under `eval-framework/` (the spec) + `docs/v11/` (V11 plan).
- M11 Phase 0 (rules.yaml serialisation, JSON Schemas, CLI scaffolding)
  is **not yet started** — was queued but the v2 audit findings took
  priority.

## Open questions blocking next-session start

1. **v2 scope:** Approve all 12 audit findings as listed?
2. **Order:** Use the recommended order in `07-v2-audit-findings.md`?
3. **C4 path:** A (restructure) or B (per-user filter, recommended)?
4. **Raster fixture:** committed GeoTIFF or generated at fixture time?
5. **CSRF-enabled test suite:** OK to add even if it turns currently-green
   tests yellow?

## Pointers for the new session

- Read in this order:
  1. This file (you're here).
  2. [`spatialapp/07-v2-audit-findings.md`](spatialapp/07-v2-audit-findings.md)
     — full audit + fix plan.
  3. [`spatialapp/06-execution-plan.md`](spatialapp/06-execution-plan.md)
     — phased rollout (Phase 0–4).
  4. [`spatialapp/05-workflow-inventory.md`](spatialapp/05-workflow-inventory.md)
     — 38 workflows; the audit findings cross-reference W01 / W11 / W20
     / W30 / W42 / W90.
- Confirm the 5 open questions before writing code.
- Start with PR #1 (C2 + X1).

## Key paths

| What | Where |
|---|---|
| Audit findings + fix plan | `work_plan/spatialapp/07-v2-audit-findings.md` |
| SpatialApp profile | `work_plan/spatialapp/01-profile.md` |
| Capability catalog | `work_plan/spatialapp/02-capability-catalog.md` |
| Domain criteria | `work_plan/spatialapp/03-domain-criteria.md` |
| Coverage matrix | `work_plan/spatialapp/04-coverage-matrix.md` |
| Workflow inventory | `work_plan/spatialapp/05-workflow-inventory.md` |
| Execution plan | `work_plan/spatialapp/06-execution-plan.md` |
| Universal framework spec | `../../cognitive-skill-agent/eval-framework/docs/` |
| V11 milestone tracking | `../../cognitive-skill-agent/docs/v11/` |
