"""Tests for plan-then-execute mode in chat engine and API."""

import json
import os
import sys
import tempfile
import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault('FLASK_DEBUG', 'false')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('ANTHROPIC_API_KEY', '')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl_gis.chat import ChatSession, PLAN_PROMPT_SUFFIX
from nl_gis.llm_provider import LLMResponse, TextBlock, ToolUseBlock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_text_response(text, input_tokens=10, output_tokens=20):
    return LLMResponse(
        content=[TextBlock(text=text)],
        stop_reason="end_turn",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _make_session_with_mock_provider():
    """Create a ChatSession with a mock LLM provider (no real API key needed)."""
    session = ChatSession()
    session.client = MagicMock()
    return session


SAMPLE_PLAN_JSON = json.dumps({
    "plan": [
        {"step": 1, "tool": "geocode", "params": {"query": "Chicago"}, "reason": "Find Chicago coordinates"},
        {"step": 2, "tool": "fetch_osm", "params": {"feature_type": "park", "location": "Chicago"}, "reason": "Get parks in the area"},
        {"step": 3, "tool": "style_layer", "params": {"layer_name": "parks_chicago", "color": "#00ff00"}, "reason": "Color parks green"},
    ],
    "estimated_steps": 3,
    "summary": "Find and display parks in Chicago, colored green",
})


# ===========================================================================
# 1. Plan Generation
# ===========================================================================

class TestPlanGeneration:
    """Tests for ChatSession._generate_plan."""

    def test_plan_generation_returns_valid_plan(self):
        """Plan mode calls LLM with no tools and yields a plan event."""
        session = _make_session_with_mock_provider()
        session.client.create_message = MagicMock(
            return_value=_make_text_response(f"```json\n{SAMPLE_PLAN_JSON}\n```")
        )

        events = list(session.process_message("Show me parks in Chicago colored green", plan_mode=True))

        # Should yield exactly one plan event
        plan_events = [e for e in events if e["type"] == "plan"]
        assert len(plan_events) == 1

        plan = plan_events[0]
        assert len(plan["plan"]) == 3
        assert plan["summary"] == "Find and display parks in Chicago, colored green"
        assert plan["estimated_steps"] == 3
        assert plan["plan"][0]["tool"] == "geocode"
        assert plan["plan"][1]["tool"] == "fetch_osm"
        assert plan["plan"][2]["tool"] == "style_layer"

    def test_plan_generation_calls_llm_without_tools(self):
        """LLM should be called with tools=[] in plan mode."""
        session = _make_session_with_mock_provider()
        session.client.create_message = MagicMock(
            return_value=_make_text_response(SAMPLE_PLAN_JSON)
        )

        list(session.process_message("Show parks", plan_mode=True))

        call_kwargs = session.client.create_message.call_args[1]
        assert call_kwargs["tools"] == []

    def test_plan_generation_appends_plan_prompt_suffix(self):
        """User message should have PLAN_PROMPT_SUFFIX appended."""
        session = _make_session_with_mock_provider()
        session.client.create_message = MagicMock(
            return_value=_make_text_response(SAMPLE_PLAN_JSON)
        )

        list(session.process_message("Show parks in Chicago", plan_mode=True))

        call_kwargs = session.client.create_message.call_args[1]
        messages = call_kwargs["messages"]
        assert len(messages) == 1
        assert messages[0]["content"].endswith(PLAN_PROMPT_SUFFIX)

    def test_plan_generation_without_client_yields_error(self):
        """Plan mode without LLM client yields an error."""
        session = ChatSession()
        session.client = None

        events = list(session.process_message("Show parks", plan_mode=True))

        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1
        assert "unavailable" in error_events[0]["text"].lower()

    def test_plan_generation_with_invalid_json_falls_back_to_message(self):
        """If LLM returns non-JSON text, yield it as a regular message."""
        session = _make_session_with_mock_provider()
        session.client.create_message = MagicMock(
            return_value=_make_text_response("I can't generate a plan for this query.")
        )

        events = list(session.process_message("Tell me a joke", plan_mode=True))

        plan_events = [e for e in events if e["type"] == "plan"]
        assert len(plan_events) == 0
        msg_events = [e for e in events if e["type"] == "message"]
        assert len(msg_events) == 1
        assert "can't generate a plan" in msg_events[0]["text"].lower()

    def test_plan_generation_tracks_usage(self):
        """Plan generation should update token usage counters."""
        session = _make_session_with_mock_provider()
        session.client.create_message = MagicMock(
            return_value=_make_text_response(SAMPLE_PLAN_JSON, input_tokens=50, output_tokens=100)
        )

        list(session.process_message("Show parks", plan_mode=True))

        assert session.usage["total_input_tokens"] == 50
        assert session.usage["total_output_tokens"] == 100
        assert session.usage["api_calls"] == 1


class TestParsePlanJson:
    """Tests for ChatSession._parse_plan_json."""

    def test_parse_raw_json(self):
        result = ChatSession._parse_plan_json(SAMPLE_PLAN_JSON)
        assert result is not None
        assert "plan" in result
        assert len(result["plan"]) == 3

    def test_parse_fenced_json(self):
        text = f"Here's the plan:\n```json\n{SAMPLE_PLAN_JSON}\n```\nLet me know!"
        result = ChatSession._parse_plan_json(text)
        assert result is not None
        assert "plan" in result

    def test_parse_fenced_no_lang(self):
        text = f"```\n{SAMPLE_PLAN_JSON}\n```"
        result = ChatSession._parse_plan_json(text)
        assert result is not None
        assert "plan" in result

    def test_parse_embedded_json(self):
        text = f"Some text before {SAMPLE_PLAN_JSON} and after"
        result = ChatSession._parse_plan_json(text)
        assert result is not None
        assert "plan" in result

    def test_parse_invalid_returns_none(self):
        result = ChatSession._parse_plan_json("This is not JSON at all")
        assert result is None


# ===========================================================================
# 2. Plan Execution
# ===========================================================================

class TestPlanExecution:
    """Tests for ChatSession.execute_plan."""

    def test_execute_plan_runs_steps_in_order(self):
        """Plan steps should execute sequentially."""
        session = _make_session_with_mock_provider()
        plan_steps = [
            {"step": 1, "tool": "geocode", "params": {"query": "Chicago"}, "reason": "Find Chicago"},
            {"step": 2, "tool": "map_command", "params": {"action": "pan_and_zoom", "lat": 41.88, "lon": -87.63, "zoom": 12}, "reason": "Pan to Chicago"},
        ]

        with patch("nl_gis.chat.dispatch_tool") as mock_dispatch:
            mock_dispatch.side_effect = [
                {"lat": 41.88, "lon": -87.63, "display_name": "Chicago, IL"},
                {"success": True, "action": "pan_and_zoom", "lat": 41.88, "lon": -87.63, "zoom": 12, "description": "Panned to Chicago"},
            ]
            events = list(session.execute_plan(plan_steps))

        tool_starts = [e for e in events if e["type"] == "tool_start"]
        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_starts) == 2
        assert len(tool_results) == 2
        assert tool_starts[0]["tool"] == "geocode"
        assert tool_starts[0]["step"] == 1
        assert tool_starts[1]["tool"] == "map_command"
        assert tool_starts[1]["step"] == 2

    def test_execute_plan_with_layer_producing_tool(self):
        """Layer-producing tools should yield layer_add events."""
        session = _make_session_with_mock_provider()
        plan_steps = [
            {"step": 1, "tool": "fetch_osm", "params": {"feature_type": "park", "location": "Chicago"}, "reason": "Get parks"},
        ]

        fake_geojson = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [-87.6, 41.9]}, "properties": {}}]}
        with patch("nl_gis.chat.dispatch_tool") as mock_dispatch:
            mock_dispatch.return_value = {
                "feature_count": 1,
                "layer_name": "parks_chicago",
                "geojson": fake_geojson,
            }
            events = list(session.execute_plan(plan_steps))

        layer_events = [e for e in events if e["type"] == "layer_add"]
        assert len(layer_events) == 1
        assert layer_events[0]["name"] == "parks_chicago"
        assert layer_events[0]["geojson"] == fake_geojson

        # Layer should be stored
        assert "parks_chicago" in session.layer_store

    def test_execute_plan_stops_on_error(self):
        """Plan execution should stop at first tool error."""
        session = _make_session_with_mock_provider()
        plan_steps = [
            {"step": 1, "tool": "geocode", "params": {"query": "Nonexistent"}, "reason": "Find place"},
            {"step": 2, "tool": "fetch_osm", "params": {"feature_type": "park"}, "reason": "Get parks"},
        ]

        with patch("nl_gis.chat.dispatch_tool") as mock_dispatch:
            mock_dispatch.return_value = {"error": "Location not found"}
            events = list(session.execute_plan(plan_steps))

        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_results) == 1  # Only first tool executed
        msg_events = [e for e in events if e["type"] == "message"]
        assert len(msg_events) == 1
        assert "stopped" in msg_events[0]["text"].lower()

    def test_execute_plan_success_message(self):
        """Successful plan execution yields a done message."""
        session = _make_session_with_mock_provider()
        plan_steps = [
            {"step": 1, "tool": "geocode", "params": {"query": "NYC"}, "reason": "Find NYC"},
        ]

        with patch("nl_gis.chat.dispatch_tool") as mock_dispatch:
            mock_dispatch.return_value = {"lat": 40.7, "lon": -74.0, "display_name": "NYC"}
            events = list(session.execute_plan(plan_steps))

        msg_events = [e for e in events if e["type"] == "message" and e.get("done")]
        assert len(msg_events) == 1
        assert "1 step" in msg_events[0]["text"]

    def test_execute_plan_handles_tool_exception(self):
        """Tool raising an exception should be caught and reported."""
        session = _make_session_with_mock_provider()
        plan_steps = [
            {"step": 1, "tool": "geocode", "params": {"query": "test"}, "reason": "Test"},
        ]

        with patch("nl_gis.chat.dispatch_tool") as mock_dispatch:
            mock_dispatch.side_effect = ValueError("Bad input")
            events = list(session.execute_plan(plan_steps))

        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_results) == 1
        assert "Bad input" in tool_results[0]["result"]["error"]

    def test_execute_plan_missing_tool_name(self):
        """Steps with missing tool name should yield error and continue."""
        session = _make_session_with_mock_provider()
        plan_steps = [
            {"step": 1, "params": {"query": "test"}, "reason": "Test"},
            {"step": 2, "tool": "geocode", "params": {"query": "NYC"}, "reason": "Find NYC"},
        ]

        with patch("nl_gis.chat.dispatch_tool") as mock_dispatch:
            mock_dispatch.return_value = {"lat": 40.7, "lon": -74.0, "display_name": "NYC"}
            events = list(session.execute_plan(plan_steps))

        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1
        assert "missing tool name" in error_events[0]["text"].lower()

    def test_execute_plan_map_command(self):
        """map_command tool should yield map_command event."""
        session = _make_session_with_mock_provider()
        plan_steps = [
            {"step": 1, "tool": "map_command", "params": {"action": "zoom", "zoom": 15}, "reason": "Zoom in"},
        ]

        with patch("nl_gis.chat.dispatch_tool") as mock_dispatch:
            mock_dispatch.return_value = {"success": True, "action": "zoom", "zoom": 15, "description": "Zoomed"}
            events = list(session.execute_plan(plan_steps))

        map_events = [e for e in events if e["type"] == "map_command"]
        assert len(map_events) == 1


