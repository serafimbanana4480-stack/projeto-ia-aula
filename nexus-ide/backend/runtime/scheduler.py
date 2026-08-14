"""Deterministic task scheduler for the NEXUS runtime.

Replaces "start every agent and hope" with an explicit admission policy:

* a task becomes ``READY`` only when **every** hard dependency is
  ``COMPLETED`` — never on a hand-off that has not been validated;
* at most ``max_parallel`` tasks run at once;
* two tasks whose write scopes overlap are serialised rather than allowed
  to race on the same file;
* admission is continuous, not wave-based, so one slow task does not hold
  back unrelated ready work;
* every task records the full lifecycle (``created_at``, ``queued_at``,
  ``scheduled_at``, ``started_at``, ``first_token_at``,
  ``first_tool_call_at``, ``completed_at``) so the *real* order can be
  proven from data instead of inferred from the UI;
* a task that stops reporting progress trips a watchdog, is cancelled, and
  is reported back to the caller instead of hanging on "thinking…".
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class RuntimeTaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Statuses from which a task may never transition back into execution.
TERMINAL_STATUSES = frozenset(
    {
        RuntimeTaskStatus.COMPLETED,
        RuntimeTaskStatus.FAILED,
        RuntimeTaskStatus.CANCELLED,
        RuntimeTaskStatus.BLOCKED,
    }
)


@dataclass
class RuntimeTask:
    """One unit of scheduled work with a provable lifecycle."""

    name: str
    run: Callable[["RuntimeTask"], Awaitable[Any]]
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    depends_on: frozenset[str] = frozenset()
    read_scope: frozenset[str] = frozenset()
    write_scope: frozenset[str] = frozenset()
    agent_id: str = "NEXUS"
    timeout_seconds: float = 300.0
    #: Cancel the task when no progress is reported for this long.
    heartbeat_timeout_seconds: float = 90.0
    max_retries: int = 0

    status: RuntimeTaskStatus = RuntimeTaskStatus.PENDING
    retries: int = 0
    error: str = ""
    result: Any = None

    # Lifecycle instants (monotonic seconds). 0.0 means "not reached".
    created_at: float = field(default_factory=time.monotonic)
    queued_at: float = 0.0
    scheduled_at: float = 0.0
    started_at: float = 0.0
    first_token_at: float = 0.0
    first_tool_call_at: float = 0.0
    completed_at: float = 0.0
    last_heartbeat_at: float = 0.0

    def heartbeat(self) -> None:
        self.last_heartbeat_at = time.monotonic()

    def mark_first_token(self) -> None:
        if not self.first_token_at:
            self.first_token_at = time.monotonic()
        self.heartbeat()

    def mark_first_tool_call(self) -> None:
        if not self.first_tool_call_at:
            self.first_tool_call_at = time.monotonic()
        self.heartbeat()

    def lifecycle(self) -> dict[str, float]:
        return {
            "created_at": self.created_at,
            "queued_at": self.queued_at,
            "scheduled_at": self.scheduled_at,
            "started_at": self.started_at,
            "first_token_at": self.first_token_at,
            "first_tool_call_at": self.first_tool_call_at,
            "completed_at": self.completed_at,
        }


class SchedulerError(RuntimeError):
    """Raised when the scheduler is asked to violate its own invariants."""


@dataclass
class SchedulerReport:
    tasks: list[RuntimeTask]
    peak_parallelism: int
    duration: float
    errors: list[str] = field(default_factory=list)

    def by_status(self, status: RuntimeTaskStatus) -> list[RuntimeTask]:
        return [task for task in self.tasks if task.status is status]

    @property
    def start_order(self) -> list[str]:
        started = [task for task in self.tasks if task.started_at]
        started.sort(key=lambda task: task.started_at)
        return [task.name for task in started]


class RuntimeScheduler:
    """Continuous-admission DAG scheduler with conflict serialisation."""

    def __init__(
        self,
        *,
        max_parallel: int = 3,
        on_status: Callable[[RuntimeTask], None] | None = None,
        poll_interval: float = 0.01,
    ) -> None:
        if max_parallel < 1:
            raise ValueError("max_parallel must be >= 1")
        self.max_parallel = max_parallel
        self._on_status = on_status
        self._poll_interval = poll_interval

    # -- graph validation ---------------------------------------------
    @staticmethod
    def validate(tasks: Iterable[RuntimeTask]) -> list[RuntimeTask]:
        by_id: dict[str, RuntimeTask] = {}
        for task in tasks:
            if task.task_id in by_id:
                raise SchedulerError(f"duplicate task id {task.task_id}")
            by_id[task.task_id] = task
        for task in by_id.values():
            unknown = task.depends_on - by_id.keys()
            if unknown:
                raise SchedulerError(
                    f"task {task.name!r} depends on unknown task(s): "
                    f"{', '.join(sorted(unknown))}"
                )
        _assert_acyclic(by_id)
        return list(by_id.values())

    # -- execution -----------------------------------------------------
    async def run(
        self,
        tasks: Iterable[RuntimeTask],
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> SchedulerReport:
        graph = self.validate(tasks)
        by_id = {task.task_id: task for task in graph}
        started = time.monotonic()
        now = started
        for task in graph:
            task.queued_at = now
            task.status = (
                RuntimeTaskStatus.PENDING if task.depends_on else RuntimeTaskStatus.READY
            )
            if not task.depends_on:
                task.scheduled_at = now
            self._notify(task)

        running: dict[asyncio.Task[Any], RuntimeTask] = {}
        errors: list[str] = []
        peak = 0

        while True:
            if cancel_event is not None and cancel_event.is_set():
                await self._cancel_all(running, by_id)
                break

            self._promote_ready(by_id)

            for task in self._admissible(by_id, running.values()):
                if len(running) >= self.max_parallel:
                    break
                task.status = RuntimeTaskStatus.RUNNING
                task.started_at = time.monotonic()
                task.heartbeat()
                self._notify(task)
                handle = asyncio.create_task(self._guarded(task))
                running[handle] = task
            peak = max(peak, len(running))

            if not running:
                if self._all_settled(by_id):
                    break
                # Nothing runnable and nothing running: the remainder can
                # never make progress. Mark it BLOCKED instead of spinning.
                stuck = [
                    task
                    for task in by_id.values()
                    if task.status
                    in (RuntimeTaskStatus.PENDING, RuntimeTaskStatus.WAITING)
                ]
                for task in stuck:
                    task.status = RuntimeTaskStatus.BLOCKED
                    task.error = task.error or "unsatisfiable dependency"
                    task.completed_at = time.monotonic()
                    self._notify(task)
                    errors.append(f"{task.name}: {task.error}")
                break

            done, _ = await asyncio.wait(
                running.keys(),
                timeout=self._poll_interval,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for handle in done:
                task = running.pop(handle)
                with contextlib.suppress(asyncio.CancelledError):
                    await handle
                if task.status is RuntimeTaskStatus.FAILED and task.error:
                    errors.append(f"{task.name}: {task.error}")
                self._notify(task)
                self._propagate_failure(task, by_id, errors)

        return SchedulerReport(
            tasks=list(by_id.values()),
            peak_parallelism=peak,
            duration=time.monotonic() - started,
            errors=errors,
        )

    # -- internals -----------------------------------------------------
    def _promote_ready(self, by_id: dict[str, RuntimeTask]) -> None:
        """PENDING/WAITING -> READY only when every dependency COMPLETED."""
        for task in by_id.values():
            if task.status not in (RuntimeTaskStatus.PENDING, RuntimeTaskStatus.WAITING):
                continue
            deps = [by_id[dep] for dep in task.depends_on]
            if any(dep.status in TERMINAL_STATUSES - {RuntimeTaskStatus.COMPLETED} for dep in deps):
                continue  # handled by _propagate_failure
            if all(dep.status is RuntimeTaskStatus.COMPLETED for dep in deps):
                task.status = RuntimeTaskStatus.READY
                task.scheduled_at = time.monotonic()
                self._notify(task)
            elif task.status is RuntimeTaskStatus.PENDING:
                task.status = RuntimeTaskStatus.WAITING
                self._notify(task)

    def _admissible(
        self,
        by_id: dict[str, RuntimeTask],
        running: Iterable[RuntimeTask],
    ) -> list[RuntimeTask]:
        """READY tasks whose write scope no running task already owns.

        Admission is stable: ready tasks are considered in the order they
        became ready, so the observable start order is the scheduler's
        decision rather than a coroutine race.
        """
        owned: set[str] = set()
        for task in running:
            owned |= task.write_scope
        candidates = sorted(
            (task for task in by_id.values() if task.status is RuntimeTaskStatus.READY),
            key=lambda task: (task.scheduled_at, task.queued_at, task.name),
        )
        admitted: list[RuntimeTask] = []
        for task in candidates:
            # Serialise writer/writer and writer/reader overlaps.
            if task.write_scope & owned or task.read_scope & owned:
                continue
            admitted.append(task)
            owned |= task.write_scope
        return admitted

    async def _guarded(self, task: RuntimeTask) -> None:
        """Run one task under a hard timeout and a progress watchdog."""
        while True:
            try:
                task.result = await asyncio.wait_for(
                    self._with_watchdog(task), timeout=task.timeout_seconds
                )
                task.status = RuntimeTaskStatus.COMPLETED
                task.completed_at = time.monotonic()
                return
            except asyncio.CancelledError:
                task.status = RuntimeTaskStatus.CANCELLED
                task.completed_at = time.monotonic()
                raise
            except TimeoutError:
                task.error = f"timed out after {task.timeout_seconds:.0f}s"
            except _StalledError as exc:
                task.error = str(exc)
            except Exception as exc:  # noqa: BLE001 - reported, never swallowed
                task.error = f"{type(exc).__name__}: {exc}"

            if task.retries < task.max_retries:
                task.retries += 1
                task.status = RuntimeTaskStatus.READY
                self._notify(task)
                continue
            task.status = RuntimeTaskStatus.FAILED
            task.completed_at = time.monotonic()
            return

    async def _with_watchdog(self, task: RuntimeTask) -> Any:
        """Fail a task that stops reporting progress, instead of hanging."""
        work = asyncio.create_task(task.run(task))
        if task.heartbeat_timeout_seconds <= 0:
            return await work
        while True:
            done, _ = await asyncio.wait({work}, timeout=self._poll_interval)
            if done:
                return await work
            silent_for = time.monotonic() - (task.last_heartbeat_at or task.started_at)
            if silent_for > task.heartbeat_timeout_seconds:
                work.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await work
                raise _StalledError(
                    f"no progress for {silent_for:.0f}s "
                    f"(heartbeat timeout {task.heartbeat_timeout_seconds:.0f}s)"
                )

    def _propagate_failure(
        self,
        task: RuntimeTask,
        by_id: dict[str, RuntimeTask],
        errors: list[str],
    ) -> None:
        if task.status is RuntimeTaskStatus.COMPLETED:
            return
        for other in by_id.values():
            if task.task_id in other.depends_on and other.status not in TERMINAL_STATUSES:
                other.status = RuntimeTaskStatus.BLOCKED
                other.error = f"dependency {task.name!r} did not complete"
                other.completed_at = time.monotonic()
                errors.append(f"{other.name}: {other.error}")
                self._notify(other)
                self._propagate_failure(other, by_id, errors)

    @staticmethod
    def _all_settled(by_id: dict[str, RuntimeTask]) -> bool:
        return all(task.status in TERMINAL_STATUSES for task in by_id.values())

    async def _cancel_all(
        self,
        running: dict[asyncio.Task[Any], RuntimeTask],
        by_id: dict[str, RuntimeTask],
    ) -> None:
        for handle, task in running.items():
            handle.cancel()
            task.status = RuntimeTaskStatus.CANCELLED
            task.completed_at = time.monotonic()
            self._notify(task)
        for handle in running:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await handle
        running.clear()
        for task in by_id.values():
            if task.status not in TERMINAL_STATUSES:
                task.status = RuntimeTaskStatus.CANCELLED
                task.completed_at = time.monotonic()
                self._notify(task)

    def _notify(self, task: RuntimeTask) -> None:
        if self._on_status is None:
            return
        try:
            self._on_status(task)
        except Exception:  # noqa: BLE001 - observers must never break a run
            logger.exception("scheduler status observer failed for %s", task.name)


class _StalledError(RuntimeError):
    """Internal: the progress watchdog fired."""


def _assert_acyclic(by_id: dict[str, RuntimeTask]) -> None:
    indegree = {task_id: len(task.depends_on) for task_id, task in by_id.items()}
    dependents: dict[str, list[str]] = {task_id: [] for task_id in by_id}
    for task in by_id.values():
        for dep in task.depends_on:
            dependents[dep].append(task.task_id)
    queue = [task_id for task_id, degree in indegree.items() if degree == 0]
    seen = 0
    while queue:
        current = queue.pop()
        seen += 1
        for child in dependents[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if seen != len(by_id):
        raise SchedulerError("task graph contains a cycle")


__all__ = [
    "RuntimeScheduler",
    "RuntimeTask",
    "RuntimeTaskStatus",
    "SchedulerError",
    "SchedulerReport",
    "TERMINAL_STATUSES",
]
