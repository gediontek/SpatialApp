# SpatialApp Improvement Plan — Research-Driven

**Based on**: `.project_plan/RESEARCH_NL_GIS.md`
**Date**: 2026-04-11
**Current state**: 44 tools, 596 tests, function-calling architecture, ~85% estimated accuracy

---

## Strategic Goal

Close the gap between SpatialApp's current accuracy (~85%, function-calling) and research state-of-the-art (~97%, code generation + multi-agent). Prioritize improvements by measured impact from published research.

---

## Track A: LLM Accuracy (highest ROI per research)

### A1. Code Generation Fallback (+11.4% accuracy per GeoJSON Agents benchmark)
**Priority**: P0 — single highest-impact improvement
**Research evidence**: Function calling: 85.71%, code generation: 97.14%
**Effort**: L

When no tool matches the user's request, instead of saying "I can't do that", let the LLM generate and execute Python code using GeoPandas/Shapely in a sandboxed environment.

| Story | Description | Acceptance Criteria |
|-------|-------------|-------------------|
| A1.1 | Create sandboxed Python executor | Execute GeoPandas/Shapely code in subprocess with timeout, memory limit, no network access |
| A1.2 | Add `execute_code` tool to tool catalog | Schema accepts Python code string, returns stdout + any generated GeoJSON |
| A1.3 | Update system prompt with code generation guidance | When to use code vs tools, safety constraints, available libraries |
| A1.4 | Add result capture | If code produces GeoJSON, add it as a layer; if it produces text/numbers, return as message |
| A1.5 | Security review | Sandbox escape prevention, input sanitization, resource limits |
| A1.6 | Tests | 10+ tests: valid code, invalid code, timeout, memory limit, GeoJSON output |

### A2. Plan-Then-Execute Mode (+accuracy for multi-step queries)
**Priority**: P1
**Research evidence**: Graph-based planning improves multi-step accuracy (GeoBenchX: multi-step 26-56%)
**Effort**: M

Before executing tools, have the LLM output a structured plan that the user can review.

| Story | Description | Acceptance Criteria |
|-------|-------------|-------------------|
| A2.1 | Add `plan_mode` parameter to chat API | When enabled, LLM returns a JSON plan (ordered tool calls) instead of executing |
| A2.2 | Frontend plan review UI | Display plan as numbered steps, user can approve/modify/reject |
| A2.3 | Plan execution engine | Execute approved plan step-by-step, showing progress |
| A2.4 | Plan validation | Check: are all referenced layers available? Are parameters valid? |
| A2.5 | Tests | Plan generation, plan validation, plan execution |

### A3. Enhanced Tool Descriptions (+30-40% error reduction per research)
**Priority**: P0
**Research evidence**: Explicit parameter semantics with examples reduce errors 30-40%
**Effort**: S

| Story | Description | Acceptance Criteria |
|-------|-------------|-------------------|
| A3.1 | Add parameter examples to ALL 44 tool schemas | Every parameter has a concrete example value in its description |
| A3.2 | Add coordinate semantics to all lat/lon params | `"lat": {"description": "Latitude (north-south, -90 to 90). Example: 41.88"}` |
| A3.3 | Add 3 more few-shot conversation examples | Cover: overlay operations, import+analyze, network analysis |
| A3.4 | Add chain patterns for all new tools (Phase 0-5) | At least 1 pattern per new tool category |
| A3.5 | Validate: run 20 test queries and measure tool selection accuracy | Before/after comparison |

### A4. LLM-as-Judge Evaluation Framework
**Priority**: P1
**Research evidence**: GeoBenchX uses LLM panel with 88-96% human agreement
**Effort**: M

| Story | Description | Acceptance Criteria |
|-------|-------------|-------------------|
| A4.1 | Create test suite of 50 reference queries with expected tool chains | Cover all 44 tools, single-step and multi-step |
| A4.2 | Implement judge script that runs queries and compares results | Uses Claude to evaluate match/partial/no-match against reference |
| A4.3 | Generate accuracy report | Per-tool accuracy, per-complexity accuracy, overall score |
| A4.4 | CI integration | Run accuracy benchmark on each commit (subset of 10 queries) |

---

## Track B: Spatial Operations Expansion

### B1. Hot Spot Analysis (Getis-Ord Gi*)
**Priority**: P1 — frequently requested, feasible with our architecture
**Effort**: M

| Story | Description |
|-------|-------------|
| B1.1 | Add `hot_spot_analysis` tool using PySAL/esda |
| B1.2 | Return GeoJSON with z-scores and p-values in properties |
| B1.3 | Color-coded visualization (hot=red, cold=blue, not significant=gray) |
| B1.4 | Tests |

### B2. IDW Interpolation
**Priority**: P2
**Effort**: M

| Story | Description |
|-------|-------------|
| B2.1 | Add `interpolate` tool using scipy.interpolate.griddata |
| B2.2 | Generate contour polygons from interpolated surface |
| B2.3 | Support point layer input with numeric attribute for value |
| B2.4 | Tests |

### B3. Topology Validation
**Priority**: P2
**Effort**: S

| Story | Description |
|-------|-------------|
| B3.1 | Add `validate_topology` tool using Shapely is_valid + explain_validity |
| B3.2 | Report: valid/invalid count, error descriptions, auto-fix option |
| B3.3 | Tests |

