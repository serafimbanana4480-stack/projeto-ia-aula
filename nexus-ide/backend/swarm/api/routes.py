"""SWARM API — FastAPI routes mounted under ``/api/swarm``.

Provides
--------
- ``POST /api/swarm/run``                  — start a SWARM run
- ``GET  /api/swarm/runs/{id}``            — retrieve a past run
- ``GET  /api/swarm/modes``                — list operational modes
- ``GET  /api/swarm/agents``               — list SWARM agent definitions
- ``GET  /api/swarm/health``               — liveness
- ``GET  /api/swarm/dashboard``            — aggregated metrics for the dashboard
- ``POST /api/swarm/rag/index``            — index a directory into the RAG
- ``POST /api/swarm/rag/search``           — hybrid search
- ``GET  /api/swarm/skills``               — list all skills (built-in + YAML)
- ``GET  /api/swarm/skills/{id}``          — inspect a single skill
- ``POST /api/swarm/skills/{id}/run``      — run a skill with provided variables
- ``GET  /api/swarm/workflows``            — list YAML-loaded workflows

Runs are kept in an in-memory store keyed by run_id. In a multi-worker
deployment swap this for Redis or the existing SQLite store.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.config.settings import resolve_project_path
from backend.middleware.auth import require_auth
from backend.swarm.core.orchestrator import SwarmOrchestrator, SwarmRunRequest
from backend.swarm.core.types import (
    AgentRole,
    OperationalMode,
    SwarmStrategy,
)
from backend.swarm.modes.mode_registry import to_dict as modes_to_dict
from backend.swarm.rag.retriever import get_retriever, index_directory
from backend.swarm.skills.skills import get_skill
from backend.swarm.skills.workflow_loader import merged_catalogue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/swarm", tags=["swarm"])

# ---------------------------------------------------------------------------
# In-memory run store (replace with persistent store if needed)
# ---------------------------------------------------------------------------

_MAX_RUNS = 100
_runs: deque[dict[str, Any]] = deque(maxlen=_MAX_RUNS)
_runs_by_id: dict[str, dict[str, Any]] = {}


def _save_run(result_dict: dict[str, Any]) -> None:
    _runs.append(result_dict)
    _runs_by_id[result_dict["run_id"]] = result_dict


def _list_runs(limit: int = 20) -> list[dict[str, Any]]:
    return list(reversed(list(_runs)))[:limit]


# ---------------------------------------------------------------------------
# Orchestrator singleton (per-process)
# ---------------------------------------------------------------------------

_orchestrator: SwarmOrchestrator | None = None
_orchestrator_lock = asyncio.Lock()


async def get_orchestrator(request=None) -> SwarmOrchestrator:
    """Return a process-wide SwarmOrchestrator wired to the FastAPI app."""
    global _orchestrator
    if _orchestrator is not None:
        return _orchestrator
    async with _orchestrator_lock:
        if _orchestrator is not None:
            return _orchestrator
        llm_client = None
        registry: dict[str, Any] = {}
        event_bus = None
        if request is not None:
            app_state = request.app.state if hasattr(request, "app") else None
            if app_state is not None:
                llm_client = getattr(app_state, "llm_client", None)
                event_bus = getattr(app_state, "event_bus", None)
                registry = getattr(app_state, "registry", None) or {}
        _orchestrator = SwarmOrchestrator(
            llm_client=llm_client,
            registry=registry,
            event_bus=event_bus,
        )
    return _orchestrator


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SwarmRunBody(BaseModel):
    objective: str = Field(min_length=1, max_length=20_000)
    session_id: str = Field(default="default", min_length=1, max_length=128)
    mode: OperationalMode | None = None
    strategy: SwarmStrategy | None = None
    agents: list[AgentRole] | None = None
    project_path: str = Field(default="", max_length=2000)
    auto_approve: bool = False
    max_iterations: int = Field(default=5, ge=1, le=20)


class RagIndexBody(BaseModel):
    project_path: str = Field(default="", max_length=2000)
    max_files: int = Field(default=500, ge=1, le=10_000)


class RagSearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    top_k: int = Field(default=8, ge=1, le=50)
    language: str | None = None


class SkillRunBody(BaseModel):
    variables: dict[str, str] = Field(default_factory=dict)
    session_id: str = Field(default="default", min_length=1, max_length=128)
    project_path: str = Field(default="", max_length=2000)
    auto_approve: bool = False
    max_iterations: int = Field(default=5, ge=1, le=20)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "ts": time.time()}


@router.get("/modes")
async def list_modes(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    return {"modes": modes_to_dict()}


@router.get("/agents")
async def list_agents(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    from backend.swarm.core.agents import AGENT_DEFINITIONS

    out: dict[str, Any] = {}
    for role, defn in AGENT_DEFINITIONS.items():
        out[role.value] = {
            "label": defn.label,
            "objective": defn.objective,
            "responsibilities": defn.responsibilities,
            "limitations": defn.limitations,
            "input_messages": [m.value for m in defn.input_messages],
            "output_messages": [m.value for m in defn.output_messages],
            "memory_layers": defn.memory_layers,
            "maps_to": defn.maps_to,
        }
    return {"agents": out}


@router.post("/run")
async def run_swarm(
    body: SwarmRunBody,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Run a SWARM cycle synchronously (returns the full result)."""
    project_path, _ = resolve_project_path(body.project_path or "")
    orch = await get_orchestrator()
    req = SwarmRunRequest(
        objective=body.objective,
        session_id=body.session_id,
        mode=body.mode,
        strategy=body.strategy,
        agents=body.agents,
        project_path=project_path,
        auto_approve=body.auto_approve,
        max_iterations=body.max_iterations,
    )
    result = await orch.run(req)
    payload = result.to_dict()
    _save_run(payload)
    return payload


