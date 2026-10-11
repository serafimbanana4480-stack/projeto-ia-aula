"""Routes for the run dead-letter queue.

A parked failure is only useful if a human can look at it and act on it. These
endpoints are that surface: list and inspect the queue, then re-arm
(``retry``/``requeue``), hand over (``replan``), close (``abandon``) or raise
(``escalate``).

Every route requires authentication at the *router* level: this queue contains
sanitised tracebacks, provider names and run identifiers, and every action
re-arms or closes real work. There is no unauthenticated read.

The service is resolved from application state when the app lifespan installed
one (``app.state.dead_letter_service``) and built on demand otherwise, so the
router works both inside the full application and standalone in a test.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from backend.middleware.auth import require_auth
from backend.runtime.dead_letter_service import (
    RECOVERABILITY_PERMANENT,
    RECOVERABILITY_TRANSIENT,
    RECOVERABILITY_UNKNOWN,
    DeadLetterError,
    DeadLetterService,
)
from backend.runtime.run_coordinator import DEAD_LETTER_STATES, RunCoordinator

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_auth)])


class DeadLetterActionRequest(BaseModel):
    """Body for the state-changing actions. ``reason`` is always optional and
    always recorded, so an action never looks unexplained in the queue."""

    reason: str = Field(default="", max_length=500)
    plan: str = Field(default="", max_length=2000)


async def get_dead_letter_service(request: Request) -> DeadLetterService:
    """Resolve the service for this process.

    Preference order:

    1. ``request.app.state.dead_letter_service`` — the lifespan-installed
       instance, which already carries the process-wide task manager.
    2. A freshly built service over the application coordinator plus the
       lifespan's ``app.state.task_manager`` when it exists.

    The coordinator is created per call only in case 2; ``RunCoordinator``
    resolves the database path at call time, so this follows the application
    database (and a test's redirected one) without extra wiring.
    """
    installed = getattr(request.app.state, "dead_letter_service", None)
    if isinstance(installed, DeadLetterService):
        return installed

    task_manager = getattr(request.app.state, "task_manager", None)
    try:
        service = DeadLetterService(RunCoordinator(), task_manager=task_manager)
    except Exception as exc:  # pragma: no cover - a broken DB is an operator problem
        logger.exception("Could not open the dead-letter service")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dead-letter storage is temporarily unavailable.",
        ) from exc
    request.app.state.dead_letter_service = service
    return service


@router.get("/dead-letters")
async def list_dead_letters(
    state: str | None = Query(default="open", description="Queue state, 'all', or empty"),
    run_id: str | None = Query(default=None),
    recoverability: str | None = Query(
        default=None,
        description=f"One of {RECOVERABILITY_TRANSIENT}, {RECOVERABILITY_PERMANENT}, "
        f"{RECOVERABILITY_UNKNOWN}",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    service: DeadLetterService = Depends(get_dead_letter_service),
) -> dict[str, Any]:
    """List the queue, newest first.

    ``state=open`` (the default) is the operator's worklist; ``state=all``
    (or an empty value) returns every state so a closed entry can still be
    audited.
    """
    state = (state or "").strip() or None
    if state is not None and state not in DEAD_LETTER_STATES and state != "all":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown dead-letter state '{state}'. Expected one of "
            f"{sorted(DEAD_LETTER_STATES)} or 'all'.",
        )
    if recoverability is not None and recoverability not in {
        RECOVERABILITY_TRANSIENT,
        RECOVERABILITY_PERMANENT,
        RECOVERABILITY_UNKNOWN,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown recoverability '{recoverability}'.",
        )
    entries = service.list(
        run_id=run_id,
        state=None if state == "all" else state,
        recoverability=recoverability,
        limit=limit,
    )
    return {"dead_letters": entries, "count": len(entries)}


@router.get("/dead-letters/{entry_id}")
async def get_dead_letter(
    entry_id: str,
    service: DeadLetterService = Depends(get_dead_letter_service),
) -> dict[str, Any]:
    """One entry with its classification and action history."""
    return _inspect(service, entry_id)


@router.post("/dead-letters/{entry_id}/retry")
async def retry_dead_letter(
    entry_id: str,
    payload: DeadLetterActionRequest | None = None,
    service: DeadLetterService = Depends(get_dead_letter_service),
) -> dict[str, Any]:
    """Re-arm the parked unit now.

    Refused (409) while the entry's ``retry_after`` is still in the future —
    use ``requeue`` to override a wait an operator has decided is over.
    """
    return await _run_action(service.retry, entry_id, payload, "retry")


@router.post("/dead-letters/{entry_id}/requeue")
async def requeue_dead_letter(
    entry_id: str,
    payload: DeadLetterActionRequest | None = None,
    service: DeadLetterService = Depends(get_dead_letter_service),
) -> dict[str, Any]:
    """Re-arm the parked unit, overriding any retry delay."""
    return await _run_action(service.requeue, entry_id, payload, "requeue")


@router.post("/dead-letters/{entry_id}/replan")
async def replan_dead_letter(
    entry_id: str,
    payload: DeadLetterActionRequest | None = None,
    service: DeadLetterService = Depends(get_dead_letter_service),
) -> dict[str, Any]:
    """Hand the failure back for a new plan. Nothing is re-armed here."""
    body = payload or DeadLetterActionRequest()
    return await _run_action(
        lambda entry: service.replan(entry, plan=body.plan or None),
        entry_id,
        payload,
        "replan",
    )


@router.post("/dead-letters/{entry_id}/abandon")
async def abandon_dead_letter(
    entry_id: str,
    payload: DeadLetterActionRequest | None = None,
    service: DeadLetterService = Depends(get_dead_letter_service),
) -> dict[str, Any]:
    """Close the entry as not worth pursuing. The reason is recorded."""
    body = payload or DeadLetterActionRequest()
    return await _run_action(
        lambda entry: service.abandon(entry, reason=body.reason), entry_id, payload, "abandon"
    )


@router.post("/dead-letters/{entry_id}/escalate")
async def escalate_dead_letter(
    entry_id: str,
    payload: DeadLetterActionRequest | None = None,
    service: DeadLetterService = Depends(get_dead_letter_service),
) -> dict[str, Any]:
    """Mark the entry as needing a human decision, with the reason recorded."""
    body = payload or DeadLetterActionRequest()
    return await _run_action(
        lambda entry: service.escalate(entry, reason=body.reason),
        entry_id,
        payload,
        "escalate",
    )


def _inspect(service: DeadLetterService, entry_id: str) -> dict[str, Any]:
    try:
        return {"dead_letter": service.inspect(entry_id)}
    except DeadLetterError as exc:
        raise _as_http(exc) from exc


async def _run_action(
    action: Any, entry_id: str, payload: DeadLetterActionRequest | None, label: str
) -> dict[str, Any]:
    """Run one queue action, translating its operational failure to an HTTP status.

    An empty body is normal: ``POST /dead-letters/{id}/abandon`` with no
    payload is a valid operator decision, so the body is optional everywhere.
    """
    try:
        result = action(entry_id)
        result = await result if hasattr(result, "__await__") else result
    except DeadLetterError as exc:
        logger.info("[DLQ] %s on %s refused: %s", label, entry_id, exc)
        raise _as_http(exc) from exc
    return result.to_dict()


def _as_http(exc: DeadLetterError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail=str(exc))
