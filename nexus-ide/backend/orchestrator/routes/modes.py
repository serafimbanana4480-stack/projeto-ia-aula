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

from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter()


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
    from backend.tools.registry import list_tools

    tools = list_tools(enabled_only=False)
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "enabled": t.enabled,
                "schema": t.schema,
            }
            for t in tools
        ]
    }


@router.post("/tools/{tool_name}/toggle")
async def toggle_tool(
    tool_name: str,
    enabled: bool,
    _user: dict = Depends(require_auth),
) -> dict:
    """Enable or disable a tool."""
    from backend.tools.registry import set_tool_enabled

    set_tool_enabled(tool_name, enabled)
    return {"tool": tool_name, "enabled": enabled}


# ---------------------------------------------------------------------------
# Database stats (read-only, no session/message creation here)
# ---------------------------------------------------------------------------


@router.get("/db/stats")
async def get_db_stats(_user: dict = Depends(require_auth)) -> dict:
    """Get database statistics: table row counts, message stats, recent sessions."""
    from backend.persistence.db import (
        count_pending_changes,
        get_db,
        get_message_statistics,
        list_sessions,
    )

    # Table row counts
    table_counts: dict[str, int] = {}
    with get_db() as conn:
        for table in (
            "users",
            "projects",
            "sessions",
            "messages",
            "tool_executions",
            "routing_decisions",
            "proposed_changes",
        ):
            try:
                row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
                table_counts[table] = int(row["cnt"]) if row else 0
            except Exception:
                table_counts[table] = 0

    # Message statistics
    msg_stats = get_message_statistics()

    # Recent sessions (last 10)
    recent = list_sessions(limit=10)

    # Pending changes
    pending = count_pending_changes()

    # Recent tool executions
    recent_tools: list[dict] = []
    with get_db() as conn:
        try:
            rows = conn.execute(
                "SELECT tool_name, success, duration_ms, created_at "
                "FROM tool_executions ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            recent_tools = [dict(r) for r in rows]
        except Exception:
            logger.debug("Failed to load recent tool executions", exc_info=True)

    # Recent routing decisions
    recent_routing: list[dict] = []
    with get_db() as conn:
        try:
            rows = conn.execute(
                "SELECT tier_chosen, reason, confidence, decision_ms, created_at "
                "FROM routing_decisions ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            recent_routing = [dict(r) for r in rows]
        except Exception:
            logger.debug("Failed to load recent routing decisions", exc_info=True)

    return {
        "table_counts": table_counts,
        "message_stats": msg_stats,
        "recent_sessions": recent,
        "pending_changes": pending,
        "recent_tool_executions": recent_tools,
        "recent_routing_decisions": recent_routing,
    }
