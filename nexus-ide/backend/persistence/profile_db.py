"""Persistent user profile, routines, and memory storage."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.persistence.db import get_db, _new_id, _now_iso

logger = logging.getLogger(__name__)


def _load_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _dump_json(value: Any) -> str:
    return json.dumps(value, default=str)


def ensure_user_profile(user_id: str) -> dict:
    """Return the user profile, creating a default row if absent."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row:
            return _hydrate_profile(row)
        conn.execute(
            """INSERT INTO user_profiles (
                user_id, preferences_json, routines_json,
                favorite_projects_json, learned_facts_json, evolution_summary
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, "{}", "[]", "[]", "[]", ""),
        )
        row = conn.execute(
            "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
    return _hydrate_profile(row)


def _hydrate_profile(row: Any) -> dict:
    d = dict(row)
    d["preferences"] = _load_json(d.pop("preferences_json", None), {})
    d["routines"] = _load_json(d.pop("routines_json", None), [])
    d["favorite_projects"] = _load_json(d.pop("favorite_projects_json", None), [])
    d["learned_facts"] = _load_json(d.pop("learned_facts_json", None), [])
    return d


def get_user_profile(user_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return None
        return _hydrate_profile(row)


def update_user_profile(user_id: str, **fields: Any) -> dict | None:
    if not fields:
        return get_user_profile(user_id)
    allowed = {
        "preferences_json",
        "routines_json",
        "favorite_projects_json",
        "learned_facts_json",
        "evolution_summary",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_user_profile(user_id)
    updates["updated_at"] = _now_iso()
    cols = ", ".join(f"{k} = ?" for k in updates)
    with get_db() as conn:
        conn.execute(
            f"UPDATE user_profiles SET {cols} WHERE user_id = ?",
            (*updates.values(), user_id),
        )
    return get_user_profile(user_id)


def update_preferences(user_id: str, preferences: dict) -> dict | None:
    ensure_user_profile(user_id)
    return update_user_profile(user_id, preferences_json=_dump_json(preferences))


def add_learned_fact(user_id: str, fact: str) -> dict | None:
    ensure_user_profile(user_id)
    profile = get_user_profile(user_id)
    facts = profile.get("learned_facts", []) if profile else []
    facts.append({"fact": fact, "learned_at": _now_iso()})
    return update_user_profile(user_id, learned_facts_json=_dump_json(facts))


def set_evolution_summary(user_id: str, summary: str) -> dict | None:
    ensure_user_profile(user_id)
    return update_user_profile(user_id, evolution_summary=summary)


def evolve_profile(user_id: str, session_summary: str) -> dict | None:
    """Append a session insight to the evolution_summary."""
    ensure_user_profile(user_id)
    profile = get_user_profile(user_id)
    current = (profile.get("evolution_summary") or "") if profile else ""
    insight = f"[{_now_iso()}] {session_summary}"
    new_summary = f"{current}\n{insight}".strip() if current else insight
    return update_user_profile(user_id, evolution_summary=new_summary)


# ───── ROUTINES ─────────────────────────────────────────────────────────


def create_routine(
    user_id: str,
    name: str,
    description: str = "",
    schedule_cron: str = "",
) -> dict:
    rid = _new_id()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO user_routines (
                id, user_id, name, description, schedule_cron
            ) VALUES (?, ?, ?, ?, ?)""",
            (rid, user_id, name, description, schedule_cron),
        )
    return get_routine(rid)


def get_routine(routine_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM user_routines WHERE id = ?", (routine_id,)
        ).fetchone()
        return dict(row) if row else None


def get_routines(user_id: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM user_routines WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def record_routine_execution(routine_id: str, success: bool = True) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT execution_count, success_count FROM user_routines WHERE id = ?",
            (routine_id,),
        ).fetchone()
        if not row:
            return None
        new_count = (row["execution_count"] or 0) + 1
        new_success = (row["success_count"] or 0) + (1 if success else 0)
        conn.execute(
            """UPDATE user_routines
               SET last_executed = ?, execution_count = ?, success_count = ?
               WHERE id = ?""",
            (_now_iso(), new_count, new_success, routine_id),
        )
    return get_routine(routine_id)


# ───── MEMORIES ─────────────────────────────────────────────────────────


def create_memory(
    user_id: str,
    content: str,
    memory_type: str = "fact",
    importance: float = 0.5,
) -> dict:
    mid = _new_id()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO user_memories (
                id, user_id, content, memory_type, importance
            ) VALUES (?, ?, ?, ?, ?)""",
            (mid, user_id, content, memory_type, importance),
        )
    return get_memory(mid)


def get_memory(memory_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM user_memories WHERE id = ?", (memory_id,)
        ).fetchone()
        return dict(row) if row else None


def get_memories(user_id: str, memory_type: str | None = None, limit: int = 50) -> list[dict]:
    with get_db() as conn:
        if memory_type:
            rows = conn.execute(
                """SELECT * FROM user_memories
                   WHERE user_id = ? AND memory_type = ?
                   ORDER BY importance DESC, created_at DESC
                   LIMIT ?""",
                (user_id, memory_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM user_memories
                   WHERE user_id = ?
                   ORDER BY importance DESC, created_at DESC
                   LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]


def search_memories(user_id: str, query: str, limit: int = 10) -> list[dict]:
    terms = [t.strip() for t in query.lower().split() if t.strip()]
    if not terms:
        return get_memories(user_id, limit=limit)

    conditions = []
    for _ in terms:
        conditions.append(
            "CASE WHEN LOWER(content) LIKE '%' || ? || '%' THEN 1 ELSE 0 END"
        )
    score_expr = " + ".join(conditions)

    sql = f"""
        SELECT * FROM (
            SELECT *, ({score_expr}) AS score
            FROM user_memories
            WHERE user_id = ?
        ) WHERE score > 0
        ORDER BY score DESC, importance DESC, created_at DESC
        LIMIT ?
    """
    params = [*terms, user_id, limit]
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def increment_memory_access(memory_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            """UPDATE user_memories
               SET access_count = COALESCE(access_count, 0) + 1
               WHERE id = ?""",
            (memory_id,),
        )
