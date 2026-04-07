"""Tests for nl_gis.chat module."""

import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl_gis.chat import ChatSession, SYSTEM_PROMPT
from nl_gis.llm_provider import LLMResponse, TextBlock, ToolUseBlock


class TestChatSessionFallback:
    """Tests for rule-based fallback when no LLM provider is configured."""

    def setup_method(self):
        """Create session with no API key."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": "", "OPENAI_API_KEY": ""}, clear=False):
            from config import Config
            Config.ANTHROPIC_API_KEY = ""
            Config.GEMINI_API_KEY = ""
            Config.OPENAI_API_KEY = ""
            self.session = ChatSession()
            self.session.client = None  # Force fallback mode

    @patch("nl_gis.tool_handlers.geocode_cache")
    @patch("nl_gis.tool_handlers.urllib.request.urlopen")
    def test_zoom_to_place(self, mock_urlopen, mock_cache):
        mock_cache.get.return_value = None  # Bypass cache
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps([{
            "lat": "47.6062", "lon": "-122.3321",
            "display_name": "Seattle, WA, USA",
            "boundingbox": ["47.4", "47.8", "-122.5", "-122.2"]
        }]).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        events = list(self.session.process_message("zoom to Seattle"))
        types = [e["type"] for e in events]

        assert "tool_start" in types
        assert "map_command" in types
        assert "message" in types

        map_cmd = next(e for e in events if e["type"] == "map_command")
        assert map_cmd["lat"] == 47.6062

    def test_satellite_view(self):
        events = list(self.session.process_message("switch to satellite view"))
        map_cmd = next(e for e in events if e["type"] == "map_command")
        assert map_cmd["basemap"] == "satellite"

    def test_osm_view(self):
        events = list(self.session.process_message("switch to osm street map"))
        map_cmd = next(e for e in events if e["type"] == "map_command")
        assert map_cmd["basemap"] == "osm"

    def test_unknown_command(self):
        events = list(self.session.process_message("analyze the spatial distribution"))
        assert any(e["type"] == "error" for e in events)


class TestChatSessionWithLLM:
    """Tests for LLM integration with mocked provider responses."""

    @staticmethod
    def _make_text_response(text):
        return LLMResponse(
            content=[TextBlock(text=text)],
            stop_reason="end_turn",
            input_tokens=10,
            output_tokens=20,
        )

    @staticmethod
    def _make_tool_response(tool_id, name, input_data):
        return LLMResponse(
            content=[ToolUseBlock(id=tool_id, name=name, input=input_data)],
            stop_reason="tool_use",
            input_tokens=10,
            output_tokens=20,
        )

    def test_simple_text_response(self):
        """Test a simple response with no tool use."""
        mock_provider = MagicMock()
        mock_provider.create_message.return_value = self._make_text_response(
            "Hello! I'm your GIS assistant."
        )

        session = ChatSession()
        session.client = mock_provider

        events = list(session.process_message("Hello"))
        assert len(events) == 1
        assert events[0]["type"] == "message"
        assert "GIS assistant" in events[0]["text"]

    @patch("nl_gis.tool_handlers.geocode_cache")
    @patch("nl_gis.tool_handlers.urllib.request.urlopen")
    def test_geocode_tool_call(self, mock_urlopen, mock_cache):
        """Test LLM calling the geocode tool."""
        mock_cache.get.return_value = None  # Bypass cache
        # Mock geocoding response
        mock_geo_response = MagicMock()
        mock_geo_response.read.return_value = json.dumps([{
            "lat": "47.6062", "lon": "-122.3321",
            "display_name": "Seattle, WA",
            "boundingbox": ["47.4", "47.8", "-122.5", "-122.2"]
        }]).encode()
        mock_geo_response.__enter__ = lambda s: s
        mock_geo_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_geo_response

        mock_provider = MagicMock()
        mock_provider.create_message.side_effect = [
            self._make_tool_response("tool_1", "geocode", {"query": "Seattle"}),
            self._make_text_response("Seattle is at 47.6°N, 122.3°W."),
        ]

        session = ChatSession()
        session.client = mock_provider

        events = list(session.process_message("Where is Seattle?"))
        types = [e["type"] for e in events]

        assert "tool_start" in types
        assert "tool_result" in types
        assert "message" in types

        tool_result = next(e for e in events if e["type"] == "tool_result")
        assert tool_result["result"]["lat"] == 47.6062

    def test_tool_call_limit(self):
        """Test that tool call limit is enforced."""
        from config import Config
        original = Config.MAX_TOOL_CALLS_PER_MESSAGE
        Config.MAX_TOOL_CALLS_PER_MESSAGE = 2

        try:
            # Create tool_use response with multiple tool calls
            tool_response = LLMResponse(
                content=[
                    ToolUseBlock(id="t1", name="map_command", input={"action": "zoom", "zoom": 10}),
                    ToolUseBlock(id="t2", name="map_command", input={"action": "zoom", "zoom": 11}),
                    ToolUseBlock(id="t3", name="map_command", input={"action": "zoom", "zoom": 12}),
                ],
                stop_reason="tool_use",
                input_tokens=10,
                output_tokens=20,
            )

            mock_provider = MagicMock()
            mock_provider.create_message.return_value = tool_response

            session = ChatSession()
            session.client = mock_provider

            events = list(session.process_message("zoom in a lot"))
            error_events = [e for e in events if e["type"] == "error"]
            assert len(error_events) > 0
            assert "limit" in error_events[0]["text"].lower()
        finally:
            Config.MAX_TOOL_CALLS_PER_MESSAGE = original


class TestChatSessionLayerStore:
    """Tests for layer store management."""

    def test_layer_store_initialized(self):
        session = ChatSession(layer_store={"existing": {"type": "FeatureCollection", "features": []}})
        assert "existing" in session.layer_store

    def test_default_empty_layer_store(self):
        session = ChatSession()
        assert session.layer_store == {}


class TestSystemPrompt:
    """Tests for system prompt content."""

    def test_contains_tool_guidance(self):
        assert "geocode" in SYSTEM_PROMPT
        assert "fetch_osm" in SYSTEM_PROMPT
        assert "map_command" in SYSTEM_PROMPT

    def test_contains_coordinate_convention(self):
        assert "lat" in SYSTEM_PROMPT.lower() and "lon" in SYSTEM_PROMPT.lower()
        assert "coordinate" in SYSTEM_PROMPT.lower()

    def test_contains_feature_types(self):
        assert "building" in SYSTEM_PROMPT
        assert "forest" in SYSTEM_PROMPT
        assert "water" in SYSTEM_PROMPT
