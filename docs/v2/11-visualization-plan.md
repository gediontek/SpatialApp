# Plan 11: Advanced Visualization

**Scope**: Add choropleth maps, time-series animation, 3D building visualization, custom legends, and chart integration (Chart.js) to SpatialApp. Wire all through NL tool dispatch. 10 eval queries.

**Estimated effort**: 1.5-2 days | ~300-400 lines of code (Python + JS)

**Depends on**: Nothing (independent track)

**Current state**: `style_layer` (line 410 in `nl_gis/tools.py`) changes uniform color/weight/opacity. `heatmap` (line 831) renders point density via `L.heatLayer`. No attribute-based classification, no temporal animation, no 3D, no legends, no charts. `LayerManager.styleLayer()` in `static/js/layers.js:239` applies uniform styles. `highlightFeatures()` at line 255 does attribute matching but only binary highlight, not graduated classification.

---

## Milestone 1: Choropleth Maps

**Goal**: Classify a numeric attribute into buckets, assign a color ramp, render per-feature.

### Epic 1.1: Backend Choropleth Tool

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 1.1.1 | Add `choropleth_map` tool schema to `nl_gis/tools.py` after `style_layer` (line 448). Params: `layer_name`, `attribute`, `method` (enum: quantile, equal_interval, natural_breaks, manual), `color_ramp` (enum: sequential, diverging, qualitative, or custom hex array), `num_classes` (int, 3-9, default 5). | Schema validates in `get_tool_definitions()`. Claude can select this tool for "color by population density". | S |
| 1.1.2 | Create `nl_gis/handlers/visualization.py` with `handle_choropleth_map()`. Reads layer from `_get_layer_snapshot()`, extracts numeric values for `attribute`, computes class breaks using selected method. Uses `numpy.percentile` for quantile, linspace for equal_interval, `jenkspy.jenks_breaks` for natural_breaks. Returns `{"action": "choropleth", "layer_name": ..., "breaks": [...], "colors": [...], "styleMap": {feature_idx: color}}`. | Given a layer with 50 features and a "population" attribute, returns correct 5-class quantile breaks with sequential colors. Handles missing/non-numeric values gracefully. | M |
| 1.1.3 | Implement color ramp generation in `handle_choropleth_map()`. Sequential: interpolate between 2 colors (light-to-dark). Diverging: light center, dark extremes. Qualitative: use ColorBrewer-inspired preset list. Custom: user-provided hex array. | `_generate_color_ramp("sequential", 5)` returns 5 hex colors from light yellow to dark red. | S |
| 1.1.4 | Register `choropleth_map` in `dispatch_tool()` in `nl_gis/handlers/__init__.py` (after line 452). Add to handler imports. | `dispatch_tool("choropleth_map", {...}, layer_store)` routes correctly. | XS |

### Epic 1.2: Frontend Choropleth Rendering

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 1.2.1 | Add `case 'choropleth':` handler in `static/js/chat.js` `handleToolResult()` (after `case 'heatmap':` at line 417). Apply per-feature style using `styleMap` from backend: iterate features in the layer, set fillColor by classified bucket. Use `LayerManager.styleLayer()` extended with a `styleFunction`. | Choropleth renders with graduated colors on the map. Features without the attribute get default gray. | M |
| 1.2.2 | Extend `LayerManager.addLayer()` in `static/js/layers.js` to accept a `styleFunction` that maps `feature.properties[attr]` to a color via the breaks/colors arrays. Pass through the existing `style.styleFunction` path (line 31). | `addLayer(name, geojson, {styleFunction: fn})` applies per-feature coloring. | S |
| 1.2.3 | Add choropleth summary in `formatToolResult()` in `static/js/chat.js` (after line 532): `case 'choropleth_map': return num_classes + ' classes by ' + attribute`. | Chat shows "5 classes by population_density". | XS |

### Epic 1.3: Choropleth Tests

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 1.3.1 | Unit tests in `tests/test_visualization.py`: test all 3 classification methods with known data, test color ramp generation, test missing values, test non-numeric attribute error. | 8+ tests passing. Covers edge cases: all same value, single feature, NaN values. | S |
| 1.3.2 | Add `jenkspy` to `requirements.txt` (for natural breaks). Verify CI passes. | `pip install jenkspy` succeeds. CI green. | XS |

---

## Milestone 2: Custom Legends

**Goal**: Auto-generate a legend for any styled/classified layer. Display in sidebar.

