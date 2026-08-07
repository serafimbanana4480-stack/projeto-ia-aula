"""HTTP routes for request cancellation.

Allows the frontend to explicitly cancel an in-flight request via:
    POST /api/chat/cancel/{request_id}

This complements the implicit cancellation that happens when the
HTTP connection is closed (frontend aborts the request).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.middleware.auth import require_auth
from backend.orchestrator.cancellation import get_cancellation_registry
from backend.orchestrator.chat_cancellation import is_valid_request_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["cancellation"])


@router.post("/cancel/{request_id}")
async def cancel_request(
    request_id: str,
    _user: dict = Depends(require_auth),
) -> dict:
    """Cancel an in-flight chat request by ID.

    Returns:
        dict with status: "cancelled" or "not_found"
    """
    if not is_valid_request_id(request_id):
        raise HTTPException(status_code=400, detail="Invalid request_id")

    registry = get_cancellation_registry()
    cancelled = await registry.cancel(request_id)
    if not cancelled:
        # Try sync as a fallback (handles edge cases)
        cancelled = registry.cancel_sync(request_id)
    if not cancelled:
        return {"status": "not_found", "request_id": request_id}
    return {"status": "cancelled", "request_id": request_id}


@router.get("/cancel/stats")
async def cancellation_stats(_user: dict = Depends(require_auth)) -> dict:
    """Return cancellation registry statistics (active/cancelled counts)."""
    registry = get_cancellation_registry()
    return registry.stats()
