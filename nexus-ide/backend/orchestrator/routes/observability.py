
"""Observability routes for the NEXUS IDE professional dashboard.

Provides real-time data for: agents, topology, task pipeline, events, commits,
knowledge graph stats, active sessions, and request flow.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.orchestrator.events import EventBus, OrchestratorEvent
from backend.orchestrator.registry import build_default_registry

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_event_bus(request: Request) -> EventBus:
    if not hasattr(request.app.state, "event_bus"):
        request.app.state.event_bus = EventBus()
    return request.app.state.event_bus


def _get_registry(request: Request) -> dict:
    return getattr(request.app.state, "registry", build_default_registry())


def _get_context_store(request: Request):
    return getattr(request.app.state, "context", None)


def _get_engine(request: Request):
    return getattr(request.app.state, "orchestration_engine", None)


@router.get("/agents/registry")
async def agents_registry(request: Request) -> list[dict[str, Any]]:
    """Return the 9 agent definitions with inferred status from recent events."""
    registry = _get_registry(request)
    event_bus = _get_event_bus(request)
    recent = event_bus.get_recent_events(limit=200)

    agents_info = []
    for name, agent in registry.items():
        agent_events = [e for e in recent if e.source == name]
        status = "idle"
        if any(e.event_type.value in ("agent_started", "task_started") for e in agent_events[-5:]):
            status = "active"
        if any(e.event_type.value in ("agent_failed", "task_failed") for e in agent_events[-5:]):
            status = "error"

        tasks_completed = sum(
            1 for e in agent_events if e.event_type.value in ("task_completed", "agent_finished")
        )
        tasks_failed = sum(
            1 for e in agent_events if e.event_type.value in ("task_failed", "agent_failed")
        )
        last_activity = max(
            (e.timestamp for e in agent_events), default=0
        )

        agents_info.append({
            "name": name,
            "model_key": getattr(agent, "model_key", "unknown"),
            "status": status,
            "tasks_completed": tasks_completed,
            "tasks_failed": tasks_failed,
            "last_activity": last_activity,
        })

    return agents_info


@router.get("/agents/topology")
async def agents_topology(request: Request) -> dict[str, Any]:
    """Return agent network topology nodes and links for graph visualization."""
    registry = _get_registry(request)
    event_bus = _get_event_bus(request)
    recent = event_bus.get_recent_events(limit=500)

    nodes = []
    links = []
    agent_names = list(registry.keys())
    colors = {
        "ARCHITECT": "#a78bfa",
        "RESEARCHER": "#5eead4",
        "CODER": "#f59e0b",
        "ANALYZER": "#ef4444",
        "DEBUGGER": "#3b82f6",
        "DOCUMENTER": "#10b981",
        "OPTIMIZER": "#8b5cf6",
        "MICRO": "#ec4899",
    }

    for idx, name in enumerate(agent_names):
        agent_events = [e for e in recent if e.source == name]
        status = "idle"
        if any(e.event_type.value in ("agent_started", "task_started") for e in agent_events[-5:]):
            status = "active"
        # Estimate CPU based on recent activity
        cpu = 0 if status == "idle" else (20 + min(len(agent_events[-10:]) * 5, 60))
        # Estimate memory based on agent type and activity
        memory = 10 + (len(agent_events) % 30)
        nodes.append({
            "id": name,
            "label": name,
            "type": "agent",
            "x": 200 + (idx % 3) * 200,
            "y": 100 + (idx // 3) * 120,
            "color": colors.get(name, "#6b7280"),
            "status": status,
            "size": 30 + min(len(agent_events) * 2, 20),
            "cpu": cpu,
            "memory": memory,
        })

    # Create links based on event correlations (same correlation_id)
    corr_groups: dict[str, list[str]] = {}
    for e in recent:
        if e.correlation_id:
            corr_groups.setdefault(e.correlation_id, []).append(e.source)

    seen_links = set()
    for sources in corr_groups.values():
        unique = list(dict.fromkeys(s for s in sources if s))
        for i in range(len(unique) - 1):
            src, tgt = unique[i], unique[i + 1]
            if src != tgt and (src, tgt) not in seen_links:
                seen_links.add((src, tgt))
                # Check if source agent is active
                src_node = next((n for n in nodes if n["id"] == src), None)
                is_active = src_node and src_node["status"] == "active"
                links.append({"source": src, "target": tgt, "value": 1, "active": is_active})

    return {"nodes": nodes, "links": links}


@router.get("/tasks/pipeline")
async def tasks_pipeline(request: Request) -> dict[str, Any]:
    """Return current task pipeline state from the orchestration engine."""
    engine = _get_engine(request)
    if engine is None:
        return {
            "phases": [
                {"name": "Planning", "status": "idle", "count": 0},
                {"name": "Executing", "status": "idle", "count": 0},
                {"name": "Validating", "status": "idle", "count": 0},
                {"name": "Complete", "status": "idle", "count": 0},
            ],
            "tasks": [],
            "active_runs": 0,
        }

    # Aggregate from all active runs if available
    tasks = []
    active_runs = len(getattr(engine, "_active_runs", {}))
    return {
        "phases": [
            {"name": "Planning", "status": "active" if active_runs else "idle", "count": 0},
            {"name": "Executing", "status": "active" if active_runs else "idle", "count": active_runs},
            {"name": "Validating", "status": "idle", "count": 0},
            {"name": "Complete", "status": "idle", "count": 0},
        ],
        "tasks": tasks,
        "active_runs": active_runs,
    }


@router.get("/events/stream")
async def events_stream(request: Request) -> StreamingResponse:
    """Stream orchestrator events via SSE in real-time."""
    event_bus = _get_event_bus(request)

    async def generator() -> AsyncIterator[str]:
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=1000)

        async def on_event(event) -> None:
            await queue.put(event.to_sse())

        await event_bus.subscribe("*", on_event)
        try:
            while True:
                data = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {json.dumps(data)}\n\n"
        except TimeoutError:
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            await event_bus.unsubscribe("*", on_event)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/observability/stream")
async def observability_stream(request: Request) -> StreamingResponse:
    """Stream observability data (logs, tokens, errors) via SSE.

    Subscribes to the real EventBus and transforms OrchestratorEvents into the
    three SSE event categories the ObservabilityPanel consumes:
      - log: error/warning/info entries from lifecycle and system events
      - token_metric: TOKEN events with token/cost data
      - error_metric: ERROR events and events carrying error count data

    Heartbeat (keep-alive) is sent every 30 s when no events arrive.
    """
    event_bus = _get_event_bus(request)

    async def generator() -> AsyncIterator[str]:
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=1000)

        # ── Categories of event_type that produce info-level log entries ──
        _INFO_LOG_EVENTS = frozenset({
            "agent_started",
            "agent_finished",
            "agent_retry",
            "task_scheduled",
            "task_started",
            "task_completed",
            "task_cancelled",
            "workflow_started",
            "workflow_step",
            "workflow_completed",
            "workflow_failed",
            "plan_created",
            "plan_updated",
            "plan_approved",
            "plan_rejected",
            "step_completed",
            "orchestrator_started",
            "orchestrator_finished",
            "metric",
            "heartbeat",
            "done",
        })

        async def on_event(event: OrchestratorEvent) -> None:
            """Transform one OrchestratorEvent into 0-3 SSE observability events."""
            et = event.event_type.value
            ts = event.timestamp
            source = event.source or "system"

            # ── 1.  Log entries ────────────────────────────────────────
            if et == "error":
                # Error → error-level log
                await queue.put({
                    "type": "log",
                    "log": {
                        "id": event.event_id,
                        "level": "error",
                        "source": source,
                        "message": event.content or event.data.get("message", str(event.data)),
                        "timestamp": ts,
                    },
                })
            elif et == "warning":
                # Warning → warn-level log
                await queue.put({
                    "type": "log",
                    "log": {
                        "id": event.event_id,
                        "level": "warn",
                        "source": source,
                        "message": event.content or event.data.get("message", str(event.data)),
                        "timestamp": ts,
                    },
                })
            elif et in _INFO_LOG_EVENTS:
                # Lifecycle / metric events → info-level log
                msg = event.content or event.data.get("message", json.dumps(event.data) if event.data else et)
                await queue.put({
                    "type": "log",
                    "log": {
                        "id": event.event_id,
                        "level": "info",
                        "source": source,
                        "message": msg,
                        "timestamp": ts,
                    },
                })
            elif et == "tool_error":
                # Tool errors → error-level log
                await queue.put({
                    "type": "log",
                    "log": {
                        "id": event.event_id,
                        "level": "error",
                        "source": source,
                        "message": event.content or event.data.get("error", "Tool error"),
                        "timestamp": ts,
                    },
                })

            # ── 2.  Token metrics ──────────────────────────────────────
            if et == "token":
                await queue.put({
                    "type": "token_metric",
                    "metric": {
                        "model": event.data.get("model", "unknown"),
                        "agent": source,
                        "task": event.data.get("task", event.task_id or "streaming"),
                        "tokens": event.data.get("tokens", len(event.content)),
                        "cost": event.data.get("cost", 0.0),
                        "timestamp": ts,
                    },
                })

            # ── 3.  Error metrics ──────────────────────────────────────
            if et == "error" or (event.data and "error_count" in event.data):
                await queue.put({
                    "type": "error_metric",
                    "metric": {
                        "type": event.data.get("type", et),
                        "source": source,
                        "count": event.data.get("error_count", 1),
                        "root_cause": event.data.get("root_cause") or event.data.get("error", "unknown"),
                        "retry_count": event.data.get("retry_count", 0),
                        "recovery_time": event.data.get("recovery_time", 0.0),
                        "last_occurrence": ts,
                    },
                })

        await event_bus.subscribe("*", on_event)
        try:
            while True:
                data = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {json.dumps(data)}\n\n"
        except TimeoutError:
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            await event_bus.unsubscribe("*", on_event)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/commits/recent")
async def recent_commits(limit: int = 20) -> list[dict[str, str]]:
    """Return recent git commits from the repository root."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "log", "--oneline", "--no-decorate", f"-{limit}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=".",
        )
        try:
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        except TimeoutError:
            return []
        if proc.returncode != 0:
            return []
        commits = []
        for line in stdout_bytes.decode("utf-8", errors="replace").strip().split("\n"):
            if not line:
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2:
                commits.append({
                    "hash": parts[0],
                    "message": parts[1],
                    "author": "system",
                    "timestamp": "",
                })
        return commits
    except Exception as e:
        logger.warning("Failed to fetch git commits: %s", e)
        return []


