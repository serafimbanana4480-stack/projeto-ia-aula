"""FastAPI entry point for the NEXUS orchestrator.

Tier 1 exposes the critical vertical slice:

- ``GET  /health``                      liveness probe
- ``GET  /api/sessions/{id}/history``   conversation replay
- ``POST /api/chat``                    Server-Sent Events streaming

Remaining endpoints from ARCHITECTURE.md §7.3 (metrics, dashboard, files,
code-execution) are scheduled for later tiers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.config.settings import get_settings, validate_configuration
from backend.middleware.rate_limit import limiter
from backend.middleware.security import SecurityHeadersMiddleware
from backend.observability.routes.alerts import router as alerts_router
from backend.observability.routes.metrics import router as metrics_router
from backend.orchestrator.routes.agent_bus import router as agent_bus_router
from backend.orchestrator.routes.agent_state import router as agent_state_router
from backend.orchestrator.routes.agents import router as agents_router
from backend.orchestrator.routes.auth import router as auth_router
from backend.orchestrator.routes.chat import router as chat_router
from backend.orchestrator.routes.dashboard import router as dashboard_router
from backend.orchestrator.routes.files import router as files_router
from backend.orchestrator.routes.guardian import router as guardian_router
from backend.orchestrator.routes.meta import router as meta_router
from backend.orchestrator.routes.meta_analyzer import router as meta_analyzer_router
from backend.orchestrator.routes.modes import router as modes_router
from backend.orchestrator.routes.overseer import router as overseer_router
from backend.orchestrator.routes.plan import router as plan_router
from backend.orchestrator.routes.projects import router as projects_router
from backend.orchestrator.routes.system import router as system_router
from backend.orchestrator.routes.terminal import router as terminal_router
from backend.orchestrator.routes.workers import router as workers_router
from backend.orchestrator.routes.workspace import router as workspace_router
from backend.orchestrator.routes.embeddings import router as embeddings_router
from backend.orchestrator.routes.wizard import router as wizard_router
from backend.orchestrator.routes.collaboration import router as collaboration_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create long-lived singletons and guarantee clean shutdown.

    ``llm_client`` must be closed explicitly so httpx does not warn about
    orphaned connections. ``ContextStore`` and the agent registry are plain
    Python objects and need no teardown.
    """
    # Lazy imports of heavy modules to keep import-time / worker start-up fast
    from backend.persistence import init_db
    from backend.llm import create_llm_client
    from backend.orchestrator.context_manager import ContextStore
    from backend.orchestrator.events import EventBus as OrchestrationEventBus
    from backend.orchestrator.registry import get_registry
    from backend.core.auto_correction import get_auto_correction_loop

    # Validate configuration at startup
    settings = get_settings()
    config_errors = validate_configuration()

    if config_errors:
        logger.error("Configuration validation failed at startup:")
        for error in config_errors:
            logger.error(f"  - {error}")
        raise RuntimeError(
            "Configuration validation failed. Please fix the errors before starting the application."
        )

    logger.info(f"Configuration validated successfully for environment: {settings.environment}")

    # Initialize database
    init_db()

    # Lazy-load tools and workspace modules so their heavy imports don't block
    # startup.  They self-register on first import.
    import backend.tools as _tools  # noqa: F401
    import backend.core.workspace as _workspace  # noqa: F401

    # Lazy-init LLM client (cached in app.state)
    if not hasattr(app.state, "llm_client") or app.state.llm_client is None:
        app.state.llm_client = create_llm_client()

    # Lazy-init registry on first access instead of eagerly at startup
    registry = get_registry(app)
    app.state.context = ContextStore()
    app.state.event_bus = OrchestrationEventBus()

    # Initialize Agent Lifecycle Manager
    from backend.core.agent_lifecycle import AgentLifecycleManager

    lifecycle = AgentLifecycleManager(registry=registry, llm_client=app.state.llm_client)
    # Wire overseer callback if overseer is in registry
    overseer = registry.get("OVERSEER")
    if overseer:
        lifecycle.set_overseer_callback(
            lambda iid, event, data, ov=overseer: ov.record_agent_event(
                data.get("agent_type", "UNKNOWN"), event, {**data, "instance_id": iid}
            )
        )
    app.state.agent_lifecycle = lifecycle
    app.state.registry = registry
    logger.info("Agent lifecycle manager initialized (execution enabled)")

    # Start Background Workers
    from backend.core.background_workers import BackgroundWorkerManager

    worker_manager = BackgroundWorkerManager()
    await worker_manager.start_all()
    app.state.worker_manager = worker_manager
    logger.info("Background workers started")

    # Start DashboardAgent background loops
    from backend.agents.dashboard_agent import DashboardAgent

    dashboard = DashboardAgent()
    monitor_task = asyncio.create_task(dashboard.monitor_loop())
    summary_task = asyncio.create_task(dashboard.session_summary_loop())
    app.state.dashboard_monitor_task = monitor_task
    app.state.dashboard_summary_task = summary_task
    logger.info("Dashboard agent background loops started")

    # Start GuardianAgent background loop
    from backend.agents.guardian import NexusGuardianAgent

    guardian = NexusGuardianAgent()
    guardian_task = asyncio.create_task(guardian.monitor_loop())
    app.state.guardian_agent = guardian
    app.state.guardian_task = guardian_task
    logger.info("Guardian agent background loop started")

    # Start Auto-Correction Loop
    auto_correction = get_auto_correction_loop(lifecycle_manager=lifecycle)
    await auto_correction.start_monitoring()
    app.state.auto_correction = auto_correction
    logger.info("Auto-correction loop started")

    logger.info("NEXUS orchestrator ready (provider=%s)", settings.llm_provider)
    try:
        yield
    finally:
        # Cancel dashboard background loops
        monitor_task.cancel()
        summary_task.cancel()
        # Cancel guardian background loop
        await guardian.stop()
        guardian_task.cancel()
        # Stop auto-correction loop
        await auto_correction.stop_monitoring()
        # Stop background workers
        worker_manager = getattr(app.state, "worker_manager", None)
        if worker_manager:
            await worker_manager.stop_all()
        # Wait for all background tasks to finish cleanly
        await asyncio.gather(
            monitor_task, summary_task, guardian_task,
            return_exceptions=True,
        )
        await app.state.llm_client.aclose()


