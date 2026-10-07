"""Cognitive modes endpoint - manage AI thinking modes (Auto, Coder, Analyst, etc.).

Also includes database statistics (read-only) and a tool toggle.

NOTE: ``/api/settings`` and ``/api/sessions`` live in their own modules
(``backend.orchestrator.routes.settings`` and ``...sessions``). This
file intentionally does NOT register duplicates — those would shadow
the canonical endpoints and silently drop the JSON body.
"""

from __future__ import annotations

import logging

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter()


class ToolExecuteRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=128)
    args: dict = Field(default_factory=dict)
    session_id: str = Field(min_length=1, max_length=128)
    confirmation_id: str | None = Field(default=None, min_length=1, max_length=128)


class ToolConfirmationRequest(BaseModel):
    confirmation_id: str = Field(min_length=1, max_length=128)
    approved: bool


def _load_modes() -> dict:
    try:
        from backend.config.settings import MODES_YAML

        with MODES_YAML.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"modes": {}}
    except Exception:
        return {"modes": {}}


@router.get("/modes")
async def list_modes(_user: dict = Depends(require_auth)) -> dict:
    """List all available cognitive modes."""
    config = _load_modes()
    return {"modes": config.get("modes", {})}


@router.get("/modes/{mode_name}")
async def get_mode(mode_name: str, _user: dict = Depends(require_auth)) -> dict:
    """Get details of a specific mode."""
    config = _load_modes()
    modes = config.get("modes", {})
    if mode_name not in modes:
        raise HTTPException(status_code=404, detail=f"Mode {mode_name} not found")
    return {"mode": mode_name, **modes[mode_name]}


@router.get("/tools")
async def list_tools(_user: dict = Depends(require_auth)) -> dict:
    """List all available tools and their status."""
    from backend.tools.registry import get_tool_catalog

    return {"tools": get_tool_catalog()}


@router.post("/tools/{tool_name}/toggle")
async def toggle_tool(
    tool_name: str,
    enabled: bool,
    _user: dict = Depends(require_auth),
) -> dict:
    """Enable or disable a tool."""
    from backend.tools.registry import get_tool, set_tool_enabled

    if get_tool(tool_name) is None:
        raise HTTPException(status_code=404, detail=f"Tool {tool_name} is not registered")
    set_tool_enabled(tool_name, enabled)
    return {"tool": tool_name, "enabled": enabled}


@router.post("/tools/execute")
async def execute_tool_endpoint(
    req: ToolExecuteRequest, _user: dict = Depends(require_auth)
) -> dict:
    """Execute one tool for a retry action from the UI."""
    from backend.persistence.db import session_belongs_to_user
    from backend.tools.registry import execute_tool

    user_id = str(_user.get("user_id") or "").strip()
    if not user_id or not session_belongs_to_user(req.session_id, user_id):
        raise HTTPException(status_code=404, detail="Session not found")

    approved_retry = False
    if req.confirmation_id:
        from backend.tools.confirmations import consume_approved_retry_confirmation

        approved_retry = consume_approved_retry_confirmation(
            req.confirmation_id,
            user_id=user_id,
            session_id=req.session_id,
            tool_name=req.tool_name,
            args=req.args,
        )
        if not approved_retry:
            raise HTTPException(status_code=409, detail="Confirmation is invalid, expired, or already used")

    return await execute_tool(
        req.tool_name,
        req.session_id,
        req.args,
        confirmed=approved_retry,
        enforce_confirmation=True,
        retry_confirmation=True,
        confirmation_user_id=user_id,
    )


