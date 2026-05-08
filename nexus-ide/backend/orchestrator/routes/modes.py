"""Cognitive modes endpoint - manage AI thinking modes (Auto, Coder, Analyst, etc.)."""
from __future__ import annotations

import yaml
from fastapi import APIRouter, HTTPException

router = APIRouter()


def _load_modes() -> dict:
    try:
        with open("config/modes.yaml") as f:
            return yaml.safe_load(f)
    except Exception:
        return {"modes": {}}


@router.get("/modes")
async def list_modes() -> dict:
    """List all available cognitive modes."""
    config = _load_modes()
    return {"modes": config.get("modes", {})}


@router.get("/modes/{mode_name}")
async def get_mode(mode_name: str) -> dict:
    """Get details of a specific mode."""
    config = _load_modes()
    modes = config.get("modes", {})
    if mode_name not in modes:
        raise HTTPException(status_code=404, detail=f"Mode {mode_name} not found")
    return {"mode": mode_name, **modes[mode_name]}


@router.get("/tools")
async def list_tools() -> dict:
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
async def toggle_tool(tool_name: str, enabled: bool) -> dict:
    """Enable or disable a tool."""
    from backend.tools.registry import set_tool_enabled
    set_tool_enabled(tool_name, enabled)
    return {"tool": tool_name, "enabled": enabled}
