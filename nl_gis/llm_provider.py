"""Multi-provider LLM abstraction for tool-calling chat.

Supports Anthropic (Claude), Google Gemini, and OpenAI-compatible providers.
Each provider normalizes its responses to a common format consumed by ChatSession.
"""

import copy
import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider hint application (v2.1 Plan 07)
#
# Tool definitions may carry a `provider_hints` field, e.g.
#     "provider_hints": {
#         "openai":  {"description_suffix": " IMPORTANT: not search_nearby."},
#         "anthropic": {"description_suffix": ""},
#         "gemini":  {"description_suffix": ""},
#     }
# At call time, each provider appends the matching suffix to the tool's
# description so the underlying API only sees a single, provider-tuned
# description string. The base description in tools.py is unchanged.
# ---------------------------------------------------------------------------


def apply_provider_hints(tools: list, provider_name: str) -> list:
    """Return a deep-copy of `tools` with `provider_hints[provider_name].
    description_suffix` appended to each tool's description.

    Tools without hints are returned unchanged. The original list is not
    mutated. The `provider_hints` field itself is stripped from the
    output so it never reaches the upstream API.
    """
    if not tools:
        return tools
    pn = (provider_name or "").lower()
    out = []
    for tool in tools:
        copied = copy.deepcopy(tool)
        hints = copied.pop("provider_hints", None)
        if isinstance(hints, dict) and pn in hints:
            suffix = hints[pn].get("description_suffix") if isinstance(hints[pn], dict) else None
            if suffix:
                copied["description"] = (copied.get("description") or "") + " " + suffix
        out.append(copied)
    return out


# ---------------------------------------------------------------------------
# Per-provider behavioral notes (v2.1 Plan 07 M5)
# Documents observed differences. Read by the eval comparison report and by
# anyone debugging routing between providers.
# ---------------------------------------------------------------------------

PROVIDER_NOTES: dict[str, dict[str, list[str]]] = {
    "anthropic": {
        "strengths": [
            "Strong tool chaining: respects layer_name references between calls.",
            "Conservative on parameter invention; sticks to declared schema.",
        ],
        "weaknesses": [
            "Can occasionally over-invoke geocode when bbox already known.",
        ],
        "tuning_applied": [
            "ANTHROPIC_ADDENDUM emphasizes layer_name continuity.",
        ],
    },
    "openai": {
        "strengths": [
            "Fast tool selection on simple queries (single-tool calls).",
        ],
        "weaknesses": [
            "Tendency to parallelize sequential tool chains.",
            "Conflates closest_facility with search_nearby on 'nearest N' queries.",
        ],
        "tuning_applied": [
            "OPENAI_ADDENDUM rules against parallel chaining.",
            "provider_hints suffix on closest_facility forbids search_nearby substitution.",
        ],
    },
    "gemini": {
        "strengths": [
            "Default budget-friendly provider for this project (cost note in memory).",
        ],
        "weaknesses": [
            "Can return string-typed coordinates unless guided to numbers.",
        ],
        "tuning_applied": [
            "GEMINI_ADDENDUM specifies number-typed coordinates.",
        ],
    },
}


# ---------------------------------------------------------------------------
# Normalized response types (provider-agnostic)
# ---------------------------------------------------------------------------

@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class LLMResponse:
    """Normalized LLM response returned by every provider."""
    content: list  # List of TextBlock / ToolUseBlock
    stop_reason: str  # "tool_use" or "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    """Interface every LLM backend must implement."""

    @abstractmethod
    def create_message(
        self,
        *,
        model: str,
        system: str,
        messages: list,
        tools: list,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Send messages + tools and return a normalized response."""

    @staticmethod
    def _tool_id() -> str:
        return f"tool_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Anthropic (Claude)
# ---------------------------------------------------------------------------

class AnthropicProvider(LLMProvider):
    """Thin wrapper — Anthropic's format IS the internal format."""

    def __init__(self, api_key: str):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)

    def create_message(self, *, model, system, messages, tools, max_tokens=2048):
        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=apply_provider_hints(tools, "anthropic"),
            messages=messages,
        )

        content = []
        for block in response.content:
            if hasattr(block, "text"):
                content.append(TextBlock(text=block.text))
            elif hasattr(block, "name"):
                content.append(ToolUseBlock(id=block.id, name=block.name, input=block.input))

        stop = "tool_use" if response.stop_reason == "tool_use" else "end_turn"
        usage = response.usage if hasattr(response, "usage") else None
        return LLMResponse(
            content=content,
            stop_reason=stop,
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        )


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------

