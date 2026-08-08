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
import os
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from backend.agents.base import AgentBase
from backend.core.disk_guard import require_disk_headroom
from backend.config.settings import get_settings
from backend.core.conversation_log import get_conversation_logger
from backend.orchestrator.agent_pool import AgentPool, get_agent_pool
from backend.orchestrator.cancellation_registry import CancellationRegistry
from backend.orchestrator.dependency_graph import ExecutionPlan, TaskNode, TaskPriority
from backend.orchestrator.events import EventBus, EventType, OrchestratorEvent
from backend.orchestrator.plan_creator import PlanCreator
from backend.orchestrator.plan_validation import PlanningResult
from backend.orchestrator.plan_executor import (
    PlanExecutor,
    extract_tool_errors,
    iterate_agent_output,
)
from backend.orchestrator.retry_manager import RetryManager
from backend.orchestrator.verification import (
    VerificationOutcome,
    _create_final_review_task,
    _create_fix_tasks,
    _create_verification_tasks,
    _extract_inconclusive_verifications,
    _extract_verification_issues,
    _find_tasks_needing_verification,
)
from backend.tools.ollama_client import ChatMessage

try:
    from cachetools import TTLCache
except ImportError:
    TTLCache = None

logger = logging.getLogger(__name__)

class OrchestrationState(StrEnum):
    IDLE = "idle"
    PLANNING = "planning"
    PLANNING_BLOCKED = "planning_blocked"
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
class PlanApprovalRequest:
    """A plan waiting for user approval, with metadata for the frontend."""

    plan_id: str
    session_id: str
    title: str = ""
    description: str = ""
    total_steps: int = 0
    risk_level: str = "low"
    estimated_duration_seconds: int = 0
    approval_timeout_s: int = 300
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "session_id": self.session_id,
            "title": self.title,
            "description": self.description,
            "total_steps": self.total_steps,
            "risk_level": self.risk_level,
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "approval_timeout_s": self.approval_timeout_s,
            "created_at": self.created_at,
        }


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

        # Approval tracking
        self._approval_requests: dict[str, PlanApprovalRequest] = {}
        self._approval_timeouts: dict[str, asyncio.Task[None]] = {}
        self._planning_results: dict[str, PlanningResult] = {}
        self._rejection_reasons: dict[str, str] = {}
        self._modifications: dict[str, dict[str, Any]] = {}

        # Sub-components — fall back to defaults if not injected
        self._plan_creator = plan_creator or PlanCreator(llm_client, event_bus)
        self._plan_executor = plan_executor or PlanExecutor(
            llm_client,
            registry,
            event_bus,
            self._agent_pool,
            default_timeout=default_timeout,
            max_parallel=max_parallel,
        )
        self._retry_manager = retry_manager or RetryManager(base_delay=1.0, max_retries=max_retries)
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
        auto_approve: bool = True,
        project_path: str = ".",
        snapshot: dict[str, Any] | None = None,
    ) -> PlanningResult:
        """Create a plan and stop explicitly when planning is blocked."""
        self._state[session_id] = OrchestrationState.PLANNING
        raw_result = await self._plan_creator.create(
            objective=objective,
            session_id=session_id,
            context=context,
            history=history,
            project_path=project_path,
            snapshot=snapshot,
        )
        result = (
            raw_result
            if isinstance(raw_result, PlanningResult)
            else PlanningResult(status="ready", plan=raw_result, source="legacy")
        )
        self._planning_results[session_id] = result
        if result.status == "blocked" or result.plan is None:
            self._state[session_id] = OrchestrationState.PLANNING_BLOCKED
            logger.warning("Planning blocked for session %s: %s", session_id, result.error)
            return result

        plan = result.plan
        self._plans[plan.plan_id] = plan
        self._session_plans[session_id] = plan.plan_id
        if auto_approve:
            plan.approved = True
            self._state[session_id] = OrchestrationState.IDLE
            return result

        self._state[session_id] = OrchestrationState.AWAITING_APPROVAL
        approval_request = PlanApprovalRequest(
            plan_id=plan.plan_id,
            session_id=session_id,
            title=plan.title,
            description=plan.description,
            total_steps=len(plan.steps),
            risk_level=plan.risk_level,
            estimated_duration_seconds=plan.estimated_duration_seconds,
            approval_timeout_s=get_settings().plan_approval_timeout,
            created_at=plan.created_at,
        )
        self._approval_requests[plan.plan_id] = approval_request
        asyncio.ensure_future(
            self._events.publish(
                OrchestratorEvent(
                    event_type=EventType.PLAN_AWAITING_APPROVAL,
                    source="ORCHESTRATOR",
                    session_id=session_id,
                    task_id=plan.plan_id,
                    data=approval_request.to_dict(),
                )
            )
        )
        timeout = get_settings().plan_approval_timeout
        if timeout > 0:
            self._approval_timeouts[plan.plan_id] = asyncio.create_task(
                self._approval_timeout_worker(plan.plan_id, session_id, timeout)
            )
        return result

    async def continue_planning(self, session_id: str) -> PlanningResult | None:
        """Expose the deterministic proposal only after explicit continuation."""
        result = self._planning_results.get(session_id)
        if result is None or result.status != "blocked" or result.deterministic_proposal is None:
            return None
        proposal = result.deterministic_proposal
        proposal.approved = False
        continued = PlanningResult(
            status="ready",
            plan=proposal,
            source="deterministic_continue",
            deterministic_proposal=proposal,
        )
        self._planning_results[session_id] = continued
        self._plans[proposal.plan_id] = proposal
        self._session_plans[session_id] = proposal.plan_id
        self._state[session_id] = OrchestrationState.AWAITING_APPROVAL
        return continued

    async def continue_plan(self, session_id: str) -> PlanningResult | None:
        return await self.continue_planning(session_id)

    # ------------------------------------------------------------------
    # Plan Approval Workflow
    # ------------------------------------------------------------------

    def request_approval(self, plan_id: str) -> PlanApprovalRequest | None:
        """Return the serialized approval request for a plan, or None if not found."""
        return self._approval_requests.get(plan_id)

    async def approve_plan(self, plan_id: str, user_id: str) -> OrchestrationResult | None:
        """Approve a plan and immediately execute it.

        Returns the :class:`OrchestrationResult` on success, or ``None`` if
        the plan was not found or was already approved/rejected.
        """
        plan = self._plans.get(plan_id)
        if plan is None:
            logger.warning("approve_plan: plan %s not found", plan_id)
            return None

        session_id = plan.session_id
        current_state = self._state.get(session_id)
        if current_state != OrchestrationState.AWAITING_APPROVAL:
            logger.warning(
                "approve_plan: plan %s is in state %s (expected AWAITING_APPROVAL)",
                plan_id,
                current_state,
            )
            return None

        # Cancel the timeout task if still running
        self._cancel_approval_timeout(plan_id)

        plan.approved = True
        plan.approved_by = user_id  # type: ignore[attr-defined]
        self._state[session_id] = OrchestrationState.EXECUTING

        # Clean up approval metadata
        self._approval_requests.pop(plan_id, None)

        logger.info(
            "Plan %s approved by user %s — executing now",
            plan_id,
            user_id,
        )

        # Publish approval event
        asyncio.ensure_future(
            self._events.publish(
                OrchestratorEvent(
                    event_type=EventType.PLAN_APPROVED,
                    source="ORCHESTRATOR",
                    session_id=session_id,
                    task_id=plan_id,
                    data={"user_id": user_id, "plan_id": plan_id},
                )
            )
        )

        # Execute the approved plan
        result = await self.execute_plan(
            plan=plan,
            session_id=session_id,
            auto_approve=True,
        )
        return result

    async def reject_plan(self, plan_id: str, reason: str = "") -> bool:
        """Reject a plan, cancelling it permanently.

        Returns ``True`` if the plan was successfully rejected.
        """
        plan = self._plans.get(plan_id)
        if plan is None:
            logger.warning("reject_plan: plan %s not found", plan_id)
            return False

        session_id = plan.session_id
        current_state = self._state.get(session_id)
        if current_state != OrchestrationState.AWAITING_APPROVAL:
            logger.warning(
                "reject_plan: plan %s is in state %s (expected AWAITING_APPROVAL)",
                plan_id,
                current_state,
            )
            return False

        # Cancel the timeout task if still running
        self._cancel_approval_timeout(plan_id)

        self._state[session_id] = OrchestrationState.CANCELLED
        self._rejection_reasons[plan_id] = reason
        self._approval_requests.pop(plan_id, None)

        logger.info(
            "Plan %s rejected (reason: %s)",
            plan_id,
            reason or "no reason given",
        )

        # Publish rejection event
        asyncio.ensure_future(
            self._events.publish(
                OrchestratorEvent(
                    event_type=EventType.PLAN_REJECTED,
                    source="ORCHESTRATOR",
                    session_id=session_id,
                    task_id=plan_id,
                    data={"reason": reason, "plan_id": plan_id},
                )
            )
        )

        return True

    async def modify_plan(
        self,
        plan_id: str,
        modifications: dict[str, Any],
    ) -> ExecutionPlan | None:
        """Apply modifications to a plan while it is awaiting approval.

        ``modifications`` supports:

        - ``steps_to_remove``: list of step indices (0-based) to remove
        - ``steps_to_add``: list of ``{name, description, agent, depends_on}``
          dicts to append
        - ``steps_to_reorder``: list of step indices specifying a new order
        - ``title``: override plan title
        - ``risk_level``: override risk level

        Returns the updated :class:`ExecutionPlan` or ``None`` if not found.
        """
        plan = self._plans.get(plan_id)
        if plan is None:
            logger.warning("modify_plan: plan %s not found", plan_id)
            return None

        self._modifications[plan_id] = modifications

        # Apply title override
        if "title" in modifications and modifications["title"]:
            plan.title = str(modifications["title"])

        # Apply risk level override
        if "risk_level" in modifications:
            allowed_risk = {"low", "medium", "high"}
            rl = str(modifications["risk_level"]).lower()
            if rl in allowed_risk:
                plan.risk_level = rl

        # Remove steps by index (high-to-low to preserve indices)
        steps_to_remove: set[int] = set(modifications.get("steps_to_remove", []))
        if steps_to_remove:
            valid = {i for i in steps_to_remove if 0 <= i < len(plan.steps)}
            plan.steps = [s for i, s in enumerate(plan.steps) if i not in valid]
            plan.total_steps = len(plan.steps)
            # Rebuild dependency graph
            from backend.orchestrator.dependency_graph import DependencyGraph

            new_graph = DependencyGraph()
            for step in plan.steps:
                new_graph.add_task(step)
            plan.dependency_graph = new_graph
            plan.parallel_layers = len(new_graph.topological_layers())

        # Add new steps
        steps_to_add: list[dict[str, Any]] = modifications.get("steps_to_add", [])
        if steps_to_add:
            for raw in steps_to_add:
                priority_val = raw.get("priority", "medium").upper()
                resolved_priority = (
                    TaskPriority[priority_val]
                    if priority_val in TaskPriority.__members__
                    else TaskPriority.MEDIUM
                )
                new_step = TaskNode(
                    name=raw.get("name", f"Step {len(plan.steps) + 1}"),
                    description=raw.get("description", ""),
                    agent=raw.get("agent", "CODER").upper(),
                    priority=resolved_priority,
                    sandboxed=raw.get("sandboxed", False),
                )
                plan.steps.append(new_step)
                plan.dependency_graph.add_task(new_step)
            plan.total_steps = len(plan.steps)
            plan.parallel_layers = len(plan.dependency_graph.topological_layers())

        # Reorder steps (requires all indices to be present)
        steps_to_reorder: list[int] = modifications.get("steps_to_reorder", [])
        if len(steps_to_reorder) == len(plan.steps) and len(set(steps_to_reorder)) == len(
            plan.steps
        ):
            ordered = []
            try:
                ordered = [plan.steps[i] for i in steps_to_reorder]
            except IndexError:
                logger.warning("modify_plan: invalid step indices in reorder")
            if ordered:
                plan.steps = ordered

        # Recalculate estimated duration
        plan.estimated_duration_seconds = sum(
            s.timeout_seconds for s in plan.steps
        )

        # Update approval request metadata
        req = self._approval_requests.get(plan_id)
        if req:
            req.total_steps = len(plan.steps)
            req.risk_level = plan.risk_level
            req.estimated_duration_seconds = plan.estimated_duration_seconds

        logger.info(
            "Plan %s modified — steps: %d, risk: %s",
            plan_id,
            len(plan.steps),
            plan.risk_level,
        )

        # Publish modification event
        asyncio.ensure_future(
            self._events.publish(
                OrchestratorEvent(
                    event_type=EventType.PLAN_MODIFIED,
                    source="ORCHESTRATOR",
                    session_id=plan.session_id,
                    task_id=plan_id,
                    data={"plan_id": plan_id, "total_steps": len(plan.steps)},
                )
            )
        )

        return plan

    def _cancel_approval_timeout(self, plan_id: str) -> None:
        """Cancel the approval timeout task for a plan if it exists."""
        task = self._approval_timeouts.pop(plan_id, None)
        if task is not None and not task.done():
            task.cancel()

    async def _approval_timeout_worker(
        self,
        plan_id: str,
        session_id: str,
        timeout: int,
    ) -> None:
        """Background task: auto-reject plan if not approved within timeout."""
        try:
            await asyncio.sleep(timeout)
            if self._state.get(session_id) == OrchestrationState.AWAITING_APPROVAL:
                await self.reject_plan(plan_id, reason="Approval timeout")
        except asyncio.CancelledError:
            pass

    async def execute_plan(
        self,
        plan: ExecutionPlan | PlanningResult,
        session_id: str,
        *,
        auto_approve: bool = False,
        project_path: str = ".",
    ) -> OrchestrationResult:
        """Execute a ready plan; blocked planning never reaches the executor."""
        if isinstance(plan, PlanningResult):
            if plan.status == "blocked" or plan.plan is None:
                return OrchestrationResult(
                    run_id=uuid.uuid4().hex[:12],
                    state=OrchestrationState.PLANNING_BLOCKED,
                    plan=plan.deterministic_proposal,
                    errors=[plan.error] if plan.error else ["planning blocked"],
                )
            plan = plan.plan
        if not auto_approve and plan.requires_approval and not plan.approved:
            raise ValueError("Plan requires approval before execution")

        run_id = uuid.uuid4().hex[:12]
        self._state[session_id] = OrchestrationState.EXECUTING
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
            if (
                cancellation_event.is_set()
                or self._state.get(session_id) == OrchestrationState.CANCELLED
            ):
                result.state = OrchestrationState.CANCELLED
            self._state[session_id] = result.state
            return result
        finally:
            self._cancellation.pop_tasks(session_id)


    async def cancel(self, session_id: str) -> None:
        """Cancel an active orchestration run."""
        cancelled = self._cancellation.cancel(session_id)
        self._state[session_id] = OrchestrationState.CANCELLED
        logger.info("Cancelled orchestration for session %s (%d task(s))", session_id, cancelled)

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
        require_disk_headroom(project_path)

        # Phase 1: PLAN (auto-approve — autonomous mode skips user approval)
        plan = await self.create_plan(
            objective=objective,
            session_id=session_id,
            context=context,
            history=history,
            auto_approve=True,
            project_path=project_path,
        )
        if isinstance(plan, PlanningResult) and plan.status == "blocked":
            return OrchestrationResult(
                run_id=uuid.uuid4().hex[:12],
                state=OrchestrationState.PLANNING_BLOCKED,
                plan=plan.deterministic_proposal,
                errors=[plan.error] if plan.error else ["planning blocked"],
            )

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
        # A failed, cancelled, or blocked primary plan is terminal.
        if result.state in (
            OrchestrationState.CANCELLED,
            OrchestrationState.FAILED,
            OrchestrationState.PLANNING_BLOCKED,
        ):
            self._state[session_id] = result.state
            return result

        # Phase 3: VERIFY & ITERATE
        #
        # ``result`` is the aggregate returned to the caller and must keep the
        # primary run's task_results.  ``latest_result`` is what the *next*
        # verification round inspects.  Conflating the two (the original bug)
        # made round N verify round N-1's fix tasks, which nested task names
        # into "Fix: Verify: Fix: Verify: ..." and discarded the primary run.
        latest_result = result
        outcome = VerificationOutcome(max_rounds=max_verify_iterations)

        # Budget guard: reduce verification intensity when provider quota is tight.
        llm_call_budget = int(os.environ.get("NEXUS_AUTONOMOUS_LLM_BUDGET", "0")) or (
            len(plan.steps) + max_verify_iterations * 2 + 2
        ) * 3
        llm_calls_used = 0

        def _remaining_llm_budget() -> int:
            return max(0, llm_call_budget - llm_calls_used)

        def _adaptive_max_rounds() -> int:
            remaining = _remaining_llm_budget()
            if remaining <= 0:
                return 0
            return min(max_verify_iterations, max(0, remaining // 2))

        effective_max_rounds = _adaptive_max_rounds()
        if effective_max_rounds < max_verify_iterations:
            logger.warning(
                "Autonomous: LLM budget reduced verification rounds from %d to %d",
                max_verify_iterations,
                effective_max_rounds,
            )

        for verify_round in range(effective_max_rounds):
            if (
                latest_result.state == OrchestrationState.CANCELLED
                or self._state.get(session_id) == OrchestrationState.CANCELLED
            ):
                result.state = OrchestrationState.CANCELLED
                self._state[session_id] = OrchestrationState.CANCELLED
                return result

            outcome.rounds_run = verify_round + 1

            # Find tasks that produced code (CODER steps) and verify them
            verification_needed = _find_tasks_needing_verification(latest_result)
            if not verification_needed:
                logger.info("Autonomous: no verification needed (round %d)", verify_round + 1)
                outcome.resolved = True
                outcome.rounds_run = verify_round
                break

            logger.info(
                "Autonomous: verification round %d/%d — %d tasks to verify",
                verify_round + 1,
                max_verify_iterations,
                len(verification_needed),
            )

            # Create verification tasks
            verify_tasks = _create_verification_tasks(
                verification_needed, latest_result, session_id
            )

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
            if verify_result.state in (OrchestrationState.CANCELLED, OrchestrationState.FAILED):
                self._state[session_id] = verify_result.state
                return verify_result

            self._merge_task_results(result, verify_result)

            # Check if verification found issues.
            #
            # "Could not verify" is tracked separately from "verified, found
            # nothing". A blocked tool or a 429 means the verifier learned
            # nothing about the code; reporting that as a pass is exactly the
            # false green this loop exists to prevent.
            issues_found = _extract_verification_issues(verify_result)
            inconclusive = _extract_inconclusive_verifications(verify_result)
            get_conversation_logger(session_id).log_verification_round(
                verify_round + 1,
                issues_found=len(issues_found),
                inconclusive=len(inconclusive),
            )
            if inconclusive:
                logger.warning(
                    "Autonomous: %d verification(s) could not run in round %d "
                    "(blocked tool / provider failure); not treating as passed: %s",
                    len(inconclusive),
                    verify_round + 1,
                    ", ".join(str(item["origin"]) for item in inconclusive[:5]),
                )
                outcome.inconclusive_verifications = inconclusive
            if not issues_found:
                if inconclusive:
                    # Do not mark fully resolved and do not keep re-running a
                    # blocked verifier: repeated provider/tool failures only
                    # consume the autonomous budget and make the run appear
                    # stalled. The final review still runs and the outcome
                    # remains explicitly inconclusive.
                    logger.info(
                        "Autonomous: round %d produced no findings, but %d verification(s) were inconclusive; "
                        "stopping verification rounds without claiming a pass",
                        verify_round + 1,
                        len(inconclusive),
                    )
                    break
                logger.info("Autonomous: verification passed (round %d)", verify_round + 1)
                outcome.resolved = True
                outcome.outstanding_issues = []
                break

            outcome.outstanding_issues = issues_found

            # Phase 4: ITERATE — create fix tasks for found issues
            logger.info(
                "Autonomous: %d issues found, creating fix tasks (round %d)",
                len(issues_found),
                verify_round + 1,
            )

            fix_tasks = _create_fix_tasks(issues_found, verify_tasks, session_id)
            fix_plan = ExecutionPlan.from_steps(
                title=f"Fix Round {verify_round + 1}",
                description=f"Fix issues found in verification round {verify_round + 1}",
                steps=fix_tasks,
                session_id=session_id,
            )

            fix_result = await self.execute_plan(
                fix_plan,
                session_id,
                auto_approve=True,
                project_path=project_path,
            )
            if fix_result.state in (OrchestrationState.CANCELLED, OrchestrationState.FAILED):
                self._state[session_id] = fix_result.state
                return fix_result

            self._merge_task_results(result, fix_result)
            latest_result = fix_result

        if self._state.get(session_id) == OrchestrationState.CANCELLED:
            result.state = OrchestrationState.CANCELLED
            return result

        # Phase 5: FINAL REVIEW with ANALYZER
        final_review = _create_final_review_task(objective, result, session_id)
        review_plan = ExecutionPlan.from_steps(
            title="Final Quality Review",
            description="Comprehensive quality review of all changes",
            steps=[final_review],
            session_id=session_id,
        )
        review_result = await self.execute_plan(
            review_plan,
            session_id,
            auto_approve=True,
            project_path=project_path,
        )
        if review_result.state in (OrchestrationState.CANCELLED, OrchestrationState.FAILED):
            self._state[session_id] = review_result.state
            return review_result

        # The review actually ran, so its findings belong in the result the
        # caller sees.  Previously it was executed and then thrown away.
        self._merge_task_results(result, review_result)

        # Running out of fix rounds is NOT success.  Surface it explicitly so
        # the caller (and the user) can tell "verified clean" from "gave up" —
        # and mark the run FAILED, otherwise the dashboard prints
        # "Execução Autónoma Concluída" over an unresolved verification issue.
        result.verification = outcome
        if outcome.exhausted:
            logger.warning("Autonomous: %s", outcome.summary())
            result.errors.append(outcome.summary())
            result.state = OrchestrationState.FAILED

        # Preserve the result of the actual execution instead of blindly
        # reporting success after the review phase.
        self._state[session_id] = result.state
        return result

    @staticmethod
    def _merge_task_results(
        target: OrchestrationResult,
        source: OrchestrationResult,
    ) -> None:
        """Fold ``source`` task results and counters into ``target``.

        Keeps the aggregate returned by :meth:`execute_autonomous` complete
        instead of letting each phase overwrite the previous one.
        """
        for task_id, artifact in source.task_results.items():
            if task_id in target.task_results:
                continue
            target.task_results[task_id] = artifact
        target.completed_tasks += source.completed_tasks
        target.failed_tasks += source.failed_tasks
        target.total_duration_ms += source.total_duration_ms
        target.tokens_used += source.tokens_used
        for err in source.errors:
            if err not in target.errors:
                target.errors.append(err)

    # ------------------------------------------------------------------
    # Verification helpers
    #
    # The implementations live in :mod:`backend.orchestrator.verification`.
    # These methods are thin delegations kept for backwards compatibility —
    # the logic was previously duplicated here *and* in verification.py,
    # and the two copies had already drifted apart.
    # ------------------------------------------------------------------

    def _find_tasks_needing_verification(self, result: OrchestrationResult) -> list[dict]:
        """Find completed CODER tasks that should be verified by DEBUGGER."""
        return _find_tasks_needing_verification(result)

    def _create_verification_tasks(
        self,
        tasks_to_verify: list[dict],
        result: OrchestrationResult,
        session_id: str,
    ) -> list[TaskNode]:
        """Create DEBUGGER verification tasks for completed CODER work."""
        return _create_verification_tasks(tasks_to_verify, result, session_id)

    def _extract_verification_issues(self, verify_result: OrchestrationResult) -> list[dict]:
        """Extract issues genuinely reported by DEBUGGER verification tasks."""
        return _extract_verification_issues(verify_result)

    def _create_fix_tasks(
        self,
        issues: list[dict],
        verify_tasks: list[TaskNode],
        session_id: str,
    ) -> list[TaskNode]:
        """Create CODER fix tasks based on DEBUGGER findings."""
        return _create_fix_tasks(issues, verify_tasks, session_id)

    def _create_final_review_task(
        self,
        objective: str,
        result: OrchestrationResult,
        session_id: str,
    ) -> TaskNode:
        """Create a final ANALYZER review task."""
        return _create_final_review_task(objective, result, session_id)

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
