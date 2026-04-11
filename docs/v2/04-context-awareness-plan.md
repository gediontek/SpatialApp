# Plan 4: Spatial Context Awareness

**Objective**: Make the LLM deeply aware of what is on the map -- layer schemas, feature attributes, bounding boxes, and conversational references -- so it can make better tool selection and parameter decisions without guessing.

**Scope**: ~350 lines of code | 2 days | Files: `nl_gis/chat.py`, `nl_gis/context.py` (new), `static/js/chat.js`, `tests/test_context.py` (new)

**Current State**: `ChatSession._process_message_inner()` (line ~689 of `nl_gis/chat.py`) builds a dynamic system prompt with map state (lines 706-743) and recent context (lines 746-756). Current limitations:
- Layer metadata is minimal: only name and feature count (line 733: `f"{name} ({count} features)"`)
- No attribute schema information (the LLM doesn't know what properties features have)
- No bounding box per layer (LLM can't tell the user "your parks layer covers downtown Chicago")
- Reference resolution is basic: tracks `last_layer`, `last_location`, `last_operation` (lines 246-250), but "those buildings", "that area", "the results" are not reliably resolved
- Viewport is sent as `map_context["bounds"]` but only used for display in the system prompt, not for implicit bounding box in tool calls
- The LLM often calls `style_layer` with wrong attribute names because it doesn't know what attributes exist

---

## M1: Enhanced Map State Injection

**Goal**: Inject rich layer metadata into the system prompt so the LLM knows layer names, feature counts, geometry types, bounding boxes, and attribute schemas.

### Epic 1.1: Layer Metadata Extraction

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.1.1 | Create `nl_gis/context.py` with function `extract_layer_metadata(layer_name: str, geojson: dict, max_features_sample: int = 100) -> dict`. Returns: `{"name": str, "feature_count": int, "geometry_types": set[str], "bbox": [south, west, north, east], "attributes": {"attr_name": {"type": str, "sample_values": list, "unique_count": int}}}`. Sample attributes from first `max_features_sample` features to avoid scanning large layers | Function returns correct metadata for a test GeoJSON with mixed geometry types; bbox computed correctly; attribute types inferred as "string", "number", "boolean" | M |
| T1.1.2 | In `extract_layer_metadata`, compute `geometry_types` by scanning `feature["geometry"]["type"]` for all features (fast -- just string reads). Deduplicate into a set: e.g., `{"Point", "Polygon"}` | Correctly identifies mixed-geometry layers; returns `{"Point"}` for point-only layers | XS |
| T1.1.3 | In `extract_layer_metadata`, compute `bbox` from feature geometries using Shapely's `unary_union(geometries).bounds` for accuracy. Fallback: scan all coordinate arrays manually if Shapely fails. Return as `[south, west, north, east]` (Leaflet convention) | Bbox is correct within 0.001 degrees for a test layer with 50 scattered points; handles empty layers (returns None) | S |
| T1.1.4 | In `extract_layer_metadata`, extract attribute schema from `feature["properties"]`. For each attribute key: infer type from first non-null value (`isinstance` check), collect up to 5 unique sample values, count unique values. Cap at 20 attributes to avoid prompt bloat | Attribute schema includes type, sample values, unique count; large layers (1000+ features) complete in < 100ms; attributes beyond 20 are truncated with a note | S |

### Epic 1.2: Rich System Prompt Injection

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.2.1 | Add `format_layer_summary(metadata: dict) -> str` to `nl_gis/context.py`. Formats one layer's metadata as a compact string: `"parks_park (247 features, Polygon, bbox: [41.85,-87.68,41.92,-87.62], attributes: name(string, 230 unique), area_sqm(number, range 100-50000))"`. Keep under 200 chars per layer | Output string is readable and under 200 chars for a layer with 5 attributes; includes geometry type and bbox | S |
| T1.2.2 | Replace the layer metadata block in `ChatSession._process_message_inner()` (lines 714-738 of `nl_gis/chat.py`). Instead of `f"{name} ({count} features)"`, call `extract_layer_metadata()` for each relevant layer, then `format_layer_summary()`. Cap at 5 layers to limit prompt size. Use `_recently_referenced_layers` priority (existing logic at lines 720-731) | System prompt includes rich layer metadata; verified by logging the prompt and checking for attribute names; performance: < 200ms for 5 layers with 1000 features each | M |
| T1.2.3 | Apply the same rich metadata injection in `_generate_plan()` (lines 483-495 of `nl_gis/chat.py`), replacing the minimal layer info block | Plan mode also gets rich layer metadata in system prompt | S |

---

## M2: Conversational Reference Resolution

**Goal**: Track and resolve anaphoric references ("this", "those", "the results", "that area") to specific layers or locations.

### Epic 2.1: Reference Tracker

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.1.1 | Add `ReferenceTracker` class to `nl_gis/context.py`. Maintains an ordered history of `ReferenceEntry` objects: `{"turn": int, "type": "layer"|"location"|"result", "name": str, "metadata": dict}`. Max 20 entries (ring buffer). Methods: `add(entry)`, `resolve(reference_text: str) -> ReferenceEntry|None`, `get_recent(n=3) -> list[ReferenceEntry]` | Class instantiates correctly; add/resolve/get_recent methods work; ring buffer evicts oldest entry at capacity | S |
| T2.1.2 | Implement `ReferenceTracker.resolve()` with pattern matching rules. Input reference text (lowered). Rules: (1) "this layer" / "that layer" / "it" -> most recent layer entry; (2) "those" / "the results" / "those features" -> most recent layer entry; (3) "that area" / "this region" / "here" -> most recent location entry or layer bbox; (4) "the X" where X matches a layer name substring -> that specific layer; (5) Fallback: return None (let LLM handle it) | "those buildings" resolves to most recent layer named `*building*`; "that area" resolves to last location; "the parks" resolves to layer containing "park" in name; "something random" returns None | M |
| T2.1.3 | In `ChatSession.__init__()` (line 231 of `nl_gis/chat.py`), instantiate `self._ref_tracker = ReferenceTracker()`. In `_update_context()` (line 384), add entries to `_ref_tracker` when layers are created or locations are geocoded. Specifically: after `self.context["last_layer"] = result["layer_name"]`, add a layer reference entry; after `self.context["last_location"] = {...}`, add a location reference entry | ReferenceTracker is populated during tool execution; entries have correct turn numbers | S |

### Epic 2.2: Reference Resolution in System Prompt

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.2.1 | In `_process_message_inner()`, after building `ctx_parts` (line 746), add resolved references. Scan the user message for reference patterns ("this", "those", "that", "the results", etc.). For each match, call `_ref_tracker.resolve()`. Append resolved references to the system prompt under `RECENT CONTEXT`: e.g., `"'those' likely refers to: parks_park (247 features)"` | System prompt includes resolved references when user message contains anaphoric terms; no false positives for messages without references | M |
| T2.2.2 | Add reference patterns list as a module constant in `nl_gis/context.py`: `ANAPHORIC_PATTERNS = ["this", "that", "those", "these", "it", "the results", "the layer", "that area", "this region", "here", "the same"]`. Used by both the scanner in T2.2.1 and `ReferenceTracker.resolve()` | Patterns are defined; comprehensive enough to catch common cases; no overly broad patterns that match everything | XS |

---

## M3: Viewport Awareness

**Goal**: Use the current map viewport as an implicit bounding box for spatial queries when no explicit location is provided.

### Epic 3.1: Viewport as Default Bounding Box

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T3.1.1 | Add `format_viewport_hint(map_context: dict) -> str` to `nl_gis/context.py`. Converts `map_context["bounds"]` dict `{south, west, north, east}` to a hint string: `"Current viewport: {south},{west},{north},{east} (approximate area: {area_description})"`. Area description: reverse-geocode the center point to get a place name (use cache, don't call API). If no cache hit, use "lat/lon center" | Function returns formatted string; includes bbox coordinates; handles missing bounds gracefully (returns empty string) | S |
| T3.1.2 | In `_process_message_inner()` SYSTEM_PROMPT construction (line ~707), enhance the map bounds injection. Currently just logs bounds as text. Add: `"When the user says 'here', 'this area', 'on the map', or asks about features without specifying a location, use the current viewport as the bounding box: {south},{west},{north},{east}"` | System prompt explicitly instructs LLM to use viewport bounds as fallback; verified by prompt inspection | S |
| T3.1.3 | In `static/js/chat.js` `sendMessage()` function (line 176), enhance the `context` object to include `center: {lat, lng}` from `map.getCenter()` alongside the existing bounds. This gives the LLM a center point for proximity queries | Context object sent to `/api/chat` includes `center` field; no breaking change to existing bounds/zoom fields | XS |
| T3.1.4 | In `_process_message_inner()`, pass `map_context["center"]` (if present) to the system prompt: `"Map center: ({lat}, {lng})"`. Add instruction: `"For 'search nearby' without a specified location, use the map center as the search origin."` | System prompt includes map center; LLM uses it for unanchored proximity queries | XS |

---

## M4: Attribute-Aware Queries

**Goal**: When the LLM needs to style, filter, or analyze by attribute, ensure it knows which attributes exist on a layer before making tool calls.

### Epic 4.1: Proactive Attribute Checking

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.1.1 | Add `get_layer_attributes(layer_store: dict, layer_name: str, layer_lock) -> list[dict]` to `nl_gis/context.py`. Thread-safe snapshot via `_get_layer_snapshot()`. Returns list of `{"name": str, "type": str, "sample_values": list[str], "unique_count": int}` for each attribute. Cap at 20 attributes, 5 samples each | Function returns correct attribute list for a test layer; thread-safe; returns empty list for missing layer | S |
| T4.1.2 | In the SYSTEM_PROMPT (line 32 of `nl_gis/chat.py`), add instruction under `TOOL SELECTION`: `"Before calling style_layer, filter_layer, or highlight_features, check the CURRENT MAP STATE section for the target layer's available attributes. Only use attribute names that appear in the layer metadata. If the needed attribute doesn't exist, tell the user which attributes are available."` | Instruction added to SYSTEM_PROMPT; no functional code change needed here (metadata from M1 provides the data) | XS |
| T4.1.3 | In `_process_message_inner()`, when building the system prompt and the user message mentions styling/filtering keywords ("color", "style", "filter", "highlight", "show only"), expand the layer metadata for all active layers to include full attribute lists (not just the 5-layer cap). This ensures the LLM has attribute names when it needs them most | Attribute-related queries get expanded layer metadata; non-attribute queries get the standard 5-layer cap; detection uses keyword set: `{"color", "style", "filter", "highlight", "show only", "hide", "taller", "larger", "greater", "above", "below"}` | M |

### Epic 4.2: Attribute Validation in Handlers

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.2.1 | In `handle_filter_layer()` (`nl_gis/handlers/analysis.py`), before filtering, check if the specified `attribute` exists in the layer's feature properties. If not found, return `{"error": "Attribute '{attr}' not found in layer '{name}'. Available attributes: {list}"}` instead of returning 0 features silently | Filter on non-existent attribute returns error with available attribute names; filter on existing attribute works as before | S |
| T4.2.2 | In `handle_style_layer()` (`nl_gis/handlers/layers.py`), if `style_by_attribute` is specified, validate the attribute exists. Return error with available attributes if not found | Style-by-attribute on non-existent attribute returns error with suggestions; existing behavior unchanged for valid attributes | S |
| T4.2.3 | In `handle_highlight_features()` (`nl_gis/handlers/analysis.py` or `layers.py`), validate the `attribute` parameter against the layer's actual properties. Return error with available attributes if not found | Highlight with wrong attribute name returns helpful error; correct attribute works unchanged | S |

---

## M5: Test Context-Dependent Queries

**Goal**: Verify that 10 context-dependent queries produce correct results after the changes.

### Epic 5.1: Context Awareness Test Suite

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T5.1.1 | Create `tests/test_context.py`. Test `extract_layer_metadata()`: empty layer, point layer, polygon layer with attributes, mixed geometry layer, layer with > 20 attributes (truncation), large layer performance (1000 features < 200ms) | 6 test cases; all pass | M |
| T5.1.2 | Test `format_layer_summary()`: verify output under 200 chars, includes geometry type, includes bbox, includes attribute names | 4 test cases; all pass | S |
| T5.1.3 | Test `ReferenceTracker`: add 3 entries, resolve "those" -> most recent layer, resolve "that area" -> most recent location, resolve "the parks" -> layer with "park" in name, resolve "random text" -> None, test ring buffer eviction at capacity 20 | 5 test cases; all pass | S |
| T5.1.4 | Test `get_layer_attributes()`: valid layer returns correct attributes, missing layer returns empty list, thread-safety (concurrent reads don't crash) | 3 test cases; all pass | S |
| T5.1.5 | Test attribute validation in `handle_filter_layer()`: filter with non-existent attribute returns error with "Available attributes"; filter with existing attribute returns matches | 2 test cases; all pass | S |
| T5.1.6 | Integration test: mock the LLM and verify the system prompt contains rich layer metadata when layers are in `layer_store`. Verify the prompt includes attribute names, geometry types, and bbox | 1 test case; passes; verifies prompt structure | M |

---

## Dependencies and Risks

| Risk | Mitigation |
|------|-----------|
| Rich metadata bloats system prompt beyond token limits | Cap at 5 layers, 20 attributes per layer, 200 chars per layer summary; total overhead ~1000 chars |
| `extract_layer_metadata()` slow on large layers | Sample first 100 features for attribute inference; bbox from Shapely is O(n) but fast for GeoJSON |
| Reference resolution produces false positives | Require exact pattern match from `ANAPHORIC_PATTERNS` list; return None on ambiguity; LLM makes final decision |
| Viewport-as-default-bbox conflicts with explicit location queries | System prompt says "when no location specified"; LLM prioritizes explicit location over viewport |
| Attribute validation breaks backward compatibility for handlers | Only add validation where attribute is explicitly specified by user; existing happy paths unchanged |

## Files Modified

| File | Change |
|------|--------|
| `nl_gis/context.py` | **New file** -- `extract_layer_metadata()`, `format_layer_summary()`, `ReferenceTracker`, `format_viewport_hint()`, `get_layer_attributes()`, `ANAPHORIC_PATTERNS` |
| `nl_gis/chat.py` | Modify `_process_message_inner()` for rich metadata injection (M1), reference resolution (M2), viewport hints (M3), attribute-aware expansion (M4). Modify `__init__` for ReferenceTracker. Modify `_update_context()` for reference tracking. Modify `_generate_plan()` for rich metadata. Add instructions to `SYSTEM_PROMPT` |
| `static/js/chat.js` | Modify `sendMessage()` to include `center` in context object |
| `nl_gis/handlers/analysis.py` | Modify `handle_filter_layer()` for attribute validation |
| `nl_gis/handlers/layers.py` | Modify `handle_style_layer()` and `handle_highlight_features()` for attribute validation |
| `tests/test_context.py` | **New file** -- unit tests for all context awareness functions |
