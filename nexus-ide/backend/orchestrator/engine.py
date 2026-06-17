"""Multi-Agent Orchestration Engine.

The heart of Nexus IDE's autonomous execution system. Coordinates multiple
specialized agents to execute complex plans with parallel execution,
dependency resolution, retries, cancellation, and streaming events.

Architecture:
- ``OrchestrationEngine``: thin coordinator (this module)
- ``PlanCreator`` (:mod:`backend.orchestrator.plan_creator`): plan generation
- ``PlanExecutor`` (:mod:`backend.orchestrator.plan_executor`): per-layer execution
- ``RetryManager`` (:mod:`backend.orchestrator.retry_manager`): exponential backoff
- ``CancellationRegistry`` (:mod:`backend.orchestrator.cancellation_registry`):
  cancellation events and active task tracking
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
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from backend.agents.base import AgentBase
from backend.orchestrator.agent_pool import AgentPool, get_agent_pool
from backend.orchestrator.cancellation_registry import CancellationRegistry
from backend.orchestrator.dependency_graph import ExecutionPlan, TaskNode, TaskPriority
from backend.orchestrator.events import EventBus, EventType, OrchestratorEvent
from backend.orchestrator.plan_creator import PlanCreator
from backend.orchestrator.plan_executor import (
    PlanExecutor,
    _extract_tool_errors,
    _iterate_agent_output,
    extract_tool_errors,
    iterate_agent_output,
)
from backend.orchestrator.retry_manager import RetryManager
from backend.tools.ollama_client import ChatMessage

try:
    from cachetools import TTLCache
except ImportError:
    TTLCache = None

logger = logging.getLogger(__name__)


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
    _global_context_parts: list[str] = field(
        default_factory=list
    )  # accumulated context from completed tasks
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

    The engine itself is a thin coordinator: it owns long-lived state
    (session → state map, plan storage) and delegates the heavy lifting
    to :class:`PlanCreator`, :class:`PlanExecutor`, :class:`RetryManager`,
    and :class:`CancellationRegistry`.

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
        plan_creator: PlanCreator | None = None,
        plan_executor: PlanExecutor | None = None,
        retry_manager: RetryManager | None = None,
        cancellation_registry: CancellationRegistry | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._registry = registry
        self._events = event_bus
        self._max_parallel = max_parallel
        self._default_timeout = default_timeout
        self._max_retries = max_retries

        # Active runs
        self._state: dict[str, OrchestrationState] = {}

        # Plan storage with TTL eviction to prevent memory leaks
        if TTLCache is not None:
            self._plans: Any = TTLCache(maxsize=1000, ttl=3600)
            self._session_plans: Any = TTLCache(maxsize=1000, ttl=3600)
        else:
            self._plans: dict[str, ExecutionPlan] = {}
            self._session_plans: dict[str, str] = {}

        self._agent_pool: AgentPool = get_agent_pool()

        # Sub-components — fall back to defaults if not injected
        self._plan_creator = plan_creator or PlanCreator(llm_client, event_bus)
        self._plan_executor = plan_executor or PlanExecutor(
            llm_client,
            registry,
            event_bus,
            self._agent_pool,
            default_timeout=default_timeout,
        )
        self._retry_manager = retry_manager or RetryManager(
            base_delay=1.0, max_retries=max_retries
        )
        self._cancellation = cancellation_registry or CancellationRegistry()

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
        """Create a structured execution plan for ``objective``."""
        self._state[session_id] = OrchestrationState.PLANNING

        plan = await self._plan_creator.create(
            objective=objective,
            session_id=session_id,
            context=context,
            history=history,
        )

        # Store plan for later retrieval
        self._plans[plan.plan_id] = plan
        self._session_plans[session_id] = plan.plan_id

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

        # Register a fresh cancellation event for this run
        cancellation_event = self._cancellation.create(session_id)
        active_tasks: list[asyncio.Task[Any]] = []
        self._cancellation.register_tasks(session_id, active_tasks)

        try:
            result, _ctx = await self._plan_executor.execute(
                plan,
                session_id,
                run_id=run_id,
                project_path=project_path,
                cancellation_event=cancellation_event,
                active_tasks=active_tasks,
            )
        except asyncio.CancelledError:
            self._state[session_id] = OrchestrationState.CANCELLED
            raise
        else:
            self._state[session_id] = result.state
            return result
        finally:
            # Clean up active task references to avoid memory leaks
            self._cancellation.pop_tasks(session_id)

    async def cancel(self, session_id: str) -> None:
        """Cancel an active orchestration run."""
        cancelled = self._cancellation.cancel(session_id)
        self._state[session_id] = OrchestrationState.CANCELLED
        logger.info(
            "Cancelled orchestration for session %s (%d task(s))", session_id, cancelled
        )

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
            plan,
            session_id,
            auto_approve=True,
            project_path=project_path,
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
                verify_round + 1,
                max_verify_iterations,
                len(verification_needed),
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
                verify_plan,
                session_id,
                auto_approve=True,
                project_path=project_path,
            )

            # Check if verification found issues
            issues_found = self._extract_verification_issues(verify_result)
            if not issues_found:
                logger.info("Autonomous: verification passed (round %d)", verify_round + 1)
                break

            # Phase 4: ITERATE — create fix tasks for found issues
            logger.info(
                "Autonomous: %d issues found, creating fix tasks (round %d)",
                len(issues_found),
                verify_round + 1,
            )

            fix_tasks = self._create_fix_tasks(issues_found, verify_tasks, session_id)
            fix_plan = ExecutionPlan.from_steps(
                title=f"Fix Round {verify_round + 1}",
                description=f"Fix issues found in verification round {verify_round + 1}",
                steps=fix_tasks,
                session_id=session_id,
            )

            result = await self.execute_plan(
                fix_plan,
                session_id,
                auto_approve=True,
                project_path=project_path,
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
            review_plan,
            session_id,
            auto_approve=True,
            project_path=project_path,
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
                tasks_needing_verify.append(
                    {
                        "task_id": task_id,
                        "name": artifact.get("name", "Unknown"),
                        "output": artifact.get("output", ""),
                    }
                )
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
                "error",
                "bug",
                "issue",
                "problem",
                "fix",
                "failed",
                "incorrect",
                "missing",
                "broken",
                "erro",
                "problema",
                "falha",  # Portuguese
            ]
            output_lower = output.lower()
            if any(ind in output_lower for ind in error_indicators):
                issues.append(
                    {
                        "task_id": task_id,
                        "name": artifact.get("name", "Unknown verification"),
                        "output": output,
                        "agent": agent,
                    }
                )
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
    # Sub-component access (useful for tests and advanced wiring)
    # ------------------------------------------------------------------

    @property
    def plan_creator(self) -> PlanCreator:
        return self._plan_creator

    @property
    def plan_executor(self) -> PlanExecutor:
        return self._plan_executor

    @property
    def retry_manager(self) -> RetryManager:
        return self._retry_manager

    @property
    def cancellation_registry(self) -> CancellationRegistry:
        return self._cancellation


# Re-export the helper at module level for backward compatibility — the
# original ``engine.py`` exposed ``_extract_tool_errors`` and
# ``_iterate_agent_output`` as module-level helpers and the existing
# test suite still imports them.
__all__ = [
    "OrchestrationEngine",
    "OrchestrationState",
    "OrchestrationResult",
    "ExecutionContext",
    "PlanCreator",
    "PlanExecutor",
    "RetryManager",
    "CancellationRegistry",
    "extract_tool_errors",
    "iterate_agent_output",
]
