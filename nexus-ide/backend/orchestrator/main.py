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
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, Request

from backend.config.settings import get_settings
from backend.middleware.security import SecurityHeadersMiddleware

try:
    from backend.config.settings import validate_configuration
except ImportError:

    def validate_configuration() -> list[str]:
        return []


from fastapi.middleware.cors import CORSMiddleware

from backend.middleware.auth import require_auth
from backend.observability.health import HealthChecker
from backend.observability.routes.alerts import router as alerts_router
from backend.observability.routes.health import router as health_router
from backend.observability.routes.metrics import router as metrics_router
from backend.observability.routes.usage import router as usage_router
from backend.orchestrator.routes.admin import router as admin_router
from backend.orchestrator.routes.advanced_modes import router as advanced_modes_router
from backend.orchestrator.routes.agent_bus import router as agent_bus_router
from backend.orchestrator.routes.agent_state import router as agent_state_router
from backend.orchestrator.routes.agents import router as agents_router
from backend.orchestrator.routes.analytics import router as analytics_router
from backend.orchestrator.routes.auth import router as auth_router
from backend.orchestrator.routes.autonomous_improvement import (
    router as autonomous_improvement_router,
)
from backend.orchestrator.routes.thinking import router as thinking_router

try:
    from backend.orchestrator.routes.browser import router as browser_router

    _BROWSER_AVAILABLE = True
except ImportError:
    _BROWSER_AVAILABLE = False
    browser_router = None
from backend.core.routes.improvement import router as improvement_router
from backend.observability.routes.workflows import router as workflows_router
from backend.orchestrator.chat_cancellation import chat_cancellation_middleware
from backend.orchestrator.routes.cancellation_routes import router as cancellation_router
from backend.orchestrator.routes.chat import router as chat_router
from backend.orchestrator.routes.collaboration import router as collaboration_router
from backend.orchestrator.routes.dashboard import router as dashboard_router
from backend.orchestrator.routes.email import router as email_router
from backend.orchestrator.routes.embeddings import router as embeddings_router
from backend.orchestrator.routes.errors import router as errors_router
from backend.orchestrator.routes.evolution import router as evolution_router
from backend.orchestrator.routes.files import router as files_router
from backend.orchestrator.routes.guardian import router as guardian_router
from backend.orchestrator.routes.knowledge import router as knowledge_router
from backend.orchestrator.routes.logs import router as logs_router
from backend.orchestrator.routes.mcp import router as mcp_router
from backend.orchestrator.routes.memories import router as memories_router
from backend.orchestrator.routes.meta import router as meta_router
from backend.orchestrator.routes.meta_analyzer import router as meta_analyzer_router
from backend.orchestrator.routes.models_ui import router as models_ui_router
from backend.orchestrator.routes.modes import router as modes_router
from backend.orchestrator.routes.neural_dashboard import router as neural_dashboard_router
from backend.orchestrator.routes.observability import agents_topology
from backend.orchestrator.routes.observability import router as observability_router
from backend.orchestrator.routes.omega import router as omega_router
from backend.orchestrator.routes.orchestrator import router as orchestrator_router
from backend.orchestrator.routes.overseer import router as overseer_router
from backend.orchestrator.routes.plan import router as plan_router
from backend.orchestrator.routes.profile import get_profile
from backend.orchestrator.routes.profile import router as profile_router
from backend.orchestrator.routes.projects import router as projects_router
from backend.orchestrator.routes.providers import router as providers_router
from backend.orchestrator.routes.second_brain import router as second_brain_router
from backend.orchestrator.routes.sessions import router as sessions_router
from backend.orchestrator.routes.settings import router as settings_router
from backend.orchestrator.routes.skills import router as skills_router
from backend.orchestrator.routes.system import router as system_router
from backend.orchestrator.routes.tasks import router as tasks_router
from backend.orchestrator.routes.terminal import router as terminal_router
from backend.orchestrator.routes.wizard import router as wizard_router
from backend.orchestrator.routes.workers import router as workers_router
from backend.orchestrator.routes.workspace import router as workspace_router
from backend.swarm.api.routes import router as swarm_router

logger = logging.getLogger(__name__)


