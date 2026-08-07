"""Agent progress feed.

Surfaces concise, user-safe progress updates emitted by agents so the
dashboard can show activity in real time. It is not a raw private
chain-of-thought log. Backed by the AgentBus ``thinking.*``
topics plus an in-memory ring buffer for the most recent events.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect

from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory ring buffer of recent thinking events per session.
_MAX_EVENTS = 200
_recent: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)

# Connected WebSocket subscribers.
_ws_subscribers: set[asyncio.Queue] = set()


@dataclass
class ThoughtEvent:
    id: str
    agent: str
    phase: str  # thinking | tool | answer | error
    text: str
    timestamp: str
    model: str | None = None
    duration_ms: int | None = None


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def publish_thought(
    agent: str,
    phase: str,
    text: str,
    *,
    model: str | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    """Broadcast a concise progress update from an agent/orchestrator."""
    ev = ThoughtEvent(
        id=str(uuid.uuid4()),
        agent=agent,
        phase=phase,
        text=text,
        timestamp=_now_iso(),
        model=model,
        duration_ms=duration_ms,
    )
    payload = asdict(ev)
    _recent.append(payload)
    # fan-out to all WebSocket subscribers (non-blocking)
    for q in list(_ws_subscribers):
        with contextlib.suppress(Exception):
            q.put_nowait(payload)
    return payload


@router.get("/agents/thinking/recent")
async def recent_thoughts(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Return the most recent N thought events (FIFO ring buffer)."""
    items = list(_recent)[-limit:]
    return {"events": items, "count": len(items)}


@router.websocket("/agents/thinking/stream")
async def stream_thoughts(ws: WebSocket) -> None:
    """WebSocket stream of new thought events."""
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _ws_subscribers.add(q)
    try:
        # Initial backlog
        for ev in list(_recent)[-10:]:
            await ws.send_text(json.dumps(ev))
        # Live fan-out
        while True:
            ev = await q.get()
            await ws.send_text(json.dumps(ev))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("thinking stream closed: %s", exc)
    finally:
        _ws_subscribers.discard(q)
