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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

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
_runs_lock = asyncio.Lock()


def _save_run(result_dict: dict[str, Any]) -> None:
    """Append a run, evicting the id-index entry the deque just dropped.

    ``deque(maxlen=...)`` silently discards the oldest item, but the
    ``_runs_by_id`` mirror had no eviction, so the process leaked one full
    run payload per request forever. Capture the evicted item and drop it.
    """
    evicted: dict[str, Any] | None = None
    if len(_runs) == _MAX_RUNS:
        evicted = _runs[0]
    _runs.append(result_dict)
    _runs_by_id[result_dict["run_id"]] = result_dict
    if evicted is not None:
        _runs_by_id.pop(evicted.get("run_id", ""), None)
    # Defensive: if anything ever desynchronises the two stores, resync.
    if len(_runs_by_id) > _MAX_RUNS:
        live = {r["run_id"] for r in _runs}
        for stale in [k for k in _runs_by_id if k not in live]:
            _runs_by_id.pop(stale, None)


def _list_runs(limit: int = 20) -> list[dict[str, Any]]:
    return list(reversed(list(_runs)))[:limit]


def _summarise_run(run: dict[str, Any]) -> dict[str, Any]:
    """Lightweight projection for list endpoints.

    ``/runs`` previously returned every full payload (final answer, all
    proposals, all evidence) for 20 runs at once, which is megabytes of JSON
    the history sidebar never reads.
    """
    return {
        "run_id": run.get("run_id", ""),
        "mode": run.get("mode", ""),
        "strategy": run.get("strategy", ""),
        "objective": run.get("objective", ""),
        "state": run.get("state", ""),
        "scores": run.get("scores", {}),
        "duration_ms": run.get("duration_ms", 0),
        "tokens_used": run.get("tokens_used", 0),
        "started_at": run.get("started_at", 0),
        "finished_at": run.get("finished_at", 0),
        "error": run.get("error", ""),
        "message_count": run.get("message_count", 0),
        "skill_id": run.get("skill_id"),
        "skill_name": run.get("skill_name"),
    }


# ---------------------------------------------------------------------------
# Orchestrator singleton (per-process)
# ---------------------------------------------------------------------------

_orchestrator: SwarmOrchestrator | None = None
_orchestrator_lock = asyncio.Lock()


def _app_state(request: Request | None) -> Any:
    """Return ``request.app.state`` when available, else ``None``."""
    if request is None:
        return None
    app = getattr(request, "app", None)
    return getattr(app, "state", None) if app is not None else None


async def get_orchestrator(request: Request | None = None) -> SwarmOrchestrator:
    """Return a process-wide SwarmOrchestrator wired to the FastAPI app.

    The previous version accepted ``request`` but every caller invoked it as
    ``get_orchestrator()``. The singleton was therefore always built with
    ``registry={}`` and ``llm_client=None``, so ``_gather_agent_outputs``
    resolved every role to ``"(agent X not available)"`` and no SWARM run ever
    reached a real model. Callers now pass the request, and if the singleton
    was created cold (e.g. by ``/health`` before startup finished) its
    dependencies are back-filled on the next call that does have app state.
    """
    global _orchestrator
    state = _app_state(request)

    if _orchestrator is not None:
        _hydrate_orchestrator(_orchestrator, state)
        return _orchestrator

    async with _orchestrator_lock:
        if _orchestrator is not None:
            _hydrate_orchestrator(_orchestrator, state)
            return _orchestrator
        _orchestrator = SwarmOrchestrator(
            llm_client=getattr(state, "llm_client", None) if state else None,
            registry=(getattr(state, "registry", None) or {}) if state else {},
            event_bus=getattr(state, "event_bus", None) if state else None,
        )
        if not _orchestrator.registry:
            logger.warning(
                "SWARM orchestrator created without an agent registry — "
                "runs will return placeholder output until app.state.registry is set."
            )
    return _orchestrator


def _hydrate_orchestrator(orch: SwarmOrchestrator, state: Any) -> None:
    """Back-fill dependencies onto an already-created singleton."""
    if state is None:
        return
    if not orch.registry:
        orch.registry = getattr(state, "registry", None) or {}
    if orch.llm_client is None:
        orch.llm_client = getattr(state, "llm_client", None)
    if orch.events is None:
        orch.events = getattr(state, "event_bus", None)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


#: Legacy / NEXUS-internal agent names accepted for backwards compatibility.
#: The UI (and older clients) used to post the underlying NEXUS agent names
#: (ARCHITECT, ANALYZER, CODER, …) which are *not* SWARM roles, producing a
#: 422 on every run. Normalise them instead of rejecting the request.
_AGENT_ALIASES: dict[str, AgentRole] = {
    "coordinator": AgentRole.COORDINATOR,
    "architect": AgentRole.ARCHITECT,
    "researcher": AgentRole.RESEARCHER,
    "investigator": AgentRole.INVESTIGATOR,
    "implementer": AgentRole.IMPLEMENTER,
    "reviewer": AgentRole.REVIEWER,
    # NEXUS agent names → nearest SWARM role
    "analyzer": AgentRole.INVESTIGATOR,
    "analyser": AgentRole.INVESTIGATOR,
    "debugger": AgentRole.INVESTIGATOR,
    "coder": AgentRole.IMPLEMENTER,
    "documenter": AgentRole.ARCHITECT,
    "optimizer": AgentRole.IMPLEMENTER,
    "optimiser": AgentRole.IMPLEMENTER,
    "planner": AgentRole.ARCHITECT,
}


