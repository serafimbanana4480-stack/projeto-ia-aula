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
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CONCURRENT_AGENTS_GLOBAL = 20
MAX_CONCURRENT_AGENTS_PER_TYPE = 5
DEFAULT_TOKEN_BUDGET = 100_000
DEFAULT_TIME_BUDGET_SECONDS = 600  # 10 minutes for explicitly managed agents
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

    When ``registry`` and ``llm_client`` are provided, spawned agents are
    *actually executed* in background asyncio tasks.  Otherwise the manager
    behaves as a pure state tracker (useful in tests).

    Usage::

        manager = AgentLifecycleManager(registry, llm_client)
        instance_id = await manager.spawn("CODER", "Implement OAuth2", mission_id="abc")
        await manager.pause(instance_id)
        await manager.resume(instance_id)
        await manager.abort(instance_id)
    """

    def __init__(
        self,
        registry: Any | None = None,
        llm_client: Any | None = None,
    ) -> None:
        self._instances: dict[str, AgentInstance] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._overseer_callback: Callable[[str, str, dict[str, Any]], Awaitable[None]] | None = None
        self._state_callback: Callable[[str, str, dict[str, Any]], Awaitable[None]] | None = None
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._resume_events: dict[str, asyncio.Event] = {}
        self._state_events: dict[str, asyncio.Event] = {}
        self._paused_at: dict[str, float] = {}
        self._registry = registry
        self._llm_client = llm_client

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

    def set_state_callback(
        self,
        callback: Callable[[str, str, dict[str, Any]], Awaitable[None]] | None,
    ) -> None:
        """Register the application callback for durable/event-bus updates.

        This is deliberately separate from the Overseer hook so the chat
        session can receive completed background work without coupling
        persistence to the monitoring agent.
        """
        self._state_callback = callback

    async def _notify_overseer(
        self, instance_id: str, event_type: str, data: dict[str, Any] | None = None
    ) -> None:
        if self._overseer_callback:
            try:
                await self._overseer_callback(instance_id, event_type, data or {})
            except Exception:
                logger.exception("Overseer notification failed for %s", instance_id)
        if self._state_callback:
            try:
                await self._state_callback(instance_id, event_type, data or {})
            except Exception:
                logger.exception("Lifecycle state callback failed for %s", instance_id)

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
        start_execution: bool = True,
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
            resume_event = asyncio.Event()
            resume_event.set()
            self._resume_events[instance.instance_id] = resume_event
            self._state_events[instance.instance_id] = asyncio.Event()

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

            # Actually execute the agent if registry + LLM client are wired.
            # External runners use this manager only for lifecycle tracking and
            # must not trigger a second provider/tool execution in parallel.
            if start_execution and self._registry is not None and self._llm_client is not None:
                task = asyncio.create_task(self._execute_agent(instance))
                self._tasks[instance.instance_id] = task

            return instance.instance_id

    async def pause(self, instance_id: str) -> AgentInstance:
        """Pause a running agent instance."""
        instance = self._get(instance_id)
        if instance is None:
            raise ValueError(f"Agent instance '{instance_id}' not found")

        if instance.status != AgentInstanceStatus.RUNNING.value:
            raise ValueError(f"Cannot pause agent in state '{instance.status}'")

        instance.status = AgentInstanceStatus.PAUSED.value
        self._paused_at[instance_id] = time.monotonic()
        self._resume_events.setdefault(instance_id, asyncio.Event()).clear()
        self._state_events.setdefault(instance_id, asyncio.Event()).set()
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

        paused_at = self._paused_at.pop(instance_id, None)
        if paused_at is not None:
            instance.deadline += max(0.0, time.monotonic() - paused_at)
        instance.status = AgentInstanceStatus.RUNNING.value
        self._resume_events.setdefault(instance_id, asyncio.Event()).set()
        self._state_events.setdefault(instance_id, asyncio.Event()).set()
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
        self._paused_at.pop(instance_id, None)
        self._resume_events.setdefault(instance_id, asyncio.Event()).set()
        self._state_events.setdefault(instance_id, asyncio.Event()).set()

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
        self._resume_events.setdefault(instance_id, asyncio.Event()).set()
        self._state_events.setdefault(instance_id, asyncio.Event()).set()
        if output:
            instance.context["output"] = output
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
        self._resume_events.setdefault(instance_id, asyncio.Event()).set()
        self._state_events.setdefault(instance_id, asyncio.Event()).set()
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

    def list_all(self) -> list[AgentInstance]:
        """Return active and recently terminal instances for UI recovery."""
        return list(self._instances.values())

    def list_by_mission(self, mission_id: str) -> list[AgentInstance]:
        """Return all agent instances associated with a mission."""
        return [i for i in self._instances.values() if i.mission_id == mission_id]

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
                    self._resume_events.pop(iid, None)
                    self._state_events.pop(iid, None)
                    self._paused_at.pop(iid, None)
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

    async def _execute_agent(self, instance: AgentInstance) -> None:
        """Run the actual agent and transition the instance to COMPLETED or FAILED."""
        agent = self._registry.get(instance.agent_type) if self._registry else None
        if agent is None:
            await self.fail(
                instance.instance_id,
                error=f"Agent type '{instance.agent_type}' not found in registry",
            )
            return

        from backend.agents.base import AgentRequest

        session_id = instance.mission_id or instance.instance_id
        request = AgentRequest(
            session_id=session_id,
            query=instance.objective,
            client=self._llm_client,
            context=instance.context,
            project_path=instance.context.get("project_path", "."),
            # Keep the ReAct ceiling high; the task deadline and repeated-tool
            # guard remain the practical safety limits.
            max_iterations=1000,
            autonomous=bool(instance.context.get("autonomous", True)),
        )

        output_parts: list[str] = []

        resume_event = self._resume_events.setdefault(instance.instance_id, asyncio.Event())

        async def _consume() -> None:
            stream = agent.run(request).__aiter__()
            while True:
                try:
                    token = await anext(stream)
                except StopAsyncIteration:
                    return
                # Pause at a token boundary. The provider may have yielded one
                # token while the pause request was in flight; it is held here
                # and only appended after an explicit resume.
                await resume_event.wait()
                if instance.status == AgentInstanceStatus.ABORTED.value:
                    return
                output_parts.append(token)

        stream_task = asyncio.create_task(_consume())
        try:
            remaining = max(1.0, instance.deadline - time.time())
            state_event = self._state_events.setdefault(instance.instance_id, asyncio.Event())
            loop = asyncio.get_running_loop()
            while not stream_task.done():
                if instance.status == AgentInstanceStatus.ABORTED.value:
                    stream_task.cancel()
                    await asyncio.gather(stream_task, return_exceptions=True)
                    return
                if instance.status == AgentInstanceStatus.PAUSED.value:
                    await resume_event.wait()
                    continue

                state_event.clear()
                state_wait = asyncio.create_task(state_event.wait())
                started = loop.time()
                done, _ = await asyncio.wait(
                    {stream_task, state_wait},
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                elapsed = loop.time() - started
                remaining = max(0.0, remaining - elapsed)
                if stream_task in done:
                    state_wait.cancel()
                    await asyncio.gather(state_wait, return_exceptions=True)
                    break
                if state_wait in done or instance.status == AgentInstanceStatus.PAUSED.value:
                    state_wait.cancel()
                    await asyncio.gather(state_wait, return_exceptions=True)
                    # If the deadline and pause landed in the same loop turn,
                    # do not charge time spent waiting for the pause checkpoint.
                    paused_at = self._paused_at.get(instance.instance_id)
                    if paused_at is not None and remaining == 0:
                        remaining += max(0.0, loop.time() - paused_at)
                    continue
                state_wait.cancel()
                await asyncio.gather(state_wait, return_exceptions=True)
                raise TimeoutError

            await stream_task
            if instance.status == AgentInstanceStatus.ABORTED.value:
                return
            output = "".join(output_parts)
            instance.context["output"] = output
            await self.complete(
                instance.instance_id,
                output=output,
                tokens_used=len(output),
            )
        except TimeoutError:
            await self.fail(
                instance.instance_id,
                error=f"Agent exceeded time budget of {instance.deadline - instance.start_time:.0f}s",
            )
        except Exception as exc:
            logger.exception("Agent execution failed for %s", instance.instance_id)
            await self.fail(instance.instance_id, error=str(exc))
        finally:
            if not stream_task.done():
                stream_task.cancel()
                await asyncio.gather(stream_task, return_exceptions=True)

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