### B4. Service Areas (Multi-Facility Isochrones)
**Priority**: P2
**Effort**: S

| Story | Description |
|-------|-------------|
| B4.1 | Add `service_area` tool — multiple isochrones + union |
| B4.2 | Input: list of facility points + time/distance |
| B4.3 | Output: merged isochrone coverage area |
| B4.4 | Tests |

---

## Track C: Infrastructure & Scale

### C1. Elevation/DEM Integration
**Priority**: P2 — requires external DEM tile service
**Effort**: L

| Story | Description |
|-------|-------------|
| C1.1 | Integrate open DEM tile service (OpenTopography API or Mapzen Terrain Tiles) |
| C1.2 | Add `elevation_profile` tool — elevation along a route or transect |
| C1.3 | Add `slope_aspect` tool — compute slope/aspect from DEM at a location |
| C1.4 | Caching for DEM tiles |
| C1.5 | Tests |

### C2. Vector Tile Generation
**Priority**: P3 — performance optimization for large layers
**Effort**: M

| Story | Description |
|-------|-------------|
| C2.1 | Add tippecanoe integration or vt2geojson for MVT generation |
| C2.2 | Auto-generate vector tiles for layers with 5000+ features |
| C2.3 | Leaflet vector tile rendering (leaflet.VectorGrid) |
| C2.4 | Tests |

### C3. Prometheus Metrics Export
**Priority**: P2
**Effort**: S

| Story | Description |
|-------|-------------|
| C3.1 | Add /metrics endpoint with Prometheus-format metrics |
| C3.2 | Expose: request count, latency histogram, tool call count, error rate, active sessions |
| C3.3 | Tests |

---

## Track D: Architecture Evolution

### D1. Multi-Agent Architecture (Planner + Worker)
**Priority**: P1 — research shows 36-49% accuracy improvement
**Effort**: XL

This is a significant architectural change. The research is clear that multi-agent outperforms single-agent, but the implementation is complex.

| Story | Description |
|-------|-------------|
| D1.1 | Design: Planner agent + Worker agent architecture |
| D1.2 | Planner agent: receives user query, decomposes into sub-tasks with dependencies |
| D1.3 | Worker agents: execute individual sub-tasks (tool calls or code generation) |
| D1.4 | Orchestrator: manages worker lifecycle, collects results, handles failures |
| D1.5 | Integration with existing ChatSession (backward compatible) |
| D1.6 | Tests + accuracy comparison |

### D2. Fine-Tuning Pipeline
**Priority**: P2 — research shows 49.2 percentage point improvement
**Effort**: L

| Story | Description |
|-------|-------------|
| D2.1 | Data collection: export successful tool chains from query_metrics |
| D2.2 | Training data formatting: convert to Claude fine-tuning format |
| D2.3 | Fine-tuning job submission via Anthropic API |
| D2.4 | A/B testing: compare fine-tuned vs base model accuracy |
| D2.5 | Rollback mechanism if fine-tuned model regresses |

---

## Implementation Order (DAG)

```
Track A (Accuracy) — do first, highest ROI:
  A3 (tool descriptions) ───── P0, effort S, no deps
  A1 (code gen fallback) ───── P0, effort L, no deps
  A2 (plan-then-execute) ───── P1, effort M, after A3
  A4 (LLM-as-Judge) ────────── P1, effort M, after A1+A3

Track B (Spatial Ops) — do in parallel with Track A:
  B1 (hot spot) ────────────── P1, effort M, no deps
  B3 (topology) ────────────── P2, effort S, no deps
  B4 (service areas) ────────── P2, effort S, no deps
  B2 (interpolation) ────────── P2, effort M, no deps

Track C (Infrastructure) — do after Tracks A+B:
  C3 (Prometheus) ──────────── P2, effort S, no deps
  C1 (elevation) ──────────── P2, effort L, needs DEM service
  C2 (vector tiles) ────────── P3, effort M, needs tippecanoe

Track D (Architecture) — future, after Tracks A-C prove value:
  D1 (multi-agent) ─────────── P1, effort XL, after A1+A2 prove concept
  D2 (fine-tuning) ─────────── P2, effort L, after A4 provides training data
```

## Priority Summary

| Priority | Items | Total Effort | Expected Impact |
|----------|-------|-------------|-----------------|
| **P0** | A1 (code gen), A3 (tool descriptions) | L + S | +30-40% error reduction + code fallback |
| **P1** | A2 (plan mode), A4 (judge), B1 (hot spot), D1 (multi-agent) | M + M + M + XL | Plan review + accuracy measurement + spatial stats |
| **P2** | B2-B4, C1, C3, D2 | M + S + S + L + S + L | Advanced analysis + infrastructure + fine-tuning |
| **P3** | C2 (vector tiles) | M | Performance for very large layers |

## Success Metrics

| Metric | Current | Target (P0+P1) | Target (All) |
|--------|---------|----------------|-------------|
| Tool selection accuracy | ~85% (estimated) | 90%+ (measured) | 95%+ |
| Multi-step query accuracy | ~50% (GeoBenchX analog) | 70%+ | 85%+ |
| Tools available | 44 | 46+ | 52+ |
| Operations not answerable | ~15% of user requests | ~5% (code gen fallback) | ~2% |
| Tests | 596 | 650+ | 700+ |