@router.get("/knowledge/stats")
async def knowledge_stats() -> dict[str, Any]:
    """Return knowledge graph statistics if ChromaDB is available."""
    try:
        import chromadb
        client = chromadb.Client()
        collections = client.list_collections()
        stats = {
            "collections": len(collections),
            "entities": 0,
            "relations": 0,
            "documents": 0,
            "embeddings": 0,
        }
        for col in collections:
            count = col.count()
            stats["documents"] += count
            stats["embeddings"] += count
        return stats
    except Exception as e:
        logger.debug("ChromaDB not available for stats: %s", e)
        return {
            "collections": 0,
            "entities": 0,
            "relations": 0,
            "documents": 0,
            "embeddings": 0,
        }


@router.get("/sessions/active")
async def active_sessions(request: Request) -> dict[str, Any]:
    """Return count of active sessions from the context store."""
    store = _get_context_store(request)
    if store is None:
        return {"count": 0, "sessions": []}

    async with store._lock:
        sessions = list(store._history.keys())

    return {
        "count": len(sessions),
        "sessions": [
            {"id": sid, "message_count": len(store._history.get(sid, []))}
            for sid in sessions
        ],
    }


@router.get("/metrics/flow")
async def metrics_flow(request: Request) -> dict[str, Any]:
    """Return request flow topology with real nodes/links."""
    from backend.observability.metrics_collector import get_metrics_collector
    collector = get_metrics_collector()
    snapshot = await collector.get_snapshot(active_sessions=0, queue_depth=0)

    nodes = [
        {"id": "user", "label": "User", "type": "source", "value": snapshot.requests_total, "color": "#3b82f6"},
        {"id": "router", "label": "Router", "type": "process", "value": snapshot.requests_total, "color": "#a78bfa"},
        {"id": "agent", "label": "Agents", "type": "process", "value": snapshot.requests_successful, "color": "#f59e0b"},
        {"id": "llm", "label": "Ollama", "type": "destination", "value": snapshot.requests_total, "color": "#10b981"},
    ]

    links = [
        {"source": "user", "target": "router", "value": snapshot.requests_total, "latency_ms": snapshot.avg_latency_ms * 0.2},
        {"source": "router", "target": "agent", "value": snapshot.requests_total, "latency_ms": snapshot.avg_latency_ms * 0.3},
        {"source": "agent", "target": "llm", "value": snapshot.requests_total, "latency_ms": snapshot.avg_latency_ms * 0.5},
    ]

    return {
        "nodes": nodes,
        "links": links,
        "summary": {
            "total_requests": snapshot.requests_total,
            "successful_requests": snapshot.requests_successful,
            "failed_requests": snapshot.requests_failed,
            "avg_latency_ms": snapshot.avg_latency_ms,
            "throughput_tps": snapshot.tokens_per_second,
        },
    }


