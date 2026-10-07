"""Persistent per-session todo list for long autonomous runs.

The agent's context window is ephemeral; a plan kept only in conversation
history is lost the moment the context is trimmed. :mod:`todo_tools` gives the
agent a durable checklist — stored in SQLite via :mod:`backend.persistence.db` —
that survives process restarts and can be re-injected into prompts via
:func:`get_session_todos_compact`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.persistence.db import (
    clear_session_todos,
    create_todo,
    delete_todo,
    get_session_todos_db,
    get_todos_by_status,
    update_todo,
)
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

TODOS_DIR: Path = Path(
    os.environ.get("NEXUS_TODOS_DIR")
    or Path(__file__).resolve().parent.parent.parent / "data" / "todos"
).expanduser().resolve()

STATUSES = ("pending", "in_progress", "completed", "cancelled")
PRIORITIES = ("low", "normal", "high")
_PRIORITY_ALIASES = {"medium": "normal", "med": "normal", "1": "low", "2": "normal", "3": "high"}
_STATUS_MARKERS = {
    "pending": "[ ]",
    "in_progress": "[~]",
    "completed": "[x]",
    "cancelled": "[-]",
}
_MAX_CONTENT_CHARS = 2000
_MAX_SESSION_CHARS = 120
_HASHED_SESSION_PREFIX = "_unsafe_"
_WINDOWS_RESERVED_BASENAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        "conin$",
        "conout$",
        *(f"com{suffix}" for suffix in "123456789¹²³"),
        *(f"lpt{suffix}" for suffix in "123456789¹²³"),
    }
)
_UNSAFE_SESSION_RE = re.compile(r"[^a-z0-9._-]")


def safe_session_id(session_id: Any) -> str:
    """Return a safe storage key for *session_id*.

    Plain lowercase IDs that match ``^[a-z0-9._-]+$`` and are <=120 chars
    are returned unchanged. Everything else (empty, None, uppercase,
    path separators, Windows reserved names, too long) is mapped to a
    deterministic ``_unsafe_<sha256>`` key.
    """
    if session_id is None:
        raise ValueError("session_id must be a non-empty string")
    text = str(session_id)
    if not text:
        raise ValueError("session_id must be a non-empty string")
    if text == "default":
        raise ValueError("session_id 'default' is reserved")
    if len(text) > 120:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:64]
        return f"{_HASHED_SESSION_PREFIX}{digest}"
    if text.lower() != text or _UNSAFE_SESSION_RE.search(text):
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:64]
        return f"{_HASHED_SESSION_PREFIX}{digest}"
    if Path(text).stem in _WINDOWS_RESERVED_BASENAMES:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:64]
        return f"{_HASHED_SESSION_PREFIX}{digest}"
    return text


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _priority_of(value: Any) -> str:
    text = str(value or "").strip().lower()
    return _PRIORITY_ALIASES.get(text, text)


def _find(items: list[dict[str, Any]], item_id: Any) -> dict[str, Any] | None:
    try:
        wanted = int(item_id)
    except (TypeError, ValueError):
        return None
    return next((item for item in items if item["id"] == wanted), None)


def _counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    for item in items:
        counts[item["status"]] += 1
    counts["total"] = len(items)
    return counts


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"counts": _counts(items)}


async def todo_write(
    operation: str = "",
    content: str = "",
    id: Any = None,
    priority: str = "",
    status: str = "",
    items: Any = None,
    session_id: str = "",
) -> dict[str, Any]:
    """Create, update, replace, remove, or clear todos for this session.

    Args:
        operation: One of ``add``, ``update``, ``set_all``, ``remove``, ``clear``.
        content: Task text (used by ``add`` and ``update``).
        id: Numeric task id (used by ``update`` and ``remove``).
        priority: ``low`` | ``normal`` | ``high`` (``add`` defaults to ``normal``;
            ``update`` only changes it when provided).
        status: New status for ``update``: ``pending`` | ``in_progress`` |
            ``completed`` | ``cancelled``.
        items: Replacement list for ``set_all`` (``[{"content": ..., "priority": ...}]``).
        session_id: Required session that scopes the list; ``default`` is reserved.

    Returns:
        The full (updated) todo list with per-status counts.
    """
    op = str(operation or "").strip().lower()
    if op not in {"add", "update", "set_all", "remove", "clear"}:
        return {
            "ok": False,
            "error": (
                f"Unknown operation {operation!r}. "
                "Use one of: add, update, set_all, remove, clear."
            ),
        }

    if not session_id or session_id == "default":
        return {"ok": False, "error": "session_id must be a non-empty string; 'default' is reserved."}

    if op == "add":
        text = str(content or "").strip()
        if not text:
            return {"ok": False, "error": "content is required for operation 'add'."}
        prio = _priority_of(priority) if str(priority or "").strip() else "normal"
        if prio not in PRIORITIES:
            return {
                "ok": False,
                "error": f"Invalid priority {priority!r}; use one of: {', '.join(PRIORITIES)}.",
            }
        row = create_todo(session_id, text[:_MAX_CONTENT_CHARS], prio)
        if row is None:
            return {"ok": False, "error": "Failed to create todo in database."}
        todo_items = get_session_todos_db(session_id)
        return {"ok": True, "operation": op, "session_id": session_id, "todos": todo_items, **_summary(todo_items)}

    if op == "update":
        todo_items = get_session_todos_db(session_id)
        target = _find(todo_items, id)
        if target is None:
            return {"ok": False, "error": f"Todo {id!r} not found."}
        changed = False
        new_content = str(content or "").strip() if content is not None else None
        new_priority = str(priority or "").strip() if priority is not None else None
        new_status = str(status or "").strip().lower() if status is not None else None
        if new_content:
            changed = True
        if new_priority:
            if new_priority not in PRIORITIES:
                return {
                    "ok": False,
                    "error": f"Invalid priority {priority!r}; use one of: {', '.join(PRIORITIES)}.",
                }
            changed = True
        if new_status:
            if new_status not in STATUSES:
                return {
                    "ok": False,
                    "error": (
                        f"Invalid status {status!r}; "
                        f"use one of: {', '.join(STATUSES)}."
                    ),
                }
            changed = True
        if not changed:
            return {"ok": True, "operation": op, "session_id": session_id, "todos": todo_items, **_summary(todo_items)}
        row = update_todo(
            target["id"],
            content=new_content or None,
            priority=new_priority or None,
            status=new_status or None,
        )
        todo_items = get_session_todos_db(session_id)
        return {"ok": True, "operation": op, "session_id": session_id, "todos": todo_items, **_summary(todo_items)}

    if op == "set_all":
        replacement = _items_from_set_all(items)
        if isinstance(replacement, str):
            return {"ok": False, "error": replacement}
        clear_session_todos(session_id)
        for entry in replacement:
            create_todo(session_id, entry["content"], entry["priority"])
        todo_items = get_session_todos_db(session_id)
        return {"ok": True, "operation": op, "session_id": session_id, "todos": todo_items, **_summary(todo_items)}

    if op == "remove":
        todo_items = get_session_todos_db(session_id)
        target = _find(todo_items, id)
        if target is None:
            return {"ok": False, "error": f"Todo {id!r} not found."}
        deleted = delete_todo(target["id"])
        if not deleted:
            return {"ok": False, "error": f"Todo {id!r} not found in database."}
        todo_items = get_session_todos_db(session_id)
        return {"ok": True, "operation": op, "session_id": session_id, "todos": todo_items, **_summary(todo_items)}

    # clear
    clear_session_todos(session_id)
    return {"ok": True, "operation": op, "session_id": session_id, "todos": [], "counts": _summary([])["counts"]}


def _items_from_set_all(items: Any) -> list[dict[str, Any]] | str:
    if not isinstance(items, list) or not items:
        return "items must be a non-empty list of {content, priority} objects."
    parsed: list[dict[str, Any]] = []
    for entry in items:
        if not isinstance(entry, dict):
            return "items must be a non-empty list of {content, priority} objects."
        text = str(entry.get("content") or "").strip()
        if not text:
            return "Every item needs a non-empty 'content'."
        prio = _priority_of(entry.get("priority") or "normal")
        if prio not in PRIORITIES:
            return f"Invalid priority {entry.get('priority')!r}; use one of: {', '.join(PRIORITIES)}."
        parsed.append({"content": text[:_MAX_CONTENT_CHARS], "priority": prio})
    return parsed


def read_session_todo_snapshot(session_id: str, status: str = "") -> dict[str, Any]:
    """Return the session's todo list with per-status counts.

    Args:
        session_id: Required session that scopes the list; ``default`` is reserved.
        status: Optional filter (``pending`` | ``in_progress`` | ``completed`` |
            ``cancelled``).

    Returns:
        Dict with the todo items and counts.
    """
    if not session_id or session_id == "default":
        return {"ok": False, "error": "session_id must be a non-empty string; 'default' is reserved.", "error_category": "invalid_session"}
    if status and status not in STATUSES:
        return {"ok": False, "error": f"Invalid status {status!r}; use one of: {', '.join(STATUSES)}.", "error_category": "invalid_status"}
    try:
        if status:
            todo_items = get_todos_by_status(session_id, status)
        else:
            todo_items = get_session_todos_db(session_id)
    except Exception as exc:
        logger.warning("Cannot read todo snapshot for session %r: %s", session_id, exc)
        return {"ok": False, "error": f"Failed to read todos: {exc}"}
    return {"ok": True, "session_id": session_id, "todos": todo_items, "counts": _counts(todo_items)}


async def todo_list(session_id: str = "", status: str = "") -> dict[str, Any]:
    """Tool-compatible reader backed by the same durable snapshot as the UI."""
    import asyncio

    return await asyncio.to_thread(read_session_todo_snapshot, session_id, status)


def get_session_todos(session_id: str) -> list[dict[str, Any]]:
    """Read the persisted todos of *session_id* (for other backend modules)."""
    if not session_id or session_id == "default":
        logger.debug("Ignoring todo lookup without a valid session_id")
        return []
    try:
        return get_session_todos_db(session_id)
    except Exception as exc:
        logger.warning("Cannot read todos for session %r: %s", session_id, exc)
        return []


def get_session_todos_compact(session_id: str, max_items: int = 8) -> str:
    """Render the session plan as a compact text block for prompt injection."""
    try:
        items = get_session_todos(session_id)
    except Exception as exc:
        logger.warning("Cannot inject todos for session %r: %s", session_id, exc)
        return "[TODO indisponível: os dados guardados são inválidos e foram preservados.]"
    if not items:
        return ""
    limit = max(0, int(max_items))
    lines: list[str] = []
    for item in items[:limit]:
        marker = _STATUS_MARKERS.get(item["status"], "[ ]")
        lines.append(f"{marker} #{item['id']} ({item['priority']}) {item['content']}")
    remaining = len(items) - len(lines)
    if remaining > 0:
        lines.append(f"... e mais {remaining} itens (usa todo_list para ver tudo)")
    return "\n".join(lines)


register_tool(
    ToolSpec(
        name="todo_write",
        description=(
            "Write to the persistent per-session todo list (add / update / "
            "set_all / remove / clear). The list survives restarts; use it to "
            "plan multi-step work and track progress across a long run."
        ),
        tags=["todo", "plan", "task", "persistence"],
        category="system",
        risk_level="low",
        when_to_use="At the start of a multi-step task to lay out the plan, and whenever "
        "a step starts, finishes, or the plan changes.",
        schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["add", "update", "set_all", "remove", "clear"],
                    "description": "add: new pending task; update: change id's content/priority/status; "
                    "set_all: replace the whole list; remove: delete id; clear: empty the list.",
                },
                "content": {"type": "string", "description": "Task text (operation add, or new text in update)."},
                "id": {
                    "type": ["integer", "string"],
                    "description": "Numeric task id (operations update and remove).",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "Task priority (default: normal).",
                    "default": "normal",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "cancelled"],
                    "description": "New status for operation update.",
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "Task text."},
                            "priority": {
                                "type": "string",
                                "enum": ["low", "normal", "high"],
                                "description": "Task priority (default: normal).",
                            },
                        },
                        "required": ["content"],
                    },
                    "description": "Replacement list for operation set_all.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Required session that scopes the todo list; 'default' is reserved.",
                    "default": "",
                },
            },
            "required": ["operation"],
        },
        handler=todo_write,
        timeout_seconds=10,
    )
)

register_tool(
    ToolSpec(
        name="todo_list",
        description=(
            "Read the persistent per-session todo list: every task with its id, "
            "status and priority, plus per-status counts."
        ),
        tags=["todo", "plan", "task", "persistence"],
        category="system",
        risk_level="low",
        when_to_use="When you need to recall the current plan or check what is still pending.",
        schema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "cancelled"],
                    "description": "Optional filter by status.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Required session that scopes the todo list; 'default' is reserved.",
                    "default": "",
                },
            },
        },
        handler=todo_list,
        timeout_seconds=10,
    )
)