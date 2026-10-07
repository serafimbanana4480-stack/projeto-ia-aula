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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.mcp.store import mcp_store
from backend.mcp.templates import list_templates
from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mcp", tags=["mcp"])


class CreateConnectorRequest(BaseModel):
    name: str
    template_id: str
    params: dict[str, str] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)


class UpdateConnectorRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    env: dict[str, str] | None = None
    approved_readonly_tools: list[str] | None = None
    approved_readonly_tools: list[str] | None = None


class MCPBuildRequest(BaseModel):
    description: str = Field(min_length=8, max_length=4_000)
    base_url: str = Field(min_length=8, max_length=500)
    auth_secret: str | None = Field(default=None, max_length=4_096)


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
async def get_overview(
    limit: int = 100,
    connector_id: str = "",
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Return the operational view used by the MCP Control Center.

    Activity is sourced from append-only MCP lifecycle and tool-call events.
    The endpoint never synthesizes health traffic when the runtime is idle.
    """
    connectors = mcp_store.list_connectors()
    activity = mcp_store.list_activity(limit=limit, connector_id=connector_id)
    return {
        "connectors": connectors,
        "summary": mcp_store.health(),
        "activity": activity[:30],
        "generated_at": time.time(),
        "data_source": "NEXUS connector store + MCP handshake/tool-call observations",
    }


@router.post("/builder/build")
async def build_mcp(
    req: MCPBuildRequest,
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Generate, validate, and register a declarative REST MCP."""
    from backend.mcp.builder import MCPBuilderError, build_from_description

    try:
        llm_client = getattr(request.app.state, "llm_client", None)
        return await build_from_description(
            description=req.description,
            base_url=req.base_url,
            llm_client=llm_client,
            auth_secret=req.auth_secret,
            activity_source="control_center",
        )
    except MCPBuilderError as exc:
        status_code = {
            "provider_unavailable": 503,
            "generation_failed": 502,
            "needs_configuration": 409,
        }.get(exc.category, 422)
        raise HTTPException(
            status_code=status_code,
            detail={"category": exc.category, "message": str(exc)},
        ) from exc


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
    readonly_permissions = updates.pop("approved_readonly_tools", None)
    if readonly_permissions is not None:
        try:
            mcp_store.set_approved_readonly_tools(connector_id, readonly_permissions)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    readonly_permissions = updates.pop("approved_readonly_tools", None)
    if readonly_permissions is not None:
        try:
            mcp_store.set_approved_readonly_tools(connector_id, readonly_permissions)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
