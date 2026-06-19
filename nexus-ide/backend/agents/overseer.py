"""OVERSEER agent — monitors all agents and intervenes when necessary.

The overseer maintains an internal health dashboard for every agent in the
system.  It detects file conflicts, tracks token budgets, identifies stuck
agents, enforces quality gates, and tracks mission progress.

Integration points
------------------
* The orchestrator calls :meth:`record_agent_event` after every ReAct
  iteration so the overseer has an up-to-date view of the system.
* The dashboard route (:mod:`backend.orchestrator.routes.overseer`) exposes
  the internal health state via REST.
* Other agents can ``consult_agent`` the overseer to check whether it is
  safe to write a file or to report a blocker.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.agents.base import AgentAction, AgentBase, AgentRequest

logger = logging.getLogger(__name__)


@dataclass
class AgentHealthRecord:
    """Snapshot of an agent's current health."""

    agent_name: str
    status: str = "idle"  # idle | running | paused | error | stuck | done
    last_seen: float = field(default_factory=time.time)
    task: str = ""
    current_file: str = ""
    iteration: int = 0
    success_count: int = 0
    failure_count: int = 0
    tokens_used: int = 0
    token_budget: int = 100_000
    blocked_since: float | None = None
    history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=50))


@dataclass
class MissionRecord:
    """Tracked autonomous mission."""

    mission_id: str
    name: str
    status: str = "active"  # active | completed | failed | aborted
    agents_involved: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None


