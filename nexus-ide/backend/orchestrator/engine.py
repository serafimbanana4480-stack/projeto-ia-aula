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
import random
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from backend.agents.base import AgentBase, AgentRequest
from backend.config.settings import get_model_config, load_prompt
from backend.orchestrator.dependency_graph import (
    DependencyGraph,
    ExecutionPlan,
    TaskNode,
    TaskPriority,
    TaskStatus,
)
from backend.orchestrator.agent_pool import AgentPool, get_agent_pool
from backend.orchestrator.events import (
    EventBus,
    EventEmitter,
    EventType,
    OrchestratorEvent,
)
from backend.tools.ollama_client import ChatMessage

try:
    from cachetools import TTLCache
except ImportError:
    TTLCache = None

logger = logging.getLogger(__name__)


async def _iterate_agent_output(output: Any) -> AsyncIterator[str]:
    """Yield tokens from async iterables, coroutines, or plain iterables."""
    if asyncio.iscoroutine(output):
        output = await output

    if hasattr(output, "__aiter__"):
        async for token in output:
            yield token
        return

    for token in output:
        yield token


class OrchestrationState(StrEnum):
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
    _global_context_parts: list[str] = field(default_factory=list)  # accumulated context from completed tasks
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def global_context(self) -> str:
        return "".join(self._global_context_parts)

    @global_context.setter
    def global_context(self, value: str) -> None:
        # Support legacy assignment, but internally append
        if not self._global_context_parts:
            self._global_context_parts.append(value)
        else:
            self._global_context_parts.append(value)


