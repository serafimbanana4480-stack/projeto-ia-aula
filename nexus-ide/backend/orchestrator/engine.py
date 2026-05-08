"""Multi-Agent Orchestration Engine.

The heart of Nexus IDE's autonomous execution system. Coordinates multiple
specialized agents to execute complex plans with parallel execution,
dependency resolution, retries, cancellation, and streaming events.

Architecture:
- ``OrchestrationEngine``: main coordinator
- ``AgentInvoker``: wraps agent execution with retry/fallback
- ``ExecutionContext``: shared state across parallel agents
- ``OrchestrationResult``: aggregated outcome of a full execution

Key features:
- Parallel execution of independent tasks
- Dependency graph resolution (DAG-based)
- Automatic retry with exponential backoff
- Cancellation propagation
- Real-time event streaming
- Conflict detection and resolution
- Resource-aware scheduling
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Optional

from backend.agents.base import AgentBase, AgentRequest, AgentResponse
from backend.orchestrator.dependency_graph import (
    DependencyGraph,
    ExecutionPlan,
    TaskNode,
    TaskPriority,
    TaskStatus,
)
from backend.orchestrator.events import (
    EventBus,
    EventEmitter,
    EventType,
    OrchestratorEvent,
)
from backend.orchestrator.fallback import invoke_with_fallback
from backend.tools.ollama_client import ChatMessage, OllamaClient, OllamaError

logger = logging.getLogger(__name__)


class OrchestrationState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExecutionContext:
    """Shared state accessible to all agents during orchestration."""

    session_id: str
    project_path: str = "."
    shared_memory: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)  # task outputs keyed by task_id
    global_context: str = ""  # accumulated context from completed tasks


@dataclass
class OrchestrationResult:
    """Aggregated result of an orchestration run."""

    run_id: str
    state: OrchestrationState
    plan: Optional[ExecutionPlan] = None
    completed_tasks: int = 0
    failed_tasks: int = 0
    total_duration_ms: int = 0
    tokens_used: int = 0
    errors: list[str] = field(default_factory=list)
    task_results: dict[str, Any] = field(default_factory=dict)


class OrchestrationEngine:
    """Coordinates multi-agent execution of structured plans.

    Usage::

        engine = OrchestrationEngine(ollama_client, agent_registry, event_bus)
        plan = await engine.create_plan("Add JWT auth to the API", session_id)
        result = await engine.execute_plan(plan, session_id)
    """

    def __init__(
        self,
        ollama: OllamaClient,
        registry: dict[str, AgentBase],
        event_bus: EventBus,
        *,
        max_parallel: int = 5,
        default_timeout: int = 300,
        max_retries: int = 2,
    ) -> None:
        self._ollama = ollama
        self._registry = registry
        self._events = event_bus
        self._max_parallel = max_parallel
        self._default_timeout = default_timeout
        self._max_retries = max_retries

        # Active runs
        self._active_runs: dict[str, asyncio.Task[Any]] = {}
        self._cancellation_events: dict[str, asyncio.Event] = {}
        self._state: dict[str, OrchestrationState] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_plan(
        self,
        objective: str,
        session_id: str,
        *,
        context: str = "",
        history: list[ChatMessage] | None = None,
    ) -> ExecutionPlan:
        """Use the Architect agent to create a structured execution plan."""
        self._state[session_id] = OrchestrationState.PLANNING

        await self._events.publish(OrchestratorEvent(
            event_type=EventType.ORCHESTRATOR_STARTED,
            source="ORCHESTRATOR",
            session_id=session_id,
            data={"objective": objective, "phase": "planning"},
        ))

        architect = self._registry.get("ARCHITECT")
        if not architect:
            raise ValueError("ARCHITECT agent not found in registry")

        # Build planning prompt
        planning_prompt = self._build_planning_prompt(objective, context)
        request = AgentRequest(
            session_id=session_id,
            query=planning_prompt,
            client=self._ollama,
            history=history or [],
            enable_thinking=True,
            max_iterations=5,
        )

        # Stream planning
        plan_content = ""
        async with EventEmitter(self._events, "ARCHITECT", session_id) as emit:
            async for token in architect.run(request):
                plan_content += token
                await emit.emit(EventType.TOKEN, content=token)

        # Parse plan into structured steps
        plan = self._parse_plan(plan_content, objective, session_id)
        plan.created_at = time.time()

        await self._events.publish(OrchestratorEvent(
            event_type=EventType.PLAN_CREATED,
            source="ARCHITECT",
            session_id=session_id,
            data=plan.to_dict(),
        ))

        self._state[session_id] = OrchestrationState.AWAITING_APPROVAL
        return plan

    async def execute_plan(
        self,
        plan: ExecutionPlan,
        session_id: str,
        *,
        auto_approve: bool = False,
        project_path: str = ".",
    ) -> OrchestrationResult:
        """Execute a plan, running tasks in dependency order with parallelism."""
        if not auto_approve and plan.requires_approval and not plan.approved:
            raise ValueError("Plan requires approval before execution")

        run_id = uuid.uuid4().hex[:12]
        self._state[session_id] = OrchestrationState.EXECUTING
        self._cancellation_events[session_id] = asyncio.Event()

        ctx = ExecutionContext(
            session_id=session_id,
            project_path=project_path,
        )

        start_time = time.time()
        total_tokens = 0
        errors: list[str] = []

        graph = plan.dependency_graph
        layers = graph.topological_layers()

        await self._events.publish(OrchestratorEvent(
            event_type=EventType.ORCHESTRATOR_STARTED,
            source="ORCHESTRATOR",
            session_id=session_id,
            data={"run_id": run_id, "layers": len(layers), "total_tasks": len(graph.get_all_tasks())},
        ))

        try:
            for layer_idx, layer in enumerate(layers):
                if self._cancellation_events[session_id].is_set():
                    break

                # Execute all tasks in this layer in parallel
                layer_tasks = []
                for task_id in layer:
                    task = graph.get_task(task_id)
                    if task is None:
                        continue
                    task.status = TaskStatus.READY
                    layer_tasks.append(self._execute_task(
                        task, ctx, graph, session_id, run_id
                    ))

                if layer_tasks:
                    results = await asyncio.gather(*layer_tasks, return_exceptions=True)
                    for result in results:
                        if isinstance(result, Exception):
                            errors.append(str(result))
                        elif isinstance(result, dict):
                            total_tokens += result.get("tokens", 0)

        except asyncio.CancelledError:
            self._state[session_id] = OrchestrationState.CANCELLED
            await self._events.publish(OrchestratorEvent(
                event_type=EventType.ORCHESTRATOR_FINISHED,
                source="ORCHESTRATOR",
                session_id=session_id,
                data={"run_id": run_id, "cancelled": True},
            ))
            raise

        duration_ms = int((time.time() - start_time) * 1000)
        completed = sum(1 for t in graph.get_all_tasks() if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in graph.get_all_tasks() if t.status == TaskStatus.FAILED)

        final_state = OrchestrationState.COMPLETED if failed == 0 else OrchestrationState.FAILED
        self._state[session_id] = final_state

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

        await self._events.publish(OrchestratorEvent(
            event_type=EventType.ORCHESTRATOR_FINISHED,
            source="ORCHESTRATOR",
            session_id=session_id,
            data=result.__dict__,
        ))

        return result

    async def cancel(self, session_id: str) -> None:
        """Cancel an active orchestration run."""
        if session_id in self._cancellation_events:
            self._cancellation_events[session_id].set()
            self._state[session_id] = OrchestrationState.CANCELLED
            logger.info("Cancelled orchestration for session %s", session_id)

    def get_state(self, session_id: str) -> OrchestrationState:
        """Get the current state of an orchestration run."""
        return self._state.get(session_id, OrchestrationState.IDLE)

    # ------------------------------------------------------------------
    # Internal: Task Execution
    # ------------------------------------------------------------------

    async def _execute_task(
        self,
        task: TaskNode,
        ctx: ExecutionContext,
        graph: DependencyGraph,
        session_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        """Execute a single task with retry logic and event emission."""
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()

        await self._events.publish(OrchestratorEvent(
            event_type=EventType.TASK_STARTED,
            source=task.agent,
            session_id=session_id,
            task_id=task.task_id,
            data={"task_name": task.name},
        ))

        agent = self._registry.get(task.agent)
        if not agent:
            task.status = TaskStatus.FAILED
            task.error_message = f"Agent {task.agent} not found"
            await self._events.publish(OrchestratorEvent(
                event_type=EventType.TASK_FAILED,
                source=task.agent,
                session_id=session_id,
                task_id=task.task_id,
                data={"error": task.error_message},
            ))
            return {"error": task.error_message}

        # Build context from dependencies
        dep_context = self._build_dependency_context(task, ctx)

        for attempt in range(task.max_retries + 1):
            try:
                if self._cancellation_events.get(session_id, asyncio.Event()).is_set():
                    task.status = TaskStatus.CANCELLED
                    return {"cancelled": True}

                request = AgentRequest(
                    session_id=session_id,
                    query=self._build_task_prompt(task, dep_context),
                    client=self._ollama,
                    context={"task": task.to_dict(), "shared_memory": ctx.shared_memory},
                    max_iterations=5,
                )

                # Stream execution
                output_parts: list[str] = []
                async with EventEmitter(self._events, task.agent, session_id, task.task_id) as emit:
                    async for token in agent.run(request):
                        output_parts.append(token)
                        await emit.emit(EventType.TOKEN, content=token)

                output = "".join(output_parts)
                task.output_data["content"] = output
                task.status = TaskStatus.COMPLETED
                task.completed_at = time.time()

                # Store artifact
                ctx.artifacts[task.task_id] = {
                    "name": task.name,
                    "agent": task.agent,
                    "output": output,
                    "status": "completed",
                }
                ctx.global_context += f"\n[{task.name}]: {output[:500]}"

                await self._events.publish(OrchestratorEvent(
                    event_type=EventType.TASK_COMPLETED,
                    source=task.agent,
                    session_id=session_id,
                    task_id=task.task_id,
                    data={"output_length": len(output)},
                ))

                return {"success": True, "output": output, "tokens": len(output_parts)}

            except (OllamaError, Exception) as exc:
                task.retry_count = attempt + 1
                logger.warning(
                    "Task %s failed (attempt %d/%d): %s",
                    task.task_id, attempt + 1, task.max_retries + 1, exc,
                )

                if attempt < task.max_retries:
                    await self._events.publish(OrchestratorEvent(
                        event_type=EventType.AGENT_RETRY,
                        source=task.agent,
                        session_id=session_id,
                        task_id=task.task_id,
                        data={"attempt": attempt + 1, "max_retries": task.max_retries},
                    ))
                    await asyncio.sleep(2 ** attempt)  # exponential backoff
                else:
                    task.status = TaskStatus.FAILED
                    task.error_message = str(exc)
                    task.completed_at = time.time()

                    await self._events.publish(OrchestratorEvent(
                        event_type=EventType.TASK_FAILED,
                        source=task.agent,
                        session_id=session_id,
                        task_id=task.task_id,
                        data={"error": str(exc), "attempts": attempt + 1},
                    ))

                    return {"error": str(exc), "attempts": attempt + 1}

        return {"error": "max retries exceeded"}

    # ------------------------------------------------------------------
    # Internal: Prompt Building
    # ------------------------------------------------------------------

    def _build_planning_prompt(self, objective: str, context: str) -> str:
        """Build the prompt for the Architect to create a plan."""
        return f"""Create a detailed, structured execution plan for the following objective:

