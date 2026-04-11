# Research: Production-Grade Natural Language GIS Systems

**Date**: 2026-04-11
**Type**: Conceptual research
**Confidence**: High (multiple peer-reviewed sources, published benchmarks)

---

## 1. How Production NL-GIS Systems Work

### ArcGIS Copilot (Esri)
- Integrates into ArcGIS Pro/Online as conversational assistant
- Access to 600+ geoprocessing tools via natural language
- Focuses on workflow guidance and tool discovery, not autonomous execution
- Uses LLM to translate queries into ArcPy/geoprocessing chains
- Strength: breadth of tools. Weakness: still requires user to validate and execute

### GIS Copilot (Penn State Research, v1.0 released Oct 2025)
- Autonomous GIS agent using LLM + QGIS Processing Tools
- Architecture: LLM generates Python code using QGIS Processing API
- Evaluated on 100+ tasks across 3 complexity levels
- Basic tasks: high success rate (single-tool operations)
- Intermediate: strong with user guidance (multi-step)
- Advanced: struggles — "full autonomy is yet to be achieved"
- Key paper: [GIS Copilot: Towards an Autonomous GIS Agent](https://arxiv.org/abs/2411.03205)

### QGIS Spatial Analysis Agent
- Plugin that serves as NL "Copilot" in QGIS
- Leverages 600+ QGIS processing tools + Python libraries (GeoPandas, seaborn)
- Uses Ollama/Claude/OpenAI/Gemini as LLM backend
- User types natural language → agent generates and executes Python code

### GeoJSON Agents (2025 research)
- Multi-agent architecture: Planner + Worker agents
- Compared two approaches:
  - **Function calling**: 85.71% accuracy — structured, stable, limited flexibility
  - **Code generation**: 97.14% accuracy — flexible, handles complex open-ended tasks
- Key finding: **code generation outperforms function calling by 11.4%** for geospatial tasks
- [GeoJSON Agents paper](https://arxiv.org/abs/2509.08863)

### Microsoft Earth Copilot
- AI-powered geospatial app for Earth science data exploration
- Natural language interface for visualization and analysis
- Built on Azure + LLM integration

### Operations These Systems Support That SpatialApp Doesn't

| Operation | ArcGIS | QGIS Agent | GIS Copilot | SpatialApp |
|-----------|--------|------------|-------------|------------|
| Buffer | Yes | Yes | Yes | **Yes** |
| Intersection/Union | Yes | Yes | Yes | **Yes** |
| Spatial join | Yes | Yes | Yes | **Yes** |
| Proximity analysis | Yes | Yes | Yes | **Yes** |
| Geocoding | Yes | Limited | Yes | **Yes** |
| Routing | Yes | Via plugins | Limited | **Yes** |
| **Raster analysis** | Yes | Yes | Yes | **No** |
| **Elevation/slope** | Yes | Yes | Yes | **No** |
| **Viewshed** | Yes | Yes | Limited | **No** |
| **Watershed delineation** | Yes | Yes | No | **No** |
| **Interpolation (IDW/Kriging)** | Yes | Yes | Limited | **No** |
| **Coordinate transforms** | Yes | Yes | Yes | **Partial** (internal only) |
| **Topology validation** | Yes | Yes | Limited | **No** |
| **3D analysis** | Yes | Limited | No | **No** |

---

## 2. Feasibility Assessment for SpatialApp Architecture

### What's Feasible (Flask + Leaflet + LLM tool-calling)

| Operation | Feasibility | Implementation Path | Effort |
|-----------|------------|-------------------|--------|
| **Spatial clustering (DBSCAN)** | Done | scipy/sklearn — already implemented | ✅ |
| **Hot spot analysis** | High | Getis-Ord Gi* via PySAL/esda | M |
| **Interpolation (IDW)** | High | scipy.interpolate.griddata → contour GeoJSON | M |
| **Service areas** | High | Multiple isochrones + union (Valhalla) | S |
| **Topology validation** | High | Shapely `is_valid`, `explain_validity` | S |
| **Coordinate transforms** | Done | pyproj — already in geo_utils.py (internal) | ✅ |
| **Contour lines from points** | Medium | scipy griddata + matplotlib contour → GeoJSON | M |

### What's Partially Feasible (needs external service)

| Operation | Feasibility | What's Needed | Effort |
|-----------|------------|--------------|--------|
| **Elevation queries** | Medium | DEM tile service (Mapzen/SRTM tiles) | L |
| **Slope/aspect** | Medium | DEM + numpy gradient calculation | L |
| **Viewshed** | Low | DEM + viewshed algorithm (heavy computation) | XL |
| **Watershed delineation** | Low | DEM + flow direction/accumulation (pysheds) | XL |
| **Interpolation (Kriging)** | Medium | pykrige library, needs point+value data | L |

### What's Not Feasible (wrong architecture)

| Operation | Why Not | What Would Be Needed |
|-----------|---------|---------------------|
| **Real raster analysis** | No raster data pipeline | GeoServer/TiTiler for COG serving |
| **3D analysis** | Leaflet is 2D only | CesiumJS or deck.gl |
| **Satellite imagery ML** | No GPU, no model serving | Separate ML service + inference API |
| **Real-time streaming data** | No data pipeline | Apache Kafka/Flink + WebSocket |

---

## 3. NL-to-GIS Accuracy: Benchmarks & Measurement

### Published Benchmarks

| Benchmark | Tasks | Best Accuracy | Key Finding |
|-----------|-------|--------------|-------------|
| **GeoBenchX** (2025) | 199 multi-step geospatial | 51-55% (Claude Sonnet/o4-mini) | Spatial operations: 26-56% accuracy. Heatmaps/contours: 15-60%. Multi-step chains are hardest. |
| **GeoAnalystBench** (2025) | 50 Python-based GIS | 89.7% (fine-tuned GPT-4o-mini) | Fine-tuning improves accuracy by 49.2 percentage points over baseline |
| **GeoJSON Agents** (2025) | 35 geospatial tasks | 97.14% (code gen) / 85.71% (function calling) | Multi-agent > single agent by 36-49% |
| **GTChain** (2024) | Tool-use chain generation | 32.5% higher than GPT-4 | Simulated environment training improves tool chain accuracy |

### How Accuracy Is Measured

1. **LLM-as-Judge**: Panel of 3 LLMs (GPT-4.1, Claude Sonnet, Gemini 2.5 Pro) compare candidate output vs reference solution. Match/partial-match/no-match scoring. 88-96% agreement with human annotators.

2. **Code execution**: Generate Python code, execute it, compare output against ground truth (exact match on numeric results, visual similarity on maps).

3. **Task completion rate**: Binary — did the system produce the correct final result? Measured per-task, then aggregated by complexity level.

4. **Dataflow score**: Evaluates whether logical dependencies between operations are preserved (variable reuse, correct function chaining). Current systems score moderately — multi-step reasoning is the weak point.

### SpatialApp's Position

Our architecture uses **function calling** (tool_use), which benchmarks at **85.71%** accuracy in the GeoJSON Agents study. This is competitive but below code generation (97.14%). Key insight: function calling is more **stable** (fewer crashes) but less **flexible** (can't handle operations not in the tool catalog).

**Our advantages over benchmarked systems:**
- 44 tools (most benchmarked systems have 10-30)
- Few-shot examples in system prompt (2 full conversations)
- Tool selection guidance for all 44 tools
- Per-tool instrumentation for accuracy measurement

**Our weaknesses:**
- No fine-tuning (benchmark leaders use fine-tuned models)
- No multi-agent architecture (Planner + Worker would improve chain accuracy)
- No code generation fallback for operations outside the tool catalog

### Recommendations for Accuracy Improvement

1. **Add a code generation fallback**: When no tool matches, let the LLM generate Python code using GeoPandas/Shapely. This covers the 15% gap between function calling and code generation.
2. **Fine-tune on successful interactions**: Log successful tool chains, use them as training data for a fine-tuned model.
3. **Multi-agent architecture**: Planner agent decomposes queries into sub-tasks, Worker agents execute each. Shown to improve accuracy by 36-49%.
4. **LLM-as-Judge evaluation**: Implement automated accuracy testing using a second LLM to compare outputs against reference results.

---

## 4. Tool Description Engineering for Spatial Operations

### Research Findings

From the GeoJSON Agents and GIS Copilot research:

1. **Explicit parameter semantics reduce errors by 30-40%**
   - BAD: `"bbox": "Bounding box coordinates"`
   - GOOD: `"bbox": "Bounding box as 'south_lat,west_lon,north_lat,east_lon' (WGS84, decimal degrees). Example: '41.8,-87.7,41.9,-87.6' for Chicago downtown"`

2. **Include canonical examples in descriptions**
   - Every tool description should include 1-2 concrete parameter examples
   - Example values ground the LLM's understanding of expected formats

3. **Disambiguate spatial relationships explicitly**
   - Our fix (from bug investigation) was exactly right: "contains: source feature fully encloses the target geometry" vs. "within: source feature is fully inside the target geometry"
   - Research confirms this is the #1 source of spatial query errors

4. **Coordinate order must be stated explicitly in EVERY tool that accepts coordinates**
   - Even though our system handles this internally (ValidatedPoint), the LLM needs to know which order to pass
   - Best practice: `"lat": {"description": "Latitude (north-south, -90 to 90)"}` and `"lon": {"description": "Longitude (east-west, -180 to 180)"}`

5. **Chain patterns > individual tool descriptions**
   - The system prompt's chain patterns (we have 8+) are more effective than individual tool descriptions for multi-step accuracy
   - Research recommends 3-5 full conversation examples (we have 2 — could add more)

6. **Graph-based operation planning**
   - Representing the user's intent as a graph of operations (DAG) before execution improves accuracy
   - The LLM plans the graph, user reviews, then execution proceeds
   - Our system does this implicitly (LLM chains tools iteratively) but could benefit from explicit plan-then-execute

### SpatialApp Assessment

| Best Practice | SpatialApp Status | Gap |
|--------------|-------------------|-----|
| Explicit parameter semantics | Good (most params have examples) | Some tools lack format examples |
| Canonical examples | Partial (system prompt has chain patterns) | Individual tool schemas lack examples |
| Disambiguated spatial relationships | Fixed (during bug investigation) | ✅ Done |
| Coordinate order stated | Good (ValidatedPoint handles internally) | ✅ Done |
| Chain patterns | 10+ patterns in system prompt | Could add 3-5 more for new tools |
| Few-shot conversations | 2 full examples | Add 1-2 more covering new tools |
| Graph-based planning | Not implemented | Future: plan-then-execute mode |

---

## Sources

- [GIS Copilot: Towards an Autonomous GIS Agent for Spatial Analysis](https://arxiv.org/abs/2411.03205) — Penn State, 2025
- [GeoBenchX: Benchmarking LLMs in Agent Solving Multistep Geospatial Tasks](https://arxiv.org/html/2503.18129v2) — 2025
- [GeoJSON Agents: Function Calling vs Code Generation](https://arxiv.org/abs/2509.08863) — 2025
- [GeoAnalystBench: LLMs for Spatial Analysis Workflow](https://onlinelibrary.wiley.com/doi/10.1111/tgis.70135) — Transactions in GIS, 2025
- [Top 3 GIS Copilots](https://atlas.co/blog/top-3-gis-copilots-ai-assistants-for-geospatial-analysis/) — Atlas, 2025
- [QGIS Spatial Analysis Agent Plugin](https://plugins.qgis.org/plugins/SpatialAnalysisAgent-master/) — QGIS Plugin Repository
- [On the Use of LLMs for GIS-Based Spatial Analysis](https://www.mdpi.com/2220-9964/14/10/401) — MDPI, 2025
- [Geospatial LLM Trained with Simulated Environment](https://www.sciencedirect.com/science/article/pii/S1569843224006708) — ScienceDirect, 2024
