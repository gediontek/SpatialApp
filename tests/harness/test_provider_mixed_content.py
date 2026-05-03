"""Harness — M4 (OpenAI converter drops text alongside tool_result).

Contract: when an Anthropic-format user message contains BOTH tool_result
blocks AND text blocks (the chat tool-loop appends a tool-limit
instruction text alongside tool results), the OpenAI converter MUST emit
both — the tool messages AND a separate user message carrying the text.

The audit symptom: nl_gis/llm_provider.py:376 emitted only the tool
messages and dropped the text, silently losing the tool-limit
instruction.
"""
import pytest


def test_text_block_emitted_alongside_tool_results():
    """Mixed user message MUST produce both tool messages and a text msg."""
    pytest.importorskip("openai")
    from nl_gis.llm_provider import OpenAIProvider

    provider = OpenAIProvider.__new__(OpenAIProvider)  # bypass __init__/API key
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool_abc",
                    "content": "result of geocode",
                },
                {
                    "type": "text",
                    "text": "You have used 5 of 10 tool calls; finish efficiently.",
                },
            ],
        },
    ]
    oai = provider._convert_messages(messages, system="sys")

    # First entry is the system message.
    assert oai[0]["role"] == "system"

    roles = [m["role"] for m in oai[1:]]
    assert "tool" in roles, "Tool result was dropped."

    # The tool-limit text MUST survive somewhere downstream of the tool.
    user_or_text_carriers = [
        m for m in oai[1:]
        if m.get("role") == "user"
        and isinstance(m.get("content"), str)
        and "tool calls" in m["content"]
    ]
    assert user_or_text_carriers, (
        "M4 regression: text block was dropped when user message also "
        "carried tool_result blocks. The tool-limit instruction is lost."
    )


def test_tool_only_user_message_unchanged():
    """User message with only tool_results (no text) emits only tool msgs."""
    pytest.importorskip("openai")
    from nl_gis.llm_provider import OpenAIProvider

    provider = OpenAIProvider.__new__(OpenAIProvider)
    messages = [{
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": "tool_xyz",
            "content": "result",
        }],
    }]
    oai = provider._convert_messages(messages, system="sys")
    # system + 1 tool message
    assert len(oai) == 2
    assert oai[1]["role"] == "tool"


def test_assistant_text_plus_tool_use_emits_both():
    """Assistant message with text + tool_use must emit content + tool_calls."""
    pytest.importorskip("openai")
    from nl_gis.llm_provider import OpenAIProvider

    provider = OpenAIProvider.__new__(OpenAIProvider)
    messages = [{
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Let me geocode that."},
            {"type": "tool_use", "id": "tu_1", "name": "geocode",
             "input": {"q": "Paris"}},
        ],
    }]
    oai = provider._convert_messages(messages, system="sys")
    msg = oai[1]
    assert msg["role"] == "assistant"
    assert msg["content"] == "Let me geocode that."
    assert msg.get("tool_calls"), "tool_use block dropped"
    assert msg["tool_calls"][0]["function"]["name"] == "geocode"
