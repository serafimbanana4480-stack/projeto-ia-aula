"""Session management tools — pause, resume, inspect, and cancel sessions and runs.

These tools wrap :mod:`backend.persistence.db` so agents can manage long-running
sessions without reaching for the REST API directly.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.persistence.db import (
    get_session,
    get_session_message_count,
    get_session_run,
    interrupt_active_session_runs,
    list_session_runs,
    mark_run_terminal,
    update_session,
)
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


async def pause_session(
    session_id: str = "",
    reason: str = "Paused by agent request",
) -> dict[str, Any]:
    """Pause a session by setting its mode to ``paused`` and interrupting any active runs.

    Args:
        session_id: The session to pause.
        reason: Reason recorded on interrupted runs.

    Returns:
        Dict with the updated session and interrupted run count.
    """
    if not session_id.strip():
        return {"error": "session_id is required."}

    session = get_session(session_id)
    if session is None:
        return {"error": f"Session {session_id} not found."}

    updated = update_session(session_id, mode="paused")
    interrupted = interrupt_active_session_runs(session_id, reason=reason)

    return {
        "ok": True,
        "session_id": session_id,
        "mode": "paused",
        "interrupted_runs": interrupted,
        "session": updated,
    }


async def resume_session(
    session_id: str = "",
    mode: str = "auto",
) -> dict[str, Any]:
    """Resume a paused session by restoring its mode.

    Args:
        session_id: The session to resume.
        mode: Mode to set (default ``auto``).

    Returns:
        Dict with the updated session.
    """
    if not session_id.strip():
        return {"error": "session_id is required."}

    session = get_session(session_id)
    if session is None:
        return {"error": f"Session {session_id} not found."}

    updated = update_session(session_id, mode=mode)

    return {
        "ok": True,
        "session_id": session_id,
        "mode": mode,
        "session": updated,
    }


async def get_session_status(session_id: str = "") -> dict[str, Any]:
    """Return detailed health information for a session.

    Includes session metadata, message count, and recent runs.

    Args:
        session_id: The session to inspect.

    Returns:
        Dict with session details, message count, and recent runs.
    """
    if not session_id.strip():
        return {"error": "session_id is required."}

    session = get_session(session_id)
    if session is None:
        return {"error": f"Session {session_id} not found."}

    try:
        message_count = get_session_message_count(session_id)
    except Exception:
        message_count = 0

    try:
        recent_runs = list_session_runs(session_id, limit=10)
    except Exception:
        recent_runs = []

    active_runs = [r for r in recent_runs if r.get("status") == "running"]
    failed_runs = [r for r in recent_runs if r.get("status") in ("failed", "cancelled", "interrupted")]

    return {
        "ok": True,
        "session_id": session_id,
        "session": session,
        "message_count": message_count,
        "recent_runs": recent_runs,
        "active_runs": len(active_runs),
        "failed_runs": len(failed_runs),
        "status": "active" if active_runs else ("idle" if message_count > 0 else "empty"),
    }


async def cancel_run(
    run_id: str = "",
    reason: str = "Cancelled by agent request",
) -> dict[str, Any]:
    """Cancel a running session run.

    Args:
        run_id: The run to cancel.
        reason: Reason recorded on the run.

    Returns:
        Dict with the cancelled run details.
    """
    if not run_id.strip():
        return {"error": "run_id is required."}

    run = get_session_run(run_id)
    if run is None:
        return {"error": f"Run {run_id} not found."}

    if run.get("status") not in ("running",):
        return {
            "ok": False,
            "error": f"Run {run_id} is already {run.get('status')!r} and cannot be cancelled.",
            "run": run,
        }

    try:
        updated = mark_run_terminal(
            run_id,
            status="cancelled",
            execution_state="cancelled",
            error=reason,
        )
    except Exception as exc:
        logger.exception("cancel_run failed for %s: %s", run_id, exc)
        return {"ok": False, "error": str(exc), "run_id": run_id}

    return {
        "ok": True,
        "run_id": run_id,
        "status": "cancelled",
        "run": updated,
    }


register_tool(
    ToolSpec(
        name="pause_session",
        description=(
            "Pause a running session. Sets the session mode to 'paused' and "
            "interrupts any active runs. Use resume_session to resume."
        ),
        tags=["session", "lifecycle", "pause"],
        category="system",
        risk_level="medium",
        when_to_use="When you need to temporarily stop a session to free resources or "
        "await external input.",
        schema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "The session to pause."},
                "reason": {"type": "string", "description": "Reason for pausing.", "default": "Paused by agent request"},
            },
            "required": ["session_id"],
        },
        handler=pause_session,
        timeout_seconds=15,
    )
)

register_tool(
    ToolSpec(
        name="resume_session",
        description=(
            "Resume a paused session by restoring its mode (default: 'auto')."
        ),
        tags=["session", "lifecycle", "resume"],
        category="system",
        risk_level="low",
        when_to_use="When a previously paused session should continue processing.",
        schema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "The session to resume."},
                "mode": {"type": "string", "description": "Mode to set (default: 'auto').", "default": "auto"},
            },
            "required": ["session_id"],
        },
        handler=resume_session,
        timeout_seconds=15,
    )
)

register_tool(
    ToolSpec(
        name="get_session_status",
        description=(
            "Return detailed health information for a session including metadata, "
            "message count, recent runs, and active/failed run counts."
        ),
        tags=["session", "lifecycle", "inspect", "health"],
        category="system",
        risk_level="low",
        when_to_use="When you need to inspect the state of a session before acting on it.",
        schema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "The session to inspect."},
            },
            "required": ["session_id"],
        },
        handler=get_session_status,
        timeout_seconds=15,
    )
)

register_tool(
    ToolSpec(
        name="cancel_run",
        description=(
            "Cancel a running session run by marking it as 'cancelled'. "
            "Only runs with status 'running' can be cancelled."
        ),
        tags=["session", "lifecycle", "cancel", "run"],
        category="system",
        risk_level="medium",
        when_to_use="When a specific run is stuck or no longer needed and must be stopped.",
        schema={
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "The run to cancel."},
                "reason": {"type": "string", "description": "Reason for cancellation.", "default": "Cancelled by agent request"},
            },
            "required": ["run_id"],
        },
        handler=cancel_run,
        timeout_seconds=15,
    )
)
