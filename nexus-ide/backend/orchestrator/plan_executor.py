"""Plan executor for the multi-agent orchestrator.

Extracted from :mod:`backend.orchestrator.engine` to keep the main
``OrchestrationEngine`` focused on coordination. ``PlanExecutor`` owns
the per-layer parallel task loop, the per-task retry loop, and the
prompt building for individual tasks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from backend.agents.base import AgentBase, AgentRequest
from backend.core.conversation_log import get_conversation_logger
from backend.orchestrator.agent_capabilities import file_locks, validate_agent_contract
from backend.orchestrator.agent_pool import AgentPool
from backend.orchestrator.dependency_graph import (
    DependencyGraph,
    ExecutionPlan,
    TaskNode,
    TaskStatus,
)
from backend.orchestrator.events import EventBus, EventEmitter, EventType, OrchestratorEvent
from backend.tools.registry import reset_tool_failures

logger = logging.getLogger(__name__)

_INLINE_TOOL_ERROR_RE = re.compile(r"<event>tool_error\|(.+?)</event>", re.DOTALL)

# Combined pattern used to order tool events: an error is only *fatal* for the
# task if no tool succeeded afterwards — a recovered "File not found" (the
# agent listed the directory, found the real path, and continued) must not
# fail the whole autonomous run.
_INLINE_TOOL_EVENT_RE = re.compile(
    r"<event>(tool_error|tool_result)\|(.+?)</event>", re.DOTALL
)

_SPAWN_RESULT_RE = re.compile(
    r"<event>tool_result\|spawn_task\|(.+?)</event>",
    re.DOTALL,
)


def extract_spawn_requests(output: str) -> list[dict[str, Any]]:
    """Extract successful ``spawn_task`` tool results from agent output."""
    requests: list[dict[str, Any]] = []
    for raw_payload in _SPAWN_RESULT_RE.findall(output or ""):
        try:
            payload = json.loads(raw_payload)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("status") == "spawned":
            requests.append(payload)
    return requests


def extract_tool_errors(output: str) -> list[str]:
    """Return tool error messages embedded in agent ReAct output."""
    return [msg.strip() for msg in _INLINE_TOOL_ERROR_RE.findall(output) if msg.strip()]


def partition_tool_errors(output: str) -> tuple[list[str], list[str]]:
    """Split tool errors into ``(unrecovered, recovered)``.

    An error is *recovered* when at least one ``tool_result`` (successful tool
    execution) appears after it in the agent's output stream — the agent hit
    the problem, adjusted, and kept making progress. An error with no later
    success is *unrecovered* and should still fail the task.
    """
    events: list[tuple[int, str, str]] = []
    for match in _INLINE_TOOL_EVENT_RE.finditer(output or ""):
        events.append((match.start(), match.group(1), match.group(2).strip()))

    unrecovered: list[str] = []
    recovered: list[str] = []
    for index, (_pos, kind, payload) in enumerate(events):
        if kind != "tool_error" or not payload:
            continue
        has_later_success = any(
            later_kind == "tool_result"
            for _, later_kind, _ in events[index + 1 :]
        )
        (recovered if has_later_success else unrecovered).append(payload)
    return unrecovered, recovered


_INCOMPLETION_MARKERS: tuple[str, ...] = (
    "[TAREFA NÃO CONCLUÍDA]",
    "[TAREFA NAO CONCLUIDA]",
    # Double-encoded UTF-8. A literal in ``agents/base.py`` was corrupted this
    # way and the marker stopped matching, so a run that had honestly declared
    # itself incomplete was invisible to this check (2026-08-02, session
    # b9f0dfbd53ad402a). Kept as a safety net: the emitter is fixed, but a
    # marker that silently stops matching is the worst possible failure mode.
    "[TAREFA NÃO CONCLUÃDA]",
    "Reached maximum iterations",
)


def output_reports_incompletion(output: str) -> str | None:
    """Return the marker text when the agent's output admits incompletion.

    The ReAct loop honestly signals when it gave up (iteration cap, refused
    work). Treating that output as a completed task — the previous behaviour —
    is what made the dashboard show "Tarefa concluída" right under a
    "task NOT completed" warning.
    """
    for marker in _INCOMPLETION_MARKERS:
        if marker in (output or ""):
            return marker
    return None


# Backwards-compatible alias — the original module-level helper lived in
# ``engine.py`` and is still imported by the test suite as a private name.
_extract_tool_errors = extract_tool_errors


async def iterate_agent_output(output: Any) -> AsyncIterator[str]:
    """Yield tokens from async iterables, coroutines, or plain iterables."""
    if asyncio.iscoroutine(output):
        output = await output

    if hasattr(output, "__aiter__"):
        async for token in output:
            yield token
        return

    for token in output:
        yield token


# Backwards-compatible alias for the same reason.
_iterate_agent_output = iterate_agent_output


class PlanExecutor:
    """Run an :class:`ExecutionPlan` layer-by-layer with parallelism and retries."""

    def __init__(
        self,
        llm_client: Any,
        registry: dict[str, AgentBase],
        event_bus: EventBus,
        agent_pool: AgentPool,
        *,
        default_timeout: int = 300,
        max_parallel: int = 5,
    ) -> None:
        self._llm_client = llm_client
        self._registry = registry
        self._events = event_bus
        self._agent_pool = agent_pool
        self._default_timeout = default_timeout
        # The engine exposes this budget and the layer loop is where tasks are
        # actually scheduled, so keep the bound here as well.
        self._max_parallel = max(1, int(max_parallel))
        # Plan tasks need room to explore (read → correct → write → verify).
        # 5 iterations — the old default — was the reason ANALYZER/CODER tasks
        # ended with "Reached maximum iterations (5) — task NOT completed".
        try:
            self._task_max_iterations = max(
                3, int(os.environ.get("NEXUS_TASK_MAX_ITERATIONS", "10"))
            )
        except ValueError:
            self._task_max_iterations = 10

    async def execute(
        self,
        plan: ExecutionPlan,
        session_id: str,
        *,
        run_id: str,
        project_path: str = ".",
        cancellation_event: asyncio.Event | None = None,
        active_tasks: list | None = None,
    ) -> tuple[Any, Any]:
        """Execute ``plan`` layer-by-layer, returning ``(result, ctx)``.

        ``result`` is an ``OrchestrationResult`` (imported lazily to avoid
        a circular import — the engine module owns the dataclass).
        ``ctx`` is an ``ExecutionContext`` for the caller to inspect.
        ``cancellation_event`` and ``active_tasks`` are optional hooks so
        the engine's :class:`CancellationRegistry` can interrupt the run.
        """
        # Local imports to avoid circular dependency with engine.py
        from backend.orchestrator.engine import ExecutionContext, OrchestrationResult

        ctx = ExecutionContext(
            session_id=session_id,
            project_path=project_path,
        )

        start_time = time.time()
        total_tokens = 0
        errors: list[str] = []

        graph = plan.dependency_graph
        plan.run_id = run_id
        # Dynamic ``spawn_task`` requests may extend the graph while it is
        # running. Recompute layers after each batch so spawned work is not
        # merely reported as an artifact and is actually executed.
        try:
            max_dynamic_tasks = max(0, int(os.environ.get("NEXUS_MAX_DYNAMIC_TASKS", "32")))
        except ValueError:
            max_dynamic_tasks = 32
        spawned_signatures: set[tuple[str, str, str]] = set()
        dynamic_tasks_created = 0
        initial_layers = graph.topological_layers()

        await self._events.publish(
            OrchestratorEvent(
                event_type=EventType.ORCHESTRATOR_STARTED,
                source="ORCHESTRATOR",
                session_id=session_id,
                data={
                    "run_id": run_id,
                    "layers": len(initial_layers),
                    "total_tasks": len(graph.get_all_tasks()),
                },
            )
        )

        try:
            while True:
                if cancellation_event is not None and cancellation_event.is_set():
                    break

                # Readiness is derived from predecessor state, not merely
                # from topological position.  A topological layer still
                # contains a task whose predecessor failed; scheduling that
                # task was the source of dependent agents starting on an
                # unvalidated hand-off.
                ready_tasks, blocked_tasks = graph.reconcile_dependencies()
                for blocked_task in blocked_tasks:
                    await self._events.publish(
                        OrchestratorEvent(
                            event_type=EventType.TASK_BLOCKED,
                            source=blocked_task.agent,
                            session_id=session_id,
                            task_id=blocked_task.task_id,
                            data={
                                "task_name": blocked_task.name,
                                "error": blocked_task.error_message,
                                "depends_on": list(blocked_task.depends_on),
                            },
                        )
                    )
                if not ready_tasks:
                    unresolved = [
                        task
                        for task in graph.get_all_tasks()
                        if task.status
                        in (TaskStatus.PENDING, TaskStatus.WAITING_DEPENDENCY)
                    ]
                    if unresolved:
                        # No runnable task remains and no task is running in
                        # this loop. This is a malformed/corrupted graph, not
                        # a reason to spin forever in planning.
                        for task in unresolved:
                            graph.transition_status(
                                task.task_id,
                                TaskStatus.BLOCKED,
                                "no runnable dependency state remained",
                            )
                            await self._events.publish(
                                OrchestratorEvent(
                                    event_type=EventType.TASK_BLOCKED,
                                    source=task.agent,
                                    session_id=session_id,
                                    task_id=task.task_id,
                                    data={
                                        "task_name": task.name,
                                        "error": task.error_message,
                                    },
                                )
                            )
                        errors.append("no runnable task remained after dependency reconciliation")
                    break
                layer = [task.task_id for task in ready_tasks]

                # Execute tasks in this layer concurrently, bounded by the
                # configured budget so provider failures do not fan out into a
                # stalled autonomous run.
                limiter = asyncio.Semaphore(self._max_parallel)
                layer_tasks: list[asyncio.Task[Any]] = []
                for task_id in layer:
                    task = graph.get_task(task_id)
                    if task is None:
                        continue
                    # ``reconcile_dependencies`` has already performed the
                    # guarded PENDING/WAITING -> READY transition.
                    if task.status != TaskStatus.READY:
                        raise RuntimeError(
                            f"scheduler attempted to start task {task.task_id} "
                            f"from {task.status.value}"
                        )
                    async def run_limited(
                        current_task: TaskNode = task,
                        semaphore: asyncio.Semaphore = limiter,
                    ) -> dict[str, Any]:
                        async with semaphore:
                            return await self._execute_task(
                                current_task,
                                ctx,
                                graph,
                                session_id,
                                run_id,
                                cancellation_event,
                            )

                    coro = run_limited()
                    t = asyncio.create_task(coro)
                    layer_tasks.append(t)
                    if active_tasks is not None:
                        active_tasks.append(t)

                if layer_tasks:
                    results = await asyncio.gather(*layer_tasks, return_exceptions=True)
                    for result in results:
                        if isinstance(result, Exception):
                            errors.append(str(result))
                        elif isinstance(result, dict):
                            if "error" in result and result["error"]:
                                errors.append(str(result["error"]))
                            total_tokens += result.get("tokens", 0)

                # A successful spawn_task event is a request for real work,
                # not just telemetry. Attach each child to its parent so it
                # runs in the next dependency layer and remains bounded.
                if dynamic_tasks_created < max_dynamic_tasks:
                    for task_id in layer:
                        parent = graph.get_task(task_id)
                        if parent is None:
                            continue
                        output = str(parent.output_data.get("content", ""))
                        for request in extract_spawn_requests(output):
                            child_name = str(request.get("task_name", "")).strip()
                            child_description = str(request.get("description", "")).strip()
                            child_agent = str(request.get("agent", "CODER")).strip().upper()
                            signature = (parent.task_id, child_name, child_agent)
                            if (
                                not child_name
                                or signature in spawned_signatures
                                or dynamic_tasks_created >= max_dynamic_tasks
                            ):
                                continue
                            if child_agent not in self._registry:
                                errors.append(
                                    f"Spawned task {child_name!r} requested unknown agent {child_agent!r}"
                                )
                                continue
                            child = TaskNode(
                                name=child_name,
                                description=child_description,
                                agent=child_agent,
                                depends_on=[parent.task_id],
                                max_retries=1,
                            )
                            graph.add_task(child)
                            spawned_signatures.add(signature)
                            dynamic_tasks_created += 1
                            await self._events.publish(
                                OrchestratorEvent(
                                    event_type=EventType.PLAN_MODIFIED,
                                    source="ORCHESTRATOR",
                                    session_id=session_id,
                                    task_id=child.task_id,
                                    data={
                                        "reason": "spawn_task",
                                        "parent_task_id": parent.task_id,
                                        "task": child.to_dict(),
                                    },
                                )
                            )

        except asyncio.CancelledError:
            await self._events.publish(
                OrchestratorEvent(
                    event_type=EventType.ORCHESTRATOR_FINISHED,
                    source="ORCHESTRATOR",
                    session_id=session_id,
                    data={"run_id": run_id, "cancelled": True},
                )
            )
            raise

        duration_ms = int((time.time() - start_time) * 1000)
        completed = sum(1 for t in graph.get_all_tasks() if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in graph.get_all_tasks() if t.status == TaskStatus.FAILED)
        blocked = sum(1 for t in graph.get_all_tasks() if t.status == TaskStatus.BLOCKED)

        from backend.orchestrator.engine import OrchestrationState

        final_state = (
            OrchestrationState.COMPLETED
            if failed == 0 and blocked == 0
            else OrchestrationState.FAILED
        )

        result = OrchestrationResult(
            run_id=run_id,
            state=final_state,
            plan=plan,
            completed_tasks=completed,
            failed_tasks=failed,
            blocked_tasks=blocked,
            total_duration_ms=duration_ms,
            tokens_used=total_tokens,
            errors=errors,
            task_results=dict(ctx.artifacts),
        )

        get_conversation_logger(session_id).log_run_summary(
            state=str(final_state.value if hasattr(final_state, "value") else final_state),
            completed_tasks=completed,
            failed_tasks=failed,
            duration_ms=duration_ms,
            errors=errors,
        )

        await self._events.publish(
            OrchestratorEvent(
                event_type=EventType.ORCHESTRATOR_FINISHED,
                source="ORCHESTRATOR",
                session_id=session_id,
                # Never attach live objects (plan.dependency_graph is a
                # DependencyGraph) — the SSE bridge must stay JSON-safe.
                data={
                    "run_id": result.run_id,
                    "state": str(result.state.value if hasattr(result.state, "value") else result.state),
                    "plan": result.plan.to_dict() if hasattr(result.plan, "to_dict") else str(result.plan),
                    "completed_tasks": result.completed_tasks,
                    "failed_tasks": result.failed_tasks,
                    "blocked_tasks": result.blocked_tasks,
                    "total_duration_ms": result.total_duration_ms,
                    "tokens_used": result.tokens_used,
                    "errors": [str(e) for e in (result.errors or [])],
                },
            )
        )

        return result, ctx

    # ------------------------------------------------------------------
    # Internal: Task Execution
    # ------------------------------------------------------------------
    def _task_scopes(self, task: TaskNode) -> list[str]:
        # ``lock_scope`` is the planner's authoritative concurrency boundary.
        # Legacy callers may still put a plural scope list in input_data, and
        # unvalidated tasks can lack lock metadata altogether; fall back to
        # their measured file scope rather than silently executing unlocked.
        raw = getattr(task, "lock_scopes", None)
        if raw is None:
            raw = getattr(task, "lock_scope", None)
        if not raw:
            data = getattr(task, "input_data", {}) or {}
            raw = data.get("lock_scopes") or data.get("lock_scope") or data.get("file_scope")
        if not raw:
            raw = getattr(task, "file_scope", None)
        if isinstance(raw, str):
            raw = [raw]
        return [str(scope).strip() for scope in (raw or ()) if str(scope).strip()]

    async def _execute_task(
        self,
        task: TaskNode,
        ctx: Any,
        graph: DependencyGraph,
        session_id: str,
        run_id: str,
        cancellation_event: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        scopes = self._task_scopes(task)
        task_owner = f"{run_id}:{task.task_id}"
        acquired: list[str] = []
        try:
            for scope in scopes:
                if not file_locks.acquire(scope, task_owner):
                    task.error_message = (
                        f"Scope lock conflict for {scope!r} "
                        f"(owner={file_locks.owner(scope)!r})"
                    )
                    graph.transition_status(task.task_id, TaskStatus.FAILED, task.error_message)
                    task.completed_at = time.time()
                    return {"error": task.error_message, "error_category": "scope_conflict"}
                acquired.append(scope)
            return await self._execute_task_unlocked(
                task, ctx, graph, session_id, run_id, cancellation_event
            )
        finally:
            for scope in reversed(acquired):
                file_locks.release(scope, task_owner)

    async def _execute_task_unlocked(
        self,
        task: TaskNode,
        ctx: Any,
        graph: DependencyGraph,
        session_id: str,
        run_id: str,
        cancellation_event: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        """Execute a single task with retry logic and event emission."""
        graph.transition_status(task.task_id, TaskStatus.RUNNING)
        task.started_at = time.time()
        task.agent_execution_id = f"{run_id}:agent:{task.task_id}"
        if task.agent == "DEBUGGER" or task.name.strip().lower().startswith("verify"):
            task.test_run_id = f"{run_id}:test:{task.task_id}"

        await self._events.publish(
            OrchestratorEvent(
                event_type=EventType.TASK_STARTED,
                source=task.agent,
                session_id=session_id,
                task_id=task.task_id,
                data={
                    "task_name": task.name,
                    "agent_execution_id": task.agent_execution_id,
                    "test_run_id": task.test_run_id,
                },
            )
        )

        agent = self._registry.get(task.agent)
        if not agent:
            task.error_message = f"Agent {task.agent} not found"
            graph.transition_status(task.task_id, TaskStatus.FAILED, task.error_message)
            await self._events.publish(
                OrchestratorEvent(
                    event_type=EventType.TASK_FAILED,
                    source=task.agent,
                    session_id=session_id,
                    task_id=task.task_id,
                    data={"error": task.error_message},
                )
            )
            return {"error": task.error_message}
        configured_model = getattr(agent, "model_key", "")
        effective_model = task.model_key or (
            configured_model if isinstance(configured_model, str) else ""
        )
        contract_errors = validate_agent_contract(
            task.agent,
            effective_model,
            task.allowed_tools,
        )
        if contract_errors:
            task.error_message = "Agent contract rejected: " + "; ".join(contract_errors)
            graph.transition_status(task.task_id, TaskStatus.FAILED, task.error_message)
            task.completed_at = time.time()
            return {"error": task.error_message, "error_category": "agent_contract"}


        # Build context from dependencies
        dep_context = self._build_dependency_context(task, ctx)
        conv_log = get_conversation_logger(session_id)

        for attempt in range(task.max_retries + 1):
            # A retry is a new execution attempt. Keep the guarded state
            # machine honest by moving RETRYING back to RUNNING before the
            # attempt can complete or fail. Without this transition a
            # recovered second attempt tried RETRYING -> COMPLETED and raised
            # a state-machine error instead of returning the real result.
            if attempt > 0 and task.status == TaskStatus.RETRYING:
                graph.transition_status(task.task_id, TaskStatus.RUNNING)
            try:
                if cancellation_event is not None and cancellation_event.is_set():
                    graph.transition_status(task.task_id, TaskStatus.CANCELLED)
                    return {"cancelled": True}

                conv_log.log_task_started(task.task_id, task.name, task.agent, attempt + 1)

                # Give every task a clean circuit breaker. The breaker is keyed
                # by (session, tool) and a session spans the whole mission, so
                # a failure streak in an earlier task would otherwise start
                # this one with its tools already short-circuited. That is what
                # killed the DEBUGGER "Verify" step in session
                # bf1e9435b9ec47c9: run_shell was disabled on iteration 1 by
                # failures that happened in a different task, and the
                # "verification" gate has no other way to close.
                reset_tool_failures(session_id)

                request = AgentRequest(
                    session_id=session_id,
                    query=self._build_task_prompt(task, dep_context, ctx.project_path),
                    client=self._llm_client,
                    project_path=ctx.project_path,
                    context={
                        "task": task.to_dict(),
                        "shared_memory": ctx.shared_memory,
                        "project_path": ctx.project_path,
                        "_enforce_agent_contract": True,
                        "_allowed_tools": list(task.allowed_tools),
                        "model": effective_model,
                        "_tool_evidence_requirement": (
                            "verification"
                            if task.agent == "DEBUGGER"
                            or task.name.strip().lower().startswith("verify")
                            else (
                                "discovery"
                                if self._task_is_discovery(task)
                                else "substantive"
                            )
                        ),
                        "_tool_evidence": [],
                    },
                    max_iterations=self._task_max_iterations,
                    autonomous=True,
                )

                # Stream execution with hard timeout
                output_parts: list[str] = []
                async with (
                    self._agent_pool.slot(task.agent),
                    EventEmitter(self._events, task.agent, session_id, task.task_id) as emit,
                ):
                    async with asyncio.timeout(self._default_timeout):
                        async for token in iterate_agent_output(agent.run(request)):
                            output_parts.append(token)
                            await emit.emit(EventType.TOKEN, content=token)

                output = "".join(output_parts)
                unrecovered_errors, recovered_errors = partition_tool_errors(output)

                # AgentBase owns evidence/iteration honesty and exposes the
                # verdict after its stream closes. PlanExecutor previously
                # ignored that verdict and marked a task COMPLETED whenever
                # the visible text lacked a recognised error marker. That
                # allowed a discovery-only list_dir loop to fail internally
                # yet still become TASK_COMPLETED.
                agent_run_success = getattr(agent, "_last_run_success", None)
                if agent_run_success is False:
                    task.output_data["content"] = output
                    task.error_message = (
                        "Agent execution failed its runtime/tool evidence gate"
                    )
                    graph.transition_status(task.task_id, TaskStatus.FAILED, task.error_message)
                    task.completed_at = time.time()
                    conv_log.log_task_failed(
                        task.task_id,
                        task.name,
                        task.agent,
                        task.error_message,
                        attempts=attempt + 1,
                    )
                    async with ctx._lock:
                        ctx.artifacts[task.task_id] = {
                            "name": task.name,
                            "agent": task.agent,
                            "output": output,
                            "status": "failed",
                            "evidence": request.context.get("_tool_evidence", []),
                            "incomplete": True,
                        }
                    await self._events.publish(
                        OrchestratorEvent(
                            event_type=EventType.TASK_FAILED,
                            source=task.agent,
                            session_id=session_id,
                            task_id=task.task_id,
                            data={"error": task.error_message, "incomplete": True},
                        )
                    )
                    return {
                        "error": task.error_message,
                        "incomplete": True,
                        "output": output,
                    }

                # Recovered errors: the agent hit a problem (e.g. a hallucinated
                # path), corrected itself, and finished. That is healthy
                # autonomy — log it, surface it, but do NOT fail the task.
                for err in recovered_errors:
                    conv_log.log_tool_recovered(task.agent, "unknown", recovered_from=err)
                if recovered_errors:
                    logger.info(
                        "Task %s recovered from %d tool error(s): %s",
                        task.task_id,
                        len(recovered_errors),
                        recovered_errors[:3],
                    )

                if unrecovered_errors:
                    task.output_data["content"] = output
                    task.error_message = unrecovered_errors[0]
                    graph.transition_status(task.task_id, TaskStatus.FAILED, task.error_message)
                    task.completed_at = time.time()

                    conv_log.log_task_failed(
                        task.task_id,
                        task.name,
                        task.agent,
                        task.error_message,
                        recovered_errors=recovered_errors,
                        attempts=attempt + 1,
                    )

                    async with ctx._lock:
                        ctx.artifacts[task.task_id] = {
                            "name": task.name,
                            "agent": task.agent,
                            "output": output,
                            "status": "failed",
                            "tool_errors": unrecovered_errors,
                            "evidence": request.context.get("_tool_evidence", []),
                            "recovered_tool_errors": recovered_errors,
                        }

                    await self._events.publish(
                        OrchestratorEvent(
                            event_type=EventType.TASK_FAILED,
                            source=task.agent,
                            session_id=session_id,
                            task_id=task.task_id,
                            data={
                                "error": task.error_message,
                                "tool_errors": unrecovered_errors,
                                "recovered_tool_errors": recovered_errors,
                            },
                        )
                    )
                    return {
                        "error": task.error_message,
                        "tool_errors": unrecovered_errors,
                        "recovered_tool_errors": recovered_errors,
                        "output": output,
                    }

                # The agent itself admitted it did not finish (iteration cap,
                # refused work). Marking this COMPLETED is what made the
                # dashboard print "Tarefa concluída" under a "task NOT
                # completed" warning. Fail honestly instead.
                incompletion = output_reports_incompletion(output)
                if incompletion:
                    task.output_data["content"] = output
                    task.error_message = (
                        f"Agent reported the task as not completed ({incompletion})"
                    )
                    graph.transition_status(task.task_id, TaskStatus.FAILED, task.error_message)
                    task.completed_at = time.time()

                    conv_log.log_task_failed(
                        task.task_id,
                        task.name,
                        task.agent,
                        task.error_message,
                        recovered_errors=recovered_errors,
                        attempts=attempt + 1,
                    )

                    async with ctx._lock:
                        ctx.artifacts[task.task_id] = {
                            "name": task.name,
                            "agent": task.agent,
                            "output": output,
                            "status": "failed",
                            "incomplete": True,
                            "evidence": request.context.get("_tool_evidence", []),
                            "recovered_tool_errors": recovered_errors,
                        }

                    await self._events.publish(
                        OrchestratorEvent(
                            event_type=EventType.TASK_FAILED,
                            source=task.agent,
                            session_id=session_id,
                            task_id=task.task_id,
                            data={
                                "error": task.error_message,
                                "incomplete": True,
                            },
                        )
                    )
                    return {
                        "error": task.error_message,
                        "incomplete": True,
                        "output": output,
                    }

                task.output_data["content"] = output
                graph.transition_status(task.task_id, TaskStatus.COMPLETED)
                task.completed_at = time.time()

                # Store artifact
                async with ctx._lock:
                    ctx.artifacts[task.task_id] = {
                        "name": task.name,
                        "agent": task.agent,
                        "output": output,
                        "status": "completed",
                        "recovered_tool_errors": recovered_errors,
                        "evidence": request.context.get("_tool_evidence", []),
                    }
                    ctx._global_context_parts.append(f"\n[{task.name}]: {output[:500]}")

                conv_log.log_task_completed(
                    task.task_id,
                    task.name,
                    task.agent,
                    duration_s=(task.completed_at - task.started_at)
                    if task.started_at
                    else None,
                )

                await self._events.publish(
                    OrchestratorEvent(
                        event_type=EventType.TASK_COMPLETED,
                        source=task.agent,
                        session_id=session_id,
                        task_id=task.task_id,
                        data={"output_length": len(output)},
                    )
                )

                return {"success": True, "output": output, "tokens": len(output_parts)}

            except TimeoutError:
                task.retry_count = attempt + 1
                logger.warning(
                    "Task %s timed out (attempt %d/%d)",
                    task.task_id,
                    attempt + 1,
                    task.max_retries + 1,
                )
                if attempt < task.max_retries:
                    graph.transition_status(task.task_id, TaskStatus.RETRYING)
                    await self._events.publish(
                        OrchestratorEvent(
                            event_type=EventType.AGENT_RETRY,
                            source=task.agent,
                            session_id=session_id,
                            task_id=task.task_id,
                            data={
                                "attempt": attempt + 1,
                                "max_retries": task.max_retries,
                                "reason": "timeout",
                            },
                        )
                    )
                    jitter = random.uniform(0, 1)
                    await asyncio.sleep((2**attempt) + jitter)
                else:
                    task.error_message = f"Task timed out after {self._default_timeout}s"
                    graph.transition_status(task.task_id, TaskStatus.FAILED, task.error_message)
                    task.completed_at = time.time()
                    conv_log.log_task_failed(
                        task.task_id,
                        task.name,
                        task.agent,
                        task.error_message,
                        attempts=attempt + 1,
                    )
                    await self._events.publish(
                        OrchestratorEvent(
                            event_type=EventType.TASK_FAILED,
                            source=task.agent,
                            session_id=session_id,
                            task_id=task.task_id,
                            data={"error": task.error_message, "attempts": attempt + 1},
                        )
                    )
                    return {"error": task.error_message, "attempts": attempt + 1}

            except Exception as exc:
                task.retry_count = attempt + 1
                logger.warning(
                    "Task %s failed (attempt %d/%d): %s",
                    task.task_id,
                    attempt + 1,
                    task.max_retries + 1,
                    exc,
                )

                if attempt < task.max_retries:
                    graph.transition_status(task.task_id, TaskStatus.RETRYING)
                    await self._events.publish(
                        OrchestratorEvent(
                            event_type=EventType.AGENT_RETRY,
                            source=task.agent,
                            session_id=session_id,
                            task_id=task.task_id,
                            data={"attempt": attempt + 1, "max_retries": task.max_retries},
                        )
                    )
                    jitter = random.uniform(0, 1)
                    await asyncio.sleep((2**attempt) + jitter)
                else:
                    task.error_message = str(exc)
                    graph.transition_status(task.task_id, TaskStatus.FAILED, task.error_message)
                    task.completed_at = time.time()

                    conv_log.log_task_failed(
                        task.task_id, task.name, task.agent, exc, attempts=attempt + 1
                    )

                    await self._events.publish(
                        OrchestratorEvent(
                            event_type=EventType.TASK_FAILED,
                            source=task.agent,
                            session_id=session_id,
                            task_id=task.task_id,
                            data={"error": str(exc), "attempts": attempt + 1},
                        )
                    )

                    return {"error": str(exc), "attempts": attempt + 1}

        return {"error": "max retries exceeded"}

    # ------------------------------------------------------------------
    # Internal: Prompt Building
    # ------------------------------------------------------------------

    def _build_task_prompt(self, task: TaskNode, dep_context: str, project_path: str = ".") -> str:
        """Build the prompt for a specific task execution."""
        return f"""Execute the following task:

