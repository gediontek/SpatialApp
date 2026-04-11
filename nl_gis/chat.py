"""LLM integration for NL-to-GIS chat (multi-provider)."""

import json
import logging
import time
import threading
from typing import Generator

from config import Config
from nl_gis.tools import get_tool_definitions
from nl_gis.handlers import dispatch_tool, LAYER_PRODUCING_TOOLS
from nl_gis.llm_provider import create_provider, DEFAULT_MODELS


logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a GIS assistant for SpatialApp. You translate natural language into spatial operations on a Leaflet.js map using 46 tools.

RESPONSE RULES:
- Lead with the answer, then explain briefly.
- Use **bold** for key numbers: "Found **247 buildings**"
- Reference layer names exactly — they become clickable links in the UI.
- Report measurements in multiple units: **1.2 km** (0.75 mi), **3,400 sq m** (0.84 acres).
- Keep responses under 3 paragraphs. Use bullet lists for summaries.

TOOL SELECTION:
- fetch_osm: Use when the user asks to "show", "find", "get", "display" features in an area. Provide location name OR bbox; the tool geocodes automatically.
- search_nearby: Use when the user asks what is "near", "around", "within X meters of" a specific point.
- geocode: Use before map_command when the user names a place ("pan to DC", "zoom to Berlin").
- map_command: Use for navigation (pan, zoom, fit_bounds, change_basemap). Always follow a data fetch with fit_bounds so the user sees the results.
- spatial_query: Use for "which features overlap/contain/are within" another geometry or layer.
- buffer: Use before spatial_query when the user asks "within X distance of".
- aggregate: Use for "how many", "total area", "group by".
- filter_layer: Use to filter existing layers by attribute ("buildings taller than X", "parks larger than 1 hectare").
- style_layer: Use to change layer appearance ("color the parks green", "make roads thicker").
- closest_facility: Use when the user asks for "nearest", "closest" N features of a type from a point. Returns results sorted by distance.
- optimize_route: Use when the user wants to optimize visiting order of 3+ locations (traveling salesman / delivery route optimization).

Geometry operations:
- intersection: Use when the user asks "where do X and Y overlap?" Returns features present in both layers.
- difference: Use to subtract one layer from another ("remove water from land area").
- symmetric_difference: Use for features in either layer but not both ("what's unique to each?").
- convex_hull: Use when the user asks for the outer boundary or "footprint" of scattered points.
- centroid: Use to get center points of polygons ("get building centers").
- simplify: Use to reduce geometry complexity for export or display ("simplify for performance").
- bounding_box: Use to get the rectangular extent of a layer.
- dissolve: Use to merge features by attribute ("merge zones by type").
- clip: Use to cut one layer to the boundary of another ("cut buildings to city limits").
- voronoi: Use to create service areas / Thiessen polygons from point features.

Advanced analysis:
- point_in_polygon: Use to determine which polygon contains a point, or tag each point in a layer with its containing polygon. Single-point mode returns polygon properties; batch mode returns a new layer.
- attribute_join: Use to join tabular data to a spatial layer by matching an attribute. Useful for enriching features with external data.
- spatial_statistics: Use to analyze spatial clustering patterns. nearest_neighbor returns NNI (< 1 clustered, > 1 dispersed). dbscan groups nearby points into clusters.
- hot_spot_analysis: Use to identify statistically significant hot spots and cold spots using Getis-Ord Gi*. Requires a numeric attribute. Returns z-scores and p-values for each feature. Use for "where are crime hot spots?", "find clusters of high property values".

Geocoding:
- reverse_geocode: Use when the user provides coordinates and wants to know "what's at this location?"
- batch_geocode: Use when the user provides multiple addresses to geocode at once.

Data import/export:
- import_csv: Use when the user provides CSV data with lat/lon columns to plot as points.
- import_wkt: Use when the user provides a WKT geometry string to display on the map.
- import_layer: Use when the user provides raw GeoJSON to add as a layer.
- export_layer: Use when the user wants to download/export layer data (GeoJSON or shapefile).

Measurement & analysis:
- calculate_area: Use when the user asks "how big" or "what area" for polygon layers.
- measure_distance: Use when the user asks "how far" between two locations.

Layer management:
- show_layer / hide_layer / remove_layer: Use when the user wants to toggle or remove layers.
- highlight_features: Use when the user wants to visually emphasize specific features by attribute value.
- merge_layers: Use to combine multiple layers into one.

Annotations:
- add_annotation: Use when the user wants to save a manual annotation or marker.
- get_annotations / export_annotations: Use when the user wants to retrieve or export saved annotations.

