"""MetaOrchestrator — dynamic, autonomous multi-phase mission orchestration.

Sits above :class:`OrchestrationEngine` and manages the full lifecycle of a
mission: Discovery → Design → Implementation → Verification → Polish → Deploy.

Key differences from the static DAG engine:
- The mission plan is a **living tree** that grows and adapts.
- Phases are executed sequentially, but each phase spawns its own DAG via
  the existing :class:`OrchestrationEngine`.
- Replanning is triggered by agent blockers, discoveries, or conditional
  evaluation (e.g. "if tests fail → debug").
- Auto-correction loops back from Verification → Implementation up to 5
  iterations.
- Resource budgets (tokens + time) are enforced per mission.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.agents.base import AgentBase, AgentRequest
from backend.config.settings import get_model_config, load_prompt
from backend.core.agent_bus import AgentBus, BusMessage, get_agent_bus
from backend.core.agent_state import AgentStateStore
from backend.orchestrator.dependency_graph import (
    DependencyGraph,
    ExecutionPlan,
    TaskNode,
    TaskPriority,
    TaskStatus,
)
from backend.orchestrator.engine import OrchestrationEngine, OrchestrationState
from backend.orchestrator.events import EventBus, EventEmitter, EventType, OrchestratorEvent
from backend.tools.ollama_client import ChatMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class MissionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class AgentTask(BaseModel):
    """A single spawned agent task tracked by the MetaOrchestrator."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    type: str
    status: MissionStatus = MissionStatus.PENDING
    objective: str
    start_time: float = Field(default_factory=time.time)
    deadline: float = 0.0
    tokens_used: int = 0
    parent_id: str = ""
    phase: str = ""
    output: str = ""
    error: str = ""


class MissionPhase(BaseModel):
    """One phase of a mission (Discovery, Design, …)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: MissionStatus = MissionStatus.PENDING
    tasks: list[str] = Field(default_factory=list)  # agent_task ids
    result_summary: str = ""
    tokens_used: int = 0
    started_at: float = 0.0
    completed_at: float = 0.0
    auto_correction_count: int = 0


class Mission(BaseModel):
    """Top-level mission object."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    objective: str
    status: MissionStatus = MissionStatus.PENDING
    phases: list[MissionPhase] = Field(default_factory=list)
    active_agents: dict[str, AgentTask] = Field(default_factory=dict)
    token_budget: int = 50_000
    time_budget_seconds: int = 3_600
    tokens_used: int = 0
    started_at: float = Field(default_factory=time.time)
    completed_at: float = 0.0
    current_phase_index: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@dataclass
class _PhaseSpec:
    name: str
    default_agents: list[str]
    requires_verification: bool = False
    verification_agent: str = "DEBUGGER"


_PHASE_ORDER: list[_PhaseSpec] = [
    _PhaseSpec("Discovery", ["RESEARCHER", "ANALYZER"]),
    _PhaseSpec("Design", ["ARCHITECT", "ANALYZER"]),
    _PhaseSpec("Implementation", ["CODER", "DEBUGGER"]),
    _PhaseSpec("Verification", ["DEBUGGER", "ANALYZER"], requires_verification=True),
    _PhaseSpec("Polish", ["OPTIMIZER", "DOCUMENTER"]),
    _PhaseSpec("Deploy", ["CODER", "DOCUMENTER"]),
]

_MAX_AUTO_CORRECTION = 5


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# MetaOrchestrator
# ---------------------------------------------------------------------------


