"""SQLite database layer for NEXUS IDE.

Singleton connection with WAL mode. Thread-safe via aiosqlite for async access.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "nexus.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas.sql"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def init_db() -> None:
    """Initialize the database. Creates directory and applies schema if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.executescript(schema)
        conn.commit()
    logger.info("DB initialized at %s", DB_PATH)


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Context manager yielding a sqlite connection with row_factory=Row."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ───── PROJECTS ─────────────────────────────────────────────────────────

def create_project(name: str, path: str, description: str = "", mode: str = "auto",
                   preferred_model: Optional[str] = None, trust: bool = False) -> dict:
    pid = _new_id()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO projects (id, name, path, description, mode, preferred_model, trust)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (pid, name, path, description, mode, preferred_model, 1 if trust else 0),
        )
    return get_project(pid)


def get_project(project_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None


def list_projects() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]


def update_project(project_id: str, **fields: Any) -> Optional[dict]:
    if not fields:
        return get_project(project_id)
    fields["updated_at"] = _now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_db() as conn:
        conn.execute(f"UPDATE projects SET {cols} WHERE id = ?", (*fields.values(), project_id))
    return get_project(project_id)


def delete_project(project_id: str) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


# ───── SESSIONS ─────────────────────────────────────────────────────────

def create_session(project_id: Optional[str] = None, title: str = "Nova sessão",
                   mode: str = "auto") -> dict:
    sid = _new_id()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, project_id, title, mode) VALUES (?, ?, ?, ?)",
            (sid, project_id, title, mode),
        )
    return get_session(sid)


def get_session(session_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


def list_sessions(project_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    with get_db() as conn:
        if project_id:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE project_id = ? ORDER BY last_active_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY last_active_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def touch_session(session_id: str) -> None:
    with get_db() as conn:
        conn.execute("UPDATE sessions SET last_active_at = ? WHERE id = ?", (_now_iso(), session_id))


# ───── MESSAGES ─────────────────────────────────────────────────────────

def add_message(session_id: str, role: str, content: str, *,
                tier_used: Optional[str] = None, model_used: Optional[str] = None,
                tools_used: Optional[list] = None, tokens_in: int = 0, tokens_out: int = 0,
                latency_ms: int = 0) -> dict:
    mid = _new_id()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO messages
               (id, session_id, role, content, tier_used, model_used, tools_used_json,
                tokens_in, tokens_out, latency_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mid, session_id, role, content, tier_used, model_used,
             json.dumps(tools_used) if tools_used else None,
             tokens_in, tokens_out, latency_ms),
        )
    touch_session(session_id)
    return {"id": mid, "session_id": session_id, "role": role, "content": content}


def get_messages(session_id: str, limit: int = 200) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ───── TOOL EXECUTIONS ──────────────────────────────────────────────────

def log_tool_execution(session_id: Optional[str], tool_name: str, args: dict,
                       result: Any, success: bool = True, error: Optional[str] = None,
                       duration_ms: int = 0) -> str:
    eid = _new_id()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO tool_executions
               (id, session_id, tool_name, args_json, result_json, success, error, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (eid, session_id, tool_name, json.dumps(args, default=str),
             json.dumps(result, default=str) if result is not None else None,
             1 if success else 0, error, duration_ms),
        )
    return eid


# ───── ROUTING DECISIONS ────────────────────────────────────────────────

def log_routing_decision(session_id: Optional[str], user_input: str,
                         tier: Optional[str] = None, tier_chosen: Optional[str] = None,
                         reason: str = "", confidence: float = 0.0, word_count: int = 0,
                         decision_ms: int = 0) -> str:
    rid = _new_id()
    resolved_tier = tier_chosen or tier or "fast"
    with get_db() as conn:
        conn.execute(
            """INSERT INTO routing_decisions
               (id, session_id, user_input, tier_chosen, reason, confidence,
                word_count, decision_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (rid, session_id, user_input[:500], resolved_tier, reason, confidence,
             word_count, decision_ms),
        )
    return rid


def recent_routing_decisions(limit: int = 50) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM routing_decisions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ───── PROPOSED CHANGES ─────────────────────────────────────────────────

def propose_change(session_id: str, project_id: Optional[str], file_path: str,
                   operation: str, diff: str = "", new_content: str = "") -> dict:
    cid = _new_id()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO proposed_changes
               (id, session_id, project_id, file_path, operation, diff, new_content)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cid, session_id, project_id, file_path, operation, diff, new_content),
        )
    return get_change(cid)


def get_change(change_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM proposed_changes WHERE id = ?", (change_id,)).fetchone()
        return dict(row) if row else None


def list_pending_changes(session_id: Optional[str] = None) -> list[dict]:
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM proposed_changes WHERE session_id = ? AND applied = 0 ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM proposed_changes WHERE applied = 0 ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def mark_change_applied(change_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE proposed_changes SET applied = 1, applied_at = ? WHERE id = ?",
            (_now_iso(), change_id),
        )
