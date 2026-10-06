"""API routes for agent topology visualization."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.orchestrator.agent_topology import AgentTopology

router = APIRouter(prefix="/api/topology", tags=["topology"])

_topology: AgentTopology | None = None


def set_topology(topology: AgentTopology) -> None:
    global _topology
    _topology = topology


@router.get("/graph")
async def get_graph() -> dict[str, Any]:
    if _topology is None:
        raise HTTPException(status_code=503, detail="Topology not available")
    return _topology.to_dict()


@router.get("/hierarchy/{root_id}")
async def get_hierarchy(root_id: str) -> dict[str, Any]:
    if _topology is None:
        raise HTTPException(status_code=503, detail="Topology not available")
    return _topology.get_hierarchy(root_id)


@router.get("/stats")
async def get_stats() -> dict[str, Any]:
    if _topology is None:
        raise HTTPException(status_code=503, detail="Topology not available")
    return _topology.stats()