#: Modules whose behaviour changes the outcome of an autonomous run. Their
#: content hash is logged at startup so a stale process is diagnosable from the
#: log alone.
_FINGERPRINTED_MODULES = (
    "backend/orchestrator/plan_creator.py",
    "backend/orchestrator/plan_executor.py",
    "backend/orchestrator/engine.py",
    "backend/orchestrator/verification.py",
    "backend/agents/base.py",
    "config/models.yaml",
)


def _log_code_fingerprint() -> None:
    """Record which *version of the source* this process is actually running.

    Motivation, with evidence. On 2026-07-27 the working tree contained a fixed
    ``plan_creator.py`` (mtime 08:38) yet the 09:18 run still logged
    ``"No JSON array found in plan content, creating single-step plan"`` — a
    string that exists only in the previous revision. Python had the old module
    object in memory and nothing in the log said so, which cost an entire
    debugging session chasing a bug that had already been fixed on disk.

    Best-effort by construction: a missing file or an unreadable path must
    never prevent the backend from starting.
    """
    import hashlib
    from datetime import datetime
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for relative in _FINGERPRINTED_MODULES:
        path = root / relative
        try:
            data = path.read_bytes()
        except OSError as exc:
            logger.warning("Code fingerprint unavailable for %s: %s", relative, exc)
            continue
        digest = hashlib.sha256(data).hexdigest()[:12]
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
        logger.info("Code fingerprint | %s | sha256=%s | mtime=%s", relative, digest, mtime)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create long-lived singletons and guarantee clean shutdown."""
    from backend.core.auto_correction import get_auto_correction_loop
    from backend.llm import create_llm_client
    from backend.observability.advanced_logging import get_structured_logger
    from backend.observability.logging_config import setup_logging
    from backend.observability.routes.workflows import init_workflow_tracker
    from backend.orchestrator.cancellation import get_cancellation_registry
    from backend.orchestrator.context_manager import ContextStore
    from backend.orchestrator.events import EventBus as OrchestrationEventBus
    from backend.orchestrator.registry import get_registry
    from backend.persistence import init_db
    from backend.persistence.db import recover_interrupted_runs
    setup_logging(level="DEBUG", json_format=True, log_file="logs/backend.log")
    slog = get_structured_logger()
    app.state.structured_logger = slog
    slog.info("NEXUS IDE backend starting", agent="SYSTEM", source="startup")
    _log_code_fingerprint()

    settings = get_settings()
    config_errors = validate_configuration()

    if config_errors:
        logger.error("Configuration validation failed at startup:")
        for error in config_errors:
            logger.error(f"  - {error}")
        raise RuntimeError(
            "Configuration validation failed. Please fix the errors before starting the application."
        )

    logger.info("Configuration validated successfully for environment: %s", settings.environment)
    init_db()
    recovered_runs = recover_interrupted_runs()
    slog.info(
        "Recovered stale execution runs",
        agent="SYSTEM",
        source="startup",
        extra={"recovered_count": len(recovered_runs)},
    )

    # Background services are individually opt-out via NEXUS_ENABLE_<SERVICE>=false.
    # They default ON in every environment, including development: NEXUS is a
    # local-first autonomous IDE, so the machine it runs on is exactly where
    # the dashboard agent, self-healing and the improvement orchestrator must
    # be alive. A previous default disabled everything in development, which
    # meant the entire autonomy stack was decorative in the environment where
    # the product is actually used. Set NEXUS_BACKGROUND_SERVICES=off to
    # disable the whole stack at once (e.g. in test runs or CI).
    master = os.environ.get("NEXUS_BACKGROUND_SERVICES", "").strip().lower()
    master_off = master in {"0", "false", "no", "off"}

    def _svc(name: str) -> bool:
        if master_off:
            return False
        raw = os.environ.get(f"NEXUS_ENABLE_{name}", "").strip().lower()
        if raw:
            return raw in {"1", "true", "yes", "on"}
        return True

    enable_workers       = _svc("BACKGROUND_WORKERS")
    enable_dashboard     = _svc("DASHBOARD_AGENT")
    enable_guardian      = _svc("GUARDIAN_AGENT")
    enable_auto_correct  = _svc("AUTO_CORRECTION")
    enable_exec_engine   = _svc("EXEC_ENGINE")
    enable_improvement   = _svc("CONTINUOUS_IMPROVEMENT")
    enable_self_improve  = _svc("SELF_IMPROVEMENT")
    enable_self_healing  = _svc("SELF_HEALING")
    enable_ai_orchestrator = _svc("AI_ORCHESTRATOR")
    enable_auto_trigger  = _svc("AUTO_TRIGGER")
    enable_session_gc    = _svc("SESSION_GC")

    off = [n for n, on in [
        ("BACKGROUND_WORKERS", enable_workers),
        ("DASHBOARD_AGENT", enable_dashboard),
        ("GUARDIAN_AGENT", enable_guardian),
        ("AUTO_CORRECTION", enable_auto_correct),
        ("EXEC_ENGINE", enable_exec_engine),
        ("CONTINUOUS_IMPROVEMENT", enable_improvement),
        ("SELF_IMPROVEMENT", enable_self_improve),
        ("SELF_HEALING", enable_self_healing),
        ("AI_ORCHESTRATOR", enable_ai_orchestrator),
        ("AUTO_TRIGGER", enable_auto_trigger),
        ("SESSION_GC", enable_session_gc),
    ] if not on]
    if off:
        logger.info("Disabled background services: %s (default is ON; NEXUS_ENABLE_<NAME>=false disables)", ", ".join(off))

    import backend.core.workspace as _workspace  # noqa: F401
    import backend.tools as _tools  # noqa: F401

    if not hasattr(app.state, "llm_client") or app.state.llm_client is None:
        app.state.llm_client = create_llm_client()

    registry = get_registry(app)
    app.state.context = ContextStore()
    app.state.event_bus = OrchestrationEventBus()
    app.state.workflow_tracker = init_workflow_tracker()

    from backend.core.agent_lifecycle import AgentLifecycleManager

    lifecycle = AgentLifecycleManager(registry=registry, llm_client=app.state.llm_client)
    overseer = registry.get("OVERSEER")
    if overseer:
        lifecycle.set_overseer_callback(
            lambda iid, event, data, ov=overseer: ov.record_agent_event(
                data.get("agent_type", "UNKNOWN"), event, {**data, "instance_id": iid}
            )
        )

    async def _on_background_agent_state(
        instance_id: str, event_type: str, data: dict[str, Any]
    ) -> None:
        """Bridge detached specialist work back into the chat session.

        ``spawn_task`` is intentionally non-blocking for the principal agent,
        so its result must have two durable destinations: the event bus for a
        live UI and the session history for refresh/recovery.
        """
        instance = lifecycle.get_status(instance_id)
        if instance is None:
            return

        from backend.orchestrator.events import EventType, OrchestratorEvent

        event_map = {
            "agent_started": EventType.AGENT_STARTED,
            "agent_finished": EventType.AGENT_FINISHED,
            "agent_failed": EventType.AGENT_FAILED,
        }
        mapped = event_map.get(event_type)
        event_data = {
            **data,
            "background": True,
            "instance_id": instance_id,
            "agent_type": instance.agent_type,
            "mission_id": instance.mission_id,
            "parent_task_id": instance.parent_task_id,
            "status": instance.status,
        }
        if mapped is not None:
            await app.state.event_bus.publish(
                OrchestratorEvent(
                    event_type=mapped,
                    source=instance.agent_type,
                    session_id=instance.mission_id,
                    task_id=instance_id,
                    content=(
                        f"{instance.agent_type} continua em background"
                        if event_type == "agent_started"
                        else f"{instance.agent_type} terminou em background"
                        if event_type == "agent_finished"
                        else f"{instance.agent_type} falhou em background"
                    ),
                    data=event_data,
                )
            )

        if event_type not in {"agent_finished", "agent_failed"} or not instance.mission_id:
            return

        # A lifecycle callback is the single completion boundary. Keep a
        # process-local guard because persistence is also attempted in the
        # normal success path and should never duplicate a specialist result.
        persisted = getattr(app.state, "background_results_persisted", None)
        if persisted is None:
            persisted = set()
            app.state.background_results_persisted = persisted
        if instance_id in persisted:
            return

        from backend.history_sanitizer import sanitize_history_content
        from backend.orchestrator.context_manager import ContextStore
        from backend.persistence.db import add_message, create_session, get_session
        from backend.tools.ollama_client import ChatMessage

        output = str(instance.context.get("output") or "").strip()
        if event_type == "agent_finished":
            output = sanitize_history_content("assistant", output)[:20_000]
            content = (
                f"[Subagente {instance.agent_type} concluído — {instance_id}]\n\n"
                f"{output or 'O subagente terminou sem texto de resposta.'}"
            )
        else:
            error = str(instance.error_message or data.get("error") or "erro desconhecido")
            content = f"[Subagente {instance.agent_type} falhou — {instance_id}]\n\n{error[:2_000]}"

        try:
            if get_session(instance.mission_id) is None:
                create_session(
                    title=instance.objective[:60] or "Sessão Nexus",
                    mode="auto",
                    session_id=instance.mission_id,
                )
            now = datetime.now(UTC).isoformat()
            context_store: ContextStore = app.state.context
            await context_store.append_message(
                instance.mission_id,
                ChatMessage(role="assistant", content=content, timestamp=now),
            )
            add_message(
                instance.mission_id,
                "assistant",
                content,
                tier_used=instance.agent_type,
                latency_ms=int(
                    max(0.0, instance.completed_at - instance.start_time) * 1000
                ),
            )
            persisted.add(instance_id)
        except Exception:
            logger.exception("Could not persist background result %s", instance_id)

    lifecycle.set_state_callback(_on_background_agent_state)
    app.state.agent_lifecycle = lifecycle
    app.state.background_results_persisted = set()
    app.state.registry = registry
    logger.info("Agent lifecycle manager ready")

    from backend.core.background_workers import BackgroundWorkerManager

    worker_manager = BackgroundWorkerManager() if enable_workers else None
    if worker_manager:
        await worker_manager.start_all()
    app.state.worker_manager = worker_manager
    if worker_manager:
        logger.info("Background workers started")

    from backend.agents.dashboard_agent import DashboardAgent

    dashboard = DashboardAgent()
    app.state.dashboard_agent = dashboard
    monitor_task = asyncio.create_task(dashboard.monitor_loop()) if enable_dashboard else None
    summary_task = asyncio.create_task(dashboard.session_summary_loop()) if enable_dashboard else None
    app.state.dashboard_monitor_task = monitor_task
    app.state.dashboard_summary_task = summary_task
    if enable_dashboard:
        logger.info("Dashboard agent loops started")

    from backend.agents.guardian import NexusGuardianAgent

    guardian = NexusGuardianAgent()
    guardian_task = await guardian.start() if enable_guardian else None
    app.state.guardian_agent = guardian
    app.state.guardian_task = guardian_task
    if enable_guardian:
        logger.info("Guardian agent loop started")

    auto_correction = get_auto_correction_loop(lifecycle_manager=lifecycle)
    if enable_auto_correct:
        await auto_correction.start_monitoring()
    app.state.auto_correction = auto_correction
    if enable_auto_correct:
        logger.info("Auto-correction loop started")

    from backend.orchestrator.autonomous_execution_engine import AutonomousExecutionEngine

    exec_engine = AutonomousExecutionEngine(max_concurrent=5)
    app.state.autonomous_execution_engine = exec_engine
    if enable_exec_engine:
        logger.info("Autonomous execution engine started (max_concurrent=5)")

    from backend.core.continuous_improvement import get_continuous_improvement_loop

    improvement_loop = get_continuous_improvement_loop()
    if enable_improvement:
        await improvement_loop.start()
    app.state.improvement_loop = improvement_loop
    if enable_improvement:
        logger.info("Continuous improvement loop started")

    from backend.orchestrator.self_improvement_loop import SelfImprovementLoop

    improver = SelfImprovementLoop(target_metrics=["response_time", "accuracy", "throughput", "success_rate"])
    app.state.self_improvement_loop = improver
    if enable_self_improve:
        logger.info("Self-improvement loop started")

    auto_apply = settings.environment == "production" or os.environ.get("NEXUS_AUTO_APPLY", "false").lower() == "true"
    from backend.core.self_healing_engine import SelfHealingEngine

    healer = SelfHealingEngine(
        auto_apply=auto_apply,
        dry_run=settings.environment == "development",
        min_confidence=0.7,
        analysis_interval=3600,
    )
    if enable_self_healing:
        await healer.start()
    app.state.healer = healer
    if enable_self_healing:
        logger.info("Self-healing engine started (auto_apply=%s, dry_run=%s)", auto_apply, settings.environment == "development")

    from backend.config.settings import get_autonomous_improvement_config
    from backend.orchestrator.autonomous_improvement_orchestrator import (
        get_autonomous_improvement_orchestrator,
    )

    ai_config = get_autonomous_improvement_config()
    ai_orchestrator = get_autonomous_improvement_orchestrator(
        config=ai_config,
        lifecycle_manager=lifecycle,
        llm_client=app.state.llm_client,
        registry=registry,
        event_bus=app.state.event_bus,
    )
    if enable_ai_orchestrator:
        await ai_orchestrator.start()
    app.state.ai_orchestrator = ai_orchestrator
    if enable_ai_orchestrator:
        logger.info("Autonomous improvement orchestrator started (interval=%sm)", ai_config.get("cycle_interval_minutes", 30))

    from backend.orchestrator.auto_trigger_engine import AutoTriggerEngine

    auto_trigger = AutoTriggerEngine(orchestrator=ai_orchestrator)
    if enable_auto_trigger:
        await auto_trigger.start()
    app.state.auto_trigger = auto_trigger
    if enable_auto_trigger:
        logger.info("Auto trigger engine started (rules=%d)", len(AutoTriggerEngine.TRIGGER_RULES))

    from pathlib import Path
    evolution_log = Path(__file__).resolve().parent.parent.parent / "data" / "evolution_log.md"
    if not evolution_log.exists():
        evolution_log.parent.mkdir(parents=True, exist_ok=True)
        evolution_log.write_text(
            f"# NEXUS IDE Evolution Log\n\n"
            f"Started: {datetime.now(UTC).isoformat()}\n"
            f"Auto-heal: {auto_apply}\n"
            f"---\n",
            encoding="utf-8"
        )
        logger.info("Evolution log created at %s", evolution_log)

    from backend.orchestrator.session_lifecycle import SessionLifecycleManager

    session_lifecycle = SessionLifecycleManager(event_bus=app.state.event_bus)
    if enable_session_gc:
        session_lifecycle.start()
    app.state.session_lifecycle = session_lifecycle
    if enable_session_gc:
        logger.info("Session lifecycle GC started (ttl=%dh, interval=%dmin)", session_lifecycle.ttl_hours, session_lifecycle.gc_interval_minutes)

    logger.info("NEXUS orchestrator ready (provider=%s)", settings.llm_provider)
    try:
        yield
    finally:
        if monitor_task:
            monitor_task.cancel()
        if summary_task:
            summary_task.cancel()
        if enable_guardian:
            await guardian.stop()
        await get_cancellation_registry().shutdown()
        if enable_auto_correct:
            await auto_correction.stop_monitoring()
        healer = getattr(app.state, "healer", None)
        if healer:
            await healer.stop()
        ai_orchestrator = getattr(app.state, "ai_orchestrator", None)
        if ai_orchestrator:
            await ai_orchestrator.stop()
        auto_trigger = getattr(app.state, "auto_trigger", None)
        if auto_trigger:
            await auto_trigger.stop()
        improvement_loop = getattr(app.state, "improvement_loop", None)
        if improvement_loop:
            await improvement_loop.stop()
        logger.info("Autonomous execution engine shut down")
        session_lifecycle = getattr(app.state, "session_lifecycle", None)
        if session_lifecycle:
            await session_lifecycle.stop()
        worker_manager = getattr(app.state, "worker_manager", None)
        if worker_manager:
            await worker_manager.stop_all()
        await asyncio.gather(
            *(task for task in (monitor_task, summary_task, guardian_task) if task is not None),
            return_exceptions=True,
        )
        from backend.orchestrator.llm_client_lifecycle import close_all_llm_clients
        await close_all_llm_clients(app)


app = FastAPI(title="NEXUS IDE Orchestrator", version="0.1.0", lifespan=lifespan)

app.add_middleware(SecurityHeadersMiddleware)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins_list(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Nexus-Request-Id"],
    expose_headers=["X-Nexus-Request-Id"],
)


@app.middleware("http")
async def _track_chat_cancellation(request: Request, call_next):
    return await chat_cancellation_middleware(request, call_next)


app.include_router(auth_router, prefix="/api")
app.include_router(admin_router)
if _BROWSER_AVAILABLE:
    app.include_router(browser_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(cancellation_router)
app.include_router(dashboard_router, prefix="/api")
app.include_router(email_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
app.include_router(health_router, prefix="/api")
app.include_router(alerts_router, prefix="/api")
app.include_router(usage_router, prefix="/api")
app.include_router(modes_router, prefix="/api")
app.include_router(profile_router, prefix="/api")
app.add_api_route("/api/me", get_profile, methods=["GET"], tags=["profile"])
app.include_router(projects_router, prefix="/api")
app.include_router(providers_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(terminal_router, prefix="/api")
app.include_router(embeddings_router, prefix="/api")
app.include_router(memories_router, prefix="/api")
app.include_router(plan_router, prefix="/api")
app.include_router(guardian_router, prefix="/api")
app.include_router(overseer_router, prefix="/api")
app.include_router(wizard_router, prefix="/api")
app.include_router(mcp_router, prefix="/api")
app.include_router(agent_state_router, prefix="/api")
app.include_router(workspace_router, prefix="/api")
app.include_router(agent_bus_router, prefix="/api")
app.include_router(meta_router, prefix="/api")
app.include_router(meta_analyzer_router, prefix="/api")
app.include_router(collaboration_router, prefix="/api")
app.include_router(workers_router, prefix="/api")
app.include_router(agents_router, prefix="/api")
app.include_router(observability_router, prefix="/api")
app.include_router(thinking_router, prefix="/api")
app.include_router(system_router, prefix="/api")
app.include_router(improvement_router)
app.include_router(autonomous_improvement_router)
app.include_router(second_brain_router, prefix="/api")
app.include_router(orchestrator_router, prefix="/api")
app.include_router(skills_router, prefix="/api")
app.include_router(models_ui_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(logs_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(neural_dashboard_router, prefix="/api")
app.add_api_route("/api/agents/topology", agents_topology, methods=["GET"], tags=["agents"])
app.include_router(omega_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")
app.include_router(errors_router, prefix="/api")
app.include_router(workflows_router, prefix="/api")
app.include_router(sessions_router)
app.include_router(swarm_router)
app.include_router(advanced_modes_router, prefix="/api")
app.include_router(evolution_router, prefix="/api")

from backend.orchestrator.routes.meta import mission_websocket as _meta_ws  # noqa: E402

app.add_api_websocket_route("/ws/missions/{mission_id}", _meta_ws)


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    # Keep the historical ``/health?deep=true`` probe working for local
    # monitors and smoke tests. The dedicated ``/health/deep`` endpoint still
    # enforces authentication; this compatibility form exposes only the same
    # bounded component statuses needed by the local runtime dashboard.
    if request.query_params.get("deep", "").lower() in {"1", "true", "yes"}:
        return await HealthChecker(request.app.state).check_all()
    return {"status": "ok"}


@app.get("/health/deep")
async def health_deep(
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    checker = HealthChecker(request.app.state)
    return await checker.check_all()


@app.get("/api/sessions/{session_id}/history")
async def get_history(
    request: Request,
    session_id: str,
    _user: dict = Depends(require_auth),
) -> dict[str, list[dict[str, str]]]:
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
    import uvicorn

    settings = get_settings()
    config_errors = validate_configuration()

    if config_errors:
        logger.error("Configuration validation failed:")
        for error in config_errors:
            logger.error(f"  - {error}")
        raise SystemExit(
            "Configuration validation failed. Please fix the errors above before starting the application."
        )

    logger.info("Starting NEXUS IDE Orchestrator in %s mode", settings.environment)
    logging.basicConfig(level=settings.log_level)

    uvicorn.run(
        "backend.orchestrator.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=settings.debug,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
