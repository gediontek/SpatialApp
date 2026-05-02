# SpatialApp — Domain criteria

The Q1 / Q6 sub-axes specific to this project. These are the
non-negotiable correctness invariants a generic web testing framework
won't catch.

Each criterion is referenced from
[`02-capability-catalog.md`](02-capability-catalog.md) as
`outputs.domain_criteria`. Tests are derived in `M6` (property /
fuzz) and `M5` (workflow) per
[`framework/06`](../../../cognitive-skill-agent/eval-framework/docs/06-test-derivation-rules.md) rule R6.2.

## GIS correctness criteria (GIS-C)

| Code | Criterion | Applies to | Test mode |
|---|---|---|---|
| **GIS-C1** | Output that claims to be GeoJSON validates against RFC 7946. | every vector capability | M6, M3 (T6 schema) |
| **GIS-C2** | Coordinates are `[lon, lat]` and inside `[-180,180] × [-90,90]`. | every vector capability | M6 |
| **GIS-C3** | Default CRS is WGS84 (EPSG:4326); any other CRS is explicit in the response. | every vector capability and `reproject_layer` | M2, M6 |
| **GIS-C4** | Polygons are closed rings; `shapely.is_valid` true (or auto-repaired). | fetch_osm, intersection, dissolve, clip, voronoi, buffer | M2, M6 |
| **GIS-C5** | Topological invariants: `intersection(A,B) ⊆ A` and `⊆ B`; `union(A,B) ⊇ A`; buffer non-shrinking; symmetric_difference excludes intersection; clip output ⊆ clipping geometry. | each named operation | M6 |
| **GIS-C6** | Metric correctness: `buffer(d_m)` produces a buffer at *d* meters within projection error; `find_route.distance_km` matches geodesic length within 1%; areas reported in m². | buffer, find_route, isochrone, calculate_area, measure_distance | M2, M6 |
| **GIS-C7** | Spatial-relation predicates `within / contains / intersects / overlaps` evaluate correctly against fixture geometries. | spatial_query, point_in_polygon | M2 |
| **GIS-C8** | Routing: `find_route(A,B)` returns a `LineString` starting at A and ending at B; `distance_km ≥ great_circle(A,B)`; `duration_s > 0`. | find_route, optimize_route, closest_facility | M2, M5 |
| **GIS-C9** | Raster: pixel value at a known coordinate matches the source raster within rounding; slope / aspect / hillshade outputs match a reference implementation on the sample raster. | raster_value, raster_statistics, raster_classify | M2 |
| **GIS-C10** | Density / scale invariants: `generalize(layer, t)` reduces vertex count without changing topology beyond the tolerance; `clip` never produces features outside the clipping geometry. | generalize, simplify, clip | M6 |
| **GIS-C11** | Tag / classification correctness: `feature_type → osm_key/value` mappings match OSM tagging rules; classifier outputs use only declared seed categories. | fetch_osm via OSM_FEATURE_MAPPINGS; classify_area, predict_labels | M2 |
| **GIS-C12** | Attribute fidelity: imports preserve attributes through round-trip (CSV → layer → export → re-import). | import_*, export_* | M3 round-trip pair |

## LLM-driven correctness criteria (LLM-C)

| Code | Criterion | Applies to | Test mode |
|---|---|---|---|
| **LLM-C1** | Tool-selection accuracy on the curated reference set ≥ documented threshold. | ChatSession | tests/eval (existing harness) |
| **LLM-C2** | Parameter-grounding: ≥ documented threshold of expected params resolved correctly from the user's noun phrases. | ChatSession | tests/eval |
| **LLM-C3** | Chain coherence: multi-step plans pass `validate_plan_chain`; layer references resolve at execute time. | ChatSession plan-mode | M2 + M5 |
| **LLM-C4** | Provider parity: tool-selection deltas across Anthropic / Gemini / OpenAI within configured threshold. | ChatSession | tests/eval (live mode) |
| **LLM-C5** | Token-budget hygiene: a single end-user query stays under `MAX_TOKENS_PER_SESSION`. *(Failed today; tracked.)* | ChatSession | M5 + M7 |

## Usability criteria specific to this app (UX-C)

| Code | Criterion | Applies to |
|---|---|---|
| **UX-C1** | Every error toast names the failed service and a concrete retry action. | every workflow under chaos |
| **UX-C2** | Spinner resolves within timeout to either success or actionable error (never hangs). | every long-running workflow |
| **UX-C3** | Map fits to bounds after every layer-producing capability. | every capability in `LAYER_PRODUCING_TOOLS` |
| **UX-C4** | Mobile viewport (375px) does not occlude the map under any tab. | all surfaces |

## How these flow into tests

For each criterion above, derivation rule R6.2 (M6 property tests) is
required. Reviewers cross-check on PR: a new capability that produces
geometry must declare which GIS-C codes apply, and the test inventory
must show a row per declared code.