Visualization:
- classify_landcover: Use for thematic classification of land cover features.
- heatmap: Use when the user wants a density/heat map visualization of point data.

Routing:
- find_route: Use when the user asks for directions or a route between locations.
- isochrone: Use when the user asks "what can I reach in X minutes?"

Code execution (fallback):
- execute_code: LAST RESORT. Use only when no other tool can accomplish the task. Generate Python using shapely/geopandas/numpy/scipy. Set `result` for text output or `geojson` for map layers.

TOOL CHAINING PATTERNS (follow these for multi-step queries):
- "Show parks in Chicago" → fetch_osm(feature_type="park", location="Chicago") → map_command(action="fit_bounds")
- "Pan to DC, zoom level 15" → geocode(query="Washington DC") → map_command(action="pan_and_zoom", lat=..., lon=..., zoom=15)
- "How many buildings in downtown Seattle?" → fetch_osm(feature_type="building", location="downtown Seattle") → aggregate(layer_name=..., operation="count")
- "Parks within 2km of Central Park" → geocode(query="Central Park") → buffer(geometry=..., distance_m=2000) → fetch_osm(feature_type="park", location="Central Park area") → spatial_query(source_layer="park_...", predicate="intersects", target_layer="buffer_...")
- "Route from Times Square to Brooklyn Bridge" → find_route(from_location="Times Square", to_location="Brooklyn Bridge") → map_command(action="fit_bounds")
- "What can I reach in 15 min driving from downtown Portland?" → isochrone(location="downtown Portland", time_minutes=15, profile="driving")
- "Distance from the White House to the Capitol" → measure_distance(from_location="The White House", to_location="US Capitol Building")
- "Color the residential buildings red" → highlight_features(layer_name=..., attribute="feature_type", value="residential", color="#ff0000")
- "Where do parks and flood zones overlap?" → fetch_osm(park) → fetch_osm(flood zone) → intersection(parks_layer, flood_layer)
- "What's at these coordinates?" → reverse_geocode(lat=..., lon=...)
- "Geocode this list of addresses" → batch_geocode(addresses=[...]) → map_command(action="fit_bounds")
- "Remove water from the land area" → fetch_osm(land) → fetch_osm(water) → difference(land_layer, water_layer)
- "Draw boundary around crime data" → convex_hull(layer_name="crime_layer")
- "Get building centers" → centroid(layer_name="buildings_layer")
- "Simplify for export" → simplify(layer_name=..., tolerance=50)
- "Show the extent of these features" → bounding_box(layer_name=...)
- "Merge zones by type" → dissolve(layer_name=..., by="zone_type")
- "Cut buildings to city boundary" → clip(clip_layer="buildings", mask_layer="city_boundary")
- "Create service areas from stations" → voronoi(layer_name="stations")
- "Plot this CSV data" → import_csv(csv_data="...", lat_column="latitude", lon_column="longitude")
- "Import this WKT polygon" → import_wkt(wkt="POLYGON((...))") → map_command(action="fit_bounds")
- "Export buildings as shapefile" → export_layer(layer_name="buildings", format="shapefile")
- "Find 3 nearest hospitals to Times Square" → closest_facility(location="Times Square", feature_type="hospital", count=3)
- "Optimize route visiting these 5 stops" → optimize_route(locations=[{lat, lon}, ...], profile="auto")
- "Which district is this point in?" → point_in_polygon(lat=..., lon=..., polygon_layer="districts")
- "Tag each store with its census tract" → point_in_polygon(point_layer="stores", polygon_layer="census_tracts")
- "Add population data to districts" → attribute_join(layer_name="districts", join_data=[...], layer_key="id", data_key="district_id")
- "Are these crime points clustered?" → spatial_statistics(layer_name="crimes", method="nearest_neighbor")
- "Find clusters in restaurant data" → spatial_statistics(layer_name="restaurants", method="dbscan", eps=200, min_samples=3)
- "Analyze crime hot spots" → fetch_osm(feature_type="police", location="Chicago") → hot_spot_analysis(layer_name="crime_data", attribute="count")
- "Where are property values highest?" → hot_spot_analysis(layer_name="parcels", attribute="price")
- "Import CSV and show heatmap" → import_csv(csv_data="...", lat_column="lat", lon_column="lon") → heatmap(layer_name="csv_import") → map_command(action="fit_bounds")
- "What's unique to each zoning layer?" → symmetric_difference(layer_a="zoning_2020", layer_b="zoning_2023") → calculate_area(layer_name="symmetric_difference_...")
- "Nearest 3 schools walkable from my location" → closest_facility(location="...", feature_type="school", count=3) → find_route(from_location="...", to_location="...", profile="walking")

