# SpatialApp — Project Plan

**Start here.** This folder is the current-state dashboard. Shipped history lives in [`docs/v1/`](../docs/v1/); active plans live in [`docs/v2/`](../docs/v2/).

## 30-Second Orientation

| Question | Go to |
|----------|-------|
| What's the current version / test count / architecture? | [`STATUS.md`](STATUS.md) |
| What's the system layout? | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| What tools exist and what do they do? | [`CAPABILITY_MAP.md`](CAPABILITY_MAP.md) |
| What's been shipped and what's next? | [`ROADMAP.md`](ROADMAP.md) |
| What research drives the NL-GIS decisions? | [`RESEARCH_NL_GIS.md`](RESEARCH_NL_GIS.md) |
| What shipped in v1? | [`docs/v1/`](../docs/v1/) |
| What's planned for v2.1? | [`docs/v2/`](../docs/v2/) |

## File Responsibilities

**Living (update as the project evolves):**
- `STATUS.md` — current version, metrics, known limitations
- `ROADMAP.md` — what shipped, what's active, what's future
- `ARCHITECTURE.md` — system layout and data flow
- `CAPABILITY_MAP.md` — tool inventory and chain patterns

**Reference (update only when primary research changes):**
- `RESEARCH_NL_GIS.md` — evidence base for NL-to-GIS accuracy work (shared across v1/v2)

## Update Protocol

- When a v2.1 plan lands: update the plan's row in [`docs/v2/README.md`](../docs/v2/README.md), then reflect the new capability in `STATUS.md` and `CAPABILITY_MAP.md`.
- When metrics change (tool count, test count, commits): update the table at the top of `STATUS.md`.
- When a decision is made that affects architecture: add a row to the Decision Log in `ROADMAP.md` and update the relevant section of `ARCHITECTURE.md`.
- Never add new plans to this folder. New plans go to `docs/v2/` (or `docs/v3/` when it's time).
- Never edit frozen plans in `docs/v1/` except to add a correction note.
