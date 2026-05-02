# SpatialApp — Evaluation Plan

This directory holds **SpatialApp's project-specific evaluation plan**:
the profile, capability catalog, domain criteria, workflow inventory,
and execution roadmap for testing this app rigorously.

The general-purpose evaluation **framework** itself — the universal
quality dimensions, evaluation modes, rule catalog, constructor spec,
and templates — was moved on 2026-05-02 to the sibling repo
`cognitive-skill-agent/`, where it is cross-project meta-tooling
maintained as part of the V11 milestone.

```
~/Documents/projects/
├── SpatialApp/                                ← project being evaluated
│   └── work_plan/
│       ├── README.md                          (this file)
│       ├── spatialapp/                        ← project-specific application of the framework
│       │   ├── 01-profile.md
│       │   ├── 02-capability-catalog.md
│       │   ├── 03-domain-criteria.md
│       │   ├── 04-coverage-matrix.md
│       │   ├── 05-workflow-inventory.md
│       │   └── 06-execution-plan.md
│       └── grants/                            ← (legacy stub; framework lives in cognitive-skill-agent)
└── cognitive-skill-agent/
    ├── eval-framework/                        ← universal framework (moved here)
    │   ├── docs/
    │   │   ├── 00-overview.md  …  13-validation-and-evolution.md
    │   │   ├── CHANGELOG.md
    │   ├── templates/
    │   ├── VERSION
    │   └── README.md
    └── docs/v11/                              ← V11 milestone tracking the constructor build
        ├── README.md
        ├── 00-VISION.md
        ├── 01-ENTRY-CRITERIA.md
        ├── 02-MOVE-PLAN.md
        ├── 03-ACCEPTANCE-CHECKLIST.md
        └── milestones/M11-eval-framework-constructor/README.md
```

## How to read these docs

Read in order:

1. [`spatialapp/01-profile.md`](spatialapp/01-profile.md) — what the
   app does, inputs / outputs / external deps / user surfaces.
2. [`spatialapp/03-domain-criteria.md`](spatialapp/03-domain-criteria.md)
   — Q1 sub-axes specific to this geospatial + LLM-driven app
   (GIS-C1..C12, LLM-C1..C5, UX-C1..C4).
3. [`spatialapp/02-capability-catalog.md`](spatialapp/02-capability-catalog.md)
   — every capability of this app, grouped.
4. [`spatialapp/05-workflow-inventory.md`](spatialapp/05-workflow-inventory.md)
   — 38 user-clickable workflows; the source list for `M5/Q1` tests.
5. [`spatialapp/04-coverage-matrix.md`](spatialapp/04-coverage-matrix.md)
   — current coverage state.
6. [`spatialapp/06-execution-plan.md`](spatialapp/06-execution-plan.md)
   — phased rollout (Phase 0 → Phase 4).

For the **universal framework** these documents apply, read the
sibling repo's docs at:

```
../../cognitive-skill-agent/eval-framework/docs/
```

Cross-references in the per-project docs use that path.

## Once the constructor exists

When V11 ships in cognitive-skill-agent, running:

```
/eval-construct ~/Documents/projects/SpatialApp
```

will (re)generate machine-derived versions of `02-capability-catalog.md`,
`04-coverage-matrix.md`, and `06-execution-plan.md` under
`work_plan/spatialapp/generated/`. The hand-drafted forms here become
the seed inputs (`extractor_config.yaml`, `domain_criteria.yaml`,
`workflow_inventory.yaml`).

Until V11 ships, the hand-drafted versions stand.

## Status

| Doc | State |
|---|---|
| `spatialapp/01-profile.md` | ✓ drafted |
| `spatialapp/02-capability-catalog.md` | ✓ drafted (top capabilities filled; remainder stubbed) |
| `spatialapp/03-domain-criteria.md` | ✓ drafted (12 GIS-C, 5 LLM-C, 4 UX-C) |
| `spatialapp/04-coverage-matrix.md` | ✓ filled with current state |
| `spatialapp/05-workflow-inventory.md` | ✓ 38 workflows enumerated |
| `spatialapp/06-execution-plan.md` | ✓ Phase 0–4 rollout |
| Phase 1 P0 workflow tests in `tests/workflows/` | ☐ pending (per execution plan) |