@dataclass
class OrchestrationResult:
    """Aggregated result of an orchestration run."""

    run_id: str
    state: OrchestrationState
    plan: ExecutionPlan | None = None
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
        llm_client: Any,
        registry: dict[str, AgentBase],
        event_bus: EventBus,
        *,
        max_parallel: int = 5,
        default_timeout: int = 300,
        max_retries: int = 2,
    ) -> None:
        self._llm_client = llm_client
        self._registry = registry
        self._events = event_bus
        self._max_parallel = max_parallel
        self._default_timeout = default_timeout
        self._max_retries = max_retries

        # Active runs
        self._active_runs: dict[str, asyncio.Task[Any]] = {}
        self._cancellation_events: dict[str, asyncio.Event] = {}
        self._state: dict[str, OrchestrationState] = {}

        # Plan storage with TTL eviction to prevent memory leaks
        if TTLCache is not None:
            self._plans: Any = TTLCache(maxsize=1000, ttl=3600)
            self._session_plans: Any = TTLCache(maxsize=1000, ttl=3600)
        else:
            self._plans: dict[str, ExecutionPlan] = {}
            self._session_plans: dict[str, str] = {}
        self._active_tasks: dict[str, list[asyncio.Task[Any]]] = {}
        self._active_tasks_lock = asyncio.Lock()
        self._agent_pool: AgentPool = get_agent_pool()

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
        """Create a structured execution plan using the coder model for clean JSON.

        Uses the coder model (qwen2.5-coder:7b) directly for planning because
        it follows structured output instructions much better than reasoning models.
        The ARCHITECT agent (reasoning model) is still used during plan execution
        for deep design tasks.
        """
        self._state[session_id] = OrchestrationState.PLANNING

        await self._events.publish(
            OrchestratorEvent(
                event_type=EventType.ORCHESTRATOR_STARTED,
                source="ORCHESTRATOR",
                session_id=session_id,
                data={"objective": objective, "phase": "planning"},
            )
        )

        # Build planning prompt
        planning_prompt = self._build_planning_prompt(objective, context)

        # Use coder model directly for clean JSON output (not the architect agent)
        planner_cfg = get_model_config("coder")
        planner_model = planner_cfg["id"]
        system_prompt = load_prompt("architect")

        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=planning_prompt),
        ]

        # Stream planning directly from Ollama
        plan_content_parts: list[str] = []
        async with EventEmitter(self._events, "PLANNER", session_id) as emit:
            async for token in self._llm_client.chat_stream(
                model=planner_model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                options={
                    "temperature": planner_cfg.get("temperature", 0.2),
                    "num_predict": 16384,  # Large plans need more tokens
                },
            ):
                plan_content_parts.append(token)
                await emit.emit(EventType.TOKEN, content=token)
        plan_content = "".join(plan_content_parts)

        # Parse plan into structured steps
        plan = self._parse_plan(plan_content, objective, session_id)
        plan.created_at = time.time()

        await self._events.publish(
            OrchestratorEvent(
                event_type=EventType.PLAN_CREATED,
                source="ARCHITECT",
                session_id=session_id,
                data=plan.to_dict(),
            )
        )

        self._state[session_id] = OrchestrationState.AWAITING_APPROVAL

        # Store plan for later retrieval
        self._plans[plan.plan_id] = plan
        self._session_plans[session_id] = plan.plan_id

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
            async with self._active_tasks_lock:
                self._active_tasks[session_id] = []
            for _layer_idx, layer in enumerate(layers):
                if session_id in self._cancellation_events and self._cancellation_events[session_id].is_set():
                    break

                # Execute all tasks in this layer in parallel
                layer_tasks = []
                for task_id in layer:
                    task = graph.get_task(task_id)
                    if task is None:
                        continue
                    task.status = TaskStatus.READY
                    coro = self._execute_task(task, ctx, graph, session_id, run_id)
                    t = asyncio.create_task(coro)
                    layer_tasks.append(t)
                    async with self._active_tasks_lock:
                        self._active_tasks[session_id].append(t)

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
            self._state[session_id] = OrchestrationState.CANCELLED
            await self._events.publish(
                OrchestratorEvent(
                    event_type=EventType.ORCHESTRATOR_FINISHED,
                    source="ORCHESTRATOR",
                    session_id=session_id,
                    data={"run_id": run_id, "cancelled": True},
                )
            )
            raise
        finally:
            # Clean up active task references to avoid memory leaks
            async with self._active_tasks_lock:
                self._active_tasks.pop(session_id, None)

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

        await self._events.publish(
            OrchestratorEvent(
                event_type=EventType.ORCHESTRATOR_FINISHED,
                source="ORCHESTRATOR",
                session_id=session_id,
                data=result.__dict__,
            )
        )

        return result

    async def cancel(self, session_id: str) -> None:
        """Cancel an active orchestration run."""
        if session_id not in self._cancellation_events:
            self._cancellation_events[session_id] = asyncio.Event()
        self._cancellation_events[session_id].set()
        self._state[session_id] = OrchestrationState.CANCELLED
        # Actually cancel running asyncio tasks
        async with self._active_tasks_lock:
            tasks = self._active_tasks.pop(session_id, [])
        for t in tasks:
            if not t.done():
                t.cancel()
        logger.info("Cancelled orchestration for session %s", session_id)

    async def execute_autonomous(
        self,
        objective: str,
        session_id: str,
        *,
        context: str = "",
        history: list[ChatMessage] | None = None,
        project_path: str = ".",
        max_verify_iterations: int = 3,
    ) -> OrchestrationResult:
        """Full autonomous cycle: Plan → Execute → Verify → Iterate.

        This is the core autonomy feature. After creating and executing a plan,
        it automatically:
        1. Runs DEBUGGER verification after each CODER step
        2. If errors found, creates fix tasks and re-executes
        3. Runs ANALYZER for final quality review
        4. Iterates up to max_verify_iterations times

        Returns the final OrchestrationResult with all verification data.
        """
        # Phase 1: PLAN
        plan = await self.create_plan(
            objective=objective,
            session_id=session_id,
            context=context,
            history=history,
        )
        plan.approved = True  # Auto-approve in autonomous mode

        await self._events.publish(
            OrchestratorEvent(
                event_type=EventType.ORCHESTRATOR_STARTED,
                source="ORCHESTRATOR",
                session_id=session_id,
                data={"phase": "execute", "plan_id": plan.plan_id, "steps": len(plan.steps)},
            )
        )

        # Phase 2: EXECUTE
        result = await self.execute_plan(
            plan, session_id, auto_approve=True, project_path=project_path,
        )

        # Phase 3: VERIFY & ITERATE
        for verify_round in range(max_verify_iterations):
            if result.state == OrchestrationState.CANCELLED:
                break

            # Find tasks that produced code (CODER steps) and verify them
            verification_needed = self._find_tasks_needing_verification(result)
            if not verification_needed:
                logger.info("Autonomous: no verification needed (round %d)", verify_round + 1)
                break

            logger.info(
                "Autonomous: verification round %d/%d — %d tasks to verify",
                verify_round + 1, max_verify_iterations, len(verification_needed),
            )

            # Create verification tasks
            verify_tasks = self._create_verification_tasks(verification_needed, result, session_id)

            # Execute verification
            verify_plan = ExecutionPlan.from_steps(
                title=f"Verification Round {verify_round + 1}",
                description=f"Verify outputs from round {verify_round}",
                steps=verify_tasks,
                session_id=session_id,
            )

            verify_result = await self.execute_plan(
                verify_plan, session_id, auto_approve=True, project_path=project_path,
            )

            # Check if verification found issues
            issues_found = self._extract_verification_issues(verify_result)
            if not issues_found:
                logger.info("Autonomous: verification passed (round %d)", verify_round + 1)
                break

            # Phase 4: ITERATE — create fix tasks for found issues
            logger.info(
                "Autonomous: %d issues found, creating fix tasks (round %d)",
                len(issues_found), verify_round + 1,
            )

            fix_tasks = self._create_fix_tasks(issues_found, verify_tasks, session_id)
            fix_plan = ExecutionPlan.from_steps(
                title=f"Fix Round {verify_round + 1}",
                description=f"Fix issues found in verification round {verify_round + 1}",
                steps=fix_tasks,
                session_id=session_id,
            )

            result = await self.execute_plan(
                fix_plan, session_id, auto_approve=True, project_path=project_path,
            )

        # Phase 5: FINAL REVIEW with ANALYZER
        final_review = self._create_final_review_task(objective, result, session_id)
        review_plan = ExecutionPlan.from_steps(
            title="Final Quality Review",
            description="Comprehensive quality review of all changes",
            steps=[final_review],
            session_id=session_id,
        )
        await self.execute_plan(
            review_plan, session_id, auto_approve=True, project_path=project_path,
        )

        self._state[session_id] = OrchestrationState.COMPLETED
        return result

    def _find_tasks_needing_verification(self, result: OrchestrationResult) -> list[dict]:
        """Find completed CODER tasks that should be verified by DEBUGGER."""
        tasks_needing_verify = []
        for task_id, artifact in result.task_results.items():
            if not isinstance(artifact, dict):
                continue
            agent = artifact.get("agent", "")
            status = artifact.get("status", "")
            if agent == "CODER" and status == "completed":
                tasks_needing_verify.append({
                    "task_id": task_id,
                    "name": artifact.get("name", "Unknown"),
                    "output": artifact.get("output", ""),
                })
        return tasks_needing_verify

    def _create_verification_tasks(
        self,
        tasks_to_verify: list[dict],
        result: OrchestrationResult,
        session_id: str,
    ) -> list[TaskNode]:
        """Create DEBUGGER verification tasks for completed CODER work."""
        verify_steps: list[TaskNode] = []
        for task_info in tasks_to_verify:
            verify_task = TaskNode(
                name=f"Verify: {task_info['name']}",
                description=(
                    f"Verify the output of task '{task_info['name']}'. "
                    f"Check for: bugs, syntax errors, missing imports, "
                    f"logic errors, edge cases. "
                    f"Run any tests if available. "
                    f"Original output:\n{task_info['output'][:1000]}"
                ),
                agent="DEBUGGER",
                priority=TaskPriority.HIGH,
                context=task_info["output"][:2000],
            )
            verify_steps.append(verify_task)
        return verify_steps

    def _extract_verification_issues(self, verify_result: OrchestrationResult) -> list[dict]:
        """Extract issues found by DEBUGGER from verification results."""
        issues = []
        for task_id, artifact in verify_result.task_results.items():
            if not isinstance(artifact, dict):
                continue
            output = artifact.get("output", "")
            agent = artifact.get("agent", "")
            # Only check DEBUGGER outputs for issues
            if agent != "DEBUGGER":
                continue
            # Heuristic: look for error indicators in DEBUGGER output
            error_indicators = [
                "error", "bug", "issue", "problem", "fix",
                "failed", "incorrect", "missing", "broken",
                "erro", "problema", "falha",  # Portuguese
            ]
            output_lower = output.lower()
            if any(ind in output_lower for ind in error_indicators):
                issues.append({
                    "task_id": task_id,
                    "name": artifact.get("name", "Unknown verification"),
                    "output": output,
                    "agent": agent,
                })
        return issues

    def _create_fix_tasks(
        self,
        issues: list[dict],
        verify_tasks: list[TaskNode],
        session_id: str,
    ) -> list[TaskNode]:
        """Create CODER fix tasks based on DEBUGGER findings."""
        fix_steps: list[TaskNode] = []
        for issue in issues:
            fix_task = TaskNode(
                name=f"Fix: {issue['name']}",
                description=(
                    f"Fix the issues found during verification of '{issue['name']}'. "
                    f"DEBUGGER findings:\n{issue['output'][:2000]}\n\n"
                    f"Apply all necessary fixes and ensure the code works correctly."
                ),
                agent="CODER",
                priority=TaskPriority.HIGH,
                context=issue["output"][:2000],
            )
            fix_steps.append(fix_task)
        return fix_steps

    def _create_final_review_task(
        self,
        objective: str,
        result: OrchestrationResult,
        session_id: str,
    ) -> TaskNode:
        """Create a final ANALYZER review task."""
        completed_summary = "\n".join(
            f"- {a.get('name', 'Unknown')}: {a.get('status', '?')}"
            for a in result.task_results.values()
            if isinstance(a, dict)
        )
        return TaskNode(
            name="Final Quality Review",
            description=(
                f"Perform a comprehensive quality review of all work done for: {objective}\n\n"
                f"Completed tasks:\n{completed_summary}\n\n"
                f"Check for: consistency, completeness, code quality, "
                f"security issues, performance problems, missing documentation."
            ),
            agent="ANALYZER",
            priority=TaskPriority.MEDIUM,
        )

    def get_state(self, session_id: str) -> OrchestrationState:
        """Get the current state of an orchestration run."""
        return self._state.get(session_id, OrchestrationState.IDLE)

    def get_plan(self, plan_id: str) -> ExecutionPlan | None:
        """Retrieve a stored plan by its ID."""
        return self._plans.get(plan_id)

    def get_plan_by_session(self, session_id: str) -> ExecutionPlan | None:
        """Retrieve the plan associated with a session."""
        plan_id = self._session_plans.get(session_id)
        if plan_id:
            return self._plans.get(plan_id)
        return None

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
                if session_id in self._cancellation_events and self._cancellation_events[session_id].is_set():
                    task.status = TaskStatus.CANCELLED
                    return {"cancelled": True}

                request = AgentRequest(
                    session_id=session_id,
                    query=self._build_task_prompt(task, dep_context, ctx.project_path),
                    client=self._llm_client,
                    context={"task": task.to_dict(), "shared_memory": ctx.shared_memory, "project_path": ctx.project_path},
                    max_iterations=5,
                )

                # Stream execution with hard timeout
                output_parts: list[str] = []
                async with self._agent_pool.slot(task.agent):
                    async with EventEmitter(self._events, task.agent, session_id, task.task_id) as emit:
                        async with asyncio.timeout(self._default_timeout):
                            async for token in _iterate_agent_output(agent.run(request)):
                                output_parts.append(token)
                                await emit.emit(EventType.TOKEN, content=token)

                output = "".join(output_parts)
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

            except asyncio.TimeoutError as exc:
                task.retry_count = attempt + 1
                logger.warning("Task %s timed out (attempt %d/%d)", task.task_id, attempt + 1, task.max_retries + 1)
                if attempt < task.max_retries:
                    await self._events.publish(
                        OrchestratorEvent(
                            event_type=EventType.AGENT_RETRY,
                            source=task.agent,
                            session_id=session_id,
                            task_id=task.task_id,
                            data={"attempt": attempt + 1, "max_retries": task.max_retries, "reason": "timeout"},
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

    def _build_planning_prompt(self, objective: str, context: str) -> str:
        """Build the prompt for creating a professional multi-phase execution plan."""
        return f"""You are a senior software architect and project manager. Create a COMPREHENSIVE, PROFESSIONAL execution plan for:

OBJECTIVE: {objective}

ADDITIONAL CONTEXT: {context or "None"}

IMPORTANT: Create a DETAILED plan with 10-25 steps organized into phases. Each phase builds on the previous one.
Think like a real project manager: setup -> implementation -> testing -> documentation -> review.

Available agents and their specialties:
- ARCHITECT: system design, architecture decisions, code review, final approval
- CODER: writing code, implementing features, creating files, scaffolding, refactoring
- ANALYZER: reviewing code quality, security audit, finding issues, code smells
- DEBUGGER: fixing bugs, troubleshooting, running tests, verifying fixes
- RESEARCHER: searching web, reading docs, gathering info, API documentation
- DOCUMENTER: writing docs, README, API docs, inline comments, changelogs
- OPTIMIZER: performance tuning, benchmarking, profiling, optimization

PHASE GUIDELINES:
1. SETUP: Project initialization, directory structure, dependencies, configuration
2. CORE IMPLEMENTATION: Main features, data models, business logic, API endpoints
3. TESTING: Unit tests, integration tests, edge cases, error handling
4. QUALITY ASSURANCE: Code review, security audit, performance check
5. DOCUMENTATION: README, API docs, inline comments, usage examples
6. FINAL REVIEW: Architecture review, integration verification, polish

Respond with ONLY a JSON array. No markdown, no explanation, just the JSON:
[
  {{"name": "Phase 1: Setup - Initialize project structure", "description": "Create directory structure, setup configuration files, install dependencies", "agent": "CODER", "depends_on": [], "priority": "high", "sandboxed": false}},
  {{"name": "Phase 1: Setup - Configure development environment", "description": "Set up linting, formatting, and build configuration", "agent": "CODER", "depends_on": [0], "priority": "high", "sandboxed": false}},
  {{"name": "Phase 2: Core - Implement data models", "description": "Define core data structures and types", "agent": "CODER", "depends_on": [0], "priority": "high", "sandboxed": false}},
  {{"name": "Phase 2: Core - Implement business logic", "description": "Write main application logic and algorithms", "agent": "CODER", "depends_on": [2], "priority": "high", "sandboxed": false}},
  {{"name": "Phase 3: Testing - Write unit tests", "description": "Create comprehensive unit tests for all modules", "agent": "DEBUGGER", "depends_on": [3], "priority": "high", "sandboxed": false}},
  {{"name": "Phase 4: QA - Code review and security audit", "description": "Review code quality, identify issues, check for security vulnerabilities", "agent": "ANALYZER", "depends_on": [3], "priority": "medium", "sandboxed": false}},
  {{"name": "Phase 4: QA - Fix issues from review", "description": "Address all issues found during code review and security audit", "agent": "DEBUGGER", "depends_on": [5], "priority": "high", "sandboxed": false}},
  {{"name": "Phase 5: Docs - Write documentation", "description": "Create README, API documentation, and usage examples", "agent": "DOCUMENTER", "depends_on": [6], "priority": "medium", "sandboxed": false}},
  {{"name": "Phase 6: Review - Final architecture review", "description": "Verify all components work together, review final code quality", "agent": "ARCHITECT", "depends_on": [7], "priority": "medium", "sandboxed": false}}
]

The depends_on field uses 0-based index of the step this depends on.
Priority values: "high", "medium", "low".
Make steps SPECIFIC and ACTIONABLE. Each step must produce a concrete deliverable.
Include at least 10 steps. More complex objectives should have 15-25 steps.
Use phase prefixes in step names: "Phase N: Name - Description"."""

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

    def _build_dependency_context(self, task: TaskNode, ctx: ExecutionContext) -> str:
        """Build context string from completed dependencies."""
        parts: list[str] = []
        # Synchronous lock acquisition for read — safe because we only
        # read and the GIL protects dict.get() as a single opcode.
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

        # Remove thinking blocks first (common with reasoning models)
        cleaned = re.sub(r"<thinking>.*?</thinking>", "", plan_content, flags=re.DOTALL)
        # Remove markdown code fences
        cleaned = re.sub(r"```json\s*", "", cleaned)
        cleaned = re.sub(r"```\s*", "", cleaned)
        # Remove any text before the first [ and after the last ]
        json_match = re.search(r"\[.*\]", cleaned, re.DOTALL)

        if not json_match:
            # Try to parse as natural text with numbered steps
            text_plan = self._parse_text_plan(cleaned, objective)
            if text_plan is not None and len(text_plan.steps) > 1:
                return text_plan

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
            # Try to fix common JSON issues (trailing commas, etc.)
            raw_text = json_match.group(0)
            # Remove trailing commas before ] or }
            raw_text = re.sub(r",\s*([}\]])", r"\1", raw_text)
            try:
                raw_steps = json.loads(raw_text)
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

        if not isinstance(raw_steps, list) or len(raw_steps) == 0:
            logger.warning("Plan JSON is not a valid list, creating single-step plan")
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
            if not isinstance(raw, dict):
                continue
            task = TaskNode(
                name=raw.get("name", f"Step {i + 1}"),
                description=raw.get("description", ""),
                agent=raw.get("agent", "CODER").upper(),
                priority=TaskPriority[raw.get("priority", "medium").upper()]
                if raw.get("priority", "medium").upper() in TaskPriority.__members__
                else TaskPriority.MEDIUM,
                sandboxed=raw.get("sandboxed", False),
            )
            steps.append(task)

        if not steps:
            task = TaskNode(name="Execute Objective", description=objective, agent="CODER")
            steps.append(task)

        # Resolve dependencies (convert indices OR names to task_ids)
        # Build a name→index lookup for string-based depends_on
        name_to_idx: dict[str, int] = {}
        for idx, step in enumerate(steps):
            name_to_idx[step.name.lower().strip()] = idx
            # Also register shortened forms (e.g. "Phase 1: Setup" → "Setup")
            if ":" in step.name:
                short = step.name.split(":", 1)[-1].strip().lower()
                name_to_idx[short] = idx
            if "-" in step.name:
                short = step.name.split("-", 1)[-1].strip().lower()
                name_to_idx[short] = idx

        for i, raw in enumerate(raw_steps):
            if not isinstance(raw, dict):
                continue
            raw_deps = raw.get("depends_on", [])
            if not isinstance(raw_deps, list):
                raw_deps = [raw_deps] if raw_deps else []
            for dep_ref in raw_deps:
                dep_idx = self._resolve_dep_ref(dep_ref, len(steps), name_to_idx)
                if dep_idx is not None and dep_idx != i:
                    steps[i].depends_on.append(steps[dep_idx].task_id)
                    steps[dep_idx].required_by.append(steps[i].task_id)

        return ExecutionPlan.from_steps(
            title=objective[:100],
            description=objective,
            steps=steps,
            session_id=session_id,
        )

    @staticmethod
    def _resolve_dep_ref(
        dep_ref: Any,
        total_steps: int,
        name_to_idx: dict[str, int],
    ) -> int | None:
        """Resolve a depends_on reference to a step index.

        Handles:
        - Integer indices (0-based): directly validated
        - String names: fuzzy-matched against step names
        - 1-based indices from LLMs that forget 0-based convention
        """
        # Integer index (0-based)
        if isinstance(dep_ref, int):
            if 0 <= dep_ref < total_steps:
                return dep_ref
            # Maybe 1-based? Convert and check
            if 1 <= dep_ref <= total_steps:
                return dep_ref - 1
            return None

        # String reference — try exact then fuzzy match
        if isinstance(dep_ref, str):
            lowered = dep_ref.lower().strip()
            # Exact match
            if lowered in name_to_idx:
                return name_to_idx[lowered]
            # Try removing common prefixes
            for prefix in ("step ", "phase ", "task "):
                if lowered.startswith(prefix):
                    stripped = lowered[len(prefix):]
                    if stripped in name_to_idx:
                        return name_to_idx[stripped]
            # Try numeric string (e.g. "1", "2")
            try:
                num = int(lowered)
                if 0 <= num < total_steps:
                    return num
                if 1 <= num <= total_steps:
                    return num - 1
            except ValueError:
                logger.debug("Non-numeric depends_on reference: %r", lowered)
            # Fuzzy: check if any step name contains this reference
            for name, idx in name_to_idx.items():
                if lowered in name or name in lowered:
                    return idx
            logger.warning("Could not resolve depends_on reference: %r", dep_ref)
            return None

        logger.warning("Unexpected depends_on type: %r", type(dep_ref))
        return None

    def _parse_text_plan(
        self,
        text: str,
        objective: str,
    ) -> ExecutionPlan | None:
        """Parse a natural-text plan into an ExecutionPlan.

        Handles formats like:
        - "1. Setup project\\n2. Implement feature\\n3. Write tests"
        - "Step 1: Setup\\nStep 2: Implement"
        - "- Setup project\\n- Implement feature"
        """
        import re

        # Match numbered steps: "1.", "1)", "Step 1:", etc.
        numbered_pattern = r"(?:^|\n)\s*(?:step\s*)?(\d+)[.)]\s*(.+?)(?=(?:\n\s*(?:step\s*)?\d+[.)])|$)"
        matches = re.findall(numbered_pattern, text, re.IGNORECASE | re.DOTALL)

        # If no numbered steps, try bullet points
        if not matches:
            bullet_pattern = r"(?:^|\n)\s*[-*]\s*(.+?)(?=(?:\n\s*[-*])|$)"
            bullets = re.findall(bullet_pattern, text, re.DOTALL)
            if len(bullets) >= 2:
                matches = [(str(i + 1), b.strip()) for i, b in enumerate(bullets)]

        if len(matches) < 2:
            return None

        steps: list[TaskNode] = []
        for _, content in matches:
            content = content.strip()
            if not content:
                continue

            # Try to extract agent from content (e.g. "[CODER]", "(architect)")
            agent_match = re.search(r"[\[(](\w+)[\])]", content)
            agent = agent_match.group(1).upper() if agent_match else "CODER"
            if agent not in (
                "ARCHITECT", "CODER", "ANALYZER", "DEBUGGER",
                "RESEARCHER", "DOCUMENTER", "OPTIMIZER", "DASHBOARD",
            ):
                agent = "CODER"

            # Clean content of agent markers
            description = re.sub(r"\s*[\[(]\w+[\])]", "", content).strip()

            task = TaskNode(
                name=description[:100],
                description=description,
                agent=agent,
            )
            steps.append(task)

        if len(steps) < 2:
            return None

        # Sequential dependencies (each step depends on previous)
        for i in range(1, len(steps)):
            steps[i].depends_on.append(steps[i - 1].task_id)
            steps[i - 1].required_by.append(steps[i].task_id)

        return ExecutionPlan.from_steps(
            title=objective[:100],
            description=objective,
            steps=steps,
            session_id="",
        )
