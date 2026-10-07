"""API routes for the NEXUS Advanced Modes (Infinity Suite v2.0).

Provides endpoints for:
- Listing all advanced modes with their status
- Activating/deactivating modes
- Getting mode-specific status and sessions
- Resolving /commands to mode configurations
- Checking mode health and gates
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictInt, StrictStr

from backend.core.disk_guard import disk_pressure_status
from backend.middleware.auth import require_auth
from backend.orchestrator.advanced_modes import (
    REPO_ROOT,
    AdvancedModeOrchestrator,
    get_advanced_mode,
    get_command_aliases,
    get_mode_groups,
    get_orchestrator,
    get_state_manager,
    resolve_command,
)

logger = logging.getLogger(__name__)

router = APIRouter()

NonEmptyText = Annotated[StrictStr, Field(min_length=1, max_length=100_000)]
Score = Annotated[float, Field(strict=True, ge=0, le=100, allow_inf_nan=False)]
Weight = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]


class ModeContextRequest(BaseModel):
    request: NonEmptyText


class CompletionReviewRequest(BaseModel):
    session_id: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    claim: NonEmptyText
    evidence: dict[str, Any] = Field(default_factory=dict)


class SentinelCheckRequest(BaseModel):
    action: NonEmptyText
    risk_level: Annotated[StrictInt, Field(ge=0, le=4)] = 0
    files: list[StrictStr] = Field(default_factory=list, max_length=1000)


class TournamentEntryRequest(BaseModel):
    id: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    name: Annotated[StrictStr, Field(min_length=1, max_length=256)]
    description: StrictStr = ""
    files: list[StrictStr] = Field(default_factory=list)
    scores: dict[str, Score] = Field(default_factory=dict)


class TournamentRequest(BaseModel):
    entries: list[TournamentEntryRequest] = Field(default_factory=list, max_length=100)
    weights: dict[str, Weight] | None = None


def _require_mode(mode_id: str) -> None:
    if not get_advanced_mode(mode_id):
        raise HTTPException(status_code=404, detail=f"Advanced mode '{mode_id}' not found")


def _get_orch() -> AdvancedModeOrchestrator:
    return get_orchestrator()


# ═══════════════════════════════════════════════════════════════════════════
# Mode Listing & Status
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/advanced-modes")
async def list_advanced_modes(
    _user: dict = Depends(require_auth),
) -> dict:
    """List all advanced modes with their current status."""
    orch = _get_orch()
    return orch.get_all_statuses()


@router.get("/advanced-modes/groups")
async def list_advanced_mode_groups(
    _user: dict = Depends(require_auth),
) -> dict:
    """List advanced mode grouping configuration."""
    return {
        "groups": get_mode_groups(),
    }


@router.get("/advanced-modes/commands")
async def list_advanced_mode_commands(
    _user: dict = Depends(require_auth),
) -> dict:
    """List all available /commands and their aliases."""
    return {
        "commands": get_command_aliases(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Health & Status Dashboard Data
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/advanced-modes/health")
async def advanced_modes_health(
    _user: dict = Depends(require_auth),
) -> dict:
    """Get overall health status of the advanced modes system."""
    orch = _get_orch()
    all_statuses = orch.get_all_statuses()

    active_count = all_statuses.get("active_count", 0)
    total_count = all_statuses.get("total_count", 0)
    mode_statuses = all_statuses.get("modes", {})

    mode_summaries = {}
    for mid, status in mode_statuses.items():
        mode_summaries[mid] = {
            "active": status.get("active", False),
            "session_count": status.get("session_count", 0),
            "active_session_count": status.get("active_session_count", status.get("session_count", 0)),
            "total_session_count": status.get("total_session_count", status.get("session_count", 0)),
            "group": status.get("group", ""),
            "display_name": status.get("display_name", mid),
            "description": status.get("description", ""),
            "icon": status.get("icon", "bot"),
            "color": status.get("color", "#888888"),
            "runtime_status": status.get("runtime_status", "unknown"),
            "runtime_role": status.get("runtime_role", "unknown"),
            "runtime_summary": status.get("runtime_summary", ""),
            "handler": status.get("handler"),
            "available": status.get("available", False),
            "execution_target": status.get("execution_target"),
            "limitations": status.get("limitations", ""),
            "activity_evidence_status": status.get("activity_evidence_status", "NOT_MEASURED"),
            "evidence_count": status.get("evidence_count", 0),
            "intervention_count": status.get("intervention_count", 0),
            "checkpoint_count": status.get("checkpoint_count", 0),
        }

    return {
        # A healthy catalog means every configured mode loaded and exposed a
        # runtime contract.  HTTP 200 alone is not proof that the suite is
        # usable, so keep this explicit and machine-readable for the UI.
        "healthy": bool(total_count > 0 and len(mode_statuses) == total_count and all(
            status.get("available", True) for status in mode_statuses.values()
        )),
        "active_modes": active_count,
        "total_modes": total_count,
        "modes": mode_summaries,
        "groups": all_statuses.get("groups", {}),
        "execution_profile": all_statuses.get("execution_profile", {}),
        "catalog_evidence_scope": "configuration_and_persisted_sessions",
        "activity_evidence_status": "NOT_MEASURED",
        "disk_guard": disk_pressure_status(REPO_ROOT),
    }


@router.get("/advanced-modes/{mode_id}")
async def get_advanced_mode_status(
    mode_id: str,
    _user: dict = Depends(require_auth),
) -> dict:
    """Get detailed status of a specific advanced mode."""
    orch = _get_orch()
    result = orch.get_mode_status(mode_id)
    if not result.get("available"):
        raise HTTPException(status_code=404, detail=f"Advanced mode '{mode_id}' not found")
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Mode Activation & Deactivation
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/advanced-modes/{mode_id}/activate")
async def activate_advanced_mode(
    mode_id: str,
    _user: dict = Depends(require_auth),
) -> dict:
    """Activate an advanced mode. Returns session info and mode config."""
    orch = _get_orch()
    result = orch.activate_mode(mode_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Activation failed"))
    return result


@router.post("/advanced-modes/{mode_id}/deactivate")
async def deactivate_advanced_mode(
    mode_id: str,
    _user: dict = Depends(require_auth),
) -> dict:
    """Deactivate an advanced mode."""
    if not get_advanced_mode(mode_id):
        raise HTTPException(status_code=404, detail=f"Advanced mode '{mode_id}' not found")
    orch = _get_orch()
    result = orch.deactivate_mode(mode_id)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Session Management
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/advanced-modes/{mode_id}/sessions")
async def list_advanced_mode_sessions(
    mode_id: str,
    _user: dict = Depends(require_auth),
) -> dict:
    """List all sessions for a specific advanced mode."""
    _require_mode(mode_id)
    mgr = get_state_manager()
    sessions = mgr.list_sessions(mode_id)
    return {
        "mode_id": mode_id,
        "sessions": sessions,
    }


@router.get("/advanced-modes/{mode_id}/sessions/{session_id}")
async def get_advanced_mode_session(
    mode_id: str,
    session_id: str,
    _user: dict = Depends(require_auth),
) -> dict:
    """Get detailed information about a specific session."""
    _require_mode(mode_id)
    mgr = get_state_manager()
    session = mgr.get_session(mode_id, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "mode_id": session.mode_id,
        "session_id": session.session_id,
        "state": session.state.value,
        "start_time": session.start_time,
        "updated_time": session.updated_time,
        "goal_tree": {gid: {
            "id": g.id,
            "title": g.title,
            "state": g.state.value,
            "parent_id": g.parent_id,
            "children": g.children,
            "assigned_agent": g.assigned_agent,
            "quality_score": g.quality_score,
            "rejection_reason": g.rejection_reason,
        } for gid, g in session.goal_tree.items()},
        "goal_root": session.goal_root,
        "metrics": session.metrics,
        "interventions_count": len(session.interventions),
        "evidence_count": len(session.evidence_book),
        "trajectory_count": len(session.trajectory),
        "checkpoint_count": len(session.checkpoints),
        "evidence_book": session.evidence_book,
        "trajectory": session.trajectory[-50:],
        "quality_gates": session.quality_gates,
        "checkpoints": session.checkpoints,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Command Resolution
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/commands/resolve")
async def resolve_chat_command(
    command: str,
    _user: dict = Depends(require_auth),
) -> dict:
    """Resolve a /command to its mode configuration.

    Example: /vibe-infinity -> { mode: "vibe-infinity", config: {...} }
    """
    resolved = resolve_command(command)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Unknown command: {command}")

    mode_id = resolved["mode"]
    mode_def = get_advanced_mode(mode_id)

    return {
        "command": command,
        "resolved_to": mode_id,
        "display_name": mode_def.get("display_name", mode_id) if mode_def else mode_id,
        "description": mode_def.get("description", "") if mode_def else "",
        "group": mode_def.get("group", "") if mode_def else "",
        "icon": mode_def.get("icon", "bot") if mode_def else "bot",
        "color": mode_def.get("color", "#888888") if mode_def else "#888888",
        "config": mode_def.get("config", {}) if mode_def else {},
        "has_system_prompt": bool(mode_def and mode_def.get("system_prompt_addon")),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Mode Context Injection
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/advanced-modes/{mode_id}/context")
async def prepare_advanced_mode_context(
    mode_id: str,
    body: ModeContextRequest,
    _user: dict = Depends(require_auth),
) -> dict:
    """Prepare the augmented context for a mode execution.

    Called by the chat pipeline before routing a request to inject
    mode-specific prompts, constraints, and session state.
    """
    _require_mode(mode_id)
    user_request = body.request.strip()
    if not user_request:
        raise HTTPException(status_code=400, detail="Missing 'request' field")

    orch = _get_orch()
    result = orch.prepare_mode_context(mode_id, user_request)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Advisor-Specific: Completion Review
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/advanced-modes/advisor-infinity/review")
async def advisor_review_completion(
    body: CompletionReviewRequest,
    _user: dict = Depends(require_auth),
) -> dict:
    """Submit a completion claim for Advisor Infinity review."""
    mode_id = "advisor-infinity"
    session_id = body.session_id
    claim = body.claim.strip()
    evidence = body.evidence

    if not claim:
        raise HTTPException(status_code=400, detail="Missing 'claim' field")

    orch = _get_orch()
    result = orch.record_completion_attempt(mode_id, session_id, claim, evidence)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Sentinel-Specific: Security Gate
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/advanced-modes/sentinel/check")
async def sentinel_check_action(
    body: SentinelCheckRequest,
    _user: dict = Depends(require_auth),
) -> dict:
    """Check an action against the Sentinel security gate."""
    orch = _get_orch()
    try:
        result = orch.check_security_gate(
            action_description=body.action,
            risk_level=body.risk_level,
            files_affected=body.files,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Multiverse-Specific: Tournament Evaluation
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/advanced-modes/multiverse/evaluate")
async def multiverse_evaluate(
    body: TournamentRequest,
    _user: dict = Depends(require_auth),
) -> dict:
    """Evaluate tournament entries and select the winner."""
    from backend.orchestrator.advanced_modes import TournamentEntry

    entries = []
    for e in body.entries:
        entry = TournamentEntry(
            id=e.id,
            name=e.name,
            approach_description=e.description,
            files=e.files,
            scores=e.scores,
        )
        entries.append(entry)

    orch = _get_orch()
    try:
        result = orch.evaluate_tournament(entries, body.weights)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result
