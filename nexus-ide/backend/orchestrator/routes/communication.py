"""API routes for agent communication bus."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.orchestrator.agent_communication_bus import (
    AgentCommunicationBus,
    AgentMessage,
)

router = APIRouter(prefix="/api/communication", tags=["communication"])

_bus: AgentCommunicationBus | None = None


def set_bus(bus: AgentCommunicationBus) -> None:
    global _bus
    _bus = bus


class SendMessageRequest(BaseModel):
    sender: str
    recipient: str
    message_type: str
    payload: dict[str, Any] = {}
    priority: int = 0


class MessageResponse(BaseModel):
    message_id: str
    sender: str
    recipient: str
    message_type: str
    payload: dict[str, Any]
    timestamp: float
    priority: int


@router.post("/messages", response_model=MessageResponse)
async def send_message(request: SendMessageRequest, http_request: Request) -> MessageResponse:
    if _bus is None:
        raise HTTPException(status_code=503, detail="Communication bus not available")
    msg = AgentMessage(
        message_id=f"msg-{uuid.uuid4().hex}",
        sender=request.sender,
        recipient=request.recipient,
        message_type=request.message_type,
        payload=request.payload,
        priority=request.priority,
    )
    _bus.send(msg)
    return MessageResponse(
        message_id=msg.message_id,
        sender=msg.sender,
        recipient=msg.recipient,
        message_type=msg.message_type,
        payload=msg.payload,
        timestamp=msg.timestamp,
        priority=msg.priority,
    )


@router.get("/history")
async def get_history(
    sender: str | None = None,
    recipient: str | None = None,
    message_type: str | None = None,
    limit: int = 100,
) -> list[MessageResponse]:
    if _bus is None:
        raise HTTPException(status_code=503, detail="Communication bus not available")
    messages = _bus.get_history(sender, recipient, message_type, limit)
    return [
        MessageResponse(
            message_id=m.message_id,
            sender=m.sender,
            recipient=m.recipient,
            message_type=m.message_type,
            payload=m.payload,
            timestamp=m.timestamp,
            priority=m.priority,
        )
        for m in messages
    ]


@router.get("/stats")
async def get_stats() -> dict:
    if _bus is None:
        raise HTTPException(status_code=503, detail="Communication bus not available")
    return _bus.stats()
