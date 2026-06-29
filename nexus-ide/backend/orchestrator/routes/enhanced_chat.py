
"""Enhanced Chat Routes - Real-time chat with dashboard integration."""


import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.orchestrator.limiter import limiter

from backend.models.api import ChatRequest
from backend.observability.event_system import get_event_bus
from backend.orchestrator.enhanced_chat import get_chat_system

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat")
@limiter.limit("30/minute")
async def enhanced_chat(req: ChatRequest, request: Request) -> StreamingResponse:
    """Enhanced chat endpoint with real-time events and dashboard integration."""
    
    # Get dependencies
    ollama = request.app.state.ollama
    registry = request.app.state.registry
    
    # Get event bus and chat system
    event_bus = await get_event_bus()
    chat_system = await get_chat_system(event_bus)
    
    async def event_stream() -> AsyncIterator[str]:
        async for chunk in chat_system.process_chat_request(req, ollama, registry):
            yield chunk
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/chat/sessions")
async def get_chat_sessions(request: Request) -> dict:
    """Get all active chat sessions."""
    event_bus = await get_event_bus()
    chat_system = await get_chat_system(event_bus)
    
    return await chat_system.get_all_sessions()


@router.get("/chat/sessions/{session_id}")
async def get_chat_session(session_id: str, request: Request) -> dict:
    """Get specific chat session information."""
    event_bus = await get_event_bus()
    chat_system = await get_chat_system(event_bus)
    
    session_info = await chat_system.get_session_info(session_id)
    if not session_info:
        return {"error": "Session not found"}
    
    return session_info


@router.post("/chat/sessions/cleanup")
@limiter.limit("30/minute")
async def cleanup_inactive_sessions(request: Request) -> dict:
    """Clean up inactive chat sessions."""
    event_bus = await get_event_bus()
    chat_system = await get_chat_system(event_bus)
    
    # Get cleanup timeout from request body or use default
    cleanup_timeout = 3600  # 1 hour default
    
    cleaned_count = await chat_system.cleanup_inactive_sessions(cleanup_timeout)
    
    return {
        "cleaned_sessions": cleaned_count,
        "timeout_seconds": cleanup_timeout
    }


@router.get("/chat/stats")
async def get_chat_stats(request: Request) -> dict:
    """Get chat system statistics."""
    event_bus = await get_event_bus()
    chat_system = await get_chat_system(event_bus)
    
    return await chat_system.get_system_stats()