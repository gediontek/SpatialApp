"""Tests for chat engine internals and spatial edge cases (P0/P1 coverage gaps)."""

import json
import math
import time
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl_gis.chat import ChatSession, SYSTEM_PROMPT
from nl_gis.llm_provider import LLMResponse, TextBlock, ToolUseBlock
from nl_gis.geo_utils import (
    ValidatedPoint,
    estimate_utm_epsg,
    buffer_geometry,
    geodesic_area,
    geojson_to_shapely,
    shapely_to_geojson,
)
from shapely.geometry import Point, Polygon, MultiPolygon, box


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


def _make_tool_response(tool_id, name, input_data, input_tokens=10, output_tokens=20):
    return LLMResponse(
        content=[ToolUseBlock(id=tool_id, name=name, input=input_data)],
        stop_reason="tool_use",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _make_session_with_mock_provider():
    """Create a ChatSession with a mock LLM provider (no real API key needed)."""
    session = ChatSession()
    session.client = MagicMock()
    return session


# ===========================================================================
# 1. Chat Engine Internals
# ===========================================================================


class TestTrimHistory:
    """Tests for ChatSession._trim_history."""

    def test_preserves_first_message(self):
        """First message (context) is always preserved after trimming."""
        session = _make_session_with_mock_provider()
        session.max_history = 5

        # Add first message (context) + many more
        session.messages = [{"role": "user", "content": "context message"}]
        for i in range(10):
            session.messages.append({"role": "assistant", "content": [{"type": "text", "text": f"response {i}"}]})
            session.messages.append({"role": "user", "content": f"message {i}"})

        session._trim_history()

        assert session.messages[0] == {"role": "user", "content": "context message"}
        assert len(session.messages) <= session.max_history + 1  # +1 for possible pair preservation

    def test_preserves_tool_use_tool_result_pairs(self):
        """Trimming must not split a tool_use/tool_result pair."""
        session = _make_session_with_mock_provider()
        session.max_history = 4

        session.messages = [
            {"role": "user", "content": "context"},
            # Filler messages to push over limit
            {"role": "assistant", "content": [{"type": "text", "text": "filler 1"}]},
            {"role": "user", "content": "filler 2"},
            {"role": "assistant", "content": [{"type": "text", "text": "filler 3"}]},
            {"role": "user", "content": "filler 4"},
            # Tool use pair — assistant issues tool_use, user returns tool_result
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "geocode", "input": {"query": "NYC"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": '{"lat": 40.7}'},
            ]},
            {"role": "assistant", "content": [{"type": "text", "text": "NYC is at 40.7N"}]},
            {"role": "user", "content": "thanks"},
        ]

        session._trim_history()

        # After trimming, no tool_result message should appear without its
        # preceding assistant tool_use message
        for idx, msg in enumerate(session.messages):
            if (msg.get("role") == "user"
                    and isinstance(msg.get("content"), list)
                    and any(isinstance(b, dict) and b.get("type") == "tool_result"
                            for b in msg["content"])):
                # The previous message must be assistant with tool_use
                assert idx > 0
                prev = session.messages[idx - 1]
                assert prev["role"] == "assistant"
                assert any(isinstance(b, dict) and b.get("type") == "tool_use"
                           for b in prev["content"])

    def test_with_messages_including_tool_use_blocks(self):
        """Messages with tool_use blocks are handled correctly during trim."""
        session = _make_session_with_mock_provider()
        session.max_history = 3

        session.messages = [
            {"role": "user", "content": "context"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "geocode", "input": {"query": "LA"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": '{"lat": 34.0}'},
            ]},
            {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            {"role": "user", "content": "new question"},
        ]

        session._trim_history()

        # First message preserved
        assert session.messages[0]["content"] == "context"
        # No orphaned tool_result at start (after context)
        if len(session.messages) > 1:
            second = session.messages[1]
            if (second.get("role") == "user"
                    and isinstance(second.get("content"), list)):
                # Should not start with orphaned tool_result
                has_tool_result = any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in second["content"]
                )
                if has_tool_result:
                    # Must have been pulled back to include the assistant tool_use
                    pytest.fail("Orphaned tool_result found after context message")

    def test_no_trim_when_under_limit(self):
        """No trimming occurs when history is within bounds."""
        session = _make_session_with_mock_provider()
        session.max_history = 50

        session.messages = [
            {"role": "user", "content": "context"},
            {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
            {"role": "user", "content": "hello"},
        ]
        original_len = len(session.messages)

        session._trim_history()

        assert len(session.messages) == original_len

    def test_trailing_assistant_tool_use_removed(self):
        """If trim leaves an assistant tool_use as the last message (orphaned from
        its result), it should be removed."""
        session = _make_session_with_mock_provider()
        session.max_history = 4

        session.messages = [
            {"role": "user", "content": "context"},
            {"role": "assistant", "content": [{"type": "text", "text": "f1"}]},
            {"role": "user", "content": "f2"},
            {"role": "assistant", "content": [{"type": "text", "text": "f3"}]},
            {"role": "user", "content": "f4"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "geocode", "input": {}},
            ]},
        ]

        session._trim_history()

        # Last message should NOT be an assistant with tool_use (orphaned)
        last = session.messages[-1]
        if last.get("role") == "assistant" and isinstance(last.get("content"), list):
            assert not any(
                isinstance(b, dict) and b.get("type") == "tool_use"
                for b in last["content"]
            ), "Orphaned trailing assistant tool_use should be removed"


