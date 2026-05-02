# SpatialApp — Coverage matrix

Filled by applying [`framework/04`](../../../cognitive-skill-agent/eval-framework/docs/04-coverage-matrix.md)
to [`02-capability-catalog.md`](02-capability-catalog.md). State as of
2026-05-02.

## Snapshot

```
covered_cells:        3
gapped_cells:        20
required_cells:      45
ratio:                3 / 45  =  6.7%
```

The 1,400 unit tests in the current `tests/` tree concentrate in
**Q1 / M2** and over-cover that single cell. The matrix below shows
where reality is.

## Matrix

| | M1 static | M2 unit | M3 contract | M4 integration | M5 workflow | M6 property | M7 ops |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Q1** correctness | partial | **over-covered** | gap | gap | gap | gap | n/a |
| **Q2** completeness | partial | partial | gap | n/a | gap | n/a | n/a |
| **Q3** reliability | n/a | partial | gap | gap | gap | gap | gap |
| **Q4** performance | n/a | n/a | gap | gap | gap | n/a | gap |
| **Q5** compatibility | partial | partial | n/a | partial | gap | n/a | gap |
| **Q6** usability | partial | n/a | n/a | n/a | gap | n/a | n/a |
| **Q7** security | partial | partial | gap | gap | gap | gap | gap |
| **Q8** maintainability | partial | partial | partial | gap | gap | n/a | gap |

Legend: **covered** (✓), **partial** (some artifacts, not all
P0/P1 capabilities), **gap** (P0/P1 capabilities missing), **n/a**
(documented exclusion below).

## Exclusions

| Cell | Excluded? | Rationale |
|---|---|---|
| Q1 / M7 | n/a | M7 covers Q3 and Q4 by definition; Q1 is asserted by lower-mode tests run *during* M7 scenarios, not separately. |
| Q2 / M4, M6, M7 | n/a | Completeness is enumerated, not generated. |
| Q4 / M1, M2, M6 | n/a | Performance is operational by definition. |
| Q5 / M3, M6 | n/a | Compatibility lives in M4 (format round-trips) and M5 (browser / viewport). |
| Q6 / M2, M3, M4, M6, M7 | n/a | Usability is observed by the user; only M5 + M1 (a11y lint) apply. |

## Top gap list (drives the execution plan)

Ordered by priority and user-visible blast radius:

1. **Q1 / M5** — workflow tests for every entry in the workflow
   inventory. *Today: 5 ad-hoc Playwright scripts in `/tmp`. Required:
   ~40 committed tests in `tests/workflows/` per R5.1.*
2. **Q6 / M5** — usability assertions inside the workflow tests
   (UX-C1..C4). *Today: zero.*
3. **Q7 / M3** — bad-input + auth + CSRF matrix per route. *Today:
   header-presence checks; no actual injection / bypass attempts.*
4. **Q3 / M5** — error-recovery scenarios under simulated upstream
   failures. *Today: zero.*
5. **Q1 / M3** — schema validation on every route response. *Today:
   ad-hoc per route; no GeoJSON validator wired in.*
6. **Q1 / M6** — property tests for the 12 GIS-C criteria. *Today:
   zero.*
7. **Q4 / M7** — load profile per critical workflow. *Today: zero.*
8. **Q3 / M7** — chaos: Overpass / Nominatim / Valhalla / LLM
   provider failure injection. *Today: one breaker unit test.*

## Per-cell detail

(Auto-generated section. Below is the manual seed for Q1 / M5.)

### Q1 / M5 — Workflow correctness

```yaml
priority: P0
capabilities_covered:
  - fetch_osm                    # via Manual + Chat tabs (smoke 2026-05-02)
  - geocode                      # via #panToLocationBtn smoke
capabilities_missing:
  - find_route, isochrone, closest_facility, optimize_route, service_area
  - intersection, difference, dissolve, clip, voronoi, buffer
  - import_csv, import_kml, import_geoparquet, import_auto
  - export_layer, export_geoparquet, export_gpkg
  - choropleth_map, chart, animate_layer, visualize_3d
  - classify_area, predict_labels, evaluate_classifier
  - raster_info, raster_value, raster_statistics, raster_profile, raster_classify
  - add_annotation, classify_landcover, export_annotations
  - join_collab, cursor_move, layer_remove, layer_style
artifacts:
  - "(none committed; /tmp/manual_tab_smoke.py exists ad-hoc)"
question_answered: |
  Can the user, by clicking through the UI, complete each catalog
  capability's user-visible outcome?
owner: TBA
```

(Other cells filled in by execution plan as artifacts land.)