@router.post("/tools/confirm")
async def confirm_tool_endpoint(
    req: ToolConfirmationRequest, _user: dict = Depends(require_auth)
) -> dict:
    """Resolve a tool confirmation gate currently holding an agent stream."""
    from backend.persistence.db import session_belongs_to_user
    from backend.tools.confirmations import get_pending_confirmation, resolve_confirmation

    user_id = str(_user.get("user_id") or "").strip()
    pending = get_pending_confirmation(req.confirmation_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="Confirmation expired or not found")
    if pending.retry_enabled:
        if not user_id or pending.user_id != user_id:
            raise HTTPException(status_code=404, detail="Confirmation expired or not found")
    elif not user_id or not session_belongs_to_user(pending.session_id, user_id):
        raise HTTPException(status_code=404, detail="Confirmation expired or not found")

    resolved = await resolve_confirmation(req.confirmation_id, req.approved)
    if not resolved:
        raise HTTPException(status_code=404, detail="Confirmation expired or not found")
    return {"confirmation_id": req.confirmation_id, "approved": req.approved}


# ---------------------------------------------------------------------------
# Database stats (read-only, no session/message creation here)
# ---------------------------------------------------------------------------

#: Columns of ``recent_sessions`` this endpoint may return.  ``user_id`` (the
#: owner column) and ``context_json`` (the raw session payload) are deliberately
#: absent: a stats view needs presentation fields, never tenant metadata.
_PUBLIC_SESSION_FIELDS: tuple[str, ...] = (
    "id",
    "project_id",
    "title",
    "mode",
    "started_at",
    "last_active_at",
    "message_count",
    "status",
)

#: Shape of ``message_stats``, identical to ``db.get_message_statistics`` so the
#: frontend contract is unchanged.
_EMPTY_MESSAGE_STATS: dict[str, object] = {
    "total_messages": 0,
    "sessions_with_messages": 0,
    "user_messages": 0,
    "assistant_messages": 0,
    "tokens_in_total": 0,
    "tokens_out_total": 0,
    "cost_usd_total": 0.0,
    "avg_latency_ms": 0.0,
    "last_message_at": "",
}

_MESSAGE_STATS_SQL = """
    SELECT
        COUNT(*) AS total_messages,
        COUNT(DISTINCT m.session_id) AS sessions_with_messages,
        COALESCE(SUM(CASE WHEN m.role = 'user' THEN 1 ELSE 0 END), 0) AS user_messages,
        COALESCE(SUM(CASE WHEN m.role = 'assistant' THEN 1 ELSE 0 END), 0) AS assistant_messages,
        COALESCE(SUM(m.tokens_in), 0) AS tokens_in_total,
        COALESCE(SUM(m.tokens_out), 0) AS tokens_out_total,
        COALESCE(SUM(m.cost_usd), 0.0) AS cost_usd_total,
        COALESCE(AVG(NULLIF(m.latency_ms, 0)), 0) AS avg_latency_ms,
        COALESCE(MAX(m.created_at), '') AS last_message_at
    FROM messages m
    JOIN sessions s ON s.id = m.session_id
    WHERE s.user_id = ?
"""


#: Per-table ``COUNT(*)`` restricted to one tenant, keyed by table name. Every
#: statement here is answerable from ``sessions.user_id``: ``sessions`` owns the
#: column and the rest are reachable from it through ``session_id``. Only tables
#: listed here may report a number.
_SCOPED_TABLE_COUNTS: dict[str, str] = {
    "sessions": "SELECT COUNT(*) AS cnt FROM sessions WHERE user_id = ?",
    "messages": (
        "SELECT COUNT(*) AS cnt FROM messages m "
        "JOIN sessions s ON s.id = m.session_id WHERE s.user_id = ?"
    ),
    "tool_executions": (
        "SELECT COUNT(*) AS cnt FROM tool_executions te "
        "JOIN sessions s ON s.id = te.session_id WHERE s.user_id = ?"
    ),
    "routing_decisions": (
        "SELECT COUNT(*) AS cnt FROM routing_decisions rd "
        "JOIN sessions s ON s.id = rd.session_id WHERE s.user_id = ?"
    ),
    "proposed_changes": (
        "SELECT COUNT(*) AS cnt FROM proposed_changes pc "
        "JOIN sessions s ON s.id = pc.session_id WHERE s.user_id = ?"
    ),
}

