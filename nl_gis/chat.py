"""Claude API integration for NL-to-GIS chat."""

import json
import logging
import threading
from typing import Generator

import anthropic

from config import Config
from nl_gis.tools import get_tool_definitions
from nl_gis.tool_handlers import dispatch_tool

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a GIS assistant integrated into SpatialApp, a web-based geospatial labeling and analysis tool. You help users interact with maps and spatial data through natural language.

You have access to 24 spatial tools that operate on a Leaflet.js map. When a user asks a spatial question, use the appropriate tool(s) to answer it.

GUIDELINES:
- Always use the geocode tool when the user references a place by name.
- When fetching OSM data, prefer using a location name — the tool geocodes automatically.
- Return specific numbers: "247 buildings" not "many buildings".
- Use descriptive layer names: "chicago_buildings" not "result_1".
- Chain tools when needed: geocode → fetch → analyze → display.
- After fetching data, use map_command with fit_bounds to show results.
- For area/distance, report multiple units (sq m, sq km, acres / m, km, mi).
- Reference layer names in your response — users can click them to zoom.
- Use markdown formatting: **bold** for key numbers, bullet lists for summaries.
- Keep responses concise. Lead with the answer, then explain.

TOOL LIMITS:
- fetch_osm returns max 5,000 features. If capped, tell the user.
- buffer max distance: 100 km (100,000 meters).
- search_nearby max radius: 50 km (50,000 meters).
- Max 10 tool calls per message. If you need more, summarize partial results.

ERROR RECOVERY:
- If a tool returns an error, explain what went wrong and suggest alternatives.
- If fetch_osm returns 0 features, suggest trying a different feature_type or larger area.
- If routing fails, it may be a service issue — tell the user to try again.
- Never just echo an error message. Always add context for the user.

COORDINATE CONVENTION:
- Leaflet uses [lat, lng]; GeoJSON uses [lng, lat].
- Tools handle conversion automatically. You don't need to worry about this.

AVAILABLE FEATURE TYPES for fetch_osm and search_nearby:
building, forest, water, park, grass, farmland, residential, commercial, industrial, road, river, lake

TOOLS (24 total):

Navigation & Data:
- geocode: Convert place name to coordinates
- fetch_osm: Fetch OSM features by type in an area (max 5,000)
- search_nearby: Find features near a point within radius
- map_command: Pan, zoom, fit bounds, change basemap (osm/satellite)
- import_layer: Import GeoJSON data as a named layer

Spatial Analysis:
- calculate_area: Geodesic area of polygons (multiple units)
- measure_distance: Distance between two points (m, km, mi)
- buffer: Create buffer polygon around features (max 100km)
- spatial_query: Find features by spatial predicate (intersects, within, contains, within_distance)
- aggregate: Count, total area, group by attribute
- merge_layers: Combine two layers (union or spatial join)

Layer Management:
- show_layer / hide_layer / remove_layer: Control layer visibility
- highlight_features: Highlight features matching an attribute value and color

Annotation & Classification:
- add_annotation: Save features as labeled annotations with category
- classify_landcover: Auto-classify land use (7 categories) from OSM data
- export_annotations: Export as GeoJSON, Shapefile, or GeoPackage
- get_annotations: List current annotations with category breakdown

