"""Agent State routes — inspect and manage persistent agent brains.

Endpoints:
- ``GET  /agent-states``                 list all agents with memory counts
- ``GET  /agent-states/{agent_name}``    full brain dump for an agent
- ``POST /agent-states/recall``          semantic search across an agent's memory
- ``DELETE /agent-states/{agent_name}``  clear memories for an agent
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.core.agent_state import AgentStateStore
from backend.middleware.auth import require_auth
from backend.middleware.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/agent-states")
@limiter.limit("100/minute")
async def list_agent_states(
    request: Request, auth_user: None = Depends(require_auth)
) -> dict[str, list[dict[str, Any]]]:
    """Return a summary of every agent that has persisted memories."""
    AgentStateStore()
    # We don't have a direct "list agents" query, so we scan the DB.
    from backend.persistence.db import get_db

    with get_db() as conn:
        rows = conn.execute(
            """SELECT agent_name,
                      COUNT(*) AS total_memories,
                      SUM(CASE WHEN memory_tier = 'short_term' THEN 1 ELSE 0 END) AS short_term,
                      SUM(CASE WHEN memory_tier = 'medium_term' THEN 1 ELSE 0 END) AS medium_term,
                      SUM(CASE WHEN memory_tier = 'long_term' THEN 1 ELSE 0 END) AS long_term
               FROM agent_states
               GROUP BY agent_name
               ORDER BY agent_name"""
        ).fetchall()

    agents = []
    for row in rows:
        agents.append(
            {
                "agent_name": row["agent_name"],
                "total_memories": row["total_memories"],
                "short_term": row["short_term"],
                "medium_term": row["medium_term"],
                "long_term": row["long_term"],
            }
        )

    return {"agents": agents}


@router.get("/agent-states/{agent_name}")
@limiter.limit("100/minute")
async def get_agent_brain(
    agent_name: str, request: Request, auth_user: None = Depends(require_auth)
) -> dict[str, Any]:
    """Return the complete brain (all memory tiers) for a single agent."""
    store = AgentStateStore()
    brain = store.get_agent_brain(agent_name)

    if not brain.short_term and not brain.medium_term and not brain.long_term:
        raise HTTPException(status_code=404, detail=f"No memories found for agent '{agent_name}'")

    return {
        "agent_name": brain.agent_name,
        "short_term": [m.model_dump(mode="json") for m in brain.short_term],
        "medium_term": [m.model_dump(mode="json") for m in brain.medium_term],
        "long_term": [m.model_dump(mode="json") for m in brain.long_term],
        "total": len(brain.short_term) + len(brain.medium_term) + len(brain.long_term),
    }


@router.post("/agent-states/recall")
@limiter.limit("60/minute")
async def recall_memories(
    request: Request,
    agent_name: str,
    query: str = Query(..., min_length=1, max_length=500),
    tier: str | None = Query(None),
    project_path: str | None = Query(None),
    limit: int = Query(10, ge=1, le=100),
    auth_user: None = Depends(require_auth),
) -> dict[str, Any]:
    """Search an agent's memory using simple text matching."""
    store = AgentStateStore()

    resolved_tier: Any = tier
    if tier is not None and tier not in ("short_term", "medium_term", "long_term"):
        raise HTTPException(
            status_code=400,
            detail="tier must be one of: short_term, medium_term, long_term",
        )

    try:
        results = store.recall(
            agent_name=agent_name,
            query=query,
            tier=resolved_tier,
            project_path=project_path,
            limit=limit,
        )
    except Exception as exc:
        logger.error("Recall failed for %s: %s", agent_name, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "agent_name": agent_name,
        "query": query,
        "tier": tier,
        "count": len(results),
        "memories": [m.model_dump(mode="json") for m in results],
    }


@router.delete("/agent-states/{agent_name}")
@limiter.limit("30/minute")
async def clear_agent_brain(
    request: Request,
    agent_name: str,
    tier: str | None = Query(None),
    session_id: str | None = Query(None),
    project_path: str | None = Query(None),
    auth_user: None = Depends(require_auth),
) -> dict[str, Any]:
    """Delete memories for an agent.

    If ``tier`` is provided, only that tier is cleared.
    ``session_id`` and ``project_path`` act as additional filters.
    """
    store = AgentStateStore()

    if tier is not None and tier not in ("short_term", "medium_term", "long_term"):
        raise HTTPException(
            status_code=400,
            detail="tier must be one of: short_term, medium_term, long_term",
        )

    try:
        if tier:
            deleted = store.clear_tier(
                agent_name=agent_name,
                tier=tier,  # type: ignore[arg-type]
                session_id=session_id,
                project_path=project_path,
            )
        else:
            # Clear all tiers — call clear_tier for each
            deleted = 0
            for t in ("short_term", "medium_term", "long_term"):
                deleted += store.clear_tier(
                    agent_name=agent_name,
                    tier=t,  # type: ignore[arg-type]
                    session_id=session_id,
                    project_path=project_path,
                )
    except Exception as exc:
        logger.error("Failed to clear brain for %s: %s", agent_name, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"deleted": deleted, "agent_name": agent_name}