class TestCallLLMWithRetry:
    """Tests for ChatSession._call_llm_with_retry."""

    def test_successful_call(self):
        """Successful call on first attempt returns the response."""
        session = _make_session_with_mock_provider()
        expected = _make_text_response("Hello!")
        session.client.create_message.return_value = expected

        result = session._call_llm_with_retry(
            model="test", max_tokens=100, system="sys",
            tools=[], messages=[],
        )

        assert result == expected
        assert session.client.create_message.call_count == 1

    def test_retry_on_429_then_succeed(self):
        """Retries on rate limit (429) error, then succeeds."""
        session = _make_session_with_mock_provider()
        expected = _make_text_response("Success after retry")

        session.client.create_message.side_effect = [
            Exception("rate limit exceeded (429)"),
            expected,
        ]

        with patch("time.sleep"):  # Don't actually sleep in tests
            result = session._call_llm_with_retry(
                model="test", max_tokens=100, system="sys",
                tools=[], messages=[],
            )

        assert result == expected
        assert session.client.create_message.call_count == 2

    def test_retry_on_500_then_succeed(self):
        """Retries on server error (500), then succeeds."""
        session = _make_session_with_mock_provider()
        expected = _make_text_response("Recovered")

        session.client.create_message.side_effect = [
            Exception("internal server error 500"),
            expected,
        ]

        with patch("time.sleep"):
            result = session._call_llm_with_retry(
                model="test", max_tokens=100, system="sys",
                tools=[], messages=[],
            )

        assert result == expected
        assert session.client.create_message.call_count == 2

    def test_max_retries_exhausted(self):
        """After max retries, the exception is raised."""
        session = _make_session_with_mock_provider()

        session.client.create_message.side_effect = Exception("rate limit 429")

        with patch("time.sleep"):
            with pytest.raises(Exception, match="429"):
                session._call_llm_with_retry(
                    model="test", max_tokens=100, system="sys",
                    tools=[], messages=[],
                )

        # 1 initial + 3 retries = 4 total calls
        assert session.client.create_message.call_count == 4

    def test_non_retryable_error_raises_immediately(self):
        """Non-retryable errors (e.g., auth) are raised without retry."""
        session = _make_session_with_mock_provider()

        session.client.create_message.side_effect = Exception("Invalid API key")

        with pytest.raises(Exception, match="Invalid API key"):
            session._call_llm_with_retry(
                model="test", max_tokens=100, system="sys",
                tools=[], messages=[],
            )

        assert session.client.create_message.call_count == 1

    def test_retry_on_overloaded_error(self):
        """Retries on 'overloaded' or '529' errors."""
        session = _make_session_with_mock_provider()
        expected = _make_text_response("OK")

        session.client.create_message.side_effect = [
            Exception("service overloaded (529)"),
            expected,
        ]

        with patch("time.sleep"):
            result = session._call_llm_with_retry(
                model="test", max_tokens=100, system="sys",
                tools=[], messages=[],
            )

        assert result == expected


