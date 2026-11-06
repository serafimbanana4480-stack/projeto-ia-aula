"""Bot profiles bound to the existing, owner-scoped chat sessions."""

from __future__ import annotations

import uuid
from typing import Any

from backend.persistence.db import get_db

_FIELDS = frozenset({"name", "description", "instructions", "provider", "model", "archived"})
_SELECT = """
    SELECT b.*, s.last_active_at,
           (SELECT m.content FROM messages m
            WHERE m.session_id = b.session_id AND m.role IN ('user', 'assistant')
            ORDER BY m.created_at DESC, m.rowid DESC LIMIT 1) AS last_message
    FROM bot_profiles b JOIN sessions s ON s.id = b.session_id AND s.user_id = b.user_id
"""


def _row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    result["archived"] = bool(result["archived"])
    result["deleted"] = bool(result["deleted"])
    return result


def create_bot(user_id: str, values: dict[str, Any]) -> dict[str, Any]:
    bot_id = f"bot-{uuid.uuid4().hex}"
    session_id = f"bot-session-{uuid.uuid4().hex}"
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, title, mode) VALUES (?, ?, ?, ?)",
            (session_id, user_id, values["name"], "bot"),
        )
        conn.execute(
            """INSERT INTO bot_profiles
               (id, user_id, session_id, name, description, instructions, provider, model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (bot_id, user_id, session_id, values["name"], values["description"],
             values["instructions"], values["provider"], values["model"]),
        )
        row = conn.execute(_SELECT + " WHERE b.id = ? AND b.user_id = ?", (bot_id, user_id)).fetchone()
    result = _row(row)
    assert result is not None
    return result


def list_bots(user_id: str) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            _SELECT + " WHERE b.user_id = ? AND b.deleted = 0 "
            "ORDER BY s.last_active_at DESC, b.created_at DESC", (user_id,),
        ).fetchall()
    return [item for row in rows if (item := _row(row)) is not None]


def get_bot(user_id: str, bot_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            _SELECT + " WHERE b.user_id = ? AND b.id = ? AND b.deleted = 0", (user_id, bot_id),
        ).fetchone()
    return _row(row)


def bot_for_session(user_id: str, session_id: str) -> dict[str, Any] | None:
    """Include removed profiles so their sessions cannot bypass bot policy."""
    with get_db() as conn:
        row = conn.execute(
            _SELECT + " WHERE b.user_id = ? AND b.session_id = ?", (user_id, session_id),
        ).fetchone()
    return _row(row)


def update_bot(user_id: str, bot_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
    changes = {key: value for key, value in values.items() if key in _FIELDS}
    with get_db() as conn:
        if changes:
            assignments = ", ".join(f"{key} = ?" for key in changes)
            conn.execute(
                f"UPDATE bot_profiles SET {assignments}, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE id = ? AND user_id = ? AND deleted = 0",
                (*changes.values(), bot_id, user_id),
            )
            if "name" in changes:
                conn.execute(
                    "UPDATE sessions SET title = ? WHERE user_id = ? AND id = "
                    "(SELECT session_id FROM bot_profiles WHERE id = ? AND user_id = ? AND deleted = 0)",
                    (changes["name"], user_id, bot_id, user_id),
                )
        row = conn.execute(
            _SELECT + " WHERE b.user_id = ? AND b.id = ? AND b.deleted = 0", (user_id, bot_id),
        ).fetchone()
    return _row(row)


def remove_bot(user_id: str, bot_id: str) -> bool:
    """Hide a profile without deleting its conversation or run history."""
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE bot_profiles SET deleted = 1 WHERE id = ? AND user_id = ? AND deleted = 0",
            (bot_id, user_id),
        )
        return cursor.rowcount == 1
