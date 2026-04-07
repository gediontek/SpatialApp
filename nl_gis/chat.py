"""LLM integration for NL-to-GIS chat (multi-provider)."""

import json
import logging
import time
import threading
from typing import Generator

from config import Config
from nl_gis.tools import get_tool_definitions
from nl_gis.tool_handlers import dispatch_tool
from nl_gis.llm_provider import create_provider, DEFAULT_MODELS

try:
    from app import layer_lock as _layer_lock
except ImportError:
    import threading as _threading
    _layer_lock = _threading.Lock()

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a GIS assistant for SpatialApp. You translate natural language into spatial operations on a Leaflet.js map using 24 tools.

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

TOOL CHAINING PATTERNS (follow these for multi-step queries):
- "Show parks in Chicago" → fetch_osm(feature_type="park", location="Chicago") → map_command(action="fit_bounds")
- "Pan to DC, zoom level 15" → geocode(query="Washington DC") → map_command(action="pan_and_zoom", lat=..., lon=..., zoom=15)
- "How many buildings in downtown Seattle?" → fetch_osm(feature_type="building", location="downtown Seattle") → aggregate(layer_name=..., operation="count")
- "Parks within 2km of Central Park" → geocode(query="Central Park") → buffer(geometry=..., distance_m=2000) → fetch_osm(feature_type="park", location="Central Park area") → spatial_query(source_layer="park_...", predicate="intersects", target_layer="buffer_...")
- "Route from Times Square to Brooklyn Bridge" → find_route(from_location="Times Square", to_location="Brooklyn Bridge") → map_command(action="fit_bounds")
- "What can I reach in 15 min driving from downtown Portland?" → isochrone(location="downtown Portland", time_minutes=15, profile="driving")
- "Distance from the White House to the Capitol" → measure_distance(from_location="The White House", to_location="US Capitol Building")
- "Color the residential buildings red" → highlight_features(layer_name=..., attribute="feature_type", value="residential", color="#ff0000")

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
building, forest, water, park, grass, farmland, residential, commercial, industrial, road, river, lake

COORDINATE CONVENTION:
Tools handle lat/lon ↔ GeoJSON conversion automatically. You don't need to worry about coordinate order."""


class ChatSession:
    """Manages a conversation with Claude for NL-to-GIS operations."""

    def __init__(self, layer_store: dict = None):
        """Initialize a chat session.

        Args:
            layer_store: Server-side layer store for cross-tool references.
        """
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
        """Keep message history within bounds to prevent memory leaks."""
        if len(self.messages) > self.max_history:
            # Keep first message (context) + last N messages
            self.messages = [self.messages[0]] + self.messages[-(self.max_history - 1):]

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

        # Layer metadata (names + feature counts)
        if self.layer_store:
            layer_info = []
            for name, geojson in self.layer_store.items():
                count = len(geojson.get("features", [])) if isinstance(geojson, dict) else 0
                layer_info.append(f"{name} ({count} features)")
            state_parts.append(f"Active layers: {', '.join(layer_info)}")
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

                    for block in assistant_content:
                        if getattr(block, "type", None) == "tool_use":
                            tool_call_count += 1

                            if tool_call_count >= max_tool_calls:
                                yield {"type": "error", "text": f"Tool call limit ({max_tool_calls}) reached. Returning partial results."}
                                # Add empty tool_result for ALL remaining tool_use blocks
                                # to prevent message history corruption
                                remaining_results = []
                                for remaining in assistant_content:
                                    if getattr(remaining, "type", None) == "tool_use":
                                        remaining_results.append({
                                            "type": "tool_result",
                                            "tool_use_id": remaining.id,
                                            "content": "Tool call limit reached.",
                                        })
                                if remaining_results:
                                    self.messages.append({"role": "user", "content": remaining_results})
                                # Force a text response
                                self.messages.append({
                                    "role": "user",
                                    "content": "Tool call limit reached. Please summarize what you've found so far."
                                })
                                break

                            tool_name = block.name
                            tool_input = block.input

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

                            if "error" not in result:
                                completed_tools.append(tool_name)
                                # Update session context for multi-turn awareness
                                self._update_context(tool_name, tool_input, result)

                            # Handle special tool results
                            # Tools that produce layers
                            layer_tools = {"fetch_osm", "buffer", "spatial_query", "search_nearby", "classify_landcover", "find_route", "isochrone", "import_layer", "merge_layers", "filter_layer"}
                            if tool_name in layer_tools and "geojson" in result:
                                layer_name = result.get("layer_name", f"layer_{tool_call_count}")
                                with _layer_lock:
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

                    if tool_call_count >= max_tool_calls:
                        break

                    # Send tool results back to the LLM
                    self.messages.append({"role": "user", "content": tool_results})
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
                    result = dispatch_tool("geocode", {"query": place})
                    yield {"type": "tool_result", "tool": "geocode", "result": result}
                    if "error" not in result:
                        cmd = {"action": "pan_and_zoom", "lat": result["lat"], "lon": result["lon"], "zoom": zoom}
                        map_result = dispatch_tool("map_command", cmd)
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
            result = dispatch_tool("map_command", {"action": "zoom", "zoom": zoom})
            yield {"type": "map_command", **result}
            yield {"type": "message", "text": f"Zoom set to **{zoom}**.", "done": True}
            return

        # Basemap: satellite
        if "satellite" in msg:
            result = dispatch_tool("map_command", {"action": "change_basemap", "basemap": "satellite"})
            yield {"type": "map_command", **result}
            yield {"type": "message", "text": "Switched to satellite view.", "done": True}
            return

        # Basemap: OSM/street
        if "osm" in msg or "street" in msg:
            if any(w in msg for w in ["view", "map", "basemap", "street", "switch"]):
                result = dispatch_tool("map_command", {"action": "change_basemap", "basemap": "osm"})
                yield {"type": "map_command", **result}
                yield {"type": "message", "text": "Switched to OpenStreetMap view.", "done": True}
                return

        yield {
            "type": "error",
            "text": "AI assistant unavailable (no API key configured). Supported commands: 'pan to [place]', 'zoom to [place] level [N]', 'zoom in/out', 'zoom level [N]', 'satellite view', 'street view'."
        }
