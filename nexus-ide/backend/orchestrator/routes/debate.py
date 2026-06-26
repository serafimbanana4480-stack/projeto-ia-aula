from __future__ import annotations

"""API routes for debate visualization."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Optional

from backend.orchestrator.limiter import limiter

from backend.orchestrator.debate_visualizer import DebateVisualizer, Stance

router = APIRouter(prefix="/api/debate", tags=["debate"])

_debate_viz: Optional[DebateVisualizer] = None


def set_debate_visualizer(viz: DebateVisualizer) -> None:
    global _debate_viz
    _debate_viz = viz


class CreateSessionRequest(BaseModel):
    session_id: str
    topic: str
    participants: list[str]


class AddArgumentRequest(BaseModel):
    agent_id: str
    stance: str
    content: str
    confidence: float = 0.5


@router.post("/sessions")
@limiter.limit("30/minute")
async def create_session(request: CreateSessionRequest, http_request: Request) -> dict[str, Any]:
    if _debate_viz is None:
        raise HTTPException(status_code=503, detail="Debate visualizer not available")
    session = _debate_viz.create_session(request.session_id, request.topic, request.participants)
    return {"session_id": session.session_id, "status": session.status}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    if _debate_viz is None:
        raise HTTPException(status_code=503, detail="Debate visualizer not available")
    session = _debate_viz.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.get_summary()


@router.post("/sessions/{session_id}/arguments")
@limiter.limit("30/minute")
async def add_argument(session_id: str, request: AddArgumentRequest, http_request: Request) -> dict[str, Any]:
    if _debate_viz is None:
        raise HTTPException(status_code=503, detail="Debate visualizer not available")
    try:
        stance = Stance(request.stance)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid stance: {request.stance}")
    arg = _debate_viz.add_argument(session_id, request.agent_id, stance, request.content, request.confidence)
    if not arg:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "argument_id": arg.argument_id,
        "agent_id": arg.agent_id,
        "stance": arg.stance.value,
        "confidence": arg.confidence,
    }


@router.post("/sessions/{session_id}/complete")
@limiter.limit("30/minute")
async def complete_session(session_id: str, http_request: Request) -> dict[str, Any]:
    if _debate_viz is None:
        raise HTTPException(status_code=503, detail="Debate visualizer not available")
    if not _debate_viz.complete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "completed"}


@router.get("/sessions/{session_id}/live")
async def get_live_state(session_id: str) -> dict[str, Any]:
    if _debate_viz is None:
        raise HTTPException(status_code=503, detail="Debate visualizer not available")
    state = _debate_viz.get_live_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    return state
