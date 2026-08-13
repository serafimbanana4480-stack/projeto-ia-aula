"""MCP Connector API — powers the /mcp Connection Wizard in the frontend.

Lets a user browse a catalog of well-known MCP servers (filesystem, GitHub,
Postgres, Slack, ...), fill in the handful of fields each one needs, test the
connection, and export a ready-to-use ``mcpServers`` JSON block — without
hand-writing config.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.mcp.store import mcp_store
from backend.mcp.templates import list_templates
from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mcp", tags=["mcp"])


class CreateConnectorRequest(BaseModel):
    name: str
    template_id: str
    params: dict[str, str] = {}
    env: dict[str, str] = {}


class UpdateConnectorRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    env: dict[str, str] | None = None


@router.get("/templates")
async def get_templates(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    """List the built-in MCP server templates (the wizard's gallery)."""
    return {"templates": list_templates()}


@router.get("/templates/{template_id}")
async def get_template_detail(template_id: str, _user: dict = Depends(require_auth)) -> dict[str, Any]:
    from backend.mcp.templates import get_template

    template = get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.get("/connectors")
async def list_connectors(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    return {"connectors": mcp_store.list_connectors(), "summary": mcp_store.health()}


@router.get("/overview")
async def get_overview(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    """Return the operational view used by the MCP Control Center.

    Activity is intentionally sourced from persisted connector tests. When no
    MCP calls have been observed, the response stays empty instead of showing
    decorative/sample traffic.
    """
    connectors = mcp_store.list_connectors()
    activity = []
    for connector in connectors:
        tested_at = connector.get("last_tested_at")
        activity_at = connector.get("last_activity_at") or tested_at
        if activity_at:
            activity.append(
                {
                    "at": activity_at,
                    "connector_id": connector["id"],
                    "connector": connector["name"],
                    "tool": connector.get("last_activity_tool") or "health_check",
                    "kind": "tool_call" if connector.get("last_activity_tool") else "health_check",
                    "status": connector.get("last_test_status", "untested"),
                    "latency_ms": connector.get("latency_ms"),
                    "detail": connector.get("last_test_detail", ""),
                }
            )
    activity.sort(key=lambda item: item["at"], reverse=True)
    return {
        "connectors": connectors,
        "summary": mcp_store.health(),
        "activity": activity[:30],
        "generated_at": time.time(),
        "data_source": "NEXUS connector store + local ProjectMind source inspection",
    }


@router.post("/connectors")
async def create_connector(
    req: CreateConnectorRequest,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    try:
        connector = mcp_store.create_connector(
            name=req.name,
            template_id=req.template_id,
            params=req.params,
            env_values=req.env,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return connector.to_public_dict()


@router.get("/connectors/{connector_id}")
async def get_connector(connector_id: str, _user: dict = Depends(require_auth)) -> dict[str, Any]:
    connector = mcp_store.get_connector(connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    return connector.to_public_dict()


@router.put("/connectors/{connector_id}")
async def update_connector(
    connector_id: str,
    req: UpdateConnectorRequest,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    # Merge env instead of overwriting so a partial update doesn't wipe keys.
    if "env" in updates:
        connector = mcp_store.get_connector(connector_id)
        if connector:
            merged = {**connector.env, **updates["env"]}
            updates["env"] = merged
    connector = mcp_store.update_connector(connector_id, **updates)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    return connector.to_public_dict()


@router.delete("/connectors/{connector_id}")
async def delete_connector(connector_id: str, _user: dict = Depends(require_auth)) -> dict[str, Any]:
    ok = mcp_store.delete_connector(connector_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Connector not found")
    return {"status": "deleted", "id": connector_id}


@router.post("/connectors/{connector_id}/test")
async def test_connector(connector_id: str, _user: dict = Depends(require_auth)) -> dict[str, Any]:
    connector = mcp_store.get_connector(connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    result = await mcp_store.test_connector(connector_id)
    return result


@router.get("/connectors/{connector_id}/export")
async def export_connector(connector_id: str, _user: dict = Depends(require_auth)) -> dict[str, Any]:
    exported = mcp_store.export_connector(connector_id)
    if exported is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    return exported


@router.get("/export")
async def export_all(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    """Export every enabled connector as one `mcpServers` JSON block."""
    return mcp_store.export_all()
