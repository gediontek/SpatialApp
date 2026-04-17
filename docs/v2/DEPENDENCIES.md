# v2.1 Plan Dependencies & Execution Order

**Generated:** 2026-04-17 from cross-plan audit.
**Source:** research log `2026-04-17-spatialapp-v2-1-plan-evaluation...`

The 13 plans in this folder were drafted in one session and share underlying codebase touchpoints that aren't captured in individual "Dependencies" sections. This file surfaces those latent dependencies so execution order is intentional.

---

## Execution Order (recommended)

```
Phase 0  (parallel):          01 Accuracy Audit │ 05 Error Recovery
                                      ↓                    ↓
Phase 1  (paired+linear):     02 Tool Descriptions ⇄ 03 Complex Queries
                              06 Eval Framework (needs 01 + 02)
                              07 Provider Tuning (needs 06 M1+M2)
Phase 1B (any time):          04 Context Awareness
Phase 2  (parallel):          08 Raster │ 10 Data Pipeline │ 11 Viz │ 12 Autolabel
                              09 Collaboration (after chat.py stabilizes)
Phase 3  (last):              13 Production Hardening
```

**Critical path:** 01 → 02+03 → 06 → 07 → 13 (~15-16d serial).
**Parallel total (solo):** ~4 weeks. **With 3-5 person team:** ~2-3 weeks.

---

## Hidden Dependencies (not declared in individual plans)

| Plan | Hidden dep | Why | Action |
|------|-----------|-----|--------|
| 03 Complex Queries | depends on 02 Tool Descriptions | Query patterns reference tool names + descriptions; unstable descriptions break pattern matching | Run 02 and 03 **paired**, not independent. Plan 02's own notes acknowledge "85% unreachable without 03". |
| 10 Data Pipeline | depends on 05 Error Recovery | New transform tools need the new user-friendly error paths; running 10 before 05 means duplicate error handling | Order: 05 → 10, or pair them. |
| 09 Collaboration | depends on stable `chat.py` | Per-session locking and WebSocket routing assume the ChatSession API is settled | Start 09 only after Phase 1 lands. |
| 12 OSM Autolabel | depends on `OSM_auto_label/` being installed and importable | Plan assumes the subproject is accessible but doesn't cover install | Add setup step to plan 12 M1. |
| 13 Production Hardening | depends on core app stability | Load testing is meaningless on an unstable codebase | Gate: Phase 2 test-pass rate ≥ 95% before starting 13. |

---

## Touchpoint Hotspots (where plans collide)

**Any plan modifying these files must coordinate with the others.**

| File | Plans modifying | Conflict risk |
|------|-----------------|---------------|
| `nl_gis/tools.py` | 01, 02, 03, 06, 07, 08, 10, 11, 12 | Low — each adds separate tool schemas, but description edits (02) can collide with new-tool additions (08, 10-12) |
| `nl_gis/chat.py` SYSTEM_PROMPT | 02, 03, 04, 07, 08, 10 | **HIGH** — cumulative token bloat, conflicting guidance text |
| `tests/eval/` (query set, mock responses, evaluator) | 01, 02, 03, 06, 07 | Medium — 01 establishes schema, 06 extends it; 02/03/07 add queries without breaking schema |
| `static/js/chat.js` SSE dispatch | 02, 04, 05, 08, 09, 10, 11, 12 | Low — each adds a new event case; merge conflicts likely but mechanical |
| `nl_gis/handlers/analysis.py` | 02, 03, 05, 08, 10, 11, 12 | Medium — high change density; stagger or use feature branches |

---

## Cross-Cutting Risks

| Risk | Triggered by | Mitigation |
|------|-------------|-----------|
| System-prompt token bloat | 02 + 03 + 04 all append; 07 adds provider-specific addenda | Measure prompt size after 02 lands; compress or chunk before 03/04/07 stack on |
| ChatSession concurrency | 09 (collab) expects per-session locking that no plan declares | Add `threading.Lock` per session in Phase 1 (during 02 or as a small precursor task) |
| Live eval API cost | 02, 06, 07 run repeated Claude evals | CI uses mock mode only; budget $50-100 for final live baseline runs |
| Test suite explosion | ~280-520 new tests across 13 plans | Mark slow tests `@pytest.mark.slow`; organize by domain |
| Plan 13 blast radius | 39 tasks covering CSRF, CSP, Docker, monitoring | Consider splitting into 13a Security / 13b Ops; feature-flag CSRF rollout |

---

## Scope Adjustments to Consider

| Plan | Issue | Suggested action |
|------|-------|------------------|
| 02 | Self-flags 85% target as unreachable without 03 | Pair 02 + 03; single combined success metric |
| 07 | "Within 5% parity" not achievable on all task types | Document per-category parity targets in plan 07 M1 |
| 11 | Time-series animation capped at 100 steps with no fallback | Add degradation path for >100 unique time values |
| 12 | Fine-tuning is annotation-based seed update, not real retraining | Rename M3 from "train_classifier" to "update_classifier" to set expectations |
| 13 | 39 tasks covering 6 themes (security, load, cost, deploy, monitor, docs) | Split into 13a (security + OWASP) and 13b (ops + deploy) |

---

## Independent Plans (zero declared and hidden deps)

These can start any time: **04 Context Awareness · 05 Error Recovery · 08 Raster · 11 Visualization · 12 OSM Autolabel** (with install step added).

---

## Update Protocol

When a plan lands:
1. Update the plan's status row in [`README.md`](README.md).
2. If the plan introduced a new touchpoint not listed above, add it to the Hotspot table.
3. If a declared or hidden dep was validated (or invalidated) in practice, note it in the Hidden Dependencies table.
