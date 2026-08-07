"""In-process human confirmation gates for risky tool executions."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class PendingConfirmation:
    session_id: str
    tool_name: str
    args: dict[str, Any]
    future: asyncio.Future[bool]


_pending: dict[str, PendingConfirmation] = {}
_CONFIRMATION_TIMEOUT_SECONDS = 300


async def create_confirmation(session_id: str, tool_name: str, args: dict[str, Any]) -> str:
    confirmation_id = f"confirm-{uuid.uuid4().hex[:16]}"
    _pending[confirmation_id] = PendingConfirmation(
        session_id=session_id,
        tool_name=tool_name,
        args=dict(args),
        future=asyncio.get_running_loop().create_future(),
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
    pending = _pending.get(confirmation_id)
    if pending is None or pending.future.done():
        return False
    pending.future.set_result(approved)
    return True


def discard_confirmation(confirmation_id: str) -> bool:
    """Remove a pending gate without waiting for its future.

    Autonomous runs use this for operations that are intentionally blocked by
    policy. They must not leave an orphaned future in the process-wide map or
    slowly leak confirmation records during long unattended runs.
    """
    return _pending.pop(confirmation_id, None) is not None


def get_pending_confirmation(confirmation_id: str) -> PendingConfirmation | None:
    return _pending.get(confirmation_id)
