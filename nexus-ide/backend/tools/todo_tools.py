"""Persistent per-session todo list for long autonomous runs.

The agent's context window is ephemeral; a plan kept only in conversation
history is lost the moment the context is trimmed. :mod:`todo_tools` gives the
agent a durable checklist — one JSON file per session under
``data/todos/{session_id}.json`` — that survives process restarts and can be
re-injected into prompts via :func:`get_session_todos_compact`.

Writes are atomic (``.tmp`` + ``os.replace``) so a crash never leaves a
half-written plan behind.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

_lock = threading.Lock()

_UNSAFE_SESSION_RE = re.compile(r"[^a-z0-9._-]")


class TodoStateError(ValueError):
    """Raised when a persisted todo file cannot be read without data loss."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def safe_session_id(session_id: str) -> str:
    """Return a path-safe, collision-resistant storage key for a session.

    Lowercase ASCII identifiers retain their historical filename for backwards
    compatibility. IDs that would be changed by sanitising, collide on a
    case-insensitive filesystem, exceed the historical limit, or enter the
    reserved hash namespace get a stable digest-based key instead.

    An absent session and the reserved ``default`` ID are invalid. In
    particular, they must never select the shared historical
    ``default.json`` file.
    """
    if not isinstance(session_id, str) or not session_id or not session_id.strip():
        raise ValueError("session_id must be a non-empty string")
    if session_id == "default":
        raise ValueError("session_id 'default' is reserved for legacy data")

    is_legacy_safe = (
        len(session_id) <= _MAX_SESSION_CHARS
        and session_id == session_id.lower()
        and _UNSAFE_SESSION_RE.search(session_id) is None
        and not session_id.startswith(_HASHED_SESSION_PREFIX)
        and session_id.split(".", 1)[0].casefold() not in _WINDOWS_RESERVED_BASENAMES
    )
    if is_legacy_safe:
        return session_id

    digest = hashlib.sha256(session_id.encode("utf-8", errors="surrogatepass")).hexdigest()
    return f"{_HASHED_SESSION_PREFIX}{digest}"


def _session_key_or_error(session_id: str) -> tuple[str | None, str | None]:
    try:
        return safe_session_id(session_id), None
    except ValueError as exc:
        return None, str(exc)


def _todo_path(session_key: str) -> Path:
    return TODOS_DIR / f"{session_key}.json"


def _empty_state() -> dict[str, Any]:
    return {"version": 1, "next_id": 1, "items": []}


def _load_state(session_key: str) -> dict[str, Any]:
    """Read a session plan without hiding corrupt data behind an empty list."""
    path = _todo_path(session_key)
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        # A broken symlink is present data, not an absent todo file. Treating it
        # as an empty plan would allow a later write to replace that entry.
        if path.is_symlink():
            raise TodoStateError("todo file is a broken symbolic link") from None
        return _empty_state()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        logger.warning("Cannot read todo file for session %r: %s", session_key, exc)
        raise TodoStateError("todo file is unreadable or contains invalid JSON") from exc

    if not isinstance(data, dict):
        raise TodoStateError("todo file must contain a JSON object")

    version = data.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise TodoStateError("todo file has an unsupported version")

    items_raw = data.get("items")
    if not isinstance(items_raw, list):
        raise TodoStateError("todo file must contain an items list")

    normalised_items: list[dict[str, Any]] = []
    known_ids: set[int] = set()
    for index, raw in enumerate(items_raw):
        try:
            item = _normalise_item(raw)
        except TodoStateError as exc:
            raise TodoStateError(f"todo item {index} is invalid: {exc}") from exc
        if item["id"] in known_ids:
            raise TodoStateError(f"todo item {index} has a duplicate id")
        normalised_items.append(item)
        known_ids.add(item["id"])

    minimum_next_id = max(known_ids, default=0) + 1
    raw_next_id = data.get("next_id", minimum_next_id)
    if isinstance(raw_next_id, bool) or not isinstance(raw_next_id, (int, str)):
        raise TodoStateError("todo file next_id must be a positive integer")
    try:
        next_id = int(raw_next_id)
    except ValueError as exc:
        raise TodoStateError("todo file next_id must be a positive integer") from exc
    if next_id < 1:
        raise TodoStateError("todo file next_id must be a positive integer")

    return {
        "version": 1,
        "next_id": max(minimum_next_id, next_id),
        "items": normalised_items,
    }