# ===========================================================================
# 3. Default mode unchanged
# ===========================================================================

class TestDefaultModeUnchanged:
    """Verify that plan_mode=False (default) preserves existing behavior."""

    def test_default_mode_executes_immediately(self):
        """Without plan_mode, tools execute immediately as before."""
        session = _make_session_with_mock_provider()

        # Simulate: LLM calls geocode, then returns text
        tool_response = LLMResponse(
            content=[ToolUseBlock(id="tu_1", name="geocode", input={"query": "NYC"})],
            stop_reason="tool_use",
            input_tokens=10,
            output_tokens=20,
        )
        text_response = _make_text_response("Found NYC at 40.7, -74.0")

        session.client.create_message = MagicMock(
            side_effect=[tool_response, text_response]
        )

        with patch("nl_gis.chat.dispatch_tool") as mock_dispatch:
            mock_dispatch.return_value = {"lat": 40.7, "lon": -74.0, "display_name": "NYC"}
            events = list(session.process_message("Find NYC"))

        tool_starts = [e for e in events if e["type"] == "tool_start"]
        assert len(tool_starts) == 1
        assert tool_starts[0]["tool"] == "geocode"


# ===========================================================================
# 4. API Endpoint Tests
# ===========================================================================

class TestApiEndpoints:
    """Tests for /api/chat plan_mode and /api/chat/execute-plan endpoints."""

    @pytest.fixture
    def client(self):
        """Create a test Flask client."""
        from app import app
        from state import layer_store, chat_sessions
        with tempfile.TemporaryDirectory():
            app.config["TESTING"] = True
            app.config["WTF_CSRF_ENABLED"] = False
            layer_store.clear()
            chat_sessions.clear()
            with app.test_client() as c:
                yield c

    def test_api_chat_plan_mode_parameter(self, client):
        """The /api/chat endpoint should accept plan_mode parameter."""
        with patch("blueprints.chat._get_chat_session") as mock_get:
            mock_session = MagicMock()
            mock_session.process_message = MagicMock(return_value=iter([
                {"type": "plan", "plan": [], "summary": "test", "estimated_steps": 0}
            ]))
            mock_session.usage = {"total_input_tokens": 0, "total_output_tokens": 0, "api_calls": 0}
            mock_get.return_value = mock_session

            response = client.post('/api/chat', json={
                'message': 'Show parks in Chicago',
                'plan_mode': True,
            })

            assert response.status_code == 200
            mock_session.process_message.assert_called_once()
            call_kwargs = mock_session.process_message.call_args
            assert call_kwargs[1].get('plan_mode') is True or (len(call_kwargs[0]) > 2 and call_kwargs[0][2] is True)

    def test_api_execute_plan_missing_steps(self, client):
        """execute-plan without plan_steps should return 400."""
        response = client.post('/api/chat/execute-plan', json={})
        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data

    def test_api_execute_plan_empty_steps(self, client):
        """execute-plan with empty plan_steps should return 400."""
        response = client.post('/api/chat/execute-plan', json={'plan_steps': []})
        assert response.status_code == 400

    def test_api_execute_plan_too_many_steps(self, client):
        """execute-plan with >20 steps should return 400."""
        steps = [{"step": i, "tool": "geocode", "params": {"query": "test"}} for i in range(21)]
        response = client.post('/api/chat/execute-plan', json={'plan_steps': steps})
        assert response.status_code == 400
        assert 'max 20' in response.get_json()['error'].lower()

    def test_api_execute_plan_streams_events(self, client):
        """execute-plan should stream SSE events."""
        with patch("blueprints.chat._get_chat_session") as mock_get:
            mock_session = MagicMock()
            mock_session.execute_plan = MagicMock(return_value=iter([
                {"type": "tool_start", "tool": "geocode", "input": {"query": "NYC"}, "step": 1},
                {"type": "tool_result", "tool": "geocode", "result": {"lat": 40.7, "lon": -74.0}, "step": 1},
                {"type": "message", "text": "Plan executed successfully. Completed 1 step(s).", "done": True, "tool_metrics": []},
            ]))
            mock_session.usage = {"total_input_tokens": 0, "total_output_tokens": 0, "api_calls": 0}
            mock_get.return_value = mock_session

            response = client.post('/api/chat/execute-plan', json={
                'plan_steps': [{"step": 1, "tool": "geocode", "params": {"query": "NYC"}}],
            })

            assert response.status_code == 200
            assert 'text/event-stream' in response.content_type
            data = response.get_data(as_text=True)
            assert 'event: tool_start' in data
            assert 'event: tool_result' in data
            assert 'event: message' in data