class OverseerAgent(AgentBase):
    """Monitors all agents, detects conflicts, manages resources, intervenes."""

    name = "OVERSEER"
    model_key = "reasoning"
    prompt_file = "overseer"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.CONSULT_AGENT,
        AgentAction.RECALL_CONTEXT,
    }

    # Thresholds
    STUCK_THRESHOLD_SECONDS = 120.0
    ERROR_LOOP_THRESHOLD = 3
    DEFAULT_TOKEN_BUDGET = 100_000

    def __init__(self) -> None:
        super().__init__()
        self._health: dict[str, AgentHealthRecord] = {}
        self._file_locks: dict[str, str] = {}
        self._missions: dict[str, MissionRecord] = {}
        self._intervention_log: deque[dict[str, Any]] = deque(maxlen=100)
        self._quality_gate_records: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Core ReAct execution
    # ------------------------------------------------------------------
    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        """Execute overseer with ReAct loop.

        Before streaming we run a quick internal scan so the LLM has
        fresh context about the current system state.
        """
        logger.info(
            "[OVERSEER] Starting | session=%s query=%.80s",
            request.session_id,
            request.query,
        )
        await self._scan_system()
        async for token in self._run_react_loop(request):
            yield token

    async def _scan_system(self) -> None:
        """Update our own view by checking for timeouts and conflicts."""
        async with self._lock:
            now = time.time()
            for record in self._health.values():
                if record.status == "running":
                    idle = now - record.last_seen
                    if idle > self.STUCK_THRESHOLD_SECONDS and record.blocked_since is None:
                        record.blocked_since = now
                        record.status = "stuck"
                        logger.warning(
                            "[OVERSEER] Agent %s marked STUCK (idle %.1fs)",
                            record.agent_name,
                            idle,
                        )

    # ------------------------------------------------------------------
    # Public event API — called by orchestrator or other components
    # ------------------------------------------------------------------
    async def record_agent_event(
        self,
        agent_name: str,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Record an event from another agent and update health state."""
        data = data or {}
        async with self._lock:
            record = self._health.setdefault(
                agent_name,
                AgentHealthRecord(
                    agent_name=agent_name,
                    token_budget=self.DEFAULT_TOKEN_BUDGET,
                ),
            )
            record.last_seen = time.time()
            record.history.append(
                {
                    "timestamp": record.last_seen,
                    "event": event_type,
                    "data": data,
                }
            )

            # Update state machine based on event
            if event_type == "agent_started":
                record.status = "running"
                record.task = data.get("task", "")
                record.blocked_since = None
            elif event_type == "agent_finished":
                record.status = "done"
                record.success_count += 1
                record.iteration = data.get("iteration", record.iteration)
            elif event_type == "agent_failed":
                record.status = "error"
                record.failure_count += 1
            elif event_type == "iteration":
                record.iteration = data.get("iteration", record.iteration)
                record.tokens_used = data.get("tokens_used", record.tokens_used)
                record.current_file = data.get("current_file", record.current_file)
            elif event_type == "file_locked":
                path = data.get("path", "")
                if path:
                    self._file_locks[path] = agent_name
                    record.current_file = path
            elif event_type == "file_unlocked":
                path = data.get("path", "")
                self._file_locks.pop(path, None)
                if record.current_file == path:
                    record.current_file = ""

            # Detect error loops
            if record.failure_count >= self.ERROR_LOOP_THRESHOLD:
                record.status = "stuck"
                if record.blocked_since is None:
                    record.blocked_since = time.time()
                logger.warning("[OVERSEER] Agent %s in ERROR LOOP", agent_name)

    async def set_token_budget(self, agent_name: str, budget: int) -> None:
        """Set a per-agent token budget."""
        async with self._lock:
            record = self._health.setdefault(
                agent_name,
                AgentHealthRecord(agent_name=agent_name),
            )
            record.token_budget = budget

    # ------------------------------------------------------------------
    # Dashboard queries
    # ------------------------------------------------------------------
    def get_dashboard(self) -> dict[str, Any]:
        """Return the full overseer dashboard."""
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "agents": {name: self._record_to_dict(r) for name, r in self._health.items()},
            "file_conflicts": self._detect_conflicts_sync(),
            "stuck_agents": self._detect_stuck_sync(),
            "missions": [self._mission_to_dict(m) for m in self._missions.values()],
            "interventions": list(self._intervention_log),
        }

    def get_agent_status(self, agent_name: str) -> dict[str, Any] | None:
        """Return detailed status for a single agent."""
        record = self._health.get(agent_name)
        return self._record_to_dict(record) if record else None

    def list_agents(self) -> list[str]:
        """Return the list of tracked agents."""
        return list(self._health.keys())

    # ------------------------------------------------------------------
    # Intervention API
    # ------------------------------------------------------------------
    async def intervene(
        self,
        agent_name: str,
        action: str,
        reason: str = "",
    ) -> dict[str, Any]:
        """Pause, resume, abort, or escalate an agent.

        Actions: ``pause``, ``resume``, ``abort``, ``escalate``.
        """
        valid_actions = {"pause", "resume", "abort", "escalate"}
        if action not in valid_actions:
            return {"error": f"Invalid action '{action}'. Valid: {valid_actions}"}

        async with self._lock:
            record = self._health.get(agent_name)
            if not record:
                return {"error": f"Agent '{agent_name}' not tracked"}

            old_status = record.status
            if action == "pause":
                record.status = "paused"
            elif action == "resume":
                record.status = "running"
                record.blocked_since = None
            elif action in ("abort", "escalate"):
                record.status = "error" if action == "abort" else "stuck"
                record.end_time = time.time()

            self._intervention_log.append(
                {
                    "timestamp": time.time(),
                    "agent": agent_name,
                    "action": action,
                    "old_status": old_status,
                    "new_status": record.status,
                    "reason": reason,
                }
            )

        logger.info(
            "[OVERSEER] Intervention on %s: %s (%s)",
            agent_name,
            action,
            reason,
        )
        return {
            "success": True,
            "agent": agent_name,
            "action": action,
            "previous_status": old_status,
            "current_status": record.status,
        }

    # ------------------------------------------------------------------
    # Quality gates
    # ------------------------------------------------------------------
    def record_review(self, file_path: str, reviewer: str, passed: bool) -> None:
        """Record that a file has been reviewed."""
        self._quality_gate_records[file_path] = {
            "reviewer": reviewer,
            "passed": passed,
            "timestamp": time.time(),
        }

    def check_quality_gate(self, agent_name: str, file_path: str) -> dict[str, Any]:
        """Check whether code can be marked done."""
        record = self._quality_gate_records.get(file_path)
        if not record:
            return {"passed": False, "reason": "No review record found"}
        if not record["passed"]:
            return {
                "passed": False,
                "reason": f"Review by {record['reviewer']} failed",
            }
        return {"passed": True, "reviewer": record["reviewer"]}

    # ------------------------------------------------------------------
    # Mission tracking
    # ------------------------------------------------------------------
    def start_mission(self, mission_id: str, name: str, agents: list[str]) -> None:
        """Track a new autonomous mission."""
        self._missions[mission_id] = MissionRecord(
            mission_id=mission_id,
            name=name,
            agents_involved=agents,
        )

    def update_mission(
        self,
        mission_id: str,
        status: str | None = None,
        blocker: str | None = None,
    ) -> dict[str, Any]:
        """Update mission status or add a blocker."""
        mission = self._missions.get(mission_id)
        if not mission:
            return {"error": "Mission not found"}
        if status:
            mission.status = status
            if status in ("completed", "failed", "aborted"):
                mission.end_time = time.time()
        if blocker:
            mission.blockers.append(blocker)
        return {"success": True, "mission": self._mission_to_dict(mission)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _detect_conflicts_sync(self) -> list[dict[str, Any]]:
        """Find files being worked on by more than one agent."""
        conflicts = []
        file_to_agents: dict[str, list[str]] = {}
        for name, record in self._health.items():
            if record.current_file:
                file_to_agents.setdefault(record.current_file, []).append(name)
        for path, agents in file_to_agents.items():
            if len(agents) > 1:
                conflicts.append({"file": path, "agents": agents})
        return conflicts

    def _detect_stuck_sync(self) -> list[dict[str, Any]]:
        """Return agents currently marked as stuck."""
        stuck = []
        for name, record in self._health.items():
            if record.status == "stuck":
                stuck.append(
                    {
                        "agent": name,
                        "blocked_since": record.blocked_since,
                        "task": record.task,
                    }
                )
        return stuck

    @staticmethod
    def _record_to_dict(record: AgentHealthRecord) -> dict[str, Any]:
        return {
            "agent_name": record.agent_name,
            "status": record.status,
            "last_seen": datetime.fromtimestamp(record.last_seen, UTC).isoformat(),
            "task": record.task,
            "current_file": record.current_file,
            "iteration": record.iteration,
            "success_count": record.success_count,
            "failure_count": record.failure_count,
            "tokens_used": record.tokens_used,
            "token_budget": record.token_budget,
            "budget_remaining": max(0, record.token_budget - record.tokens_used),
            "blocked_since": (
                datetime.fromtimestamp(record.blocked_since, UTC).isoformat()
                if record.blocked_since
                else None
            ),
        }

    @staticmethod
    def _mission_to_dict(mission: MissionRecord) -> dict[str, Any]:
        return {
            "mission_id": mission.mission_id,
            "name": mission.name,
            "status": mission.status,
            "agents_involved": mission.agents_involved,
            "blockers": mission.blockers,
            "start_time": datetime.fromtimestamp(mission.start_time, UTC).isoformat(),
            "end_time": (
                datetime.fromtimestamp(mission.end_time, UTC).isoformat()
                if mission.end_time
                else None
            ),
        }