TASK: {task.name}
DESCRIPTION: {task.description}
AGENT: {task.agent}
PROJECT PATH: {project_path}

CONTEXT FROM PREVIOUS STEPS:
{dep_context or "None (this is the first step)"}

ADDITIONAL CONTEXT:
{task.context or "None"}

IMPORTANT: You are working in the project at: {project_path}
- When creating or modifying files, write them to this project path.
- Use the write_file tool to create files.
- Use the read_file tool to read existing files.
- Use the list_dir tool to explore the project structure.
- Use the execute_code tool to run code and tests.
- NEVER assume a conventional file layout (e.g. "app/main.py", "src/index.ts").
  If you are not certain a file exists, call list_dir or search_codebase FIRST.
- If a read returns "File not found", do NOT retry the same path: use the
  'parent_listing' / 'same_name_files' suggestions in the error, or list_dir,
  to locate the real path and continue. A corrected read is a success, not a
  failure.

AUTONOMY RULES (mandatory):
- Work FULLY autonomously: never ask the user for confirmation or permission;
  you are already authorised to use every tool listed above.
- Plan your steps, execute them one by one with tools, and VERIFY your own
  work (re-read what you wrote, run tests when they exist) before answering.
- If a tool fails, adapt and try a different approach instead of giving up.
- Do not stop at a partial result: only give the final answer when the task
  is genuinely complete, and state clearly what was done and what remains.

Complete this task thoroughly. If you need to create or modify files, use the appropriate tools.
Provide a clear summary of what you accomplished."""

    def _build_dependency_context(self, task: TaskNode, ctx: Any) -> str:
        """Build context string from completed dependencies."""
        parts: list[str] = []
        # Synchronous lock acquisition for read — safe because we only
        # read and the GIL protects dict.get() as a single opcode.
        for dep_id in task.depends_on:
            artifact = ctx.artifacts.get(dep_id)
            if artifact:
                parts.append(f"[{artifact['name']}]: {artifact['output'][:300]}")
        return "\n".join(parts) if parts else ""