class TestBudgetExceeded:
    """Tests for ChatSession._budget_exceeded."""

    def test_returns_false_when_under_budget(self):
        """Under budget: _budget_exceeded returns False."""
        session = _make_session_with_mock_provider()
        session.usage = {"total_input_tokens": 100, "total_output_tokens": 100, "api_calls": 1}

        assert session._budget_exceeded() is False

    def test_returns_true_when_over_budget(self):
        """Over budget: _budget_exceeded returns True."""
        from config import Config
        session = _make_session_with_mock_provider()
        session.usage = {
            "total_input_tokens": Config.MAX_TOKENS_PER_SESSION,
            "total_output_tokens": 1,
            "api_calls": 50,
        }

        assert session._budget_exceeded() is True

    def test_returns_true_when_exactly_at_budget(self):
        """Exactly at budget: _budget_exceeded returns True (>=)."""
        from config import Config
        session = _make_session_with_mock_provider()
        session.usage = {
            "total_input_tokens": Config.MAX_TOKENS_PER_SESSION,
            "total_output_tokens": 0,
            "api_calls": 10,
        }

        assert session._budget_exceeded() is True

    def test_returns_false_when_just_under_budget(self):
        """One token under budget: _budget_exceeded returns False."""
        from config import Config
        session = _make_session_with_mock_provider()
        session.usage = {
            "total_input_tokens": Config.MAX_TOKENS_PER_SESSION - 1,
            "total_output_tokens": 0,
            "api_calls": 10,
        }

        assert session._budget_exceeded() is False


class TestUpdateContext:
    """Tests for ChatSession._update_context."""

    def test_geocode_updates_last_location(self):
        session = _make_session_with_mock_provider()
        session._update_context("geocode", {"query": "Seattle"}, {
            "lat": 47.6, "lon": -122.3, "display_name": "Seattle, WA",
        })

        assert session.context["last_location"]["name"] == "Seattle, WA"
        assert session.context["last_location"]["lat"] == 47.6

    def test_layer_producing_tool_updates_last_layer(self):
        session = _make_session_with_mock_provider()
        session._update_context("fetch_osm", {"feature_type": "park"}, {
            "layer_name": "park_layer_1", "feature_count": 42,
        })

        assert session.context["last_layer"] == "park_layer_1"
        assert session.context["last_operation"]["tool"] == "fetch_osm"

    def test_unknown_tool_does_not_crash(self):
        """Tools not in the summary_map should not raise."""
        session = _make_session_with_mock_provider()
        session._update_context("unknown_tool", {}, {"some": "result"})
        # No exception; last_operation unchanged
        assert session.context["last_operation"] is None


# ===========================================================================
# 2. Spatial Edge Cases
# ===========================================================================


class TestGeodesicAreaEdgeCases:
    """Edge cases for geodesic_area."""

    def test_polygon_with_holes_smaller_than_without(self):
        """A polygon with holes must have less area than the same polygon without holes."""
        # Outer ring: ~1 degree box
        outer = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        # Hole: smaller box inside
        hole = [(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75), (0.25, 0.25)]

        poly_no_holes = Polygon(outer)
        poly_with_holes = Polygon(outer, [hole])

        area_no_holes = geodesic_area(poly_no_holes)
        area_with_holes = geodesic_area(poly_with_holes)

        assert area_with_holes < area_no_holes
        assert area_with_holes > 0

    def test_multipolygon_area(self):
        """MultiPolygon area should equal sum of individual polygon areas."""
        poly1 = box(0, 0, 1, 1)
        poly2 = box(10, 10, 11, 11)

        multi = MultiPolygon([poly1, poly2])

        area_multi = geodesic_area(multi)
        area_sum = geodesic_area(poly1) + geodesic_area(poly2)

        # Should be very close (within 0.1%)
        assert abs(area_multi - area_sum) / area_sum < 0.001


class TestBufferGeometryEdgeCases:
    """Edge cases for buffer_geometry."""

    def test_empty_geometry_returns_empty(self):
        """Buffering an empty geometry should return an empty geometry."""
        from shapely.geometry import GeometryCollection
        empty = GeometryCollection()  # Empty geometry

        result = buffer_geometry(empty, 1000)

        assert result.is_empty


class TestValidatedPointEdgeCases:
    """Edge cases for ValidatedPoint: NaN, Infinity, booleans."""

    def test_rejects_nan_latitude(self):
        """NaN latitude should be rejected."""
        with pytest.raises(ValueError, match="out of range"):
            ValidatedPoint(lat=float("nan"), lon=0.0)

    def test_rejects_nan_longitude(self):
        """NaN longitude should be rejected."""
        with pytest.raises(ValueError, match="out of range"):
            ValidatedPoint(lat=0.0, lon=float("nan"))

    def test_rejects_inf_latitude(self):
        """Infinity latitude should be rejected."""
        with pytest.raises(ValueError, match="out of range"):
            ValidatedPoint(lat=float("inf"), lon=0.0)

    def test_rejects_neg_inf_longitude(self):
        """Negative infinity longitude should be rejected."""
        with pytest.raises(ValueError, match="out of range"):
            ValidatedPoint(lat=0.0, lon=float("-inf"))

    def test_boolean_accepted_as_int_subclass(self):
        """bool is a subclass of int in Python, so True/False pass isinstance check.
        ValidatedPoint(lat=True, lon=False) is equivalent to lat=1, lon=0."""
        p = ValidatedPoint(lat=True, lon=False)
        assert p.lat == 1
        assert p.lon == 0


