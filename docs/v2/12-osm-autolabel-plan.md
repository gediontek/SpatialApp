# Plan 12: OSM Auto-Label Integration

**Scope**: Integrate the existing `OSM_auto_label/` sub-project into SpatialApp's NL-GIS pipeline. Expose classification, training, and prediction as Claude tools. Wire results into map display with color-coded predicted labels.

**Estimated effort**: 1.5-2 days | ~250-350 lines of code

**Depends on**: Nothing (independent track)

**Current state**: `OSM_auto_label/` exists at project root with:
- `classifier.py` — `OSMLandcoverClassifier` using GloVe word embeddings + spectral clustering. Key methods: `process_geodataframe(gdf, name)`, `classify(gdf)`, `assign_categories()`. Uses `gensim` for embeddings, `sklearn.cluster.SpectralClustering`.
- `downloader.py` — `download_osm_landcover(place_name)`, `download_by_bbox(bbox)` using `osmnx`. Returns `GeoDataFrame`.
- `visualizer.py` — `LandcoverMapVisualizer` using `folium`. Generates standalone HTML maps.
- `config.py` — `SEED_CATEGORIES` (7 classes: builtup_area, water, bare_earth, forest, farmland, grassland, aquaculture), `CATEGORY_COLORS`, `WORD_EMBEDDING_MODEL` ("glove-wiki-gigaword-300").
- `__init__.py` — Public API: `download_osm_landcover`, `OSMLandcoverClassifier`, `download_by_bbox`, `load_classified`, etc.

The sub-project is fully functional but isolated. Not accessible from the SpatialApp NL chat interface. No connection to `nl_gis/handlers/`, `nl_gis/tools.py`, or the Leaflet frontend.

SpatialApp already has `classify_landcover` tool (tools.py line 478) and `handle_classify_landcover()` in `nl_gis/handlers/annotations.py` -- but this uses a simple rule-based approach via annotations, NOT the ML classifier from `OSM_auto_label`.

---

## Milestone 1: Expose OSM Auto-Label as NL Tools

**Goal**: Three new Claude tools: `classify_area`, `train_classifier`, `predict_labels`.

### Epic 1.1: Integration Bridge Module

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 1.1.1 | Create `nl_gis/handlers/autolabel.py` as the bridge between SpatialApp handlers and `OSM_auto_label`. Import from `OSM_auto_label` package: `OSMLandcoverClassifier`, `download_by_bbox`, `download_osm_landcover`, `config`. Handle `ImportError` gracefully if `gensim`/`osmnx` not installed (return `{"error": "OSM auto-label dependencies not installed"}`). | Module imports succeed when deps installed. Graceful error when not. | S |
| 1.1.2 | Add `gensim`, `osmnx`, `geopandas` to `requirements.txt` (if not already present). Verify they don't conflict with existing deps. Add conditional import guard in `nl_gis/handlers/__init__.py` so autolabel tools are only registered when deps are available. | `pip install -r requirements.txt` succeeds. App starts with or without autolabel deps. | S |
| 1.1.3 | Add `sys.path` or package install configuration so `OSM_auto_label` is importable from SpatialApp root. Options: (a) add `OSM_auto_label/` to `sys.path` in `autolabel.py`, or (b) install as editable package via `pip install -e OSM_auto_label/`. Prefer (b) for cleanliness. | `from OSM_auto_label import OSMLandcoverClassifier` works from any handler. | S |

### Epic 1.2: classify_area Tool

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 1.2.1 | Add `classify_area` tool schema to `nl_gis/tools.py`. Params: `location` (string, place name), `bbox` (string, "south,west,north,east"), `output_name` (string, default "classified_area"). Either `location` or `bbox` required. Description: "Classify all OSM landcover features in an area using ML. Returns a layer with predicted landcover categories (builtup_area, water, forest, farmland, grassland, bare_earth, aquaculture)." | Schema present in `get_tool_definitions()`. Claude selects for "classify buildings in Addis Ababa". | S |
| 1.2.2 | Implement `handle_classify_area()` in `nl_gis/handlers/autolabel.py`. Flow: (1) If `location` provided, call `download_osm_landcover(location)`. If `bbox`, parse to tuple and call `download_by_bbox(bbox_tuple)`. (2) Instantiate `OSMLandcoverClassifier()`. (3) Call `classifier.process_geodataframe(gdf, name=output_name)`. (4) Convert classified GeoDataFrame to GeoJSON FeatureCollection. Each feature gets `predicted_label` and `confidence` properties. (5) Return `{"geojson": fc, "layer_name": output_name, "class_counts": {...}, "total_features": N}`. | Given "Paris, France", returns GeoJSON with classified features. Each feature has `predicted_label` in properties. | L |
| 1.2.3 | Handle the GeoDataFrame-to-GeoJSON conversion carefully: `gdf.__geo_interface__` or `json.loads(gdf.to_json())`. Ensure CRS is WGS84 (EPSG:4326). Strip unnecessary columns to keep payload small. | GeoJSON is valid, coordinates in [lng, lat] order, < 5MB for typical 1km2 area. | S |
| 1.2.4 | Register `classify_area` in `dispatch_tool()` at `nl_gis/handlers/__init__.py`. Add to `LAYER_PRODUCING_TOOLS` set (line 22). | Tool dispatches correctly. Result produces a map layer. | XS |