def _normalise_agents(value: Any) -> Any:
    """Coerce a list of agent identifiers into canonical :class:`AgentRole`s."""
    if value is None:
        return None
    if not isinstance(value, list):
        return value
    out: list[AgentRole] = []
    unknown: list[str] = []
    for item in value:
        if isinstance(item, AgentRole):
            role = item
        elif isinstance(item, str):
            role = _AGENT_ALIASES.get(item.strip().lower())
            if role is None:
                unknown.append(item)
                continue
        else:
            unknown.append(str(item))
            continue
        if role not in out:  # de-duplicate, preserve order
            out.append(role)
    if unknown:
        raise ValueError(
            "Unknown agent(s): "
            + ", ".join(sorted(set(unknown)))
            + ". Valid roles: "
            + ", ".join(r.value for r in AgentRole)
        )
    return out or None


class SwarmRunBody(BaseModel):
    objective: str = Field(min_length=1, max_length=20_000)
    session_id: str = Field(default="default", min_length=1, max_length=128)
    mode: OperationalMode | None = None
    strategy: SwarmStrategy | None = None
    agents: list[AgentRole] | None = None
    project_path: str = Field(default="", max_length=2000)
    auto_approve: bool = False
    autonomous: bool = True
    max_iterations: int = Field(default=1000, ge=1, le=1000)
    index_project: bool = Field(
        default=True,
        description="Index project_path into the RAG before running if the index is empty.",
    )

    @field_validator("agents", mode="before")
    @classmethod
    def _coerce_agents(cls, v: Any) -> Any:
        return _normalise_agents(v)

    @field_validator("mode", "strategy", mode="before")
    @classmethod
    def _lower_enums(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) and v.strip() else v

    @field_validator("objective")
    @classmethod
    def _objective_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("objective must not be blank")
        return v.strip()


class RagIndexBody(BaseModel):
    project_path: str = Field(default="", max_length=2000)
    max_files: int = Field(default=500, ge=1, le=10_000)


class RagSearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    top_k: int = Field(default=8, ge=1, le=50)
    language: str | None = None
    project_path: str = Field(default="", max_length=2000)


class SkillRunBody(BaseModel):
    variables: dict[str, str] = Field(default_factory=dict)
    session_id: str = Field(default="default", min_length=1, max_length=128)
    project_path: str = Field(default="", max_length=2000)
    auto_approve: bool = False
    autonomous: bool = True
    max_iterations: int = Field(default=1000, ge=1, le=1000)
    index_project: bool = True


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


async def _ensure_indexed(project_path: str, enabled: bool) -> int:
    """Index ``project_path`` into the RAG if the index is still empty.

    Without this, ``spec.uses_rag`` short-circuits on ``chunks == 0`` and every
    run answers with zero evidence unless the user remembered to POST
    ``/rag/index`` first. Indexing is CPU-bound, so it runs in a thread.
    """
    if not enabled or not project_path:
        return 0
    retriever = get_retriever()
    if retriever.has_project(project_path):
        return 0
    try:
        return await asyncio.to_thread(index_directory, retriever, project_path)
    except Exception as exc:  # never fail a run because indexing failed
        logger.warning("SWARM auto-index of %s failed: %s", project_path, exc)
        return 0


@router.post("/run")
async def run_swarm(
    body: SwarmRunBody,
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Run a SWARM cycle synchronously (returns the full result)."""
    project_path, _ = resolve_project_path(body.project_path or "")
    orch = await get_orchestrator(request)
    await _ensure_indexed(project_path, body.index_project)
    req = SwarmRunRequest(
        objective=body.objective,
        session_id=body.session_id,
        mode=body.mode,
        strategy=body.strategy,
        agents=body.agents,
        project_path=project_path,
        auto_approve=body.auto_approve,
        autonomous=body.autonomous,
        max_iterations=body.max_iterations,
    )
    result = await orch.run(req)
    payload = result.to_dict()
    async with _runs_lock:
        _save_run(payload)
    return payload


@router.get("/runs")
async def list_runs(
    limit: int = 20,
    full: bool = False,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """List recent runs.

    Returns lightweight summaries by default; pass ``full=true`` for the
    complete payloads (previously the only, very heavy, behaviour).
    """
    limit = max(1, min(limit, _MAX_RUNS))
    runs = _list_runs(limit=limit)
    return {"runs": runs if full else [_summarise_run(r) for r in runs]}


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
    # Indexing walks the filesystem and embeds chunks — offload it so it does
    # not block the event loop (and every other request) for tens of seconds.
    chunks = await asyncio.to_thread(
        index_directory, retriever, project_path, max_files=body.max_files
    )
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
    project_path, _ = resolve_project_path(body.project_path or "")
    hits = retriever.retrieve(
        body.query,
        top_k=body.top_k,
        language=body.language,
        project_path=project_path or None,
    )
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
    all_skills = _all_skills()
    categories = sorted({s.category for s in all_skills})
    skills = [s for s in all_skills if s.category == category] if category else all_skills
    return {
        "skills": [s.to_dict() for s in skills],
        "count": len(skills),
        "categories": categories,
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
    request: Request,
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
    orch = await get_orchestrator(request)
    await _ensure_indexed(project_path, body.index_project)
    req = SwarmRunRequest(
        objective=objective,
        session_id=body.session_id,
        mode=skill.mode,
        strategy=skill.strategy,
        agents=skill.agents,
        project_path=project_path,
        auto_approve=body.auto_approve,
        autonomous=body.autonomous,
        max_iterations=body.max_iterations or skill.max_iterations,
    )
    result = await orch.run(req)
    payload = result.to_dict()
    payload["skill_id"] = skill_id
    payload["skill_name"] = skill.name
    payload["rendered_objective"] = objective
    async with _runs_lock:
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
