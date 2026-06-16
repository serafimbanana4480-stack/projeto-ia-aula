"""Cognitive modes endpoint - manage AI thinking modes (Auto, Coder, Analyst, etc.).

Also includes settings and session management endpoints.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.config.settings import get_settings
from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter()

SETTINGS_PATH = Path("data/settings.json")


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
# Settings endpoints
# ---------------------------------------------------------------------------


class SettingsUpdate(BaseModel):
    local_llm_device: str | None = None
    backend_host: str | None = None
    default_mode: str | None = None
    default_model: str | None = None
    enable_telemetry: bool | None = None
    llm_provider: str | None = None
    openai_api_key: str | None = None
    deepseek_api_key: str | None = None
    kimi_api_key: str | None = None
    groq_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None


def _load_settings() -> dict:
    """Load settings from JSON file, falling back to config defaults."""
    defaults = {
        "local_llm_device": get_settings().local_llm_device,
        "backend_host": f"http://localhost:{get_settings().backend_port}",
        "default_mode": "auto",
        "default_model": "coder",
        "enable_telemetry": True,
        "llm_provider": get_settings().llm_provider,
        "openai_api_key": "",
        "deepseek_api_key": "",
        "kimi_api_key": "",
        "groq_api_key": "",
        "anthropic_api_key": "",
        "gemini_api_key": "",
        "openrouter_api_key": "",
    }
    if SETTINGS_PATH.exists():
        try:
            with SETTINGS_PATH.open("r", encoding="utf-8") as f:
                saved = json.load(f)
            defaults.update(saved)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load settings file: %s", e)
    return defaults


def _save_settings(settings: dict) -> None:
    """Persist settings to JSON file."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SETTINGS_PATH.open("w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


@router.get("/settings")
async def get_app_settings(_user: dict = Depends(require_auth)) -> dict:
    """Get current application settings."""
    return _load_settings()


@router.put("/settings")
async def update_app_settings(
    update: SettingsUpdate,
    _user: dict = Depends(require_auth),
) -> dict:
    """Update application settings."""
    current = _load_settings()
    updates = update.model_dump(exclude_none=True)
    current.update(updates)
    _save_settings(current)
    return current


# ---------------------------------------------------------------------------
# Session endpoints
# ---------------------------------------------------------------------------


@router.post("/sessions")
async def create_session(
    title: str = "Nova sessão",
    mode: str = "auto",
    _user: dict = Depends(require_auth),
) -> dict:
    """Create a new chat session."""
    from backend.persistence.db import create_session as db_create_session

    session = db_create_session(title=title[:60], mode=mode)
    return session


@router.get("/sessions")
async def list_sessions(_user: dict = Depends(require_auth)) -> list[dict]:
    """List all chat sessions."""
    from backend.persistence.db import list_sessions as db_list_sessions

    return db_list_sessions()


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