### Epic 2.1: Legend Rendering

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 2.1.1 | Add `LegendManager` module in `static/js/legend.js`. Functions: `addLegend(layerName, legendData)`, `removeLegend(layerName)`, `refreshUI()`. Legend data format: `{type: "choropleth"|"categorical"|"simple", entries: [{color, label, min, max}]}`. Render as a color swatch list in a `#legendPanel` div. | Legend appears in sidebar below layer list with color swatches and labels. | M |
| 2.1.2 | Include `legend.js` in `templates/index.html`. Add `<div id="legendPanel">` to sidebar HTML. CSS for `.legend-item`, `.legend-swatch` in existing stylesheet. | Legend panel visible in UI. No layout breakage. | S |
| 2.1.3 | Auto-generate legend data in `handle_choropleth_map()` return value. Include `legendData` with break ranges and colors. Frontend `case 'choropleth':` handler calls `LegendManager.addLegend()`. | Choropleth map automatically shows legend with value ranges. | S |
| 2.1.4 | Generate legend for uniform `style_layer` calls too. In `case 'layer_style':` handler (chat.js line 419), call `LegendManager.addLegend()` with `{type: "simple", entries: [{color, label: layerName}]}`. | Manually styled layers show a simple color legend. | XS |

---

## Milestone 3: Chart Integration (Chart.js)

**Goal**: Aggregate layer attributes and render bar/pie/histogram/scatter charts.

### Epic 3.1: Backend Chart Tool

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 3.1.1 | Add `chart` tool schema to `nl_gis/tools.py`. Params: `layer_name`, `attribute`, `chart_type` (enum: bar, pie, histogram, scatter), `group_by` (optional, for bar/pie), `x_attribute` (for scatter), `num_bins` (for histogram, default 10). | Schema present in tool definitions. | S |
| 3.1.2 | Add `handle_chart()` in `nl_gis/handlers/visualization.py`. Reads layer via `_get_layer_snapshot()`. For bar/pie: group by attribute, count or sum. For histogram: bin numeric values (reuse pattern from `handle_attribute_statistics()` at analysis.py:2560). For scatter: extract x/y pairs. Returns `{"action": "chart", "chart_type": ..., "labels": [...], "datasets": [...], "title": ...}`. | Given parks layer with "type" attribute, `chart_type="pie"` returns `{labels: ["playground","garden","park"], datasets: [{data: [12,8,25]}]}`. | M |
| 3.1.3 | Register `chart` in `dispatch_tool()`. | Routing works. | XS |

### Epic 3.2: Frontend Chart Rendering

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 3.2.1 | Add Chart.js CDN to `templates/index.html`: `<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>`. | Chart.js loaded globally. | XS |
| 3.2.2 | Add `ChartManager` in `static/js/chart.js`. Functions: `renderChart(containerId, config)` wrapping Chart.js constructor. Creates a floating panel (`<div class="chart-panel">`) with close button. Panel positioned over the map. Multiple charts supported (stacked panels). | Chart renders as a closeable overlay panel. | M |
| 3.2.3 | Add `case 'chart':` in chat.js `handleToolResult()`. Map backend data format to Chart.js config. Bar: `{type:'bar', data:{labels, datasets}}`. Pie: `{type:'pie', ...}`. Histogram: bar chart with bin labels. Scatter: `{type:'scatter', data:{datasets:[{data:[{x,y}]}]}}`. | All 4 chart types render correctly from tool results. | M |
| 3.2.4 | Add chart summary in `formatToolResult()`: `case 'chart': return chart_type + ' chart of ' + attribute`. | Chat feedback for chart rendering. | XS |

### Epic 3.3: Chart Tests

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 3.3.1 | Unit tests for `handle_chart()`: bar aggregation, pie counts, histogram binning, scatter extraction. Test empty layer, missing attribute, non-numeric histogram. | 6+ tests passing. | S |

---

## Milestone 4: Time-Series Animation

**Goal**: Animate layers with temporal attributes through time steps.

### Epic 4.1: Backend Animation Tool

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 4.1.1 | Add `animate_layer` tool schema to `nl_gis/tools.py`. Params: `layer_name`, `time_attribute` (property name containing date/time), `interval_ms` (animation speed, default 1000), `time_format` (optional, e.g. "%Y-%m-%d"), `cumulative` (bool, default false: show all features up to current time). | Schema validates. Claude selects for "show how permits spread over time". | S |
| 4.1.2 | Add `handle_animate_layer()` in `nl_gis/handlers/visualization.py`. Reads layer, extracts all unique time values from `time_attribute`, sorts chronologically, groups features by time step. Returns `{"action": "animate", "layer_name": ..., "time_steps": [{time: "2020-01", feature_indices: [0,3,7]}, ...], "interval_ms": 1000, "cumulative": false}`. | Given 100 features with "year" attribute (2020-2024), returns 5 time steps with correct feature grouping. | M |
| 4.1.3 | Register `animate_layer` in `dispatch_tool()`. | Routing works. | XS |

