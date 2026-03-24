"""Claude API integration for NL-to-GIS chat."""

import json
import logging
from typing import Generator

import anthropic

from config import Config
from nl_gis.tools import get_tool_definitions
from nl_gis.tool_handlers import dispatch_tool

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a GIS assistant integrated into SpatialApp, a web-based geospatial labeling and analysis tool. You help users interact with maps and spatial data through natural language.

You have access to spatial tools that operate on a Leaflet.js map. When a user asks a spatial question, use the appropriate tool(s) to answer it.

GUIDELINES:
- Always use the geocode tool when the user references a place by name.
- When fetching OSM data, prefer using a location name. The tool will geocode it automatically.
- Return specific numbers: "247 buildings" not "many buildings".
- When creating layers via fetch_osm, use descriptive category_name values: "chicago_buildings" not "result".
- Chain tools when needed: geocode → fetch → analyze → display.
- After fetching data or geocoding, use map_command to navigate the map to show results.
- For area/distance calculations, report multiple units (sq m, sq km, acres / m, km, mi).
- Reference created layers by name in your response so the user can manage them.
- Keep responses concise. Lead with the answer.

COORDINATE CONVENTION:
- Leaflet uses [lat, lng]
- GeoJSON uses [lng, lat]
- The tools handle conversion automatically.

AVAILABLE FEATURE TYPES for fetch_osm and search_nearby:
building, forest, water, park, grass, farmland, residential, commercial, industrial, road, river, lake

TOOLS OVERVIEW:
- geocode: Look up coordinates for a place name
- fetch_osm: Fetch OSM features in an area
- search_nearby: Find OSM features near a point
- map_command: Pan, zoom, fit bounds, change basemap
- calculate_area: Geodesic area of polygons
- measure_distance: Distance between two points
- buffer: Create buffer polygon around features
- spatial_query: Find features matching spatial predicates (intersects, within, contains, within_distance)
- aggregate: Count features, total area, group by attribute
- show_layer/hide_layer/remove_layer: Layer visibility control
- add_annotation: Save features as labeled annotations
- classify_landcover: Auto-classify land use from OSM data
- export_annotations: Export annotations as GeoJSON/Shapefile/GeoPackage
- get_annotations: List all current annotations"""


class ChatSession:
    """Manages a conversation with Claude for NL-to-GIS operations."""

    def __init__(self, layer_store: dict = None):
        """Initialize a chat session.

        Args:
            layer_store: Server-side layer store for cross-tool references.
        """
        self.messages = []
        self.layer_store = layer_store or {}
        self.client = None
        self._init_client()

    def _init_client(self):
        """Initialize the Anthropic client if API key is available."""
        api_key = Config.ANTHROPIC_API_KEY
        if api_key:
            self.client = anthropic.Anthropic(api_key=api_key)
        else:
            logger.warning("No ANTHROPIC_API_KEY set. Chat will use rule-based fallback only.")

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

        # Add user message to history
        self.messages.append({"role": "user", "content": message})

        tools = get_tool_definitions()
        tool_call_count = 0
        max_tool_calls = Config.MAX_TOOL_CALLS_PER_MESSAGE

        try:
            while True:
                response = self.client.messages.create(
                    model=Config.CLAUDE_MODEL,
                    max_tokens=2048,
                    system=system,
                    tools=tools,
                    messages=self.messages,
                )

                # Process response content blocks
                assistant_content = response.content
                self.messages.append({"role": "assistant", "content": assistant_content})

                # Check if we need to handle tool use
                if response.stop_reason == "tool_use":
                    tool_results = []

                    for block in assistant_content:
                        if block.type == "tool_use":
                            tool_call_count += 1

                            if tool_call_count > max_tool_calls:
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
                            except Exception as e:
                                logger.error(f"Tool {tool_name} failed: {e}")
                                result = {"error": str(e)}

                            yield {"type": "tool_result", "tool": tool_name, "result": result}

                            # Handle special tool results
                            # Tools that produce layers
                            layer_tools = {"fetch_osm", "buffer", "spatial_query", "search_nearby", "classify_landcover", "find_route", "isochrone"}
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

                    if text_parts:
                        yield {"type": "message", "text": "\n".join(text_parts), "done": True}
                    break

        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            yield {"type": "error", "text": f"AI service error: {str(e)}"}
        except Exception as e:
            logger.error(f"Chat processing error: {e}", exc_info=True)
            yield {"type": "error", "text": f"Error processing message: {str(e)}"}

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
