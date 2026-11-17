"""Owner-scoped storage for bot group conversations."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from backend.persistence.db import get_db


def participant_session(user_id: str, group_id: str, bot_id: str) -> str:
    """Return a durable private runtime session for this group participant.

    Group transcripts remain in the group tables; this separate session keeps
    primary-runtime history out of the bot's private chat and other groups.
    The stable id avoids a schema migration and survives process restarts.
    """
    if not user_id or not group_id or not bot_id:
        raise ValueError("A sessão de grupo requer utilizador, grupo e bot.")
    identity = json.dumps([user_id, group_id, bot_id], ensure_ascii=False).encode("utf-8")
    session_id = "group-session-" + hashlib.sha256(identity).hexdigest()
    with get_db() as conn:
        member = conn.execute(
            """SELECT p.name FROM bot_groups g
               JOIN bot_group_members m ON m.group_id = g.id
               JOIN bot_profiles p ON p.id = m.bot_id
               WHERE g.id = ? AND g.user_id = ? AND p.id = ?
                 AND p.user_id = ? AND p.deleted = 0""",
            (group_id, user_id, bot_id, user_id),
        ).fetchone()
        if member is None:
            raise ValueError("O bot já não pertence a este grupo.")
        conn.execute(
            """INSERT OR IGNORE INTO sessions (id, user_id, title, mode)
               VALUES (?, ?, ?, '__bot_group__')""",
            (session_id, user_id, f"Grupo: {member['name']}"),
        )
        session = conn.execute(
            "SELECT user_id, mode FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if session is None or session["user_id"] != user_id or session["mode"] != "__bot_group__":
            raise ValueError("Não foi possível isolar a sessão do bot no grupo.")
    return session_id


def _group(conn: Any, user_id: str, group_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT g.*, (SELECT content FROM bot_group_messages m
               WHERE m.group_id = g.id ORDER BY m.rowid DESC LIMIT 1) AS last_message
           FROM bot_groups g WHERE g.id = ? AND g.user_id = ?""",
        (group_id, user_id),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result.pop("user_id")
    result["bot_ids"] = [r[0] for r in conn.execute(
        "SELECT bot_id FROM bot_group_members WHERE group_id = ? ORDER BY position", (group_id,)
    )]
    return result


def create_group(user_id: str, name: str, bot_ids: list[str]) -> dict[str, Any] | None:
    group_id = f"group-{uuid4().hex}"
    with get_db() as conn:
        # Membership is checked in the same transaction as creation. Deleted
        # profiles are never enrolled, including profiles belonging to others.
        found = conn.execute(
            f"SELECT id FROM bot_profiles WHERE user_id = ? AND deleted = 0 AND id IN ({','.join('?' for _ in bot_ids)})",
            (user_id, *bot_ids),
        ).fetchall()
        if len(found) != len(bot_ids):
            return None
        conn.execute("INSERT INTO bot_groups (id, user_id, name) VALUES (?, ?, ?)",
                     (group_id, user_id, name))
        conn.executemany(
            "INSERT INTO bot_group_members (group_id, bot_id, position) VALUES (?, ?, ?)",
            [(group_id, bot_id, index) for index, bot_id in enumerate(bot_ids)],
        )
        return _group(conn, user_id, group_id)


def list_groups(user_id: str) -> list[dict[str, Any]]:
    with get_db() as conn:
        ids = conn.execute(
            "SELECT id FROM bot_groups WHERE user_id = ? ORDER BY updated_at DESC, rowid DESC",
            (user_id,),
        ).fetchall()
        return [group for row in ids if (group := _group(conn, user_id, row[0])) is not None]


def get_group(user_id: str, group_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        return _group(conn, user_id, group_id)


def get_messages(user_id: str, group_id: str, limit: int = 500) -> list[dict[str, Any]] | None:
    with get_db() as conn:
        if _group(conn, user_id, group_id) is None:
            return None
        rows = conn.execute(
            """SELECT id, role, content, bot_id, bot_name, run_id, created_at
               FROM bot_group_messages
               WHERE group_id = ? AND rowid IN
                 (SELECT rowid FROM bot_group_messages WHERE group_id = ? ORDER BY rowid DESC LIMIT ?)
               ORDER BY rowid ASC""", (group_id, group_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def get_messages_page(user_id: str, group_id: str, limit: int,
                      before: str | None) -> dict[str, Any] | None:
    with get_db() as conn:
        if _group(conn, user_id, group_id) is None:
            return None
        cursor_rowid: int | None = None
        if before:
            cursor = conn.execute(
                "SELECT rowid FROM bot_group_messages WHERE id = ? AND group_id = ?",
                (before, group_id),
            ).fetchone()
            if cursor is None:
                raise ValueError("Cursor de mensagens inválido")
            cursor_rowid = cursor[0]
        rows = conn.execute(
            """SELECT id, role, content, bot_id, bot_name, run_id, created_at
               FROM bot_group_messages
               WHERE group_id = ? AND (? IS NULL OR rowid < ?)
               ORDER BY rowid DESC LIMIT ?""",
            (group_id, cursor_rowid, cursor_rowid, limit + 1),
        ).fetchall()
        has_more = len(rows) > limit
        messages = [dict(row) for row in reversed(rows[:limit])]
        return {"messages": messages, "has_more": has_more,
                "next_before": messages[0]["id"] if has_more and messages else None}


def add_message(group_id: str, role: str, content: str, bot_id: str | None = None,
                bot_name: str | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Persist one group message, optionally tied to its execution run.

    ``run_id`` is nullable so historical rows and callers that predate the
    canonical execution identity keep working; new composer messages pass it so
    a database reload can associate the message with its run without rebuilding
    the link from side records.
    """
    message_id = f"group-message-{uuid4().hex}"
    with get_db() as conn:
        conn.execute(
            "INSERT INTO bot_group_messages "
            "(id, group_id, role, content, bot_id, bot_name, run_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (message_id, group_id, role, content, bot_id, bot_name, run_id),
        )
        conn.execute("UPDATE bot_groups SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (group_id,))
        return dict(conn.execute(
            "SELECT id, role, content, bot_id, bot_name, run_id, created_at "
            "FROM bot_group_messages WHERE id = ?",
            (message_id,),
        ).fetchone())
