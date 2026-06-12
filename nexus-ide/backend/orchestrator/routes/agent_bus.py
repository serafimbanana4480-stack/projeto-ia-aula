"""Agent Bus REST + SSE routes.

Endpoints:
    POST /api/bus/publish      — Publish a message to a topic.
    GET  /api/bus/history/{topic} — Replay last N messages on a topic.
    GET  /api/bus/topics       — List known topics.
    GET  /api/bus/stream       — SSE stream of bus messages.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.core.agent_bus import BusMessage, get_agent_bus
from backend.middleware.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic request/response models ──────────────────────────────────────────


class BusPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=256)
    source_agent: str = Field(default="FRONTEND", min_length=1, max_length=128)
    target_agents: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=3, ge=1, le=5)
    ttl_seconds: int = Field(default=3600, ge=1)


class BusPublishResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    message_id: str
    topic: str
    timestamp: str


class BusHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    messages: list[dict[str, Any]]
    count: int


class BusTopicsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topics: list[str]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _sse_payload(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, default=str)}\n\n"


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/bus/publish", response_model=BusPublishResponse)
@limiter.limit("120/minute")
async def bus_publish(req: BusPublishRequest, request: Request) -> Any:
    """Publish a message to the Agent Bus."""
    import uuid

    bus = get_agent_bus()
    msg = BusMessage(
        message_id=uuid.uuid4().hex[:16],
        topic=req.topic,
        source_agent=req.source_agent,
        target_agents=req.target_agents,
        payload=req.payload,
        priority=req.priority,
        ttl_seconds=req.ttl_seconds,
    )
    await bus.publish(req.topic, msg)
    return BusPublishResponse(
        success=True,
        message_id=msg.message_id,
        topic=msg.topic,
        timestamp=msg.timestamp.isoformat(),
    )


@router.get("/bus/history/{topic}")
@limiter.limit("120/minute")
async def bus_history(
    request: Request,
    topic: str,
    limit: int = Query(50, ge=1, le=500),
    include_expired: bool = False,
) -> BusHistoryResponse:
    """Replay last *limit* messages on *topic*, newest first."""
    bus = get_agent_bus()
    messages = await bus.get_history(topic, limit=limit, include_expired=include_expired)
    return BusHistoryResponse(
        topic=topic,
        messages=[m.model_dump(mode="json") for m in messages],
        count=len(messages),
    )


@router.get("/bus/topics")
@limiter.limit("120/minute")
async def bus_topics(request: Request) -> BusTopicsResponse:
    """Return all topics that currently have history or subscribers."""
    bus = get_agent_bus()
    return BusTopicsResponse(topics=bus.get_topics())


@router.get("/bus/stream")
async def bus_stream(
    request: Request,
    topics: list[str] | None = Query(None),
    session_id: str | None = Query(None),
) -> StreamingResponse:
    """Stream Agent Bus messages via Server-Sent Events.

    Query parameters:
        topics:      Comma-separated or repeated topic filters.
        session_id:  If provided, only messages whose payload contains this
                     session_id are forwarded (best-effort filtering).
    """
    bus = get_agent_bus()
    filter_topics = set(t.lower().strip() for t in topics) if topics else None

    queue: asyncio.Queue[BusMessage | None] = asyncio.Queue(maxsize=1_000)

    async def _on_message(msg: BusMessage) -> None:
        if filter_topics and msg.topic not in filter_topics:
            return
        if session_id:
            # Best-effort session filtering via payload
            msg_session = msg.payload.get("session_id") if isinstance(msg.payload, dict) else None
            if msg_session and msg_session != session_id:
                return
        try:
            queue.put_nowait(msg)
        except asyncio.QueueFull:
            logger.warning("Agent Bus SSE queue full; dropping message %s", msg.message_id)

    # Subscribe to all requested topics (or "*" for everything)
    subs: list[Any] = []
    target_topics = topics if topics else ["*"]
    for t in target_topics:
        sub = await bus.subscribe(t, _on_message)
        subs.append(sub)

    async def _event_generator() -> AsyncIterator[str]:
        try:
            while True:
                msg = await queue.get()
                if msg is None:
                    break
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                yield _sse_payload({
                    "type": "bus_message",
                    "topic": msg.topic,
                    "message_id": msg.message_id,
                    "source_agent": msg.source_agent,
                    "target_agents": msg.target_agents,
                    "payload": msg.payload,
                    "timestamp": msg.timestamp.isoformat(),
                    "priority": msg.priority,
                })
        except asyncio.CancelledError:
            logger.debug("Agent Bus SSE stream cancelled")
        finally:
            # Unsubscribe all temporary subscriptions
            for sub in subs:
                try:
                    await bus.unsubscribe(sub.subscription_id)
                except Exception:
                    logger.debug("Failed to unsubscribe %s from bus", sub.subscription_id, exc_info=True)
            # Signal queue to drain
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                logger.debug("Agent Bus SSE queue full while draining")

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