#: Tables with no owner column. ``users`` and ``projects`` are keyed by their own
#: id/path and nothing references a tenant, so no predicate can restrict either
#: to one caller — a global count there is a tenant census (``users`` in
#: particular) and is reported as ``None`` instead. The keys stay in the
#: response because ``frontend/app/database/page.tsx`` renders all seven.
_UNSCOPABLE_TABLES: tuple[str, ...] = ("users", "projects")

#: Response order of ``table_counts``, unchanged for the frontend.
_STATS_TABLES: tuple[str, ...] = _UNSCOPABLE_TABLES + tuple(_SCOPED_TABLE_COUNTS)

#: Recent tool executions of the caller's own sessions. ``db.py`` has no
#: ``user_id``-aware reader for this table, so the join is spelled out here
#: rather than by editing the persistence layer. An inner join also drops rows
#: whose ``session_id`` is NULL or orphaned: they belong to nobody, so they
#: cannot be shown to anybody.
_RECENT_TOOL_EXECUTIONS_SQL = """
    SELECT te.tool_name, te.success, te.duration_ms, te.created_at
    FROM tool_executions te
    JOIN sessions s ON s.id = te.session_id
    WHERE s.user_id = ?
    ORDER BY te.created_at DESC
    LIMIT 20
"""

#: Recent routing decisions of the caller's own sessions, scoped as above.
_RECENT_ROUTING_DECISIONS_SQL = """
    SELECT rd.tier_chosen, rd.reason, rd.confidence, rd.decision_ms, rd.created_at
    FROM routing_decisions rd
    JOIN sessions s ON s.id = rd.session_id
    WHERE s.user_id = ?
    ORDER BY rd.created_at DESC
    LIMIT 20
"""

#: Unapplied proposed changes of the caller's own sessions. The shared
#: ``count_pending_changes()`` takes a ``session_id`` or nothing, so calling it
#: bare counted every tenant's queue.
_PENDING_CHANGES_SQL = """
    SELECT COUNT(*) AS cnt
    FROM proposed_changes pc
    JOIN sessions s ON s.id = pc.session_id
    WHERE s.user_id = ? AND pc.applied = 0
"""


def _public_session_row(row: dict) -> dict:
    """Project a session row onto the fields this endpoint is allowed to return."""
    return {field: row.get(field) for field in _PUBLIC_SESSION_FIELDS}


def _scoped_count(sql: str, user_id: str, what: str) -> int:
    """Run an owner-scoped single-row ``COUNT(*)``; ``0`` when the query fails."""
    from backend.persistence.db import get_db

    try:
        with get_db() as conn:
            row = conn.execute(sql, (user_id,)).fetchone()
    except Exception:
        logger.warning("Failed to count %s", what, exc_info=True)
        return 0
    return int(row["cnt"]) if row else 0


def _scoped_rows(sql: str, user_id: str, what: str) -> list[dict]:
    """Run an owner-scoped row query; ``[]`` when the query fails."""
    from backend.persistence.db import get_db

    try:
        with get_db() as conn:
            rows = conn.execute(sql, (user_id,)).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        logger.debug("Failed to load %s", what, exc_info=True)
        return []