class TestEstimateUtmEpsgBoundaries:
    """Boundary tests for estimate_utm_epsg."""

    def test_lon_180_returns_valid_zone(self):
        """lon=180 should return UTM zone 60 (EPSG 32660), not zone 61."""
        epsg = estimate_utm_epsg(lon=180, lat=0)
        assert epsg == 32660  # Zone 60, clamped by min(..., 60)

    def test_lon_neg180_returns_zone_1(self):
        """lon=-180 should return UTM zone 1 (EPSG 32601)."""
        epsg = estimate_utm_epsg(lon=-180, lat=0)
        assert epsg == 32601

    def test_lon_neg180_southern(self):
        """lon=-180 in southern hemisphere should return EPSG 32701."""
        epsg = estimate_utm_epsg(lon=-180, lat=-45)
        assert epsg == 32701


# ===========================================================================
# 3. Integration-style Tests
# ===========================================================================


class TestMultiToolChainSimulation:
    """Integration tests simulating multi-tool chains."""

    @patch("nl_gis.handlers.navigation.geocode_cache")
    @patch("nl_gis.handlers.navigation.requests.get")
    def test_geocode_result_feeds_into_buffer(self, mock_get, mock_cache):
        """A geocode result should produce coordinates usable by buffer_geometry."""
        mock_cache.get.return_value = None
        mock_response = MagicMock()
        mock_response.json.return_value = [{
            "lat": "47.6062", "lon": "-122.3321",
            "display_name": "Seattle, WA, USA",
            "boundingbox": ["47.4", "47.8", "-122.5", "-122.2"],
        }]
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        from nl_gis.tool_handlers import dispatch_tool

        # Step 1: Geocode
        geocode_result = dispatch_tool("geocode", {"query": "Seattle"})
        assert "error" not in geocode_result
        lat = geocode_result["lat"]
        lon = geocode_result["lon"]

        # Step 2: Use geocoded point for buffer
        point = Point(lon, lat)  # GeoJSON order: lon, lat
        buffered = buffer_geometry(point, 1000)

        assert buffered.geom_type == "Polygon"
        assert not buffered.is_empty
        assert buffered.is_valid

        # Buffered area should be approximately pi * r^2
        area = geodesic_area(buffered)
        expected = math.pi * 1000 * 1000
        assert abs(area - expected) / expected < 0.05

    def test_spatial_query_contains_vs_within(self):
        """'contains' and 'within' predicates are directional opposites.
        A large polygon 'contains' a small polygon, but a small polygon
        is 'within' a large polygon."""
        from nl_gis.tool_handlers import dispatch_tool

        # Create layers: large box contains small box
        large_box = box(-122.4, 47.5, -122.2, 47.7)
        small_box = box(-122.35, 47.55, -122.25, 47.65)

        large_feature = {
            "type": "Feature",
            "properties": {"name": "large"},
            "geometry": shapely_to_geojson(large_box),
        }
        small_feature = {
            "type": "Feature",
            "properties": {"name": "small"},
            "geometry": shapely_to_geojson(small_box),
        }

        layer_store = {
            "large_layer": {"type": "FeatureCollection", "features": [large_feature]},
            "small_layer": {"type": "FeatureCollection", "features": [small_feature]},
        }

        # "contains": source features that CONTAIN the target
        # Large box contains small box => match
        contains_result = dispatch_tool("spatial_query", {
            "source_layer": "large_layer",
            "predicate": "contains",
            "target_layer": "small_layer",
        }, layer_store)

        assert "error" not in contains_result
        assert contains_result["feature_count"] == 1  # large contains small

        # "within": source features that are WITHIN the target
        # Large box is NOT within small box => no match
        within_result = dispatch_tool("spatial_query", {
            "source_layer": "large_layer",
            "predicate": "within",
            "target_layer": "small_layer",
        }, layer_store)

        assert "error" not in within_result
        assert within_result["feature_count"] == 0  # large is NOT within small

        # Reverse: small within large => match
        within_reverse = dispatch_tool("spatial_query", {
            "source_layer": "small_layer",
            "predicate": "within",
            "target_layer": "large_layer",
        }, layer_store)

        assert "error" not in within_reverse
        assert within_reverse["feature_count"] == 1  # small IS within large
