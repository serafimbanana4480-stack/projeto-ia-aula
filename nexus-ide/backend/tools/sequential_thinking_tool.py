"""Local sequential thinking — step-by-step reasoning without requiring MCP.

Provides ``sequential_thinking`` as a self-contained tool. When the MCP
``sequential-thinking`` connector is unavailable, :mod:`backend.tools.mcp_tools`
falls back to this implementation.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_thoughts: dict[str, list[dict[str, Any]]] = {}


def _key(session_id: str, thought_number: int) -> str:
    return f"{session_id or 'default'}::{thought_number}"


async def sequential_thinking(
    thought: str = "",
    thought_number: int = 1,
    total_thoughts: int = 5,
    next_thought_needed: bool = True,
    session_id: str = "",
) -> dict[str, Any]:
    """Record one step in a sequential thinking chain.

    Thoughts are stored in a local in-memory list keyed by ``session_id`` and
    ``thought_number``. The full history is returned on every call so the agent
    can see the chain so far.

    Args:
        thought: The thought content.
        thought_number: The 1-based index of this thought in the chain.
        total_thoughts: Expected total number of thoughts.
        next_thought_needed: Whether another thought is expected after this one.
        session_id: Optional session id to scope the chain.

    Returns:
        Dict with the thought history and whether more thoughts are expected.
    """
    thought_number = max(1, min(int(thought_number), 128))
    total_thoughts = max(1, min(int(total_thoughts), 128))
    session_key = session_id or "default"

    entry = {
        "thought": str(thought)[:6000],
        "thought_number": thought_number,
        "total_thoughts": total_thoughts,
        "next_thought_needed": bool(next_thought_needed),
    }

    with _lock:
        chain = _thoughts.setdefault(session_key, [])
        while len(chain) < thought_number:
            chain.append({})
        chain[thought_number - 1] = entry
        history = list(chain)

    return {
        "ok": True,
        "thought_number": thought_number,
        "total_thoughts": total_thoughts,
        "next_thought_needed": next_thought_needed,
        "thoughts": history,
        "session_id": session_key,
    }


register_tool(
    ToolSpec(
        name="sequential_thinking",
        description=(
            "Step-by-step reasoning tool. Records a thought in a local chain "
            "and returns the full history. Use this when you need to break a "
            "complex problem into discrete reasoning steps. Does not require MCP."
        ),
        tags=["reasoning", "thinking", "planning"],
        category="system",
        risk_level="low",
        when_to_use="When a task crosses the complexity gate (architecture, debugging "
        "after multiple failures, or low confidence) and you need to reason step "
        "by step.",
        schema={
            "type": "object",
            "properties": {
                "thought": {"type": "string", "maxLength": 6000, "description": "The thought content."},
                "thought_number": {"type": "integer", "minimum": 1, "maximum": 128, "default": 1},
                "total_thoughts": {"type": "integer", "minimum": 1, "maximum": 128, "default": 5},
                "next_thought_needed": {"type": "boolean", "default": True},
                "session_id": {"type": "string", "description": "Optional session id to scope the chain.", "default": ""},
            },
            "required": ["thought"],
        },
        handler=sequential_thinking,
        timeout_seconds=10,
    )
)