app = FastAPI(title="NEXUS IDE Orchestrator", version="0.1.0", lifespan=lifespan)

# Setup rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# CORS configuration from settings - restrictive, no wildcards
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins_list(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Include routers
app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
app.include_router(alerts_router, prefix="/api")
app.include_router(modes_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(terminal_router, prefix="/api")
app.include_router(embeddings_router, prefix="/api")
app.include_router(plan_router, prefix="/api")
app.include_router(guardian_router, prefix="/api")
app.include_router(overseer_router, prefix="/api")
app.include_router(wizard_router, prefix="/api")
app.include_router(agent_state_router, prefix="/api")
app.include_router(workspace_router, prefix="/api")
app.include_router(agent_bus_router, prefix="/api")
app.include_router(meta_router, prefix="/api")
app.include_router(meta_analyzer_router, prefix="/api")
app.include_router(collaboration_router, prefix="/api")
app.include_router(workers_router, prefix="/api")
app.include_router(agents_router, prefix="/api")
app.include_router(system_router, prefix="/api")

# MetaOrchestrator WebSocket — mounted directly so path is ``/ws/missions/{id}``
from backend.orchestrator.routes.meta import mission_websocket as _meta_ws  # noqa: E402
app.add_api_websocket_route("/ws/missions/{mission_id}", _meta_ws)


@app.get("/health")
@limiter.limit("100/minute")
async def health(request: Request) -> dict[str, str]:
    """Liveness probe. Returns ``200`` whenever the process is up."""
    return {"status": "ok"}


@app.get("/api/sessions/{session_id}/history")
@limiter.limit("200/minute")
async def get_history(request: Request, session_id: str) -> dict[str, list[dict[str, str]]]:
    """Return the rolling conversation history for a session."""
    history = await app.state.context.get_history(session_id)
    return {
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": getattr(m, "timestamp", ""),
                **({"agent": m.agent} if getattr(m, "agent", None) else {}),
                **({"metrics": m.metrics} if getattr(m, "metrics", None) else {}),
            }
            for m in history
        ]
    }


def main() -> None:  # pragma: no cover
    """Dev entry point: ``python -m backend.orchestrator.main``."""
    import uvicorn

    # Validate configuration before starting the application
    settings = get_settings()
    config_errors = validate_configuration()

    if config_errors:
        logger.error("Configuration validation failed:")
        for error in config_errors:
            logger.error(f"  - {error}")
        raise SystemExit(
            "Configuration validation failed. Please fix the errors above before starting the application."
        )

    logger.info(f"Starting NEXUS IDE Orchestrator in {settings.environment} mode")
    logging.basicConfig(level=settings.log_level)

    uvicorn.run(
        "backend.orchestrator.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=settings.debug,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