class GeminiProvider(LLMProvider):
    """Google Gemini via the google-genai SDK."""

    def __init__(self, api_key: str):
        from google import genai
        self.client = genai.Client(api_key=api_key)

    def _convert_tools(self, tools: list) -> list:
        """Convert Anthropic-format tool defs to Gemini function declarations."""
        tools = apply_provider_hints(tools, "gemini")
        declarations = []
        for tool in tools:
            schema = tool["input_schema"].copy()
            # Gemini doesn't support top-level 'additionalProperties' on params
            schema.pop("additionalProperties", None)
            # Recursively clean nested schemas
            self._clean_schema(schema)
            declarations.append({
                "name": tool["name"],
                "description": tool["description"],
                "parameters": schema,
            })
        return declarations

    def _clean_schema(self, schema: dict):
        """Remove JSON Schema fields Gemini doesn't support."""
        schema.pop("additionalProperties", None)
        props = schema.get("properties", {})
        for prop in props.values():
            if isinstance(prop, dict):
                self._clean_schema(prop)
            # Handle items for array types
            items = prop.get("items") if isinstance(prop, dict) else None
            if isinstance(items, dict):
                self._clean_schema(items)

    def _convert_messages(self, messages: list, system: str):
        """Convert Anthropic-format messages to Gemini contents list."""
        from google.genai import types

        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            raw_content = msg["content"]

            if isinstance(raw_content, str):
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=raw_content)],
                ))
            elif isinstance(raw_content, list):
                parts = []
                for block in raw_content:
                    if block.get("type") == "text":
                        parts.append(types.Part.from_text(text=block["text"]))
                    elif block.get("type") == "tool_use":
                        parts.append(types.Part.from_function_call(
                            name=block["name"],
                            args=block["input"],
                        ))
                    elif block.get("type") == "tool_result":
                        result_content = block.get("content", "{}")
                        if isinstance(result_content, str):
                            try:
                                result_data = json.loads(result_content)
                            except json.JSONDecodeError:
                                result_data = {"result": result_content}
                        else:
                            result_data = result_content
                        parts.append(types.Part.from_function_response(
                            name=block.get("name", "unknown"),
                            response=result_data,
                        ))
                if parts:
                    contents.append(types.Content(role=role, parts=parts))
        return contents

    def create_message(self, *, model, system, messages, tools, max_tokens=2048):
        from google.genai import types

        gemini_tools = [types.Tool(function_declarations=self._convert_tools(tools))]
        contents = self._convert_messages(messages, system)

        # Gemini 2.5 Flash/Pro have thinking ON by default; with a large
        # system prompt + 82 tools (~22K input tokens) the entire
        # max_output_tokens budget is consumed by thinking and zero tokens
        # remain for the actual function call. Disable thinking for the
        # tool-calling path — the model has explicit tools, no need to
        # ruminate before picking one.
        config_kwargs = dict(
            system_instruction=system,
            tools=gemini_tools,
            max_output_tokens=max_tokens,
            temperature=0.2,
        )
        if hasattr(types, "ThinkingConfig"):
            try:
                config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
            except Exception:
                logger.debug("Could not set ThinkingConfig; falling back to defaults", exc_info=True)
        config = types.GenerateContentConfig(**config_kwargs)

        response = self.client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

        content = []
        has_tool_call = False

        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    fc = part.function_call
                    # Convert proto map to regular dict
                    args = dict(fc.args) if fc.args else {}
                    content.append(ToolUseBlock(
                        id=self._tool_id(),
                        name=fc.name,
                        input=args,
                    ))
                    has_tool_call = True
                elif part.text:
                    content.append(TextBlock(text=part.text))

        usage_meta = getattr(response, "usage_metadata", None)
        input_tokens = 0
        output_tokens = 0
        
        if usage_meta:
            input_tokens = getattr(usage_meta, "prompt_token_count", None) or 0
            output_tokens = getattr(usage_meta, "candidates_token_count", None) or 0
        
        return LLMResponse(
            content=content,
            stop_reason="tool_use" if has_tool_call else "end_turn",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


# ---------------------------------------------------------------------------
# OpenAI (and any OpenAI-compatible endpoint)
# ---------------------------------------------------------------------------

class OpenAIProvider(LLMProvider):
    """OpenAI or any compatible API (Azure, Groq, Together, local Ollama, etc.)."""

    def __init__(self, api_key: str, base_url: str = None):
        import openai
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = openai.OpenAI(**kwargs)

    def _convert_tools(self, tools: list) -> list:
        """Convert Anthropic-format tool defs to OpenAI function format."""
        tools = apply_provider_hints(tools, "openai")
        result = []
        for tool in tools:
            result.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            })
        return result

    def _convert_messages(self, messages: list, system: str) -> list:
        """Convert Anthropic-format messages to OpenAI format."""
        oai_messages = [{"role": "system", "content": system}]
        for msg in messages:
            role = msg["role"]
            raw = msg["content"]

            if isinstance(raw, str):
                oai_messages.append({"role": role, "content": raw})
            elif isinstance(raw, list):
                # Audit M4: a user message can carry tool_results AND a text
                # prelude (e.g. the tool-limit instruction injected at
                # nl_gis/chat.py:938). The previous code emitted only the
                # tool messages and dropped the text. Emit both.
                tool_result_blocks = [b for b in raw if b.get("type") == "tool_result"]
                text_blocks = [b for b in raw if b.get("type") == "text"]
                tool_use_blocks = [b for b in raw if b.get("type") == "tool_use"]

                if tool_result_blocks:
                    for b in tool_result_blocks:
                        oai_messages.append({
                            "role": "tool",
                            "tool_call_id": b["tool_use_id"],
                            "content": b["content"],
                        })
                    # Preserve any accompanying text as a separate user msg.
                    if text_blocks:
                        oai_messages.append({
                            "role": role,
                            "content": "\n".join(b["text"] for b in text_blocks),
                        })
                else:
                    # Assistant content with text/tool_use blocks
                    text_parts = [b["text"] for b in text_blocks]
                    tool_calls = []
                    for b in tool_use_blocks:
                        tool_calls.append({
                            "id": b["id"],
                            "type": "function",
                            "function": {
                                "name": b["name"],
                                "arguments": json.dumps(b["input"]),
                            },
                        })

                    entry = {"role": "assistant"}
                    if text_parts:
                        entry["content"] = "\n".join(text_parts)
                    else:
                        entry["content"] = None
                    if tool_calls:
                        entry["tool_calls"] = tool_calls
                    oai_messages.append(entry)

        return oai_messages

    def create_message(self, *, model, system, messages, tools, max_tokens=2048):
        oai_tools = self._convert_tools(tools)
        oai_messages = self._convert_messages(messages, system)

        response = self.client.chat.completions.create(
            model=model,
            messages=oai_messages,
            tools=oai_tools,
            max_tokens=max_tokens,
            temperature=0.2,
        )

        choice = response.choices[0]
        content = []
        has_tool_call = False

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                content.append(ToolUseBlock(
                    id=tc.id,
                    name=tc.function.name,
                    input=args,
                ))
                has_tool_call = True

        if choice.message.content:
            content.append(TextBlock(text=choice.message.content))

        usage = response.usage
        return LLMResponse(
            content=content,
            stop_reason="tool_use" if has_tool_call else "end_turn",
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

# Default model per provider
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-20250514",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4.1",
}


def create_provider(
    provider_name: str,
    api_key: str,
    base_url: str = None,
) -> Optional[LLMProvider]:
    """Create an LLM provider by name. Returns None if key is empty."""
    if not api_key:
        return None

    provider_name = provider_name.lower().strip()

    if provider_name == "anthropic":
        return AnthropicProvider(api_key=api_key)
    elif provider_name == "gemini":
        return GeminiProvider(api_key=api_key)
    elif provider_name == "openai":
        return OpenAIProvider(api_key=api_key, base_url=base_url)
    else:
        logger.error(f"Unknown LLM provider: {provider_name}. Supported: anthropic, gemini, openai")
        return None