def _normalise_item(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TodoStateError("item must be a JSON object")
    raw_id = raw.get("id")
    if isinstance(raw_id, bool) or not isinstance(raw_id, (int, str)):
        raise TodoStateError("id must be a positive integer")
    try:
        item_id = int(raw_id)
    except ValueError as exc:
        raise TodoStateError("id must be a positive integer") from exc
    if item_id < 1:
        raise TodoStateError("id must be a positive integer")

    raw_content = raw.get("content")
    if not isinstance(raw_content, str) or not raw_content.strip():
        raise TodoStateError("content must be a non-empty string")
    content = raw_content.strip()
    if len(content) > _MAX_CONTENT_CHARS:
        raise TodoStateError("content exceeds the supported length")

    raw_priority = raw.get("priority", "normal")
    if raw_priority is None or raw_priority == "":
        raw_priority = "normal"
    if not isinstance(raw_priority, str):
        raise TodoStateError("priority must be a string")
    priority = _priority_of(raw_priority)
    if priority not in PRIORITIES:
        raise TodoStateError("priority is unsupported")

    raw_status = raw.get("status", "pending")
    if raw_status is None or raw_status == "":
        raw_status = "pending"
    if not isinstance(raw_status, str) or raw_status not in STATUSES:
        raise TodoStateError("status is unsupported")

    created_at = raw.get("created_at", "")
    updated_at = raw.get("updated_at", "")
    if created_at is None:
        created_at = ""
    if updated_at is None:
        updated_at = ""
    if not isinstance(created_at, str) or not isinstance(updated_at, str):
        raise TodoStateError("timestamps must be strings")

    return {
        "id": item_id,
        "content": content,
        "priority": priority,
        "status": raw_status,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _state_error_result(session_key: str, exc: TodoStateError) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"Stored todo state is invalid; no changes were written. {exc}",
        "error_category": "invalid_todo_state",
        "session_id": session_key,
    }


def _save_state(session_key: str, state: dict[str, Any]) -> None:
    """Persist atomically: write ``*.tmp`` then ``os.replace`` over the target."""
    TODOS_DIR.mkdir(parents=True, exist_ok=True)
    path = _todo_path(session_key)
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    for item in items:
        counts[item["status"]] += 1
    counts["total"] = len(items)
    return counts


def _priority_of(value: Any) -> str:
    text = str(value or "").strip().lower()
    return _PRIORITY_ALIASES.get(text, text)


def _find(items: list[dict[str, Any]], item_id: Any) -> dict[str, Any] | None:
    try:
        wanted = int(item_id)
    except (TypeError, ValueError):
        return None
    return next((item for item in items if item["id"] == wanted), None)


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

    key, session_error = _session_key_or_error(session_id)
    if session_error is not None:
        return {"ok": False, "error": session_error}
    assert key is not None
    with _lock:
        try:
            state = _load_state(key)
        except TodoStateError as exc:
            return _state_error_result(key, exc)
        todo_items: list[dict[str, Any]] = state["items"]

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
            item = {
                "id": state["next_id"],
                "content": text[:_MAX_CONTENT_CHARS],
                "priority": prio,
                "status": "pending",
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            state["next_id"] += 1
            todo_items.append(item)
            state["items"] = todo_items
            _save_state(key, state)
            return {"ok": True, "operation": op, "session_id": key, "todos": todo_items, **_summary(todo_items)}

        if op == "update":
            target = _find(todo_items, id)
            if target is None:
                return {"ok": False, "error": f"Todo {id!r} not found."}
            changed = False
            if str(content or "").strip():
                target["content"] = str(content).strip()[:_MAX_CONTENT_CHARS]
                changed = True
            if str(priority or "").strip():
                prio = _priority_of(priority)
                if prio not in PRIORITIES:
                    return {
                        "ok": False,
                        "error": f"Invalid priority {priority!r}; use one of: {', '.join(PRIORITIES)}.",
                    }
                target["priority"] = prio
                changed = True
            new_status = str(status or "").strip().lower()
            if new_status:
                if new_status not in STATUSES:
                    return {
                        "ok": False,
                        "error": (
                            f"Invalid status {status!r}; "
                            f"use one of: {', '.join(STATUSES)}."
                        ),
                    }
                target["status"] = new_status
                changed = True
            if changed:
                target["updated_at"] = _now_iso()
            state["items"] = todo_items
            _save_state(key, state)
            return {"ok": True, "operation": op, "session_id": key, "todos": todo_items, **_summary(todo_items)}

        if op == "set_all":
            replacement = _items_from_set_all(items)
            if isinstance(replacement, str):
                return {"ok": False, "error": replacement}
            state = _empty_state()
            for entry in replacement:
                state["items"].append(
                    {
                        "id": state["next_id"],
                        "content": entry["content"],
                        "priority": entry["priority"],
                        "status": "pending",
                        "created_at": _now_iso(),
                        "updated_at": _now_iso(),
                    }
                )
                state["next_id"] += 1
            _save_state(key, state)
            return {"ok": True, "operation": op, "session_id": key, "todos": state["items"], **_summary(state["items"])}

        if op == "remove":
            target = _find(todo_items, id)
            if target is None:
                return {"ok": False, "error": f"Todo {id!r} not found."}
            todo_items.remove(target)
            state["items"] = todo_items
            _save_state(key, state)
            return {"ok": True, "operation": op, "session_id": key, "todos": todo_items, **_summary(todo_items)}

        # clear
        state = _empty_state()
        _save_state(key, state)
        return {"ok": True, "operation": op, "session_id": key, "todos": [], **_summary([])}


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


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"counts": _counts(items)}


def read_session_todo_snapshot(session_id: str, status: str = "") -> dict[str, Any]:
    """Return the session's todo list with per-status counts.

    Args:
        session_id: Required session that scopes the list; ``default`` is reserved.
        status: Optional filter (``pending`` | ``in_progress`` | ``completed`` |
            ``cancelled``).

    Returns:
        Dict with the todo items and counts.
    """
    key, session_error = _session_key_or_error(session_id)
    if session_error is not None:
        return {"ok": False, "error": session_error}
    assert key is not None
    with _lock:
        try:
            todo_items = _load_state(key)["items"]
        except TodoStateError as exc:
            return _state_error_result(key, exc)
    wanted = str(status or "").strip().lower()
    if wanted:
        if wanted not in STATUSES:
            return {"ok": False, "error": f"Invalid status {status!r}; use one of: {', '.join(STATUSES)}."}
        todo_items = [item for item in todo_items if item["status"] == wanted]
    return {"ok": True, "session_id": key, "todos": todo_items, "counts": _counts(todo_items)}


async def todo_list(session_id: str = "", status: str = "") -> dict[str, Any]:
    """Tool-compatible reader backed by the same durable snapshot as the UI."""
    import asyncio

    return await asyncio.to_thread(read_session_todo_snapshot, session_id, status)


def get_session_todos(session_id: str) -> list[dict[str, Any]]:
    """Read the persisted todos of *session_id* (for other backend modules)."""
    key, session_error = _session_key_or_error(session_id)
    if session_error is not None:
        logger.debug("Ignoring todo lookup without a valid session_id")
        return []
    assert key is not None
    with _lock:
        return list(_load_state(key)["items"])


def get_session_todos_compact(session_id: str, max_items: int = 8) -> str:
    """Render the session plan as a compact text block for prompt injection."""
    try:
        items = get_session_todos(session_id)
    except TodoStateError as exc:
        logger.warning("Cannot inject todos for a corrupt session plan: %s", exc)
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
