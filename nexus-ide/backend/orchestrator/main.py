"""FastAPI entry point for the NEXUS orchestrator.

Tier 1 exposes the critical vertical slice:

- ``GET  /health``                      liveness probe
- ``GET  /api/sessions/{id}/history``   conversation replay
- ``POST /api/chat``                    Server-Sent Events streaming

Remaining endpoints from ARCHITECTURE.md §7.3 (metrics, dashboard, files,
code-execution) are scheduled for later tiers.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config.settings import get_settings
from backend.observability.routes.alerts import router as alerts_router
from backend.observability.routes.metrics import router as metrics_router
from backend.orchestrator.context_manager import ContextStore
from backend.orchestrator.registry import build_default_registry
from backend.orchestrator.routes.chat import router as chat_router
from backend.orchestrator.routes.dashboard import router as dashboard_router
from backend.orchestrator.routes.files import router as files_router
from backend.orchestrator.routes.modes import router as modes_router
from backend.orchestrator.routes.projects import router as projects_router
from backend import tools as _tools  # noqa: F401
from backend.persistence import init_db
from backend.tools.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create long-lived singletons and guarantee clean shutdown.

    ``OllamaClient`` must be closed explicitly so httpx does not warn about
    orphaned connections. ``ContextStore`` and the agent registry are plain
    Python objects and need no teardown.
    """
    # Initialize database
    init_db()
    
    settings = get_settings()
    app.state.ollama = OllamaClient(settings.ollama_host)
    app.state.registry = build_default_registry()
    app.state.context = ContextStore()
    logger.info("NEXUS orchestrator ready (ollama=%s)", settings.ollama_host)
    try:
        yield
    finally:
        await app.state.ollama.aclose()


app = FastAPI(title="NEXUS IDE Orchestrator", version="0.1.0", lifespan=lifespan)

# Dev CORS: frontend runs on :3000, backend on :8000. Tighten for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
app.include_router(alerts_router, prefix="/api")
app.include_router(modes_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(files_router, prefix="/api")


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe. Returns ``200`` whenever the process is up."""
    return {"status": "ok"}


@app.get("/api/sessions/{session_id}/history")
async def get_history(session_id: str) -> dict[str, list[dict[str, str]]]:
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

    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    uvicorn.run(
        "backend.orchestrator.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=True,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
