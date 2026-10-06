"""Enhanced FastAPI entry point for the NEXUS orchestrator.

This enhanced version includes:
- Event system initialization
- WebSocket server startup
- Real-time metrics collection
- Enhanced dashboard integration
- Memory system monitoring
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend import tools as _tools  # noqa: F401
from backend.agents.event_emitting_agent import (
    EventEmittingArchitectAgent,
    EventEmittingCoderAgent,
    EventEmittingDebuggerAgent,
)
from backend.config.settings import get_settings
from backend.dashboard.websocket_server import get_websocket_server, stop_websocket_server
from backend.memory.memory_dashboard import get_memory_dashboard, shutdown_memory_dashboard
from backend.metrics.realtime_metrics import get_metrics_collector, shutdown_metrics_collector
from backend.observability.event_system import get_event_bus, shutdown_event_system
from backend.observability.routes.alerts import router as alerts_router
from backend.observability.routes.metrics import router as metrics_router
from backend.orchestrator.context_manager import ContextStore
from backend.orchestrator.registry import build_default_registry
from backend.orchestrator.routes.additional import router as additional_router
from backend.orchestrator.routes.agents import router as agents_router
from backend.orchestrator.routes.chat import router as chat_router
from backend.orchestrator.routes.dashboard import router as dashboard_router
from backend.orchestrator.routes.enhanced_chat import router as enhanced_chat_router
from backend.orchestrator.routes.files import router as files_router
from backend.orchestrator.routes.knowledge import router as knowledge_router
from backend.orchestrator.routes.modes import router as modes_router
from backend.orchestrator.routes.observability import router as observability_router
from backend.orchestrator.routes.omega import router as omega_router
from backend.orchestrator.routes.projects import router as projects_router
from backend.orchestrator.routes.tasks import router as tasks_router
from backend.persistence import init_db
from backend.tools.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


@asynccontextmanager
async def enhanced_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Enhanced lifespan manager with all systems initialization."""
    
    logger.info("Starting enhanced NEXUS orchestrator...")
    
    # Initialize database
    await init_db()
    
    # Get settings
    settings = get_settings()
    
    # Initialize core systems
    app.state.ollama = OllamaClient(settings.ollama_host)
    app.state.registry = build_default_registry()
    app.state.context = ContextStore()
    
    # Initialize event system
    event_bus = await get_event_bus()
    app.state.event_bus = event_bus
    logger.info("Event system initialized")
    
    # Initialize WebSocket server
    websocket_server = await get_websocket_server(event_bus)
    app.state.websocket_server = websocket_server
    logger.info("WebSocket server initialized")
    
    # Initialize metrics collector
    metrics_collector = await get_metrics_collector(event_bus)
    app.state.metrics_collector = metrics_collector
    logger.info("Metrics collector initialized")
    
    # Initialize memory dashboard
    memory_dashboard = await get_memory_dashboard(event_bus)
    app.state.memory_dashboard = memory_dashboard
    logger.info("Memory dashboard initialized")
    
    # Register memory systems with dashboard
    if hasattr(app.state.context, 'memory_store'):
        await memory_dashboard.register_memory_system("main_memory", app.state.context.memory_store)
    if hasattr(app.state.context, 'vector_store'):
        await memory_dashboard.register_memory_system("vector_memory", app.state.context.vector_store)
    
    # Initialize enhanced agents with event emission
    enhanced_agents = []
    for agent_name, agent_class in [
        ("CODER", EventEmittingCoderAgent),
        ("ARCHITECT", EventEmittingArchitectAgent),
        ("DEBUGGER", EventEmittingDebuggerAgent)
    ]:
        try:
            agent = agent_class(event_bus)
            await agent.start()
            enhanced_agents.append(agent)
            logger.info(f"Enhanced agent {agent_name} initialized")
        except Exception as e:
            logger.error(f"Failed to initialize enhanced agent {agent_name}: {e}")
    
    app.state.enhanced_agents = enhanced_agents
    
    logger.info(f"NEXUS orchestrator ready (ollama={settings.ollama_host})")
    
    try:
        yield
    finally:
        # Cleanup all systems
        logger.info("Shutting down enhanced NEXUS orchestrator...")
        
        # Stop enhanced agents
        for agent in enhanced_agents:
            try:
                await agent.stop()
            except Exception as e:
                logger.error(f"Failed to stop agent {agent.name}: {e}")
        
        # Shutdown systems
        await stop_websocket_server()
        await shutdown_metrics_collector()
        await shutdown_memory_dashboard()
        await shutdown_event_system()
        
        await app.state.ollama.aclose()
        
        logger.info("Enhanced NEXUS orchestrator shutdown complete")


# Create enhanced FastAPI app
app = FastAPI(
    title="NEXUS IDE Enhanced Orchestrator", 
    version="2.0.0", 
    lifespan=enhanced_lifespan
)