@router.get("/runs")
async def list_runs(
    limit: int = 20,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    return {"runs": _list_runs(limit=limit)}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    run = _runs_by_id.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


@router.post("/rag/index")
async def rag_index(
    body: RagIndexBody,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    project_path, _ = resolve_project_path(body.project_path or "")
    if not project_path:
        raise HTTPException(status_code=400, detail="project_path is required for indexing")
    retriever = get_retriever()
    chunks = index_directory(retriever, project_path, max_files=body.max_files)
    return {
        "project_path": project_path,
        "chunks": chunks,
        "stats": retriever.stats(),
    }


@router.post("/rag/search")
async def rag_search(
    body: RagSearchBody,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    retriever = get_retriever()
    hits = retriever.retrieve(body.query, top_k=body.top_k, language=body.language)
    return {
        "query": body.query,
        "hits": [h.to_dict() for h in hits],
        "stats": retriever.stats(),
    }


@router.get("/dashboard")
async def dashboard(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    """Aggregated metrics for the new dashboard widget."""
    from backend.swarm.memory.memory_layers import get_memory_store

    mem = get_memory_store()
    retriever = get_retriever()
    recent = _list_runs(limit=20)
    return {
        "memory": mem.stats(),
        "retriever": retriever.stats(),
        "recent_runs": [
            {
                "run_id": r["run_id"],
                "mode": r["mode"],
                "state": r["state"],
                "scores": r["scores"],
                "duration_ms": r["duration_ms"],
                "tokens_used": r.get("tokens_used", 0),
                "finished_at": r.get("finished_at", 0),
            }
            for r in recent
        ],
        "total_runs": len(_runs),
    }


# ---------------------------------------------------------------------------
# Skills / workflows
# ---------------------------------------------------------------------------


def _all_skills() -> list[Any]:
    """Return the merged catalogue (built-in + YAML workflows)."""
    return merged_catalogue()


@router.get("/skills")
async def list_skills(
    category: str | None = None,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """List all available skills (built-in + user-defined YAML workflows)."""
    skills = _all_skills()
    if category:
        skills = [s for s in skills if s.category == category]
    return {
        "skills": [s.to_dict() for s in skills],
        "count": len(skills),
        "categories": sorted({s.category for s in _all_skills()}),
    }


@router.get("/skills/{skill_id}")
async def get_skill_endpoint(
    skill_id: str,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    skill = get_skill(skill_id) or next((s for s in _all_skills() if s.id == skill_id), None)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill {skill_id} not found")
    return skill.to_dict()


@router.post("/skills/{skill_id}/run")
async def run_skill(
    skill_id: str,
    body: SkillRunBody,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Render the skill's objective template and run a SWARM cycle."""
    skill = get_skill(skill_id) or next((s for s in _all_skills() if s.id == skill_id), None)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill {skill_id} not found")
    # Validate required variables
    missing = [v.name for v in skill.variables if v.required and not body.variables.get(v.name)]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required variables: {', '.join(missing)}",
        )
    try:
        objective = skill.render_objective(body.variables)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    project_path, _ = resolve_project_path(body.project_path or "")
    orch = await get_orchestrator()
    req = SwarmRunRequest(
        objective=objective,
        session_id=body.session_id,
        mode=skill.mode,
        strategy=skill.strategy,
        agents=skill.agents,
        project_path=project_path,
        auto_approve=body.auto_approve,
        max_iterations=body.max_iterations or skill.max_iterations,
    )
    result = await orch.run(req)
    payload = result.to_dict()
    payload["skill_id"] = skill_id
    payload["skill_name"] = skill.name
    payload["rendered_objective"] = objective
    _save_run(payload)
    return payload


@router.get("/workflows")
async def list_workflows(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    """List only the YAML-loaded workflows (excluding built-in skills)."""
    from backend.swarm.skills.workflow_loader import load_workflows

    workflows = load_workflows()
    return {
        "workflows": [s.to_dict() for s in workflows],
        "count": len(workflows),
    }


# ---------------------------------------------------------------------------
# Singleton reset (used by tests)
# ---------------------------------------------------------------------------


def reset_orchestrator() -> None:
    global _orchestrator
    _orchestrator = None
    _runs.clear()
    _runs_by_id.clear()


__all__ = ["router", "reset_orchestrator", "get_orchestrator"]
