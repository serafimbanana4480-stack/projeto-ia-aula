"""Agent Lifecycle Manager — dynamic agent instance management.

Manages the full lifecycle of agent instances: spawn, pause, resume, abort,
and garbage collection. Enforces resource limits and integrates with the
Overseer for health tracking.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.core.agent_bus import BusMessage, get_agent_bus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CONCURRENT_AGENTS_GLOBAL = 20
MAX_CONCURRENT_AGENTS_PER_TYPE = 5
DEFAULT_TOKEN_BUDGET = 100_000
DEFAULT_TIME_BUDGET_SECONDS = 600  # 10 minutes
GC_MAX_AGE_SECONDS = 3_600  # 1 hour

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class AgentInstanceStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class AgentInstance(BaseModel):
    """A single dynamically spawned agent instance."""

    model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    agent_type: str
    status: str = AgentInstanceStatus.IDLE.value
    objective: str = ""
    start_time: float = Field(default_factory=time.time)
    deadline: float = 0.0
    tokens_used: int = 0
    token_budget: int = DEFAULT_TOKEN_BUDGET
    parent_task_id: str = ""
    mission_id: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    error_message: str = ""
    completed_at: float = 0.0

    def is_terminal(self) -> bool:
        return self.status in {
            AgentInstanceStatus.COMPLETED.value,
            AgentInstanceStatus.FAILED.value,
            AgentInstanceStatus.ABORTED.value,
        }


# ---------------------------------------------------------------------------
# AgentLifecycleManager
# ---------------------------------------------------------------------------


class AgentLifecycleManager:
    """Manages dynamic agent instances with resource limits and overseer integration.

    Usage::

        manager = AgentLifecycleManager()
        instance_id = await manager.spawn("CODER", "Implement OAuth2", mission_id="abc")
        await manager.pause(instance_id)
        await manager.resume(instance_id)
        await manager.abort(instance_id)
    """

    def __init__(self) -> None:
        self._instances: dict[str, AgentInstance] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._overseer_callback: Callable[[str, str, dict[str, Any]], Awaitable[None]] | None = None
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    # -- overseer integration -----------------------------------------------

    def set_overseer_callback(
        self,
        callback: Callable[[str, str, dict[str, Any]], Awaitable[None]] | None,
    ) -> None:
        """Register a callback invoked on every state change.

        The callback receives ``(instance_id, event_type, data_dict)``.
        Typically wired to ``OverseerAgent.record_agent_event``.
        """
        self._overseer_callback = callback

    async def _notify_overseer(
        self, instance_id: str, event_type: str, data: dict[str, Any] | None = None
    ) -> None:
        if self._overseer_callback:
            try:
                await self._overseer_callback(instance_id, event_type, data or {})
            except Exception:
                logger.exception("Overseer notification failed for %s", instance_id)

    # -- CRUD ---------------------------------------------------------------

    async def spawn(
        self,
        agent_type: str,
        objective: str,
        context: dict[str, Any] | None = None,
        mission_id: str = "",
        token_budget: int | None = None,
        time_budget_seconds: int | None = None,
        parent_task_id: str = "",
    ) -> str:
        """Spawn a new agent instance after validating resource limits.

        Returns:
            The ``instance_id`` of the newly created agent.

        Raises:
            RuntimeError: If global or per-type concurrent limits are exceeded.
        """
        async with self._global_lock:
            active = [i for i in self._instances.values() if not i.is_terminal()]

            if len(active) >= MAX_CONCURRENT_AGENTS_GLOBAL:
                raise RuntimeError(
                    f"Global concurrent agent limit reached ({MAX_CONCURRENT_AGENTS_GLOBAL})"
                )

            type_count = sum(1 for i in active if i.agent_type == agent_type)
            if type_count >= MAX_CONCURRENT_AGENTS_PER_TYPE:
                raise RuntimeError(
                    f"Concurrent limit for agent type '{agent_type}' reached ({MAX_CONCURRENT_AGENTS_PER_TYPE})"
                )

            instance = AgentInstance(
                agent_type=agent_type,
                objective=objective,
                context=context or {},
                mission_id=mission_id,
                token_budget=token_budget or DEFAULT_TOKEN_BUDGET,
                deadline=time.time() + (time_budget_seconds or DEFAULT_TIME_BUDGET_SECONDS),
                parent_task_id=parent_task_id,
            )
            instance.status = AgentInstanceStatus.RUNNING.value
            self._instances[instance.instance_id] = instance
            self._locks[instance.instance_id] = asyncio.Lock()

            await self._notify_overseer(
                instance.instance_id,
                "agent_started",
                {
                    "agent_type": agent_type,
                    "objective": objective,
                    "mission_id": mission_id,
                    "token_budget": instance.token_budget,
                    "deadline": instance.deadline,
                },
            )

            logger.info(
                "Agent spawned | id=%s type=%s mission=%s",
                instance.instance_id,
                agent_type,
                mission_id,
            )
            return instance.instance_id

    async def pause(self, instance_id: str) -> AgentInstance:
        """Pause a running agent instance."""
        instance = self._get(instance_id)
        if instance is None:
            raise ValueError(f"Agent instance '{instance_id}' not found")

        if instance.status != AgentInstanceStatus.RUNNING.value:
            raise ValueError(f"Cannot pause agent in state '{instance.status}'")

        instance.status = AgentInstanceStatus.PAUSED.value
        await self._notify_overseer(
            instance_id,
            "agent_paused",
            {"agent_type": instance.agent_type, "mission_id": instance.mission_id},
        )
        logger.info("Agent paused | id=%s", instance_id)
        return instance

    async def resume(self, instance_id: str) -> AgentInstance:
        """Resume a paused agent instance."""
        instance = self._get(instance_id)
        if instance is None:
            raise ValueError(f"Agent instance '{instance_id}' not found")

        if instance.status != AgentInstanceStatus.PAUSED.value:
            raise ValueError(f"Cannot resume agent in state '{instance.status}'")

        instance.status = AgentInstanceStatus.RUNNING.value
        await self._notify_overseer(
            instance_id,
            "agent_resumed",
            {"agent_type": instance.agent_type, "mission_id": instance.mission_id},
        )
        logger.info("Agent resumed | id=%s", instance_id)
        return instance

    async def abort(self, instance_id: str, reason: str = "") -> AgentInstance:
        """Abort a running or paused agent instance."""
        instance = self._get(instance_id)
        if instance is None:
            raise ValueError(f"Agent instance '{instance_id}' not found")

        if instance.is_terminal():
            raise ValueError(f"Cannot abort agent in terminal state '{instance.status}'")

        instance.status = AgentInstanceStatus.ABORTED.value
        instance.completed_at = time.time()
        instance.error_message = reason or "Aborted by lifecycle manager"

        # Cancel any associated task
        task = self._tasks.pop(instance_id, None)
        if task and not task.done():
            task.cancel()

        await self._notify_overseer(
            instance_id,
            "agent_aborted",
            {
                "agent_type": instance.agent_type,
                "mission_id": instance.mission_id,
                "reason": reason,
            },
        )
        logger.info("Agent aborted | id=%s reason=%s", instance_id, reason)
        return instance

    async def complete(
        self, instance_id: str, output: str = "", tokens_used: int = 0
    ) -> AgentInstance:
        """Mark an agent instance as completed (called by orchestrator)."""
        instance = self._get(instance_id)
        if instance is None:
            raise ValueError(f"Agent instance '{instance_id}' not found")

        instance.status = AgentInstanceStatus.COMPLETED.value
        instance.completed_at = time.time()
        instance.tokens_used = tokens_used
        await self._notify_overseer(
            instance_id,
            "agent_finished",
            {
                "agent_type": instance.agent_type,
                "mission_id": instance.mission_id,
                "output_preview": output[:200],
                "tokens_used": tokens_used,
            },
        )
        logger.info("Agent completed | id=%s tokens=%d", instance_id, tokens_used)
        return instance

    async def fail(self, instance_id: str, error: str = "") -> AgentInstance:
        """Mark an agent instance as failed (called by orchestrator)."""
        instance = self._get(instance_id)
        if instance is None:
            raise ValueError(f"Agent instance '{instance_id}' not found")

        instance.status = AgentInstanceStatus.FAILED.value
        instance.completed_at = time.time()
        instance.error_message = error
        await self._notify_overseer(
            instance_id,
            "agent_failed",
            {
                "agent_type": instance.agent_type,
                "mission_id": instance.mission_id,
                "error": error,
            },
        )
        logger.warning("Agent failed | id=%s error=%s", instance_id, error)
        return instance

    def get_status(self, instance_id: str) -> AgentInstance | None:
        """Return the full status of an agent instance."""
        return self._get(instance_id)

    def list_active(self) -> list[AgentInstance]:
        """Return all non-terminal agent instances."""
        return [i for i in self._instances.values() if not i.is_terminal()]

    def list_by_mission(self, mission_id: str) -> list[AgentInstance]:
        """Return all agent instances associated with a mission."""
        return [
            i for i in self._instances.values() if i.mission_id == mission_id
        ]

    async def garbage_collect(self) -> list[str]:
        """Remove completed/failed/aborted agents older than 1 hour.

        Returns:
            List of removed instance IDs.
        """
        now = time.time()
        removed: list[str] = []
        async with self._global_lock:
            for iid, instance in list(self._instances.items()):
                if (
                    instance.is_terminal()
                    and instance.completed_at > 0
                    and (now - instance.completed_at) > GC_MAX_AGE_SECONDS
                ):
                    del self._instances[iid]
                    self._locks.pop(iid, None)
                    self._tasks.pop(iid, None)
                    removed.append(iid)
        if removed:
            logger.info("GC removed %d agent instances: %s", len(removed), removed)
        return removed

    def track_task(self, instance_id: str, task: asyncio.Task[Any]) -> None:
        """Track an asyncio task associated with an agent instance."""
        self._tasks[instance_id] = task

    # -- helpers ------------------------------------------------------------

    def _get(self, instance_id: str) -> AgentInstance | None:
        return self._instances.get(instance_id)

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate statistics about managed instances."""
        statuses: dict[str, int] = {}
        for i in self._instances.values():
            statuses[i.status] = statuses.get(i.status, 0) + 1
        return {
            "total_instances": len(self._instances),
            "active_instances": len(self.list_active()),
            "status_breakdown": statuses,
            "global_limit": MAX_CONCURRENT_AGENTS_GLOBAL,
            "per_type_limit": MAX_CONCURRENT_AGENTS_PER_TYPE,
        }