### Epic 4.2: Frontend Animation Player

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 4.2.1 | Add `AnimationPlayer` in `static/js/animation.js`. State: `playing`, `currentStep`, `totalSteps`, `intervalHandle`. Methods: `play(layerName, timeSteps, intervalMs, cumulative)`, `pause()`, `stop()`, `stepForward()`, `stepBackward()`. Controls feature visibility: in non-cumulative mode, show only features in current step; in cumulative mode, show all features up to current step. Use `L.GeoJSON.resetStyle()` + `setStyle({opacity:0})` for hidden features. | Animation plays through time steps at configured speed. | L |
| 4.2.2 | Add animation control bar UI: play/pause button, step counter ("Step 3/12"), time label, progress slider. Render as overlay above the map. Include `animation.js` in `templates/index.html`. | Controls appear when animation starts. Slider scrubs to any step. | M |
| 4.2.3 | Add `case 'animate':` in chat.js `handleToolResult()`. Calls `AnimationPlayer.play()`. | NL command triggers animation. | S |

### Epic 4.3: Animation Tests

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 4.3.1 | Unit tests for `handle_animate_layer()`: valid time grouping, missing attribute, unparseable dates, single time step. | 4+ tests passing. | S |

---

## Milestone 5: 3D Building Visualization

**Goal**: Extrude buildings by height using OSMBuildings or deck.gl overlay.

### Epic 5.1: 3D Building Rendering

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 5.1.1 | Add `visualize_3d` tool schema to `nl_gis/tools.py`. Params: `layer_name`, `height_attribute` (default "height" or "building:levels"), `height_multiplier` (default 3.0 for levels-to-meters), `color` (default by height gradient). | Schema validates. | S |
| 5.1.2 | Add `handle_visualize_3d()` in `nl_gis/handlers/visualization.py`. Reads layer, validates polygon geometries, extracts height values. Returns `{"action": "3d_buildings", "layer_name": ..., "geojson": featureCollection, "height_attribute": ..., "height_multiplier": ...}`. Injects computed `_height_m` property into each feature. | Returns features with computed heights. Missing height defaults to 10m. | M |
| 5.1.3 | Add OSMBuildings Leaflet plugin CDN to `templates/index.html`. Add `case '3d_buildings':` in chat.js: create `OSMBuildings` layer from GeoJSON with height extrusion. Register with `LayerManager`. | Buildings render with height extrusion on the map. | M |
| 5.1.4 | Register `visualize_3d` in `dispatch_tool()`. | Routing works. | XS |

### Epic 5.2: 3D Tests

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 5.2.1 | Unit tests for `handle_visualize_3d()`: height extraction, missing heights, non-polygon error, level-to-meter conversion. | 4+ tests passing. | S |

---

## Milestone 6: NL Integration and Evaluation

**Goal**: 10 eval queries that exercise all new visualization capabilities.

### Epic 6.1: Eval Query Suite

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 6.1.1 | Add 10 eval queries to `tests/eval/` (or inline test file). Queries: (1) "Color neighborhoods by population density" -> choropleth_map, (2) "Show a pie chart of building types in downtown Chicago" -> chart, (3) "Make a bar chart of park sizes" -> chart, (4) "Animate construction permits from 2020 to 2024" -> animate_layer, (5) "Show buildings in 3D by height" -> visualize_3d, (6) "Create a histogram of road lengths" -> chart, (7) "Color census tracts by income using natural breaks" -> choropleth_map, (8) "Show a diverging choropleth of temperature change" -> choropleth_map, (9) "Animate COVID cases by month cumulatively" -> animate_layer, (10) "Show a scatter plot of area vs population" -> chart. | All 10 queries route to the correct tool with correct parameters. At least 8/10 pass (80%). | M |
| 6.1.2 | Verify tool descriptions in `nl_gis/tools.py` are specific enough for Claude to select correctly. Update descriptions if eval accuracy < 80%. | Claude selects correct tool for each query. | S |

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| `jenkspy` adds native dependency | Fallback: implement equal_interval if jenkspy fails to install. CI installs it. |
| OSMBuildings plugin conflicts with Leaflet version | Test with current Leaflet version first. Fallback: use simple CSS 3D transforms. |
| Chart.js CDN unavailable | Bundle locally in `static/vendor/chart.min.js` as fallback. |
| Large layers slow down per-feature styling | Limit choropleth to 10,000 features. Warn user above threshold. |
| Time-series animation memory with many steps | Cap at 100 time steps. Aggregate if more unique values exist. |

## Output Artifacts

| Artifact | Path |
|----------|------|
| Visualization handler module | `nl_gis/handlers/visualization.py` |
| Legend manager (JS) | `static/js/legend.js` |
| Chart manager (JS) | `static/js/chart.js` |
| Animation player (JS) | `static/js/animation.js` |
| Updated tool schemas | `nl_gis/tools.py` (4 new tools) |
| Updated dispatch | `nl_gis/handlers/__init__.py` |
| Updated SSE handler | `static/js/chat.js` (4 new cases) |
| Updated template | `templates/index.html` (CDN includes, new divs) |
| Tests | `tests/test_visualization.py` |
| Eval queries | `tests/eval/visualization_eval.py` |
