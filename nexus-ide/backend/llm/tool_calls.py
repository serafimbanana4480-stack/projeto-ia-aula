"""Native tool-call transport shared by the LLM provider adapters.

The agent loop understands exactly **one** tool-call dialect: the explicit
``<tool_call>{"name": "...", "arguments": {...}}</tool_call>`` wrapper that
``backend/agents/base.py::_parse_tool_calls`` parses and enforces against its
tool allow-list.

Providers that speak a *native* function-calling protocol (OpenAI-compatible,
Anthropic, Gemini, Kimi) therefore have two jobs:

1. forward the tool schema in the dialect the provider understands, and
2. fold the provider's native tool-call blocks back into that wrapper, so a
   native call and a hand-written wrapper end up on the same single, audited
   execution path.

Doing the folding here (instead of in each adapter) keeps the wrapper format
defined in exactly one place: a change to the agent parser's expectation is a
change to :data:`TOOL_CALL_OPEN` / :data:`TOOL_CALL_CLOSE` only.
"""

from __future__ import annotations

import json
from typing import Any

#: Opening tag of the wrapper the agent parser expects.
TOOL_CALL_OPEN = "<tool_call>"

#: Closing tag of the wrapper the agent parser expects.
TOOL_CALL_CLOSE = "</tool_call>"


def _iter_openai_tools(tools: Any) -> list[dict[str, Any]]:
    """Return the OpenAI-style tool entries of *tools*, ignoring junk."""
    if not isinstance(tools, (list, tuple)):
        return []
    entries: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        entries.append({"name": name, "function": function})
    return entries


def normalize_tool_arguments(raw: Any) -> dict[str, Any]:
    """Coerce a provider's tool arguments into a JSON object.

    Providers deliver arguments as a JSON string (OpenAI, Anthropic
    ``input_json_delta``) or as an object (Gemini ``functionCall.args``).  A
    malformed payload must never raise: a broken call is simply a call with no
    arguments, which the agent's own validator rejects.
    """
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError):
            return {}
        return dict(decoded) if isinstance(decoded, dict) else {}
    return {}


def render_tool_call(name: str, arguments: Any) -> str:
    """Render one native tool call in the wrapper the agent parser expects."""
    payload = {
        "name": str(name or "").strip(),
        "arguments": normalize_tool_arguments(arguments),
    }
    return TOOL_CALL_OPEN + json.dumps(payload, ensure_ascii=False) + TOOL_CALL_CLOSE


def fold_tool_calls(calls: list[tuple[str, Any]]) -> str:
    """Render ``(name, arguments)`` pairs as wrapper blocks.

    Returns an empty string when there is no usable call, so a caller can use
    the result as a boolean.
    """
    blocks = [
        render_tool_call(name, arguments)
        for name, arguments in calls
        if str(name or "").strip()
    ]
    if not blocks:
        return ""
    return "\n" + "\n".join(blocks)


# ---------------------------------------------------------------------------
# Tool-schema translation
# ---------------------------------------------------------------------------


def _schema_with_type(schema: Any, *, uppercase_types: bool) -> dict[str, Any]:
    """Return a JSON-Schema object, optionally with proto3 enum-style types."""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    result = dict(schema)
    result.setdefault("type", "object")
    result.setdefault("properties", {})
    if uppercase_types:
        _uppercase_types(result)
    return result


def _uppercase_types(node: Any) -> None:
    """Rewrite JSON-Schema ``type`` values in place to proto3 enum names.

    Gemini's REST API types its ``Schema.type`` as a proto3 enum
    (``OBJECT``, ``STRING``, …).  Lowercase values are accepted by the
    frontend today but are not the canonical wire form, so they are
    normalized here instead of hoping the provider is lenient.
    """
    if isinstance(node, dict):
        value = node.get("type")
        if isinstance(value, str):
            node["type"] = value.upper()
        for key in ("properties", "items", "$defs", "definitions"):
            child = node.get(key)
            if isinstance(child, dict):
                for sub in child.values():
                    _uppercase_types(sub)
            elif isinstance(child, list):
                for sub in child:
                    _uppercase_types(sub)
        for key in ("anyOf", "oneOf", "allOf"):
            child = node.get(key)
            if isinstance(child, list):
                for sub in child:
                    _uppercase_types(sub)
    elif isinstance(node, list):
        for sub in node:
            _uppercase_types(sub)


def openai_tools_to_anthropic(tools: Any) -> list[dict[str, Any]]:
    """Convert OpenAI-style tool schemas into Anthropic's ``input_schema`` form."""
    converted: list[dict[str, Any]] = []
    for entry in _iter_openai_tools(tools):
        function = entry["function"]
        schema = _schema_with_type(function.get("parameters"), uppercase_types=False)
        item: dict[str, Any] = {"name": entry["name"], "input_schema": schema}
        description = function.get("description")
        if description:
            item["description"] = str(description)
        converted.append(item)
    return converted


def anthropic_tool_choice(tool_choice: Any) -> dict[str, Any] | None:
    """Translate an OpenAI-style ``tool_choice`` into Anthropic's form."""
    if tool_choice is None:
        return None
    if isinstance(tool_choice, dict):
        function = tool_choice.get("function")
        name = ""
        if isinstance(function, dict):
            name = str(function.get("name") or "").strip()
        if not name:
            name = str(tool_choice.get("name") or "").strip()
        if name:
            return {"type": "tool", "name": name}
        return None
    selector = str(tool_choice).strip().lower()
    if selector in ("auto", ""):
        return {"type": "auto"}
    if selector in ("required", "any"):
        return {"type": "any"}
    if selector == "none":
        return {"type": "none"}
    return {"type": "auto"}


def openai_tools_to_gemini(tools: Any) -> list[dict[str, Any]]:
    """Convert OpenAI-style tool schemas into Gemini's ``functionDeclarations``."""
    declarations: list[dict[str, Any]] = []
    for entry in _iter_openai_tools(tools):
        function = entry["function"]
        declaration: dict[str, Any] = {
            "name": entry["name"],
            "parameters": _schema_with_type(
                function.get("parameters"), uppercase_types=True
            ),
        }
        description = function.get("description")
        if description:
            declaration["description"] = str(description)
        declarations.append(declaration)
    if not declarations:
        return []
    return [{"functionDeclarations": declarations}]


def gemini_tool_config(tool_choice: Any) -> dict[str, Any] | None:
    """Translate an OpenAI-style ``tool_choice`` into Gemini's ``toolConfig``."""
    if tool_choice is None:
        return None
    if isinstance(tool_choice, dict):
        function = tool_choice.get("function")
        name = ""
        if isinstance(function, dict):
            name = str(function.get("name") or "").strip()
        if not name:
            name = str(tool_choice.get("name") or "").strip()
        if name:
            return {
                "functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": [name]}
            }
        return None
    selector = str(tool_choice).strip().lower()
    if selector in ("auto", ""):
        return {"functionCallingConfig": {"mode": "AUTO"}}
    if selector in ("required", "any"):
        return {"functionCallingConfig": {"mode": "ANY"}}
    if selector == "none":
        return {"functionCallingConfig": {"mode": "NONE"}}
    return {"functionCallingConfig": {"mode": "AUTO"}}


__all__ = [
    "TOOL_CALL_CLOSE",
    "TOOL_CALL_OPEN",
    "anthropic_tool_choice",
    "fold_tool_calls",
    "gemini_tool_config",
    "normalize_tool_arguments",
    "openai_tools_to_anthropic",
    "openai_tools_to_gemini",
    "render_tool_call",
]