# Dev CORS: frontend runs on :3000, backend on :8000
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routers
app.include_router(chat_router, prefix="/api")
app.include_router(enhanced_chat_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
app.include_router(alerts_router, prefix="/api")
app.include_router(modes_router, prefix="/api")
app.include_router(observability_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(agents_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")
app.include_router(additional_router, prefix="/api")
app.include_router(omega_router, prefix="/api")


@app.get("/health")
async def health() -> dict[str, str]:
    """Enhanced health check with system status."""
    return {"status": "ok", "version": "2.0.0"}


@app.get("/health/detailed")
async def detailed_health(request: Request) -> dict[str, Any]:
    """Detailed health check with all system status."""
    try:
        # Get event bus status
        event_bus = request.app.state.event_bus
        event_stats = await event_bus.get_stats()
        
        # Get WebSocket server status
        websocket_server = request.app.state.websocket_server
        websocket_stats = await websocket_server.get_stats()
        
        # Get metrics collector status
        metrics_collector = request.app.state.metrics_collector
        metrics_stats = await metrics_collector.get_stats()
        
        # Get memory dashboard status
        memory_dashboard = request.app.state.memory_dashboard
        memory_status = await memory_dashboard.get_memory_status()
        
        # Get enhanced agents status
        enhanced_agents = request.app.state.enhanced_agents
        agent_status = {
            agent.name: {
                "state": agent.state.value,
                "is_alive": agent.is_alive(),
                "current_task": agent.current_task_id,
                "metrics": agent.get_current_metrics()
            }
            for agent in enhanced_agents
        }
        
        return {
            "status": "healthy",
            "version": "2.0.0",
            "systems": {
                "event_bus": event_stats,
                "websocket_server": websocket_stats,
                "metrics_collector": metrics_stats,
                "memory_dashboard": memory_status,
                "enhanced_agents": agent_status
            },
            "timestamp": app.state.metrics_collector.stats.get("last_collection", "unknown")
        }
        
    except Exception as e:
        logger.error(f"Detailed health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "version": "2.0.0"
        }


@app.get("/api/system/status")
async def system_status(request: Request) -> dict[str, Any]:
    """Get comprehensive system status."""
    try:
        # Get all system statistics
        event_bus = request.app.state.event_bus
        websocket_server = request.app.state.websocket_server
        metrics_collector = request.app.state.metrics_collector
        memory_dashboard = request.app.state.memory_dashboard
        
        # Collect all stats
        event_stats = await event_bus.get_stats()
        websocket_stats = await websocket_server.get_stats()
        metrics_stats = await metrics_collector.get_stats()
        memory_status = await memory_dashboard.get_memory_status()
        
        # Get enhanced agents info
        enhanced_agents = request.app.state.enhanced_agents
        agent_info = []
        for agent in enhanced_agents:
            agent_info.append({
                "name": agent.name,
                "state": agent.state.value,
                "is_alive": agent.is_alive(),
                "current_task": agent.current_task_id,
                "capabilities": getattr(agent, 'capabilities', []),
                "metrics": agent.get_current_metrics()
            })
        
        return {
            "system": {
                "event_bus": event_stats,
                "websocket_server": websocket_stats,
                "metrics_collector": metrics_stats,
                "memory_dashboard": memory_status
            },
            "agents": agent_info,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"System status check failed: {e}")
        return {
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


@app.get("/api/system/metrics")
async def system_metrics(request: Request) -> dict[str, Any]:
    """Get system metrics."""
    try:
        metrics_collector = request.app.state.metrics_collector
        
        # Get all metrics
        system_metrics = await metrics_collector.get_metrics()
        aggregations = await metrics_collector.get_aggregations()
        
        return {
            "metrics": system_metrics,
            "aggregations": aggregations,
            "stats": await metrics_collector.get_stats()
        }
        
    except Exception as e:
        logger.error(f"System metrics failed: {e}")
        return {"error": str(e)}


@app.get("/api/system/events")
async def system_events(request: Request) -> dict[str, Any]:
    """Get recent system events."""
    try:
        event_bus = request.app.state.event_bus
        
        # Get recent events
        events = await event_bus.get_events(limit=100)
        
        return {
            "events": [event.to_dict() for event in events],
            "stats": await event_bus.get_stats()
        }
        
    except Exception as e:
        logger.error(f"System events failed: {e}")
        return {"error": str(e)}


def main() -> None:  # pragma: no cover
    """Dev entry point: ``python -m backend.orchestrator.main_enhanced``."""
    import uvicorn

    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    uvicorn.run(
        "backend.orchestrator.main_enhanced:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=True,
        log_level="info"
    )


if __name__ == "__main__":  # pragma: no cover
    main()