EXAMPLE CONVERSATIONS:
Example 1 — Multi-step spatial analysis:
User: "How many restaurants are within 500m of Central Park?"
Assistant thinking: Need to (1) find Central Park, (2) create 500m buffer, (3) find restaurants in the area, (4) spatial_query to find which are within the buffer, (5) count them.
Tool calls: geocode("Central Park, NYC") → buffer(geometry=park_bbox_polygon, distance_m=500) → search_nearby(lat=40.78, lon=-73.97, radius_m=600, feature_type="restaurant") → spatial_query(source="restaurants_nearby_...", predicate="within", target="buffer_...") → aggregate(layer="spatial_query_...", operation="count")
Result: "Found **23 restaurants** within 500m of Central Park."

Example 2 — Layer comparison:
User: "Show me where parks and commercial zones overlap in downtown Seattle"
Tool calls: fetch_osm(feature_type="park", location="downtown Seattle") → fetch_osm(feature_type="commercial", location="downtown Seattle") → intersection(layer_a="parks_...", layer_b="commercial_...") → calculate_area(layer_name="intersection_...")
Result: "The overlap between parks and commercial zones covers **0.12 sq km** (29.6 acres)."

Example 3 — Overlay operations:
User: "Show overlap between parks and flood zones in Portland"
Tool calls: fetch_osm(feature_type="park", location="Portland, Oregon") → fetch_osm(feature_type="water", location="Portland, Oregon", category_name="flood_zones") → intersection(layer_a="parks_...", layer_b="flood_zones") → calculate_area(layer_name="intersection_...") → style_layer(layer_name="intersection_...", color="#ff0000", fill_opacity=0.5)
Result: "Found **0.08 sq km** (19.8 acres) of park area overlapping flood zones. Highlighted in red on the map."

Example 4 — Import + analyze:
User: "Import this CSV and find clusters: name,lat,lon\nA,40.71,-74.01\nB,40.72,-74.00\nC,40.715,-74.005\nD,40.80,-73.95\nE,40.81,-73.96"
Tool calls: import_csv(csv_data="name,lat,lon\nA,40.71,-74.01\n...", lat_column="lat", lon_column="lon", layer_name="imported_points") → spatial_statistics(layer_name="imported_points", method="dbscan", eps=200, min_samples=2) → map_command(action="fit_bounds")
Result: "Imported **5 points** and found **2 clusters**: cluster 0 has 3 points in Lower Manhattan, cluster 1 has 2 points in Upper Manhattan. NNI = **0.45** indicating significant clustering."

Example 5 — Network analysis:
User: "Find the 5 nearest hospitals from Times Square"
Tool calls: closest_facility(location="Times Square, NYC", feature_type="hospital", count=5) → map_command(action="fit_bounds")
Result: "Found **5 hospitals** nearest to Times Square: 1. NYC Health (0.4 km), 2. Bellevue (1.2 km), 3. Mount Sinai West (1.8 km), 4. NYU Langone (2.1 km), 5. Lenox Hill (2.9 km)."

DISAMBIGUATION:
- When a place name is ambiguous (e.g., "Washington" could be DC, state, or 30+ other places), check the current map bounds. If the map shows the east coast, assume DC. If ambiguity remains, ask: "Did you mean Washington, D.C. or Washington State?"
- When the user says "those", "that layer", "the buildings" — check the RECENT CONTEXT section below for the last layer created or referenced.
- "Zoom in" without a level → increase zoom by 2 from current. "Zoom out" → decrease by 2.

LIMITS:
- fetch_osm: max 5,000 features. If capped, say so and suggest a smaller area.
- buffer: max 100 km. search_nearby: max 50 km radius.
- Max 10 tool calls per message. If you need more, summarize partial results and offer to continue.

ERROR RECOVERY:
- 0 features returned → suggest different feature_type or larger area.
- Tool error → explain what went wrong and suggest an alternative approach. Never just echo the error.
- Routing/isochrone failure → likely a service issue; tell the user to retry.
- If the user asks for something you can't do (3D, real-time traffic, satellite imagery analysis), say what's not possible and suggest what IS possible.

FEATURE TYPES (for fetch_osm and search_nearby):
Land use: building, forest, water, park, grass, farmland, residential, commercial, industrial, road, river, lake
Amenities: restaurant, school, hospital, pharmacy, supermarket, hotel, church, mosque, bank, atm, cafe, bar, cinema, library, university, police, fire_station, post_office
Transport: bus_stop, rail, parking, fuel
Recreation: playground, stadium, swimming_pool, cemetery
Nature: wetland, beach, cliff
For unlisted types, use osm_key and osm_value parameters for custom Overpass queries.

