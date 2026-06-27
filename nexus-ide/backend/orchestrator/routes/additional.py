
"""Additional routes for dashboard functionality.

Provides endpoints for commits, tools, web search, etc.
"""

import logging
import random
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from backend.orchestrator.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/commits/recent")
async def get_recent_commits() -> list[dict]:
    """Return recent git commits."""
    # Mock data - in production this would come from actual git operations
    return [
        {
            "hash": "a1b2c3d4e5f6g7h8i9j0",
            "message": "feat: implement dashboard components",
            "author": "AI Agent",
            "timestamp": "2026-05-09T10:30:00Z",
        },
        {
            "hash": "b2c3d4e5f6g7h8i9j0k1l",
            "message": "fix: resolve circular import issue",
            "author": "AI Agent",
            "timestamp": "2026-05-09T09:45:00Z",
        },
        {
            "hash": "c3d4e5f6g7h8i9j0k1l2m",
            "message": "docs: update architecture documentation",
            "author": "AI Agent",
            "timestamp": "2026-05-09T08:30:00Z",
        },
    ]


@router.get("/tools")
async def get_tools() -> dict:
    """Return available tools."""
    return {
        "tools": [
            {
                "name": "read_file",
                "description": "Read file contents",
                "enabled": True,
            },
            {
                "name": "write_file",
                "description": "Write file contents",
                "enabled": True,
            },
            {
                "name": "execute_code",
                "description": "Execute code in sandbox",
                "enabled": True,
            },
            {
                "name": "search_web",
                "description": "Search the web",
                "enabled": True,
            },
            {
                "name": "database_query",
                "description": "Query database",
                "enabled": False,
            },
        ],
    }


@router.post("/web_search")
@limiter.limit("60/minute")
async def web_search(query: dict, request: Request) -> list[dict]:
    """Perform web search."""
    # Mock data - in production this would use actual web search API
    return [
        {
            "title": f"Results for {query.get('query', 'test')}",
            "url": "https://example.com",
            "snippet": "This is a mock search result for demonstration purposes.",
        },
    ]


@router.get("/system/status")
async def get_system_status(
    min_agents: int = Query(0, ge=0, le=100, description="Minimum number of agents to return"),
    max_agents: int = Query(10, ge=0, le=100, description="Maximum number of agents to return"),
) -> dict:
    """Return overall system status."""
    if min_agents > max_agents:
        raise HTTPException(
            status_code=400,
            detail="min_agents must be less than or equal to max_agents"
        )
    
    # Mock data - in production this would come from actual system monitoring
    return {
        "status": "operational",
        "agents_active": random.randint(min_agents, min(max_agents, min_agents + 5)),
        "models_executing": random.randint(1, 3),
        "tasks_running": random.randint(2, 5),
        "self_improvement_enabled": False,
    }


@router.get("/self-improvement/improvements")
async def get_self_improvement_improvements(
    limit: int = Query(10, ge=1, le=100, description="Number of improvements to return")
) -> list[dict]:
    """Return self-improvement records."""
    # Try to get real data from MetaLearner
    try:
        from backend.orchestrator.meta_learner import MetaLearner
        # Note: MetaLearner would need to be initialized in main.py and accessible
        # For now, we'll return empty list if not available
        # In production, this would query the MetaLearner for actual improvements
        logger.info("MetaLearner integration not yet initialized - returning empty improvements")
        return []
    except Exception as e:
        logger.warning(f"Failed to get self-improvement data: {e}")
        return []


@router.get("/self-improvement/metrics")
async def get_self_improvement_metrics(
    limit: int = Query(10, ge=1, le=50, description="Number of metrics to return")
) -> list[dict]:
    """Return metric improvements."""
    # Try to get real data from MetaLearner
    try:
        from backend.orchestrator.meta_learner import MetaLearner
        # Note: MetaLearner would need to be initialized in main.py and accessible
        # For now, we'll return empty list if not available
        # In production, this would query the MetaLearner for actual metrics
        logger.info("MetaLearner integration not yet initialized - returning empty metrics")
        return []
    except Exception as e:
        logger.warning(f"Failed to get self-improvement metrics: {e}")
        return []


@router.get("/self-improvement/learnings")
async def get_self_improvement_learnings(
    limit: int = Query(20, ge=1, le=100, description="Number of learnings to return"),
    min_confidence: float = Query(0.5, ge=0.0, le=1.0, description="Minimum confidence threshold")
) -> list[dict]:
    """Return learned patterns."""
    # Try to get real data from MetaLearner
    try:
        from backend.orchestrator.meta_learner import MetaLearner
        # Note: MetaLearner would need to be initialized in main.py and accessible
        # For now, we'll return empty list if not available
        # In production, this would query the MetaLearner for actual learnings
        logger.info("MetaLearner integration not yet initialized - returning empty learnings")
        return []
    except Exception as e:
        logger.warning(f"Failed to get self-improvement learnings: {e}")
        return []


@router.get("/self-improvement/stream")
async def self_improvement_stream():
    """Stream self-improvement updates via SSE."""
    import json
    import asyncio
    import time
    
    async def event_generator():
        while True:
            # Send heartbeat
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
            
            # Try to get real events from MetaLearner
            try:
                from backend.orchestrator.meta_learner import MetaLearner
                # Note: MetaLearner would need to be initialized in main.py and accessible
                # For now, we'll just send heartbeat
                # In production, this would stream real events from MetaLearner
                logger.debug("MetaLearner integration not yet initialized - sending heartbeat only")
            except Exception as e:
                logger.warning(f"Failed to get self-improvement stream events: {e}")
            
            await asyncio.sleep(2)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/system/health")
async def get_system_health() -> dict:
    """Return system health snapshot for frontend Mission Control."""
    return {
        "workers": [
            {"name": "chat", "status": "healthy", "last_run": None, "queue_size": 0},
            {"name": "agents", "status": "healthy", "last_run": None, "queue_size": 0},
            {"name": "missions", "status": "healthy", "last_run": None, "queue_size": 0},
            {"name": "bus", "status": "healthy", "last_run": None, "queue_size": 0},
            {"name": "dashboard", "status": "healthy", "last_run": None, "queue_size": 0},
        ]
    }