class MetaOrchestrator:
    """Dynamic, autonomous mission orchestrator.

    Usage::

        meta = MetaOrchestrator(engine, event_bus, llm_client, registry)
        mission = await meta.create_mission("Add OAuth2 to the API")
        await meta.run_mission(mission.id)
    """

    def __init__(
        self,
        engine: OrchestrationEngine,
        event_bus: EventBus,
        llm_client: Any,
        registry: dict[str, AgentBase],
        *,
        max_parallel_agents: int = 5,
        default_token_budget: int = 50_000,
        default_time_budget: int = 3_600,
    ) -> None:
        self._engine = engine
        self._events = event_bus
        self._llm_client = llm_client
        self._registry = registry
        self._max_parallel = max_parallel_agents
        self._default_token_budget = default_token_budget
        self._default_time_budget = default_time_budget

        # In-memory mission store (mirrored to AgentState for persistence)
        self._missions: dict[str, Mission] = {}
        self._mission_tasks: dict[str, asyncio.Task[Any]] = {}
        self._pause_events: dict[str, asyncio.Event] = {}
        self._abort_events: dict[str, asyncio.Event] = {}
        self._state_store = AgentStateStore()

    # ------------------------------------------------------------------
    # Public API — mission lifecycle
    # ------------------------------------------------------------------

    async def create_mission(
        self,
        objective: str,
        *,
        token_budget: int | None = None,
        time_budget_seconds: int | None = None,
        project_path: str = ".",
    ) -> Mission:
        """Decompose a high-level objective into a living mission tree."""
        mission = Mission(
            objective=objective,
            token_budget=token_budget or self._default_token_budget,
            time_budget_seconds=time_budget_seconds or self._default_time_budget,
            metadata={"project_path": project_path},
        )

        # Build initial phase skeleton
        for spec in _PHASE_ORDER:
            mission.phases.append(
                MissionPhase(
                    name=spec.name,
                    status=MissionStatus.PENDING,
                )
            )

        self._missions[mission.id] = mission
        self._pause_events[mission.id] = asyncio.Event()
        self._abort_events[mission.id] = asyncio.Event()

        await self._persist_mission(mission)
        await self._emit(
            EventType.PLAN_CREATED,
            mission_id=mission.id,
            data={"objective": objective, "phases": [p.name for p in mission.phases]},
        )
        return mission

    async def run_mission(self, mission_id: str) -> Mission:
        """Execute the mission through all phases."""
        mission = self._get_mission(mission_id)
        if mission is None:
            raise ValueError(f"Mission {mission_id} not found")

        mission.status = MissionStatus.RUNNING
        await self._persist_mission(mission)
        await self._emit(
            EventType.ORCHESTRATOR_STARTED,
            mission_id=mission_id,
            data={"objective": mission.objective},
        )

        try:
            for idx, phase in enumerate(mission.phases):
                if self._abort_events[mission_id].is_set():
                    mission.status = MissionStatus.ABORTED
                    break

                mission.current_phase_index = idx
                await self._run_phase(mission, phase)

                if mission.status == MissionStatus.ABORTED:
                    break

                # Conditional branching after Verification
                if phase.name == "Verification" and phase.status == MissionStatus.FAILED:
                    await self._handle_verification_failure(mission, phase)
                    if mission.status in (MissionStatus.ABORTED, MissionStatus.FAILED):
                        break

                # Conditional: if complexity > threshold → spawn REFACTOR_PERFORMANCE
                if phase.name == "Implementation":
                    await self._evaluate_complexity_condition(mission, phase)

            if mission.status == MissionStatus.RUNNING:
                mission.status = MissionStatus.COMPLETED

        except Exception as exc:
            logger.exception("Mission %s failed: %s", mission_id, exc)
            mission.status = MissionStatus.FAILED
            mission.metadata["error"] = str(exc)

        mission.completed_at = _now()
        await self._persist_mission(mission)
        await self._emit(
            EventType.ORCHESTRATOR_FINISHED,
            mission_id=mission_id,
            data={
                "status": mission.status.value,
                "tokens_used": mission.tokens_used,
                "duration_seconds": int(mission.completed_at - mission.started_at),
            },
        )
        return mission

    async def pause(self, mission_id: str) -> Mission:
        """Pause all active work in a mission."""
        mission = self._get_mission(mission_id)
        if mission and mission.status == MissionStatus.RUNNING:
            mission.status = MissionStatus.PAUSED
            self._pause_events[mission_id].set()
            await self._persist_mission(mission)
            await self._emit(
                EventType.PLAN_UPDATED,
                mission_id=mission_id,
                data={"status": MissionStatus.PAUSED.value},
            )
        return mission

    async def resume(self, mission_id: str) -> Mission:
        """Resume a paused mission."""
        mission = self._get_mission(mission_id)
        if mission and mission.status == MissionStatus.PAUSED:
            mission.status = MissionStatus.RUNNING
            self._pause_events[mission_id].clear()
            await self._persist_mission(mission)
            # Re-launch the mission run if it was cancelled
            if mission_id not in self._mission_tasks or self._mission_tasks[mission_id].done():
                self._mission_tasks[mission_id] = asyncio.create_task(self.run_mission(mission_id))
            await self._emit(
                EventType.PLAN_UPDATED,
                mission_id=mission_id,
                data={"status": MissionStatus.RUNNING.value},
            )
        return mission

    async def abort(self, mission_id: str) -> Mission:
        """Abort a mission and cancel all its agents."""
        mission = self._get_mission(mission_id)
        if mission:
            mission.status = MissionStatus.ABORTED
            self._abort_events[mission_id].set()
            # Cancel underlying engine runs tied to this mission session
            await self._engine.cancel(mission_id)
            for task in mission.active_agents.values():
                task.status = MissionStatus.ABORTED
            await self._persist_mission(mission)
            await self._emit(
                EventType.PLAN_UPDATED,
                mission_id=mission_id,
                data={"status": MissionStatus.ABORTED.value},
            )
        return mission

    async def replan(
        self,
        mission_id: str,
        trigger_reason: str,
        *,
        new_tasks: list[dict[str, Any]] | None = None,
        remove_task_ids: list[str] | None = None,
    ) -> Mission:
        """Adapt the mission plan when blockers or discoveries occur.

        *new_tasks* should be dicts with keys: ``agent_type``, ``objective``,
        ``context`` (optional), ``parent_id`` (optional).
        """
        mission = self._get_mission(mission_id)
        if mission is None:
            raise ValueError(f"Mission {mission_id} not found")

        await self._emit(
            EventType.PLAN_UPDATED,
            mission_id=mission_id,
            data={"reason": trigger_reason, "action": "replan"},
        )

        # Remove obsolete tasks
        for tid in remove_task_ids or []:
            if tid in mission.active_agents:
                del mission.active_agents[tid]

        # Add new tasks into the current phase
        current_phase = mission.phases[mission.current_phase_index]
        for task_info in new_tasks or []:
            agent_task = await self.spawn_agent(
                agent_type=task_info["agent_type"],
                objective=task_info["objective"],
                context=task_info.get("context", ""),
                parent_task_id=task_info.get("parent_id", ""),
                phase_name=current_phase.name,
                mission_id=mission_id,
            )
            current_phase.tasks.append(agent_task.id)

        mission.metadata["last_replan_reason"] = trigger_reason
        mission.metadata["replan_count"] = mission.metadata.get("replan_count", 0) + 1
        await self._persist_mission(mission)
        return mission

    async def spawn_agent(
        self,
        agent_type: str,
        objective: str,
        context: str = "",
        parent_task_id: str = "",
        phase_name: str = "",
        mission_id: str = "",
        deadline: float = 0.0,
    ) -> AgentTask:
        """Dynamically spawn a new agent task."""
        agent_task = AgentTask(
            type=agent_type,
            objective=objective,
            parent_id=parent_task_id,
            phase=phase_name,
            deadline=deadline or (_now() + 600),
        )

        if mission_id:
            mission = self._missions.get(mission_id)
            if mission:
                mission.active_agents[agent_task.id] = agent_task
                await self._persist_mission(mission)

        await self._emit(
            EventType.TASK_SCHEDULED,
            mission_id=mission_id,
            task_id=agent_task.id,
            data={"agent_type": agent_type, "objective": objective, "phase": phase_name},
        )
        return agent_task

    def get_mission(self, mission_id: str) -> Mission | None:
        """Retrieve mission by id (reads from memory, falls back to store)."""
        return self._get_mission(mission_id)

    def list_active_agents(self, mission_id: str) -> list[AgentTask]:
        """Return all active (non-terminal) agents for a mission."""
        mission = self._get_mission(mission_id)
        if mission is None:
            return []
        terminal = {
            MissionStatus.COMPLETED.value,
            MissionStatus.FAILED.value,
            MissionStatus.ABORTED.value,
        }
        return [a for a in mission.active_agents.values() if a.status.value not in terminal]

    async def stream_events(
        self,
        mission_id: str,
    ) -> AsyncIterator[OrchestratorEvent]:
        """Yield real-time events scoped to a mission."""
        async for event in self._events.stream_events(
            event_types=["*"],
            session_id=mission_id,
        ):
            yield event

    # ------------------------------------------------------------------
    # Internal — phase execution
    # ------------------------------------------------------------------

    async def _run_phase(self, mission: Mission, phase: MissionPhase) -> None:
        """Run a single phase using the low-level OrchestrationEngine."""
        phase.status = MissionStatus.RUNNING
        phase.started_at = _now()
        await self._emit(
            EventType.ORCHESTRATOR_STARTED,
            mission_id=mission.id,
            data={"phase": phase.name, "action": "phase_start"},
        )

        # Wait out any pause
        while self._pause_events[mission.id].is_set():
            if self._abort_events[mission.id].is_set():
                phase.status = MissionStatus.ABORTED
                return
            await asyncio.sleep(0.5)

        # Build a DAG plan for this phase via the engine
        plan = await self._engine.create_plan(
            objective=f"[{phase.name}] {mission.objective}",
            session_id=mission.id,
            context=self._build_phase_context(mission, phase),
        )
        plan.approved = True  # Auto-approve under MetaOrchestrator

        # Spawn tracker agents for every step in the plan
        for step in plan.steps:
            agent_task = await self.spawn_agent(
                agent_type=step.agent,
                objective=step.name,
                context=step.description,
                parent_task_id="",
                phase_name=phase.name,
                mission_id=mission.id,
            )
            phase.tasks.append(agent_task.id)

        # Execute via the low-level engine
        result = await self._engine.execute_plan(
            plan,
            mission.id,
            auto_approve=True,
            project_path=mission.metadata.get("project_path", "."),
        )

        # Update trackers with results
        for step in plan.steps:
            artifact = result.task_results.get(step.task_id, {})
            for at in mission.active_agents.values():
                if at.objective == step.name and at.phase == phase.name:
                    at.status = (
                        MissionStatus.COMPLETED
                        if step.status == TaskStatus.COMPLETED
                        else MissionStatus.FAILED
                        if step.status == TaskStatus.FAILED
                        else MissionStatus.ABORTED
                    )
                    at.output = str(artifact.get("output", ""))[:2000]
                    at.error = step.error_message
                    at.tokens_used = len(at.output)

        phase.tokens_used = result.tokens_used
        mission.tokens_used += result.tokens_used

        # Check budgets
        if mission.tokens_used > mission.token_budget:
            await self._abort_for_budget(mission, "token")
            return
        if (_now() - mission.started_at) > mission.time_budget_seconds:
            await self._abort_for_budget(mission, "time")
            return

        # Determine phase status
        if result.state == OrchestrationState.COMPLETED:
            phase.status = MissionStatus.COMPLETED
        elif result.state == OrchestrationState.CANCELLED:
            phase.status = MissionStatus.ABORTED
        else:
            phase.status = MissionStatus.FAILED

        phase.result_summary = (
            f"Completed {result.completed_tasks}/{result.completed_tasks + result.failed_tasks} tasks. "
            f"Tokens: {result.tokens_used}. Errors: {len(result.errors)}"
        )
        phase.completed_at = _now()

        # Peer review integration for Implementation and Design phases
        if phase.name in ("Implementation", "Design"):
            await self._trigger_peer_review(mission, phase)

        await self._persist_mission(mission)
        await self._emit(
            EventType.ORCHESTRATOR_FINISHED,
            mission_id=mission.id,
            data={
                "phase": phase.name,
                "status": phase.status.value,
                "tokens_used": phase.tokens_used,
            },
        )

    async def _handle_verification_failure(self, mission: Mission, phase: MissionPhase) -> None:
        """Auto-correction loop: spawn DEBUGGER + CODER and loop back."""
        if phase.auto_correction_count >= _MAX_AUTO_CORRECTION:
            mission.status = MissionStatus.FAILED
            mission.metadata["failure_reason"] = (
                f"Verification failed after {_MAX_AUTO_CORRECTION} auto-correction iterations"
            )
            await self._persist_mission(mission)
            return

        phase.auto_correction_count += 1
        await self._emit(
            EventType.PLAN_UPDATED,
            mission_id=mission.id,
            data={
                "action": "auto_correct",
                "iteration": phase.auto_correction_count,
                "phase": phase.name,
            },
        )

        # Replan: inject DEBUGGER then CODER fix tasks
        await self.replan(
            mission.id,
            trigger_reason=f"Verification failed — auto-correction round {phase.auto_correction_count}",
            new_tasks=[
                {
                    "agent_type": "DEBUGGER",
                    "objective": f"Debug issues found in {mission.objective}",
                    "context": phase.result_summary,
                },
                {
                    "agent_type": "CODER",
                    "objective": f"Fix issues found during verification of {mission.objective}",
                    "context": phase.result_summary,
                    "parent_id": "",
                },
            ],
        )

        # Re-run the Implementation phase by moving index back
        mission.current_phase_index = max(
            0,
            next(
                (i for i, p in enumerate(mission.phases) if p.name == "Implementation"),
                mission.current_phase_index,
            ),
        )
        impl_phase = mission.phases[mission.current_phase_index]
        impl_phase.status = MissionStatus.PENDING
        await self._run_phase(mission, impl_phase)

    async def _evaluate_complexity_condition(self, mission: Mission, phase: MissionPhase) -> None:
        """Evaluate 'if complexity > threshold → spawn REFACTOR_PERFORMANCE'."""
        try:
            complexity = await self._analyze_complexity(mission)
        except Exception as exc:
            logger.warning("Complexity analysis failed for mission %s: %s", mission.id, exc)
            return

        threshold = mission.metadata.get("complexity_threshold", 7)
        if complexity > threshold:
            await self._emit(
                EventType.PLAN_UPDATED,
                mission_id=mission.id,
                data={
                    "action": "conditional_spawn",
                    "condition": f"complexity ({complexity}) > threshold ({threshold})",
                },
            )
            await self.spawn_agent(
                agent_type="OPTIMIZER",
                objective=f"Performance refactor for {mission.objective}",
                context=f"Complexity score {complexity} exceeded threshold {threshold}",
                phase_name=phase.name,
                mission_id=mission.id,
            )

    async def _trigger_peer_review(
        self, mission: Mission, phase: MissionPhase
    ) -> None:
        """Submit phase artifacts for mandatory peer review."""
        from backend.core.peer_review import get_peer_review_system

        prs = get_peer_review_system()
        for task_id in phase.tasks:
            task = mission.active_agents.get(task_id)
            if task is None:
                continue
            artifact_type = "code" if phase.name == "Implementation" else "design"
            author = task.type
            prs.submit_for_review(
                artifact_id=f"{mission.id}:{task.id}",
                artifact_type=artifact_type,
                author_agent=author,
                content=task.output or "",
            )
        await self._emit(
            EventType.PLAN_UPDATED,
            mission_id=mission.id,
            data={"action": "peer_review_triggered", "phase": phase.name},
        )

    async def _analyze_complexity(self, mission: Mission) -> int:
        """Use a quick LLM call (META_ANALYZER role) to estimate complexity 1-10."""
        model_cfg = get_model_config("nano")
        model_id = model_cfg["id"]
        prompt = (
            f"Rate the technical complexity of this objective on a scale of 1-10.\n\n"
            f"Objective: {mission.objective}\n\n"
            f"Respond with ONLY an integer between 1 and 10."
        )
        try:
            raw = await self._llm_client.chat_complete(
                model=model_id,
                messages=[
                    ChatMessage(role="system", content="You are a complexity analyzer. Be concise."),
                    ChatMessage(role="user", content=prompt),
                ],
                options={"temperature": 0.1, "num_predict": 16},
            )
            # Extract first integer
            import re

            match = re.search(r"\b(\d+)\b", raw)
            if match:
                return max(1, min(10, int(match.group(1))))
        except Exception as exc:
            logger.warning("Complexity LLM call failed: %s", exc)
        return 5

    # ------------------------------------------------------------------
    # Internal — persistence & events
    # ------------------------------------------------------------------

    def _get_mission(self, mission_id: str) -> Mission | None:
        if mission_id in self._missions:
            return self._missions[mission_id]
        # Attempt recovery from AgentStateStore
        mem = self._state_store.load_state(
            agent_name="META_ORCHESTRATOR",
            session_id=mission_id,
            project_path="",
            tier="medium_term",
            key="mission",
        )
        if mem and mem.value:
            try:
                mission = Mission.model_validate(mem.value)
                self._missions[mission_id] = mission
                return mission
            except Exception as exc:
                logger.warning("Failed to restore mission %s from store: %s", mission_id, exc)
        return None

    async def _persist_mission(self, mission: Mission) -> None:
        self._state_store.save_state(
            agent_name="META_ORCHESTRATOR",
            session_id=mission.id,
            project_path=mission.metadata.get("project_path", ""),
            tier="medium_term",
            key="mission",
            value=mission.model_dump(mode="json"),
            importance=0.9,
        )

    async def _abort_for_budget(self, mission: Mission, budget_type: str) -> None:
        logger.warning(
            "Mission %s aborted: %s budget exceeded (%s / %s)",
            mission.id,
            budget_type,
            mission.tokens_used if budget_type == "token" else int(_now() - mission.started_at),
            mission.token_budget if budget_type == "token" else mission.time_budget_seconds,
        )
        mission.status = MissionStatus.ABORTED
        mission.metadata["abort_reason"] = f"{budget_type}_budget_exceeded"
        await self._engine.cancel(mission.id)
        await self._persist_mission(mission)
        await self._emit(
            EventType.ERROR,
            mission_id=mission.id,
            data={"reason": f"{budget_type}_budget_exceeded"},
        )

    async def _emit(
        self,
        event_type: EventType,
        *,
        mission_id: str = "",
        task_id: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        await self._events.publish(
            OrchestratorEvent(
                event_type=event_type,
                source="META_ORCHESTRATOR",
                session_id=mission_id,
                task_id=task_id,
                data=data or {},
            )
        )

    def _build_phase_context(self, mission: Mission, phase: MissionPhase) -> str:
        """Aggregate outputs from previous phases as context."""
        parts: list[str] = []
        for prev in mission.phases:
            if prev.name == phase.name:
                break
            if prev.status == MissionStatus.COMPLETED and prev.result_summary:
                parts.append(f"## {prev.name}\n{prev.result_summary}")
        return "\n\n".join(parts)
