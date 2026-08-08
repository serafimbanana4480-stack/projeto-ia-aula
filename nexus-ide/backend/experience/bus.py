"""Experience Bus — centralised structured-trace capture for NEXUS IDE.

FASE 2 — Every interaction is transformed into a structured
:class:`ExperienceTrace` matching the schema:

    USER → DASHBOARD → API → ORCHESTRATOR → ... → RESULT → EXPERIENCE BUS

The bus is a thin layer over :class:`TraceLake` (persistence) and
:class:`EventBus` (real-time pub/sub).  It exposes both a *singleton*
accessor for production code and a *context-manager* helper for easy
instrumentation of orchestrator calls.
"""
from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from backend.experience.lake import TraceLake, get_trace_lake
from backend.experience.models import (
    ComponentKind,
    ExperienceTrace,
    ModelInfo,
    TaskCategory,
    TraceEvaluation,
    TraceMetrics,
    TraceResult,
    TrajectoryEntry,
)

logger = logging.getLogger(__name__)


class ExperienceBus:
    """Centralised capture point for structured execution traces.

    Production code obtains the singleton via :func:`get_experience_bus`::

        bus = get_experience_bus()
        trace = bus.start_trace(prompt="...", task_type="coding")
        ... # orchestrator runs, populating trajectory
        bus.record_trajectory(trace, agent="CODER", action="write",
                              tool="write_file", observation="created main.py")
        bus.complete(trace, success=True, score=0.9, latency_ms=1250)

    For one-liner usage::

        bus = get_experience_bus()
        bus.record_trace(trace)
    """

    def __init__(self, lake: TraceLake | None = None, event_bus: Any | None = None) -> None:
        self._lake = lake or get_trace_lake()
        self._event_bus = event_bus  # backend.observability.events.EventBus | None
        self._active: dict[str, ExperienceTrace] = {}

    # ── Trace lifecycle ──

    def start_trace(
        self,
        *,
        prompt: str = "",
        task_type: str = "",
        difficulty: float = 0.5,
        category: TaskCategory = TaskCategory.UNKNOWN,
        session_id: str = "",
        model: ModelInfo | None = None,
        agents: list[str] | None = None,
        parent_trace_id: str | None = None,
        experiment_id: str | None = None,
        component_kind: ComponentKind | None = None,
        component_version: str | None = None,
        workflow_version: str | None = None,
        tags: list[str] | None = None,
    ) -> ExperienceTrace:
        """Begin collecting a new trace and track it as *active*."""
        trace = ExperienceTrace(
            prompt=prompt,
            task_type=task_type,
            difficulty=difficulty,
            category=category,
            session_id=session_id,
            model=model or ModelInfo(),
            agents=agents or [],
            parent_trace_id=parent_trace_id,
            experiment_id=experiment_id,
            component_kind=component_kind,
            component_version=component_version,
            workflow_version=workflow_version,
            tags=tags or [],
        )
        self._active[trace.task_id] = trace
        return trace

    def record_trajectory(
        self,
        trace: ExperienceTrace,
        *,
        agent: str = "",
        action: str = "",
        tool: str | None = None,
        observation: str | None = None,
        duration_ms: int = 0,
        tokens_used: int = 0,
        success: bool = True,
        error: str | None = None,
        input_data: dict[str, Any] | None = None,
    ) -> TrajectoryEntry:
        """Append a step to an *in-progress* trace's trajectory."""
        entry = trace.add_trajectory_entry(
            agent=agent,
            action=action,
            tool=tool,
            observation=observation,
            duration_ms=duration_ms,
            tokens_used=tokens_used,
            success=success,
            error=error,
            input_data=input_data or {},
        )
        _update_metrics_from_entry(trace.metrics, entry)
        return entry

    def complete(
        self,
        trace: ExperienceTrace,
        *,
        success: bool = False,
        score: float = 0.0,
        error: str | None = None,
        output: str | None = None,
        latency_ms: int | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        tool_calls: int | None = None,
        retries: int = 0,
        cost_usd: float | None = None,
        correctness: float = 0.0,
        efficiency: float = 0.0,
        quality: float = 0.0,
        regression: bool = False,
        evaluation_explanation: str = "",
        memory_retrieved: list[str] | None = None,
        files_modified: list[str] | None = None,
        commands_executed: list[str] | None = None,
        tests_executed: list[str] | None = None,
    ) -> str:
        """Finalise a trace, persist it, and publish to the event bus.

        Returns the ``task_id``.
        """
        trace.result = TraceResult(
            success=success,
            score=score,
            error=error,
            output=output,
        )
        if latency_ms is not None:
            trace.metrics.latency_ms = latency_ms
        if tokens_input is not None:
            trace.metrics.tokens_input = tokens_input
        if tokens_output is not None:
            trace.metrics.tokens_output = tokens_output
        if tool_calls is not None:
            trace.metrics.tool_calls = tool_calls
        trace.metrics.retries = retries
        if cost_usd is not None:
            trace.metrics.cost_usd = cost_usd

        trace.memory_retrieved = memory_retrieved or trace.memory_retrieved
        trace.files_modified = files_modified or trace.files_modified
        trace.commands_executed = commands_executed or trace.commands_executed
        trace.tests_executed = tests_executed or trace.tests_executed

        trace.evaluation = TraceEvaluation(
            correctness=correctness,
            efficiency=efficiency,
            quality=quality,
            regression=regression,
            explanation=evaluation_explanation,
        )

        self._active.pop(trace.task_id, None)
        return self.record_trace(trace)

    def record_trace(self, trace: ExperienceTrace) -> str:
        """Persist a fully-formed trace and publish an event.

        Returns the ``task_id``.
        """
        # Ensure metrics reflect the trajectory
        _reconcile_metrics(trace)

        task_id = self._lake.store_trace(trace)

        # Fire-and-forget event bus publish
        if self._event_bus is not None:
            try:
                self._event_bus.publish(
                    "trace.recorded",
                    {
                        "task_id": trace.task_id,
                        "task_type": trace.task_type,
                        "success": trace.result.success,
                        "score": trace.result.score,
                    },
                )
            except Exception:
                logger.debug("Failed to publish trace event", exc_info=True)

        logger.debug("Trace %s persisted and published", trace.task_id)
        return task_id

    # ── Retrieval ──

    def get_active_traces(self) -> list[ExperienceTrace]:
        """Return all in-progress traces."""
        return list(self._active.values())

    def get_trace(self, task_id: str) -> ExperienceTrace | None:
        """Fetch a stored trace from the lake."""
        return self._lake.get_trace(task_id)

    def cancel(self, task_id: str, reason: str = "") -> None:
        """Remove a trace from the active set (on cancellation)."""
        trace = self._active.pop(task_id, None)
        if trace is not None:
            trace.result.error = reason or trace.result.error
            trace.result.success = False
            self.record_trace(trace)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _update_metrics_from_entry(metrics: TraceMetrics, entry: TrajectoryEntry) -> None:
    """Accumulate metrics from a trajectory entry."""
    metrics.latency_ms += entry.duration_ms
    metrics.tokens_input += entry.tokens_used
    metrics.tool_calls += 1
    if not entry.success:
        metrics.retries += 1


