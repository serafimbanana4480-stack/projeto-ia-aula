"""Plan executor for the multi-agent orchestrator.

Extracted from :mod:`backend.orchestrator.engine` to keep the main
``OrchestrationEngine`` focused on coordination. ``PlanExecutor`` owns
the per-layer parallel task loop, the per-task retry loop, and the
prompt building for individual tasks.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from backend.agents.base import AgentBase, AgentRequest
from backend.orchestrator.agent_pool import AgentPool
from backend.orchestrator.dependency_graph import (
    DependencyGraph,
    ExecutionPlan,
    TaskNode,
    TaskStatus,
)
from backend.orchestrator.events import EventBus, EventEmitter, EventType, OrchestratorEvent

logger = logging.getLogger(__name__)

_INLINE_TOOL_ERROR_RE = re.compile(r"<event>tool_error\|(.+?)</event>", re.DOTALL)


def extract_tool_errors(output: str) -> list[str]:
    """Return tool error messages embedded in agent ReAct output."""
    return [msg.strip() for msg in _INLINE_TOOL_ERROR_RE.findall(output) if msg.strip()]


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
    ) -> None:
        self._llm_client = llm_client
        self._registry = registry
        self._events = event_bus
        self._agent_pool = agent_pool
        self._default_timeout = default_timeout

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
        layers = graph.topological_layers()

        await self._events.publish(
            OrchestratorEvent(
                event_type=EventType.ORCHESTRATOR_STARTED,
                source="ORCHESTRATOR",
                session_id=session_id,
                data={
                    "run_id": run_id,
                    "layers": len(layers),
                    "total_tasks": len(graph.get_all_tasks()),
                },
            )
        )

        try:
            for _layer_idx, layer in enumerate(layers):
                if cancellation_event is not None and cancellation_event.is_set():
                    break

                # Execute all tasks in this layer in parallel
                layer_tasks: list[asyncio.Task[Any]] = []
                for task_id in layer:
                    task = graph.get_task(task_id)
                    if task is None:
                        continue
                    task.status = TaskStatus.READY
                    coro = self._execute_task(
                        task, ctx, graph, session_id, run_id, cancellation_event
                    )
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

        from backend.orchestrator.engine import OrchestrationState

        final_state = OrchestrationState.COMPLETED if failed == 0 else OrchestrationState.FAILED

        result = OrchestrationResult(
            run_id=run_id,
            state=final_state,
            plan=plan,
            completed_tasks=completed,
            failed_tasks=failed,
            total_duration_ms=duration_ms,
            tokens_used=total_tokens,
            errors=errors,
            task_results=dict(ctx.artifacts),
        )

        await self._events.publish(
            OrchestratorEvent(
                event_type=EventType.ORCHESTRATOR_FINISHED,
                source="ORCHESTRATOR",
                session_id=session_id,
                data=result.__dict__,
            )
        )

        return result, ctx

    # ------------------------------------------------------------------
    # Internal: Task Execution
    # ------------------------------------------------------------------

    async def _execute_task(
        self,
        task: TaskNode,
        ctx: Any,
        graph: DependencyGraph,
        session_id: str,
        run_id: str,
        cancellation_event: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        """Execute a single task with retry logic and event emission."""
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()

        await self._events.publish(
            OrchestratorEvent(
                event_type=EventType.TASK_STARTED,
                source=task.agent,
                session_id=session_id,
                task_id=task.task_id,
                data={"task_name": task.name},
            )
        )

        agent = self._registry.get(task.agent)
        if not agent:
            task.status = TaskStatus.FAILED
            task.error_message = f"Agent {task.agent} not found"
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

        # Build context from dependencies
        dep_context = self._build_dependency_context(task, ctx)

        for attempt in range(task.max_retries + 1):
            try:
                if cancellation_event is not None and cancellation_event.is_set():
                    task.status = TaskStatus.CANCELLED
                    return {"cancelled": True}

                request = AgentRequest(
                    session_id=session_id,
                    query=self._build_task_prompt(task, dep_context, ctx.project_path),
                    client=self._llm_client,
                    project_path=ctx.project_path,
                    context={
                        "task": task.to_dict(),
                        "shared_memory": ctx.shared_memory,
                        "project_path": ctx.project_path,
                    },
                    max_iterations=5,
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
                tool_errors = extract_tool_errors(output)
                if tool_errors:
                    task.output_data["content"] = output
                    task.status = TaskStatus.FAILED
                    task.error_message = tool_errors[0]
                    task.completed_at = time.time()

                    async with ctx._lock:
                        ctx.artifacts[task.task_id] = {
                            "name": task.name,
                            "agent": task.agent,
                            "output": output,
                            "status": "failed",
                            "tool_errors": tool_errors,
                        }

                    await self._events.publish(
                        OrchestratorEvent(
                            event_type=EventType.TASK_FAILED,
                            source=task.agent,
                            session_id=session_id,
                            task_id=task.task_id,
                            data={
                                "error": task.error_message,
                                "tool_errors": tool_errors,
                            },
                        )
                    )
                    return {
                        "error": task.error_message,
                        "tool_errors": tool_errors,
                        "output": output,
                    }

                task.output_data["content"] = output
                task.status = TaskStatus.COMPLETED
                task.completed_at = time.time()

                # Store artifact
                async with ctx._lock:
                    ctx.artifacts[task.task_id] = {
                        "name": task.name,
                        "agent": task.agent,
                        "output": output,
                        "status": "completed",
                    }
                    ctx._global_context_parts.append(f"\n[{task.name}]: {output[:500]}")

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
                    task.status = TaskStatus.FAILED
                    task.error_message = f"Task timed out after {self._default_timeout}s"
                    task.completed_at = time.time()
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
                    task.status = TaskStatus.FAILED
                    task.error_message = str(exc)
                    task.completed_at = time.time()

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