OBJECTIVE: {objective}

ADDITIONAL CONTEXT: {context or "None"}

Your plan MUST be structured as a JSON array of steps. Each step must have:
- "name": short descriptive name
- "description": what this step accomplishes
- "agent": which agent should execute it (ARCHITECT, CODER, ANALYZER, DEBUGGER, RESEARCHER, DOCUMENTER, OPTIMIZER, MICRO)
- "depends_on": list of step indices (0-based) this step depends on
- "priority": "high", "medium", or "low"
- "sandboxed": true if this step needs sandboxed execution

Output ONLY valid JSON array. No other text.

Example:
[
  {{"name": "Analyze codebase", "description": "Understand current auth state", "agent": "ANALYZER", "depends_on": [], "priority": "high", "sandboxed": false}},
  {{"name": "Implement JWT", "description": "Add JWT auth middleware", "agent": "CODER", "depends_on": [0], "priority": "high", "sandboxed": false}}
]"""

    def _build_task_prompt(self, task: TaskNode, dep_context: str) -> str:
        """Build the prompt for a specific task execution."""
        return f"""Execute the following task:

TASK: {task.name}
DESCRIPTION: {task.description}
AGENT: {task.agent}

CONTEXT FROM PREVIOUS STEPS:
{dep_context or "None (this is the first step)"}

