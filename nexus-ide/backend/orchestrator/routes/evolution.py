"""Evolution Engine API routes (FASE 4-9 integration).

Exposes:
- GET  /api/evolution/state          → engine state (version tree, experiments, failures, rollbacks)
- GET  /api/evolution/champions      → list all champion versions
- GET  /api/evolution/champions/{kind}/versions → version history for a component
- GET  /api/evolution/experiments    → recent experiments
- POST /api/evolution/bootstrap      → register default champions
- POST /api/evolution/run            → execute an evolution cycle
- GET  /api/evolution/failures       → failure classification summary
- GET  /api/evolution/rollbacks      → rollback history
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.evolution.engine import DEFAULT_COMPONENT_CONFIGS, EvolutionConfig, EvolutionEngine

logger = logging.getLogger(__name__)
router = APIRouter(tags=["evolution"])


# ── Singleton engine ──────────────────────────────────────────────────────────

_ENGINE: EvolutionEngine | None = None


def get_engine() -> EvolutionEngine:
    """Return the global EvolutionEngine singleton, creating it on first use."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = EvolutionEngine()
    return _ENGINE


class RunRequest(BaseModel):
    """Request body for running an evolution cycle."""

    max_cycles: int = 1
    candidates_per_cycle: int = 3
    benchmark_task_ids: list[str] = []
    components_to_evolve: list[str] = []
    min_failure_priority_score: float = 0.05
    auto_promote: bool = False
    allow_simulation: bool = False
    min_benchmark_tasks: int = 5


class RegisterRequest(BaseModel):
    """Request body for manually registering a champion."""

    component_kind: str
    config: dict[str, Any]
    changelog: str = "Manual registration"


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/evolution/state")
async def get_evolution_state() -> dict[str, Any]:
    """Return the full evolution engine state for dashboard rendering."""
    engine = get_engine()
    return engine.get_state()


@router.get("/evolution/components")
async def list_evolution_components() -> list[str]:
    """List all evolvable component kinds."""
    return list(DEFAULT_COMPONENT_CONFIGS.keys())


@router.get("/evolution/champions")
async def list_champions(component_kind: str | None = None) -> list[dict[str, Any]]:
    """List all champion versions, optionally filtered by component kind."""
    engine = get_engine()
    from dataclasses import asdict
    if component_kind:
        champ = engine._registry.get_champion(component_kind)
        if champ is None:
            return []
        return [asdict(champ)]
    champions = []
    for kind in DEFAULT_COMPONENT_CONFIGS:
        for v in engine._registry.list_versions(kind, status="champion"):
            champions.append(asdict(v))
    return champions

@router.get("/evolution/champions/{component_kind}/versions")
async def list_component_versions(
    component_kind: str, status: str | None = None
) -> list[dict[str, Any]]:
    """List all versions of a component, optionally filtered by status."""
    engine = get_engine()
    from dataclasses import asdict
    versions = engine._registry.list_versions(component_kind, status=status)
    return [asdict(v) for v in versions]

@router.get("/evolution/experiments")
async def list_experiments(limit: int = 50) -> list[dict[str, Any]]:
    """List recent experiments."""
    engine = get_engine()
    experiments = engine._arena.list_experiments(limit=limit)
    result = []
    for e in experiments:
        d = vars(e) if hasattr(e, "__dict__") else dict(e)
        # Convert enum to string for JSON
        if "status" in d and hasattr(d["status"], "value"):
            d["status"] = d["status"].value
        result.append(d)
    return result


@router.get("/evolution/experiments/{experiment_id}")
async def get_experiment(experiment_id: str) -> dict[str, Any]:
    """Get details of a specific experiment."""
    engine = get_engine()
    experiments = engine._arena.list_experiments(limit=1000)
    for e in experiments:
        if e.experiment_id == experiment_id:
            d = vars(e) if hasattr(e, "__dict__") else dict(e)
            if "status" in d and hasattr(d["status"], "value"):
                d["status"] = d["status"].value
            return d
    raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")


@router.post("/evolution/bootstrap")
async def bootstrap_defaults() -> dict[str, Any]:
    """Register initial champion versions for all default components."""
    engine = get_engine()
    registered = engine.bootstrap_defaults()
    return {"registered": registered, "count": len(registered)}


@router.post("/evolution/register")
async def register_champion(request: RegisterRequest) -> dict[str, Any]:
    """Manually register a champion for a component."""
    engine = get_engine()
    version = engine.register_champion(
        component_kind=request.component_kind,
        config=request.config,
        changelog=request.changelog,
    )
    return {
        "component_kind": version.component_kind,
        "version": version.version,
        "status": version.status.value if hasattr(version.status, "value") else str(version.status),
    }


@router.post("/evolution/run")
async def run_evolution(request: RunRequest) -> dict[str, Any]:
    """Execute an evolution cycle."""
    engine = get_engine()
    config = EvolutionConfig(
        max_cycles=request.max_cycles,
        candidates_per_cycle=request.candidates_per_cycle,
        benchmark_task_ids=request.benchmark_task_ids,
        components_to_evolve=request.components_to_evolve or list(DEFAULT_COMPONENT_CONFIGS.keys()),
        min_failure_priority_score=request.min_failure_priority_score,
        auto_promote=request.auto_promote,
        allow_simulation=request.allow_simulation,
        min_benchmark_tasks=request.min_benchmark_tasks,
    )
    result = engine.evolve(config=config)
    return {
        "cycle": result.cycle,
        "candidates_generated": result.candidates_generated,
        "experiments_run": result.experiments_run,
        "promoted": result.promoted,
        "rejected": result.rejected,
        "regressions": result.regressions,
        "success_rate_before": result.success_rate_before,
        "success_rate_after": result.success_rate_after,
        "delta": result.delta,
        "explanation": result.explanation,
    }


@router.get("/evolution/failures")
async def get_failure_summary() -> dict[str, Any]:
    """Return the failure classification summary."""
    engine = get_engine()
    return engine._failure_miner.get_failure_summary()


@router.get("/evolution/rollbacks")
async def get_rollback_history(component_kind: str = "all") -> list[dict[str, Any]]:
    """Return the rollback history for a component (or all)."""
    engine = get_engine()
    return engine._rollback.get_rollback_history(component_kind)


@router.get("/evolution/registry/stats")
async def get_registry_stats() -> dict[str, Any]:
    """Return summary statistics from the champion registry."""
    engine = get_engine()
    versions = engine._registry.get_version_tree()
    stats: dict[str, Any] = {"components": {}}
    for kind, history in versions.items():
        stats["components"][kind] = {
            "total_versions": len(history),
            "champions": sum(1 for v in history if v["status"] == "champion"),
            "challengers": sum(1 for v in history if v["status"] == "challenger"),
            "archived": sum(1 for v in history if v["status"] == "archived"),
            "rejected": sum(1 for v in history if v["status"] == "rejected"),
        }
    return stats