def _reconcile_metrics(trace: ExperienceTrace) -> None:
    """Ensure metrics are consistent with the trajectory if not explicitly set."""
    if trace.metrics.latency_ms == 0 and trace.trajectory:
        trace.metrics.latency_ms = sum(e.duration_ms for e in trace.trajectory)
    if trace.metrics.tool_calls == 0:
        trace.metrics.tool_calls = len(trace.trajectory)
    if trace.metrics.tokens_input == 0:
        trace.metrics.tokens_input = sum(e.tokens_used for e in trace.trajectory)


# ── Context manager for easy instrumentation ─────────────────────────────────

@asynccontextmanager
async def trace_context(
    bus: ExperienceBus,
    *,
    prompt: str = "",
    task_type: str = "",
    difficulty: float = 0.5,
    category: TaskCategory = TaskCategory.UNKNOWN,
    session_id: str = "",
    **trace_kw: Any,
) -> AsyncIterator[ExperienceTrace]:
    """Async context manager that starts, tracks, and persists a trace.

    Usage::

        async with trace_context(bus, prompt="...", task_type="coding") as trace:
            ... # orchestrator runs
            bus.record_trajectory(trace, agent="CODER", action="...", ...)
            bus.complete(trace, success=True, score=0.9)
    """
    start = time.perf_counter()
    trace = bus.start_trace(
        prompt=prompt,
        task_type=task_type,
        difficulty=difficulty,
        category=category,
        session_id=session_id,
        **trace_kw,
    )
    try:
        yield trace
    except Exception as exc:
        trace.result.success = False
        trace.result.error = str(exc)
        trace.evaluation.regression = True
        trace.evaluation.explanation = f"Trace failed: {exc}"
        elapsed = int((time.perf_counter() - start) * 1000)
        bus.record_trace(trace)
        raise
    else:
        elapsed = int((time.perf_counter() - start) * 1000)
        if trace.metrics.latency_ms == 0:
            trace.metrics.latency_ms = elapsed
        # Only auto-record if not already completed
        if trace.task_id not in bus._lake.__dict__.get("_persisted_ids", set()):
            pass  # caller calls bus.complete() explicitly


# ── Singleton accessor ───────────────────────────────────────────────────────

_bus: ExperienceBus | None = None


def get_experience_bus() -> ExperienceBus:
    """Return the process-wide :class:`ExperienceBus` singleton."""
    global _bus
    if _bus is None or getattr(_bus, "_lake", None) is None:
        from backend.observability.events import get_event_bus as _get_eb

        _bus = ExperienceBus(event_bus=_get_eb())
    return _bus