### Epic 1.3: predict_labels Tool

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 1.3.1 | Add `predict_labels` tool schema to `nl_gis/tools.py`. Params: `layer_name` (existing layer to classify), `output_name` (default appends "_classified"). Description: "Run landcover classification on features in an existing layer. Adds predicted_label property to each feature." | Schema validates. | S |
| 1.3.2 | Implement `handle_predict_labels()` in `nl_gis/handlers/autolabel.py`. Flow: (1) Get layer via `_get_layer_snapshot(layer_store, layer_name)`. (2) Convert features to GeoDataFrame using `gpd.GeoDataFrame.from_features()`. (3) Run `classifier.process_geodataframe(gdf)`. (4) Convert back to GeoJSON. (5) Return as new layer with `predicted_label` properties. | Given a layer of OSM polygons fetched via `fetch_osm`, correctly classifies and returns new layer. | M |
| 1.3.3 | Register `predict_labels` in `dispatch_tool()` and `LAYER_PRODUCING_TOOLS`. | Tool dispatches and produces layer. | XS |

### Epic 1.4: train_classifier Tool

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 1.4.1 | Add `train_classifier` tool schema to `nl_gis/tools.py`. Params: `layer_name` (layer with user-corrected labels), `label_attribute` (property name containing ground truth, default "category_name"), `output_model_name` (string). Description: "Fine-tune the landcover classifier using user-annotated features. Uses annotations as ground truth to update category seeds." | Schema validates. | S |
| 1.4.2 | Implement `handle_train_classifier()` in `nl_gis/handlers/autolabel.py`. Flow: (1) Get layer snapshot. (2) Extract features with `label_attribute` set. (3) Group by label to build new seed categories. (4) Update `OSMLandcoverClassifier` seed config: merge user seeds with `config.SEED_CATEGORIES`. (5) Save updated seeds to `OSM_auto_label/data/custom_seeds_{output_model_name}.json`. (6) Return `{"success": True, "training_samples": N, "categories": [...], "model_name": ...}`. | Given 50 annotated features across 4 categories, saves updated seeds. Subsequent `predict_labels` uses updated seeds. | M |
| 1.4.3 | Register `train_classifier` in `dispatch_tool()`. | Tool dispatches. | XS |

---

## Milestone 2: Map Visualization of Classification Results

**Goal**: Classified features render with color-coded predicted labels. Users can correct labels.