def _scoped_message_statistics(user_id: str) -> dict:
    """Message statistics for the caller's own sessions.

    ``backend.persistence.db.get_message_statistics()`` (db.py:1535) takes no
    arguments and aggregates ``messages`` over the whole table, so it cannot
    answer a per-tenant question: returning it here disclosed every tenant's
    volume, token spend and cost.  The same aggregate is recomputed below over
    ``sessions.user_id``, which keeps the numbers honest and the response shape
    identical.  A ``user_id``-aware variant in ``db.py`` should replace this.
    """
    from backend.persistence.db import get_db

    try:
        with get_db() as conn:
            row = conn.execute(_MESSAGE_STATS_SQL, (user_id,)).fetchone()
    except Exception:
        logger.warning("Failed to load message statistics", exc_info=True)
        return dict(_EMPTY_MESSAGE_STATS)
    if not row:
        return dict(_EMPTY_MESSAGE_STATS)
    stats = dict(row)
    return {
        "total_messages": int(stats["total_messages"] or 0),
        "sessions_with_messages": int(stats["sessions_with_messages"] or 0),
        "user_messages": int(stats["user_messages"] or 0),
        "assistant_messages": int(stats["assistant_messages"] or 0),
        "tokens_in_total": int(stats["tokens_in_total"] or 0),
        "tokens_out_total": int(stats["tokens_out_total"] or 0),
        "cost_usd_total": float(stats["cost_usd_total"] or 0.0),
        "avg_latency_ms": float(stats["avg_latency_ms"] or 0.0),
        "last_message_at": stats["last_message_at"] or "",
    }


@router.get("/db/stats")
async def get_db_stats(_user: dict = Depends(require_auth)) -> dict:
    """Get database statistics for the authenticated user.

    Scoped to the caller, through ``sessions.user_id``: ``recent_sessions``,
    ``message_stats``, ``recent_tool_executions``, ``recent_routing_decisions``,
    ``pending_changes`` and the ``sessions``, ``messages``,
    ``tool_executions``, ``routing_decisions`` and ``proposed_changes`` entries
    of ``table_counts``.

    NOT scoped: ``table_counts["users"]`` and ``table_counts["projects"]`` are
    reported as ``None``. Neither table has an owner column, so no predicate can
    restrict it to one tenant and a global count would disclose how many tenants
    share this instance. Their keys remain in the response because the database
    page renders all seven tables.
    """
    from backend.persistence.db import get_db, list_sessions_with_counts

    # Every count and row below belongs to the caller.  ``list_sessions`` only
    # filters by owner when ``user_id`` is passed (db.py:841), so an unscoped
    # call returned other tenants' sessions verbatim - including their
    # ``user_id`` and ``context_json``.
    user_id = str(_user.get("user_id") or "").strip()

    # Table row counts.  Counting every row of every table answered a question
    # nobody asked and leaked three things: the size of the instance
    # (``users``), and the volume of work done for other tenants
    # (``sessions``, ``messages``, ``proposed_changes``).
    table_counts: dict[str, int | None] = {}
    with get_db() as conn:
        for table in _STATS_TABLES:
            sql = _SCOPED_TABLE_COUNTS.get(table)
            if sql is None:
                # Unscopable table: report "unknown", never a global count.
                table_counts[table] = None
                continue
            try:
                row = conn.execute(sql, (user_id,)).fetchone()
                table_counts[table] = int(row["cnt"]) if row else 0
            except Exception:
                logger.debug("Failed to count %s", table, exc_info=True)
                table_counts[table] = None

    # Message statistics (caller's sessions only)
    msg_stats = _scoped_message_statistics(user_id)

    # Recent sessions (last 10, caller's own)
    recent = [
        _public_session_row(row)
        for row in list_sessions_with_counts(limit=10, user_id=user_id)
    ]

    # Pending changes (caller's sessions only)
    pending = _scoped_count(_PENDING_CHANGES_SQL, user_id, "pending changes")

    # Recent tool executions (caller's sessions only)
    recent_tools = _scoped_rows(
        _RECENT_TOOL_EXECUTIONS_SQL, user_id, "recent tool executions"
    )

    # Recent routing decisions (caller's sessions only)
    recent_routing = _scoped_rows(
        _RECENT_ROUTING_DECISIONS_SQL, user_id, "recent routing decisions"
    )

    return {
        "table_counts": table_counts,
        "message_stats": msg_stats,
        "recent_sessions": recent,
        "pending_changes": pending,
        "recent_tool_executions": recent_tools,
        "recent_routing_decisions": recent_routing,
    }
