"""In-process human confirmation gates for risky tool executions."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class PendingConfirmation:
    session_id: str
    tool_name: str
    args: dict[str, Any]
    future: asyncio.Future[bool]
    created_at: float
    retry_enabled: bool = False
    user_id: str = ""


_pending: dict[str, PendingConfirmation] = {}
_CONFIRMATION_TIMEOUT_SECONDS = 300


def _prune_expired_confirmations() -> None:
    cutoff = time.monotonic() - _CONFIRMATION_TIMEOUT_SECONDS
    for confirmation_id, pending in list(_pending.items()):
        if pending.created_at < cutoff:
            _pending.pop(confirmation_id, None)


async def create_confirmation(
    session_id: str,
    tool_name: str,
    args: dict[str, Any],
    *,
    retry_enabled: bool = False,
    user_id: str = "",
) -> str:
    _prune_expired_confirmations()
    confirmation_id = f"confirm-{uuid.uuid4().hex}"
    _pending[confirmation_id] = PendingConfirmation(
        session_id=session_id,
        tool_name=tool_name,
        args=dict(args),
        future=asyncio.get_running_loop().create_future(),
        created_at=time.monotonic(),
        retry_enabled=retry_enabled,
        user_id=user_id,
    )
    return confirmation_id


async def wait_for_confirmation(confirmation_id: str) -> bool:
    pending = _pending.get(confirmation_id)
    if pending is None:
        return False
    try:
        return await asyncio.wait_for(
            asyncio.shield(pending.future), timeout=_CONFIRMATION_TIMEOUT_SECONDS
        )
    except TimeoutError:
        return False
    finally:
        _pending.pop(confirmation_id, None)


async def resolve_confirmation(confirmation_id: str, approved: bool) -> bool:
    _prune_expired_confirmations()
    pending = _pending.get(confirmation_id)
    if pending is None or pending.future.done():
        return False
    pending.future.set_result(approved)
    if pending.retry_enabled and not approved:
        _pending.pop(confirmation_id, None)
    return True


def consume_approved_retry_confirmation(
    confirmation_id: str,
    *,
    user_id: str,
    session_id: str,
    tool_name: str,
    args: dict[str, Any],
) -> bool:
    """Consume one approved, request-bound retry authorization exactly once."""
    _prune_expired_confirmations()
    pending = _pending.get(confirmation_id)
    if (
        pending is None
        or not pending.retry_enabled
        or not pending.future.done()
        or pending.future.cancelled()
        or pending.future.result() is not True
        or pending.user_id != user_id
        or pending.session_id != session_id
        or pending.tool_name != tool_name
        or pending.args != args
    ):
        return False
    _pending.pop(confirmation_id, None)
    return True


def discard_confirmation(confirmation_id: str) -> bool:
    """Remove a pending gate without waiting for its future.

    Autonomous runs use this for operations that are intentionally blocked by
    policy. They must not leave an orphaned future in the process-wide map or
    slowly leak confirmation records during long unattended runs.
    """
    return _pending.pop(confirmation_id, None) is not None


def get_pending_confirmation(confirmation_id: str) -> PendingConfirmation | None:
    _prune_expired_confirmations()
    return _pending.get(confirmation_id)