### Epic 2.1: Color-Coded Classification Display

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 2.1.1 | In `handle_classify_area()` and `handle_predict_labels()`, include a `style` object in the response with a `styleFunction` definition. Map each `predicted_label` to colors from `OSM_auto_label/config.py` `CATEGORY_COLORS` dict (builtup_area=#E31A1C, water=#1F78B4, forest=#33A02C, etc.). Return `{"style": {"colorMap": {"builtup_area": "#E31A1C", ...}}}`. | Response includes color mapping for frontend. | S |
| 2.1.2 | In `static/js/chat.js`, when a `layer_add` event arrives with `data.style.colorMap`, create a `styleFunction` that reads `feature.properties.predicted_label` and maps to the color. Pass to `LayerManager.addLayer()` via `style.styleFunction` (layers.js line 31). | Classified layer renders with per-category colors on the map. | M |
| 2.1.3 | Update popup template in `LayerManager.addLayer()` `onEachFeature` callback (layers.js line 58) to show `predicted_label` and `confidence` if present in properties. Format: "Predicted: forest (87%)". | Clicking a classified feature shows its prediction in the popup. | S |

### Epic 2.2: Label Correction Feedback Loop

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 2.2.1 | Add a "Correct Label" dropdown to the popup for classified features. When user selects a different category, call `POST /api/annotations` (existing endpoint in `blueprints/annotations.py`) with the feature geometry and corrected `category_name`. | User can click a misclassified feature, select the correct label, and save as annotation. | M |
| 2.2.2 | Add NL support: "Show me misclassified features" -> filter layer where `predicted_label != category_name` (if user-corrected annotations exist). Implement by cross-referencing `get_annotations` with classified layer features using spatial proximity. | Query surfaces features where prediction differs from user correction. | M |

---

## Milestone 3: Training Data Pipeline

**Goal**: Export annotations as training data. Import pre-trained models. Evaluate accuracy.

### Epic 3.1: Training Data Export

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 3.1.1 | Add `export_training_data` tool schema. Params: `format` (enum: geojson, csv), `output_name`. Description: "Export all annotations as labeled training data for the landcover classifier." | Schema validates. | XS |
| 3.1.2 | Implement `handle_export_training_data()` in `autolabel.py`. Reads all annotations via `state.db.get_annotations()` (or `handle_get_annotations()`). Converts to GeoJSON FeatureCollection with `category_name` as the label field. Optionally exports as CSV with WKT geometry column. Saves to `OSM_auto_label/data/training_{output_name}.geojson`. Returns file path and sample count. | Exports 100 annotations as valid GeoJSON with labels. File is loadable by `OSMLandcoverClassifier`. | S |
| 3.1.3 | Register in `dispatch_tool()`. | Routing works. | XS |

### Epic 3.2: Model Accuracy Evaluation

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 3.2.1 | Add `evaluate_classifier` tool schema. Params: `layer_name` (layer with ground truth labels), `label_attribute` (default "category_name"), `predicted_attribute` (default "predicted_label"). | Schema validates. | XS |
| 3.2.2 | Implement `handle_evaluate_classifier()` in `autolabel.py`. Computes: accuracy, per-class precision/recall/F1, confusion matrix. Uses features where both `label_attribute` and `predicted_attribute` exist. Returns `{"accuracy": 0.85, "per_class": {...}, "confusion_matrix": {...}, "total_evaluated": N}`. | Given 200 features with ground truth, returns correct accuracy metrics. | M |
| 3.2.3 | Register in `dispatch_tool()`. | Routing works. | XS |

---

## Milestone 4: Integration Testing

**Goal**: Verify end-to-end: classify 1km2 area with >80% accuracy.

### Epic 4.1: Test Suite

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 4.1.1 | Unit tests in `tests/test_autolabel.py` for `handle_classify_area()`: mock `OSMLandcoverClassifier` and `download_osm_landcover`. Test valid location, valid bbox, missing params, download failure, classification failure. | 6+ tests passing. No network calls in unit tests. | M |
| 4.1.2 | Unit tests for `handle_predict_labels()`: mock layer_store with synthetic GeoJSON features. Test classification, empty layer, non-polygon features. | 4+ tests passing. | S |
| 4.1.3 | Unit tests for `handle_train_classifier()`: mock layer with annotated features. Test seed update, empty training set, invalid labels. | 3+ tests passing. | S |
| 4.1.4 | Unit tests for `handle_evaluate_classifier()`: synthetic features with known labels and predictions. Verify accuracy calculation, per-class metrics. | 3+ tests passing. | S |
| 4.1.5 | Integration test (marked `@pytest.mark.slow`): download + classify a small bbox (0.01 degree square). Verify >80% of features get a `predicted_label`. Skip if `gensim`/`osmnx` not installed. | Test passes when deps available. Skips gracefully otherwise. | M |

### Epic 4.2: NL Eval Queries

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 4.2.1 | Add 5 eval queries: (1) "Classify all buildings in Addis Ababa" -> classify_area, (2) "What type of land use is this area?" (with bbox context) -> classify_area, (3) "Run classification on the parks layer" -> predict_labels, (4) "Train the classifier on my annotations" -> train_classifier, (5) "How accurate is the classifier on this area?" -> evaluate_classifier. | Claude selects correct tool for each. At least 4/5 pass. | S |

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| `gensim` model download is ~400MB, slow first run | Document first-run latency. Add progress logging in `_get_word_vectors()`. Consider pre-downloading in Docker image. |
| `osmnx` requires network access | Mock in all unit tests. Integration test marked `@pytest.mark.slow`. |
| GeoDataFrame <-> GeoJSON conversion loses CRS | Explicitly call `gdf.to_crs(epsg=4326)` before conversion. Assert CRS in tests. |
| Large area classification (e.g., all of Paris) returns huge payload | Cap at 10,000 features. If area yields more, suggest smaller bbox. Log feature count. |
| `OSM_auto_label` package structure conflicts with SpatialApp | Use editable install (`pip install -e OSM_auto_label/`). Namespace isolated. |
| Word embedding model not available offline | Cache model in `OSM_auto_label/cache/`. Docker image pre-downloads. |

## Output Artifacts

| Artifact | Path |
|----------|------|
| Autolabel handler module | `nl_gis/handlers/autolabel.py` |
| Updated tool schemas | `nl_gis/tools.py` (5 new tools: classify_area, predict_labels, train_classifier, export_training_data, evaluate_classifier) |
| Updated dispatch | `nl_gis/handlers/__init__.py` |
| Updated requirements | `requirements.txt` (gensim, osmnx if missing) |
| Updated chat.js | `static/js/chat.js` (colorMap style support, popup update) |
| Updated layers.js | `static/js/layers.js` (predicted_label in popup) |
| Tests | `tests/test_autolabel.py` |
| Eval queries | `tests/eval/autolabel_eval.py` |
