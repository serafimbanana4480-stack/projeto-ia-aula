"""Conversation-history cleanup shared by agents and the context store."""

from __future__ import annotations

import re

_TOOL_FENCE_RE = re.compile(r"```tool\b.*?(?:```|\Z)", re.IGNORECASE | re.DOTALL)
_TOOL_XML_RE = re.compile(
    r"<(?:tool_call|tool)>.*?(?:</(?:tool_call|tool)>|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_KIMI_TOOL_RE = re.compile(
    r"<\|tool_calls_section_begin\|>.*?(?:<\|tool_calls_section_end\|>|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_TOOL_PAYLOAD_MARKER_RE = re.compile(
    r'"(?:name|arguments)"\s*:|<tool_call>|```tool\b|<\|tool_calls_section_begin\|>',
    re.IGNORECASE,
)
_TOOL_CALL_NAME_RE = re.compile(r'"name"\s*:', re.IGNORECASE)
_WARNING_LINE_RE = re.compile(r"(?im)^[ \t]*[⚠!].{0,600}$")
_QUARANTINED_TOOL_HISTORY = (
    "[Histórico técnico ocultado: a resposta anterior repetiu chamadas internas "
    "de ferramenta e nenhuma dessas chamadas deve ser tratada como ação confirmada.]"
)


def sanitize_history_content(role: str, content: str) -> str:
    """Remove provider tool transport before old chat is sent back to a model."""
    if role != "assistant" or not content:
        return content

    marker_count = len(_TOOL_PAYLOAD_MARKER_RE.findall(content))
    call_count = len(_TOOL_CALL_NAME_RE.findall(content))
    if call_count >= 3:
        warnings = _WARNING_LINE_RE.findall(content)
        suffix = f"\n{warnings[-1].strip()}" if warnings else ""
        return _QUARANTINED_TOOL_HISTORY + suffix

    cleaned = _TOOL_FENCE_RE.sub("", content)
    cleaned = _TOOL_XML_RE.sub("", cleaned)
    cleaned = _KIMI_TOOL_RE.sub("", cleaned).strip()
    if cleaned:
        return cleaned
    if marker_count:
        return _QUARANTINED_TOOL_HISTORY
    return content