Routing & Visualization:
- find_route: Route between two points (driving/walking/cycling via Valhalla)
- isochrone: Reachable area from a point (true network-based, not circular)
- heatmap: Density visualization from feature centroids"""


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
        self._init_client()

    def _init_client(self):
        """Initialize the Anthropic client if API key is available.

        Validates the key format and logs clear warnings for misconfiguration.
        """
        api_key = Config.ANTHROPIC_API_KEY
        if not api_key:
            logger.warning("No ANTHROPIC_API_KEY set. Chat will use rule-based fallback only.")
            return
        if not api_key.startswith("sk-ant-"):
            logger.error(
                "ANTHROPIC_API_KEY appears invalid (expected 'sk-ant-...' format). "
                "Chat may fail on first request. Check your .env file."
            )
        self.client = anthropic.Anthropic(api_key=api_key)

    def _trim_history(self):
        """Keep message history within bounds to prevent memory leaks."""
        if len(self.messages) > self.max_history:
            # Keep first message (context) + last N messages
            self.messages = self.messages[-self.max_history:]

    @staticmethod
    def _serialize_content(content):
        """Serialize Anthropic SDK content blocks to JSON-safe dicts."""
        serialized = []
        for block in content:
            if hasattr(block, "text"):
                serialized.append({"type": "text", "text": block.text})
            elif hasattr(block, "name"):
                serialized.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
            else:
                serialized.append({"type": "unknown"})
        return serialized

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

        # Add map context to system prompt if available
        system = SYSTEM_PROMPT
        if map_context:
            context_parts = []
            if "bounds" in map_context:
                b = map_context["bounds"]
                context_parts.append(f"Map bounds: south={b.get('south')}, west={b.get('west')}, north={b.get('north')}, east={b.get('east')}")
            if "zoom" in map_context:
                context_parts.append(f"Zoom level: {map_context['zoom']}")
            if "active_layers" in map_context:
                context_parts.append(f"Active layers: {', '.join(map_context['active_layers']) or 'none'}")
            if context_parts:
                system += "\n\nCURRENT MAP STATE:\n" + "\n".join(context_parts)

        # Add user message to history (with cap)
        self.messages.append({"role": "user", "content": message})
        self._trim_history()

        tools = get_tool_definitions()
        tool_call_count = 0
        max_tool_calls = Config.MAX_TOOL_CALLS_PER_MESSAGE
        completed_tools = []  # Track successful tools for error recovery

        try:
            while True:
                response = self.client.messages.create(
                    model=Config.CLAUDE_MODEL,
                    max_tokens=2048,
                    system=system,
                    tools=tools,
                    messages=self.messages,
                )

                # Track token usage
                if hasattr(response, 'usage') and response.usage:
                    self.usage["total_input_tokens"] += getattr(response.usage, 'input_tokens', 0)
                    self.usage["total_output_tokens"] += getattr(response.usage, 'output_tokens', 0)
                    self.usage["api_calls"] += 1
                    logger.info(
                        "Claude API usage: input=%d output=%d total_in=%d total_out=%d calls=%d",
                        getattr(response.usage, 'input_tokens', 0),
                        getattr(response.usage, 'output_tokens', 0),
                        self.usage["total_input_tokens"],
                        self.usage["total_output_tokens"],
                        self.usage["api_calls"],
                    )

                # Serialize SDK objects to dicts for JSON safety
                assistant_content = response.content
                serialized = self._serialize_content(assistant_content)
                self.messages.append({"role": "assistant", "content": serialized})

                # Check if we need to handle tool use
                if response.stop_reason == "tool_use":
                    tool_results = []

                    for block in assistant_content:
                        if block.type == "tool_use":
                            tool_call_count += 1

                            if tool_call_count >= max_tool_calls:
                                yield {"type": "error", "text": f"Tool call limit ({max_tool_calls}) reached. Returning partial results."}
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

                            # Handle special tool results
                            # Tools that produce layers
                            layer_tools = {"fetch_osm", "buffer", "spatial_query", "search_nearby", "classify_landcover", "find_route", "isochrone", "import_layer", "merge_layers"}
                            if tool_name in layer_tools and "geojson" in result:
                                layer_name = result.get("layer_name", f"layer_{tool_call_count}")
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

                            # Heatmap rendering instruction
                            if tool_name == "heatmap" and result.get("success"):
                                yield {"type": "heatmap", **result}

                            # Add tool result to messages for Claude
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result),
                            })

                    if tool_call_count > max_tool_calls:
                        break

                    # Send tool results back to Claude
                    self.messages.append({"role": "user", "content": tool_results})
                    continue  # Loop to get Claude's next response

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

        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            partial = ""
            if completed_tools:
                partial = f" Completed {len(completed_tools)} tool(s) before failure: {', '.join(completed_tools)}. Any layers created are still on the map."
            # Sanitize: only show error type, not full details
            error_type = type(e).__name__
            yield {"type": "error", "text": f"AI service error ({error_type}). Please try again.{partial}"}
        except Exception as e:
            logger.error(f"Chat processing error: {e}", exc_info=True)
            partial = ""
            if completed_tools:
                partial = f" Completed {len(completed_tools)} tool(s) before failure: {', '.join(completed_tools)}. Any layers created are still on the map."
            yield {"type": "error", "text": f"An unexpected error occurred. Please try again.{partial}"}

    def _fallback_process(self, message: str) -> Generator[dict, None, None]:
        """Simple rule-based fallback when Claude API is unavailable."""
        msg = message.lower().strip()

        # Basic map commands
        if any(w in msg for w in ["zoom to", "go to", "show me", "pan to", "navigate to"]):
            # Try to extract a place name
            for prefix in ["zoom to ", "go to ", "show me ", "pan to ", "navigate to "]:
                if prefix in msg:
                    place = msg.split(prefix, 1)[1].strip().rstrip(".")
                    if place:
                        yield {"type": "tool_start", "tool": "geocode", "input": {"query": place}}
                        result = dispatch_tool("geocode", {"query": place})
                        yield {"type": "tool_result", "tool": "geocode", "result": result}

                        if "error" not in result:
                            cmd = {"action": "pan_and_zoom", "lat": result["lat"], "lon": result["lon"], "zoom": 13}
                            map_result = dispatch_tool("map_command", cmd)
                            yield {"type": "map_command", **map_result}
                            yield {"type": "message", "text": f"Panned to {result['display_name']}", "done": True}
                        else:
                            yield {"type": "message", "text": result["error"], "done": True}
                        return

        if "satellite" in msg:
            result = dispatch_tool("map_command", {"action": "change_basemap", "basemap": "satellite"})
            yield {"type": "map_command", **result}
            yield {"type": "message", "text": "Switched to satellite view.", "done": True}
            return

        if "osm" in msg and ("view" in msg or "map" in msg or "basemap" in msg or "street" in msg):
            result = dispatch_tool("map_command", {"action": "change_basemap", "basemap": "osm"})
            yield {"type": "map_command", **result}
            yield {"type": "message", "text": "Switched to OpenStreetMap view.", "done": True}
            return

        yield {
            "type": "error",
            "text": "AI assistant unavailable (no API key configured). Basic commands supported: 'zoom to [place]', 'satellite view', 'osm view'."
        }