ADDITIONAL CONTEXT:
{task.context or "None"}

Complete this task thoroughly. If you need to create or modify files, use the appropriate tools.
Provide a clear summary of what you accomplished."""

    def _build_dependency_context(self, task: TaskNode, ctx: ExecutionContext) -> str:
        """Build context string from completed dependencies."""
        parts: list[str] = []
        for dep_id in task.depends_on:
            artifact = ctx.artifacts.get(dep_id)
            if artifact:
                parts.append(f"[{artifact['name']}]: {artifact['output'][:300]}")
        return "\n".join(parts) if parts else ""

    # ------------------------------------------------------------------
    # Internal: Plan Parsing
    # ------------------------------------------------------------------

    def _parse_plan(
        self,
        plan_content: str,
        objective: str,
        session_id: str,
    ) -> ExecutionPlan:
        """Parse the Architect's JSON output into an ExecutionPlan."""
        import json
        import re

        # Extract JSON array from content
        json_match = re.search(r'\[.*\]', plan_content, re.DOTALL)
        if not json_match:
            logger.warning("No JSON array found in plan content, creating single-step plan")
            task = TaskNode(
                name="Execute Objective",
                description=objective,
                agent="CODER",
            )
            return ExecutionPlan.from_steps(
                title=objective[:100],
                description=objective,
                steps=[task],
                session_id=session_id,
            )

        try:
            raw_steps = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            logger.warning("Failed to parse plan JSON, creating single-step plan")
            task = TaskNode(
                name="Execute Objective",
                description=objective,
                agent="CODER",
            )
            return ExecutionPlan.from_steps(
                title=objective[:100],
                description=objective,
                steps=[task],
                session_id=session_id,
            )

        steps: list[TaskNode] = []
        for i, raw in enumerate(raw_steps):
            task = TaskNode(
                name=raw.get("name", f"Step {i+1}"),
                description=raw.get("description", ""),
                agent=raw.get("agent", "CODER").upper(),
                priority=TaskPriority[raw.get("priority", "medium").upper()] if raw.get("priority", "medium").upper() in TaskPriority.__members__ else TaskPriority.MEDIUM,
                sandboxed=raw.get("sandboxed", False),
            )
            steps.append(task)

        # Resolve dependencies (convert indices to task_ids)
        for i, raw in enumerate(raw_steps):
            for dep_idx in raw.get("depends_on", []):
                if 0 <= dep_idx < len(steps) and dep_idx != i:
                    steps[i].depends_on.append(steps[dep_idx].task_id)
                    steps[dep_idx].required_by.append(steps[i].task_id)

        return ExecutionPlan.from_steps(
            title=objective[:100],
            description=objective,
            steps=steps,
            session_id=session_id,
        )