@router.get("/workflows/stream")
async def workflows_stream(request: Request) -> StreamingResponse:
    """Stream workflow events via SSE in real-time."""
    event_bus = _get_event_bus(request)

    async def generator() -> AsyncIterator[str]:
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=1000)

        # Filter for workflow-related events
        workflow_event_types = [
            "workflow_started",
            "workflow_step",
            "workflow_completed",
            "workflow_failed",
        ]

        async def on_event(event) -> None:
            # Only emit workflow events
            if event.event_type.value in workflow_event_types:
                await queue.put(event.to_sse())

        await event_bus.subscribe("*", on_event)
        try:
            while True:
                data = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {json.dumps(data)}\n\n"
        except TimeoutError:
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            await event_bus.unsubscribe("*", on_event)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str) -> dict[str, Any]:
    """Get workflow state by ID."""
    from backend.observability.workflow_tracker import WorkflowTracker
    tracker = WorkflowTracker(enable_persistence=True)
    
    # Try to get from database first
    workflow_state = tracker.get_persisted_workflow(workflow_id)
    if workflow_state:
        return workflow_state
    
    # Fallback to in-memory
    workflow = tracker.get_workflow(workflow_id)
    if workflow:
        return workflow.to_dict()
    
    return {"error": "Workflow not found"}


@router.get("/workflows")
async def list_workflows(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List workflows, optionally filtered by status."""
    from backend.observability.workflow_tracker import WorkflowTracker
    tracker = WorkflowTracker(enable_persistence=True)
    
    if status == "active":
        return tracker.list_active_workflows(limit)
    elif status == "completed":
        return tracker.list_completed_workflows(limit)
    elif status == "failed":
        return tracker.list_failed_workflows(limit)
    else:
        # Return from in-memory tracker
        workflows = tracker.list_workflows(status=status, limit=limit)
        return [w.to_dict() for w in workflows]


@router.get("/workflows/{workflow_id}/timeline")
async def get_workflow_timeline(workflow_id: str) -> list[dict[str, Any]]:
    """Get workflow timeline for replay."""
    from backend.observability.workflow_tracker import WorkflowTracker
    tracker = WorkflowTracker()
    
    return tracker.get_timeline(workflow_id)