COORDINATE CONVENTION:
Tools handle lat/lon ↔ GeoJSON conversion automatically. You don't need to worry about coordinate order."""


class ChatSession:
    """Manages a conversation with Claude for NL-to-GIS operations."""

    def __init__(self, layer_store: dict = None, layer_lock=None):
        """Initialize a chat session.

        Args:
            layer_store: Server-side layer store for cross-tool references.
            layer_lock: Threading lock for layer_store access. If None, creates a local lock.
        """
        self._layer_lock = layer_lock or threading.Lock()
        self.messages = []
        self.max_history = 50  # Keep last 50 messages to prevent memory leak
        self.layer_store = layer_store or {}
        self.client = None
        self.usage = {"total_input_tokens": 0, "total_output_tokens": 0, "api_calls": 0}
        self._lock = threading.Lock()  # Prevent concurrent process_message on same session
        # Session context for multi-turn awareness
        self.context = {
            "last_location": None,      # {"name": str, "lat": float, "lon": float}
            "last_layer": None,         # layer name string
            "last_operation": None,     # {"tool": str, "summary": str}
        }
        self._recently_referenced_layers = set()  # Layers referenced in recent turns
        self._turn_counter = 0  # Tracks conversation turns for layer recency
        self._init_client()

    def _init_client(self):
        """Initialize the LLM provider if an API key is available."""
        provider_name = Config.LLM_PROVIDER
        api_key = Config.get_llm_api_key()
        if not api_key:
            logger.warning(
                f"No API key set for provider '{provider_name}'. "
                "Chat will use rule-based fallback only."
            )
            return

        base_url = Config.OPENAI_BASE_URL if provider_name.lower() == "openai" else None
        self.client = create_provider(provider_name, api_key, base_url=base_url)
        if self.client:
            logger.info(f"LLM provider initialized: {provider_name}")
        else:
            logger.error(f"Failed to create LLM provider: {provider_name}")

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed in this session (input + output)."""
        return self.usage["total_input_tokens"] + self.usage["total_output_tokens"]

    def _budget_exceeded(self) -> bool:
        """Check if session token budget is exhausted."""
        return self.total_tokens >= Config.MAX_TOKENS_PER_SESSION

    def _call_llm_with_retry(self, **kwargs):
        """Call the LLM provider with retry + exponential backoff.

        Retries up to 3 times on transient errors (rate limit, timeout,
        server error). Non-retryable errors are raised immediately.
        """
        max_retries = 3
        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                return self.client.create_message(**kwargs)
            except Exception as e:
                last_exception = e
                error_str = str(e).lower()
                error_type = type(e).__name__

                # Determine if the error is retryable
                retryable = False

                # Check for common transient HTTP error indicators
                if any(keyword in error_str for keyword in
                       ("rate limit", "429", "timeout", "timed out",
                        "500", "502", "503", "529", "overloaded",
                        "internal server error", "service unavailable")):
                    retryable = True

                # Check for anthropic SDK specific exceptions
                if error_type in ("RateLimitError", "APITimeoutError",
                                  "InternalServerError", "APIStatusError",
                                  "OverloadedError", "APIConnectionError"):
                    retryable = True

                if not retryable or attempt == max_retries:
                    raise

                wait_time = (2 ** attempt) + 0.5  # 1.5s, 2.5s, 4.5s
                logger.warning(
                    "LLM API call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1, max_retries, error_type, wait_time,
                )
                time.sleep(wait_time)

        # Should not reach here, but satisfy type checker
        raise last_exception

    def _trim_history(self):
        """Keep message history within bounds to prevent memory leaks.

        Ensures trim boundary never splits a tool_use/tool_result pair.
        """
        if len(self.messages) > self.max_history:
            # Keep first message (context) + last N messages
            keep_from = len(self.messages) - (self.max_history - 1)

            # If the message at the trim boundary is a user message with
            # tool_result content, it's orphaned from its preceding assistant
            # tool_use message. Move the boundary one earlier to include both.
            if keep_from > 1:
                boundary_msg = self.messages[keep_from]
                if (boundary_msg.get("role") == "user"
                        and isinstance(boundary_msg.get("content"), list)
                        and any(
                            (isinstance(b, dict) and b.get("type") == "tool_result")
                            for b in boundary_msg["content"]
                        )):
                    keep_from -= 1

            trimmed = [self.messages[0]] + self.messages[keep_from:]

            # If the last message is an assistant with tool_use blocks (its
            # tool_result was trimmed), remove it to maintain the invariant.
            if len(trimmed) > 1:
                last = trimmed[-1]
                if (last.get("role") == "assistant"
                        and isinstance(last.get("content"), list)
                        and any(
                            (isinstance(b, dict) and b.get("type") == "tool_use")
                            for b in last["content"]
                        )):
                    trimmed = trimmed[:-1]

            self.messages = trimmed

    @staticmethod
    def _serialize_content(content):
        """Serialize LLM response content blocks to JSON-safe dicts."""
        serialized = []
        for block in content:
            if getattr(block, "type", None) == "tool_use":
                serialized.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
            elif hasattr(block, "text"):
                serialized.append({"type": "text", "text": block.text})
            else:
                serialized.append({"type": "unknown"})
        return serialized

    def _update_context(self, tool_name: str, tool_input: dict, result: dict):
        """Track session context from tool results for multi-turn awareness."""
        # Track last geocoded location
        if tool_name == "geocode" and "lat" in result:
            self.context["last_location"] = {
                "name": result.get("display_name", tool_input.get("query", "")),
                "lat": result["lat"],
                "lon": result["lon"],
            }
        # Track last layer created
        if "layer_name" in result:
            self.context["last_layer"] = result["layer_name"]
            self._recently_referenced_layers.add(result["layer_name"])
        # Track layers referenced as inputs (source_layer, target_layer, layer_name, etc.)
        for key in ("layer_name", "source_layer", "target_layer", "layer_a",
                     "layer_b", "clip_layer", "mask_layer"):
            ref = tool_input.get(key)
            if ref and isinstance(ref, str):
                self._recently_referenced_layers.add(ref)
        # Track last operation summary
        summary_map = {
            "fetch_osm": lambda: f"fetched {result.get('feature_count', '?')} {tool_input.get('feature_type', 'features')}",
            "buffer": lambda: f"buffered by {tool_input.get('distance_m', '?')}m",
            "spatial_query": lambda: f"{tool_input.get('predicate', 'query')} found {result.get('feature_count', '?')} features",
            "aggregate": lambda: f"{tool_input.get('operation', 'aggregation')}: {result.get('total', result.get('total_area_sq_km', '?'))}",
            "find_route": lambda: f"route {result.get('distance_km', '?')} km, {result.get('duration_min', '?')} min",
            "isochrone": lambda: f"isochrone {tool_input.get('time_minutes', '?')} min {tool_input.get('profile', 'driving')}",
            "search_nearby": lambda: f"found {result.get('feature_count', '?')} nearby {tool_input.get('feature_type', 'features')}",
        }
        if tool_name in summary_map:
            try:
                self.context["last_operation"] = {"tool": tool_name, "summary": summary_map[tool_name]()}
            except Exception:
                logger.debug("Failed to update context for tool %s", tool_name, exc_info=True)

    def process_message(self, message: str, map_context: dict = None) -> Generator[dict, None, None]:
        """Process a user message and yield events.

        Yields events:
            {"type": "tool_start", "tool": str, "input": dict}
            {"type": "tool_result", "tool": str, "result": dict}
            {"type": "layer_add", "name": str, "geojson": dict, "style": dict}
            {"type": "map_command", ...command params...}
            {"type": "message", "text": str, "done": bool}
            {"type": "error", "text": str}

        Args:
            message: User's natural language input.
            map_context: Current map state (bounds, zoom, layers).

        Yields:
            Event dicts for SSE streaming.
        """
        if not self._lock.acquire(timeout=330):  # Must exceed max tool timeout (300s)
            yield {"type": "error", "text": "Session is busy processing another request. Please wait."}
            return

        try:
            yield from self._process_message_inner(message, map_context)
        finally:
            self._lock.release()

    def _process_message_inner(self, message: str, map_context: dict = None) -> Generator[dict, None, None]:
        """Internal message processing (called under lock)."""
        if not self.client:
            # Rule-based fallback
            yield from self._fallback_process(message)
            return

        # Track turn counter for layer recency; reset referenced layers every 3 turns
        self._turn_counter += 1
        if self._turn_counter % 3 == 0:
            self._recently_referenced_layers.clear()

        # Build dynamic system prompt with map state and session context
        system = SYSTEM_PROMPT
        state_parts = []

        # Map state
        if map_context:
            if "bounds" in map_context:
                b = map_context["bounds"]
                state_parts.append(f"Map bounds: south={b.get('south')}, west={b.get('west')}, north={b.get('north')}, east={b.get('east')}")
            if "zoom" in map_context:
                state_parts.append(f"Zoom level: {map_context['zoom']}")

        # Layer metadata: prefer recently-referenced layers, fallback to last 5
        with self._layer_lock:
            layer_snapshot = dict(self.layer_store)
        if layer_snapshot:
            layer_info = []
            total_layers = len(layer_snapshot)
            # Filter to recently-referenced layers if any exist
            if self._recently_referenced_layers:
                relevant = {
                    name: geojson
                    for name, geojson in layer_snapshot.items()
                    if name in self._recently_referenced_layers
                }
            else:
                relevant = {}
            # Fallback: if no recent layers match, show the last 5
            if not relevant:
                layer_items = list(layer_snapshot.items())
                relevant = dict(layer_items[-5:])
            for name, geojson in relevant.items():
                count = len(geojson.get("features", [])) if isinstance(geojson, dict) else 0
                layer_info.append(f"{name} ({count} features)")
            summary = f"Active layers: {', '.join(layer_info)}"
            if total_layers > len(relevant):
                summary += f" ({total_layers} layers total, showing {len(relevant)} relevant)"
            state_parts.append(summary)
        else:
            state_parts.append("Active layers: none")

        if state_parts:
            system += "\n\nCURRENT MAP STATE:\n" + "\n".join(state_parts)

        # Recent context for multi-turn reference resolution
        ctx_parts = []
        if self.context["last_location"]:
            loc = self.context["last_location"]
            ctx_parts.append(f"Last location: {loc['name']} ({loc['lat']:.4f}, {loc['lon']:.4f})")
        if self.context["last_layer"]:
            ctx_parts.append(f"Last layer created: {self.context['last_layer']}")
        if self.context["last_operation"]:
            op = self.context["last_operation"]
            ctx_parts.append(f"Last operation: {op['tool']} — {op['summary']}")
        if ctx_parts:
            system += "\n\nRECENT CONTEXT:\n" + "\n".join(ctx_parts)

        # Add user message to history (with cap)
        self.messages.append({"role": "user", "content": message})
        self._trim_history()

        tools = get_tool_definitions()
        model = Config.get_llm_model()
        tool_call_count = 0
        max_tool_calls = Config.MAX_TOOL_CALLS_PER_MESSAGE
        completed_tools = []  # Track successful tools for error recovery
        tool_metrics = []  # Per-tool-call instrumentation

        try:
            while True:
                # Check token budget before each LLM call
                if self._budget_exceeded():
                    budget = Config.MAX_TOKENS_PER_SESSION
                    yield {
                        "type": "error",
                        "text": (
                            f"Session token budget exhausted ({self.total_tokens:,} / {budget:,} tokens). "
                            "Please start a new chat session to continue."
                        ),
                    }
                    return

                response = self._call_llm_with_retry(
                    model=model,
                    max_tokens=2048,
                    system=system,
                    tools=tools,
                    messages=self.messages,
                )

                # Track token usage
                self.usage["total_input_tokens"] += response.input_tokens
                self.usage["total_output_tokens"] += response.output_tokens
                self.usage["api_calls"] += 1
                logger.info(
                    "LLM API usage: input=%d output=%d total_in=%d total_out=%d calls=%d",
                    response.input_tokens,
                    response.output_tokens,
                    self.usage["total_input_tokens"],
                    self.usage["total_output_tokens"],
                    self.usage["api_calls"],
                )

                # Serialize content blocks to dicts for JSON safety
                assistant_content = response.content
                serialized = self._serialize_content(assistant_content)
                self.messages.append({"role": "assistant", "content": serialized})

                # Check if we need to handle tool use
                if response.stop_reason == "tool_use":
                    tool_results = []
                    processed_ids = set()  # Track dispatched tool_use IDs (H1b fix)
                    tool_calls_this_iteration = 0  # Guard for M2

                    for block in assistant_content:
                        if getattr(block, "type", None) == "tool_use":
                            tool_call_count += 1

                            if tool_call_count > max_tool_calls:  # H1a: changed >= to >
                                yield {"type": "error", "text": f"Tool call limit ({max_tool_calls}) reached. Returning partial results."}
                                # H1b: Only create "limit reached" results for
                                # tool_use blocks NOT already processed
                                remaining_results = list(tool_results)  # keep already-executed results
                                for remaining in assistant_content:
                                    if (getattr(remaining, "type", None) == "tool_use"
                                            and remaining.id not in processed_ids):
                                        remaining_results.append({
                                            "type": "tool_result",
                                            "tool_use_id": remaining.id,
                                            "content": "Tool call limit reached.",
                                        })
                                # H2: Merge remaining results + summarization into
                                # a single user message to avoid consecutive user messages
                                if remaining_results:
                                    remaining_results.append({
                                        "type": "text",
                                        "text": "Tool call limit reached. Please summarize what you've found so far.",
                                    })
                                    self.messages.append({"role": "user", "content": remaining_results})
                                else:
                                    self.messages.append({
                                        "role": "user",
                                        "content": "Tool call limit reached. Please summarize what you've found so far."
                                    })
                                break

                            tool_name = block.name
                            tool_input = block.input
                            processed_ids.add(block.id)
                            tool_calls_this_iteration += 1

                            yield {"type": "tool_start", "tool": tool_name, "input": tool_input}

                            # Execute tool
                            try:
                                result = dispatch_tool(tool_name, tool_input, self.layer_store)
                            except ValueError as e:
                                # Expected validation errors — safe to return
                                result = {"error": str(e)}
                            except Exception as e:
                                # Unexpected errors — log details, return generic message
                                logger.error(f"Tool {tool_name} failed: {e}", exc_info=True)
                                result = {"error": f"Tool '{tool_name}' encountered an internal error."}

                            yield {"type": "tool_result", "tool": tool_name, "result": result}

                            # Track per-tool metrics
                            tool_metrics.append({
                                "tool": tool_name,
                                "success": "error" not in result,
                                "chain_position": tool_call_count,
                                "retry": False,
                            })

                            if "error" not in result:
                                completed_tools.append(tool_name)
                                # Update session context for multi-turn awareness
                                self._update_context(tool_name, tool_input, result)

                            # Handle special tool results
                            # Tools that produce layers
                            if tool_name in LAYER_PRODUCING_TOOLS and "geojson" in result:
                                layer_name = result.get("layer_name", f"layer_{tool_call_count}")
                                with self._layer_lock:
                                    self.layer_store[layer_name] = result["geojson"]

                                # Pick style based on tool
                                style = {"color": "#3388ff", "weight": 2}
                                if tool_name == "buffer":
                                    style = {"color": "#ff7800", "weight": 2, "fillOpacity": 0.15}
                                elif tool_name == "spatial_query":
                                    style = {"color": "#e31a1c", "weight": 2}
                                elif tool_name == "classify_landcover":
                                    style = {"color": "#33a02c", "weight": 1, "fillOpacity": 0.6}
                                elif tool_name == "find_route":
                                    style = {"color": "#6610f2", "weight": 4, "fillOpacity": 0}
                                elif tool_name == "isochrone":
                                    style = {"color": "#20c997", "weight": 2, "fillOpacity": 0.2}

                                yield {
                                    "type": "layer_add",
                                    "name": layer_name,
                                    "geojson": result["geojson"],
                                    "style": style,
                                    "colors": result.get("colors"),  # For classification legend
                                }

                            # Map navigation commands
                            if tool_name == "map_command" and result.get("success"):
                                yield {"type": "map_command", **result}

                            # Layer visibility commands
                            if tool_name in ("show_layer", "hide_layer", "remove_layer") and result.get("success"):
                                yield {"type": "layer_command", **result}

                            # Feature highlighting
                            if tool_name == "highlight_features" and result.get("success"):
                                yield {"type": "highlight", **result}

                            # Layer styling
                            if tool_name == "style_layer" and result.get("success"):
                                yield {"type": "layer_style", **result}

                            # Heatmap rendering instruction
                            if tool_name == "heatmap" and result.get("success"):
                                yield {"type": "heatmap", **result}

                            # Add tool result to messages for next LLM call
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "name": tool_name,  # Needed by Gemini provider
                                "content": json.dumps(result),
                            })

                    if tool_call_count > max_tool_calls:  # H1a: changed >= to >
                        break

                    # M2: Guard against infinite loop — stop_reason was tool_use
                    # but no tool_use blocks were found in content
                    if tool_calls_this_iteration == 0:
                        logger.warning(
                            "LLM returned stop_reason=tool_use but no tool_use "
                            "blocks found in content. Breaking to prevent infinite loop."
                        )
                        break

                    # M3: Only append tool_results if non-empty
                    if tool_results:
                        self.messages.append({"role": "user", "content": tool_results})
                    else:
                        logger.warning("No tool results to append despite tool_use stop_reason.")
                        break
                    continue  # Loop to get LLM's next response

                else:
                    # End turn — extract text response
                    text_parts = []
                    for block in assistant_content:
                        if hasattr(block, "text"):
                            text_parts.append(block.text)

                    text = "\n".join(text_parts) if text_parts else "I processed your request but have nothing additional to add."
                    yield {
                        "type": "message",
                        "text": text,
                        "done": True,
                        "usage": self.usage.copy(),
                        "tool_metrics": tool_metrics,
                    }
                    break

        except Exception as e:
            logger.error(f"LLM processing error: {e}", exc_info=True)
            partial = ""
            if completed_tools:
                partial = f" Completed {len(completed_tools)} tool(s) before failure: {', '.join(completed_tools)}. Any layers created are still on the map."
            error_type = type(e).__name__
            yield {"type": "error", "text": f"AI service error ({error_type}). Please try again.{partial}"}

    def _fallback_process(self, message: str) -> Generator[dict, None, None]:
        """Rule-based fallback when LLM API is unavailable. Handles common NL patterns."""
        msg = message.lower().strip()
        import re

        # Navigation: "pan to DC", "zoom to Berlin", "go to Paris"
        nav_prefixes = ["zoom to ", "go to ", "show me ", "pan to ", "navigate to ", "fly to "]
        for prefix in nav_prefixes:
            if prefix in msg:
                place = msg.split(prefix, 1)[1].strip().rstrip(".")
                # Check for zoom level: "zoom to DC level 15" or "zoom to DC, 15"
                zoom_match = re.search(r'(?:level|zoom)\s*(\d+)', place)
                zoom = int(zoom_match.group(1)) if zoom_match else 13
                if zoom_match:
                    place = place[:zoom_match.start()].strip().rstrip(",")
                if place:
                    yield {"type": "tool_start", "tool": "geocode", "input": {"query": place}}
                    try:
                        result = dispatch_tool("geocode", {"query": place}, layer_store=self.layer_store)
                    except Exception as e:
                        logger.error("Fallback dispatch_tool failed for geocode", exc_info=True)
                        yield {"type": "error", "error": "Tool execution failed"}
                        return
                    yield {"type": "tool_result", "tool": "geocode", "result": result}
                    if "error" not in result:
                        cmd = {"action": "pan_and_zoom", "lat": result["lat"], "lon": result["lon"], "zoom": zoom}
                        try:
                            map_result = dispatch_tool("map_command", cmd, layer_store=self.layer_store)
                        except Exception as e:
                            logger.error("Fallback dispatch_tool failed for map_command", exc_info=True)
                            yield {"type": "error", "error": "Tool execution failed"}
                            return
                        yield {"type": "map_command", **map_result}
                        yield {"type": "message", "text": f"Panned to **{result['display_name']}** (zoom {zoom})", "done": True}
                    else:
                        yield {"type": "message", "text": result["error"], "done": True}
                    return

        # Zoom in/out (relative to current zoom level)
        if msg in ("zoom in", "zoom in more"):
            yield {"type": "map_command", "action": "zoom_relative", "delta": 2, "success": True, "description": "Zoomed in"}
            yield {"type": "message", "text": "Zoomed in.", "done": True}
            return
        if msg in ("zoom out", "zoom out more"):
            yield {"type": "map_command", "action": "zoom_relative", "delta": -2, "success": True, "description": "Zoomed out"}
            yield {"type": "message", "text": "Zoomed out.", "done": True}
            return

        # Set zoom level: "zoom level 15", "set zoom 12"
        zoom_match = re.match(r'(?:set\s+)?zoom\s*(?:level\s*)?(\d+)', msg)
        if zoom_match:
            zoom = int(zoom_match.group(1))
            try:
                result = dispatch_tool("map_command", {"action": "zoom", "zoom": zoom}, layer_store=self.layer_store)
            except Exception as e:
                logger.error("Fallback dispatch_tool failed for map_command", exc_info=True)
                yield {"type": "error", "error": "Tool execution failed"}
                return
            yield {"type": "map_command", **result}
            yield {"type": "message", "text": f"Zoom set to **{zoom}**.", "done": True}
            return

        # Basemap: satellite
        if "satellite" in msg:
            try:
                result = dispatch_tool("map_command", {"action": "change_basemap", "basemap": "satellite"}, layer_store=self.layer_store)
            except Exception as e:
                logger.error("Fallback dispatch_tool failed for map_command", exc_info=True)
                yield {"type": "error", "error": "Tool execution failed"}
                return
            yield {"type": "map_command", **result}
            yield {"type": "message", "text": "Switched to satellite view.", "done": True}
            return

        # Basemap: OSM/street
        if "osm" in msg or "street" in msg:
            if any(w in msg for w in ["view", "map", "basemap", "street", "switch"]):
                try:
                    result = dispatch_tool("map_command", {"action": "change_basemap", "basemap": "osm"}, layer_store=self.layer_store)
                except Exception as e:
                    logger.error("Fallback dispatch_tool failed for map_command", exc_info=True)
                    yield {"type": "error", "error": "Tool execution failed"}
                    return
                yield {"type": "map_command", **result}
                yield {"type": "message", "text": "Switched to OpenStreetMap view.", "done": True}
                return

        yield {
            "type": "error",
            "text": "AI assistant unavailable (no API key configured). Supported commands: 'pan to [place]', 'zoom to [place] level [N]', 'zoom in/out', 'zoom level [N]', 'satellite view', 'street view'."
        }
