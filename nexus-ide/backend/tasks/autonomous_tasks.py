"""Autonomous Tasks System - Self-executing tasks for NEXUS OMEGA.

This system provides:
- Autonomous task scheduling
- Task lifecycle management
- Self-healing capabilities
- Task dependency resolution
- Autonomous decision making

Recovery contract (see :mod:`backend.tasks.handler_registry`):

* Persisted tasks are rehydrated from SQLite with their handler name; the live
  callable is re-attached through the :class:`HandlerRegistry`.
* ``NEXUS_TASKS_RESUME_PENDING`` (default **false**) keeps recovered
  write-effect tasks in quarantine instead of firing them at boot. The operator
  re-enables them through ``POST /api/tasks/{task_id}/requeue``. Read-only
  handlers are exempt and may resume without the flag.
* A recovered task whose handler is not registered in this build fails
  explicitly and is never silently retried or dropped.

Execution is exactly-once per persisted task:

* the persisted row is flipped to ``running`` by an atomic conditional UPDATE
  *before* the handler runs, so a crash can never be mistaken for "never
  started" and a second worker sharing the database loses the claim and skips
  the task instead of running it twice;
* a row still ``running`` at boot was interrupted mid-execution. It is
  quarantined (or, for a read-only handler, resumed) and only an explicit
  :meth:`TaskScheduler.requeue_task` re-arms it;
* a shutdown marks the tasks it cancels the same way, so ``stop()`` never
  leaves a task looking runnable.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, StrEnum
from typing import Any

from backend.observability.event_system import Event, EventBus, EventPriority, EventType
from backend.persistence.db import (
    delete_scheduled_task,
    get_db,
    load_scheduled_tasks,
    save_scheduled_task,
    update_scheduled_task_status,
)
from backend.tasks.handler_registry import HandlerRegistry

logger = logging.getLogger(__name__)


class TaskStatus(StrEnum):
    """Task execution status."""
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"
    WAITING = "waiting"


class TaskPriority(StrEnum):
    """Task priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"
    URGENT = "urgent"


class TaskType(StrEnum):
    """Types of autonomous tasks."""
    MONITORING = "monitoring"
    OPTIMIZATION = "optimization"
    MAINTENANCE = "maintenance"
    ANALYSIS = "analysis"
    LEARNING = "learning"
    CLEANUP = "cleanup"
    HEALTH_CHECK = "health_check"
    PERFORMANCE_TUNING = "performance_tuning"
    ERROR_RECOVERY = "error_recovery"


#: Recovery statuses rehydrated on startup (mirrors the DB load filter).
_RESUMABLE_STATUSES = (
    TaskStatus.PENDING,
    TaskStatus.SCHEDULED,
    TaskStatus.WAITING,
    TaskStatus.RETRYING,
)
_TERMINAL_STATUSES = (
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
)

#: DB statuses from which an execution may still be claimed. A row outside this
#: set is either owned by a live worker ('running') or already finished, so it
#: must never be executed again.
_CLAIMABLE_DB_STATUSES = ("pending", "scheduled", "waiting", "retrying")

#: DB status meaning "a worker started this task and never reported back"
#: (process died, or was killed, mid-execution).
_INTERRUPTED_DB_STATUS = "running"


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean environment flag with an explicit default."""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _parse_json(value: Any, default: Any) -> Any:
    """Best-effort JSON decode that tolerates already-decoded columns."""
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return default
        return default if parsed is None else parsed
    return default


def _coerce_enum(enum_cls: type[Enum], value: Any, default: Enum) -> Enum:
    """Coerce a stored string/enum value into *enum_cls*, else *default*."""
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip().lower())
        except ValueError:
            return default
    return default


@dataclass
class Task:
    """Autonomous task definition."""
    task_id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:12]}")
    name: str = ""
    task_type: TaskType = TaskType.MONITORING
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING

    # Scheduling
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Execution
    handler: Callable | None = None
    #: Persisted handler name (the ``handler`` column). Callables cannot be
    #: serialised, so this is what a recovered task re-attaches against.
    handler_name: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    dependencies: set[str] = field(default_factory=set)

    # Configuration
    retry_count: int = 0
    max_retries: int = 3
    timeout: int = 300  # seconds
    interval: int | None = None  # For recurring tasks
    auto_retry: bool = True

    # Results
    result: Any | None = None
    error: str | None = None
    execution_time: float = 0.0

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "custom"

    def to_dict(self) -> dict[str, Any]:
        """Convert task to dictionary."""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "task_type": self.task_type.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "handler": self.handler_name
            if self.handler_name
            else (self.handler.__name__ if self.handler else None),
            "parameters": self.parameters,
            "dependencies": list(self.dependencies),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
            "interval": self.interval,
            "auto_retry": self.auto_retry,
            "result": self.result,
            "error": self.error,
            "execution_time": self.execution_time,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
            "source": self.source,
        }


class TaskScheduler:
    """Schedules and manages autonomous tasks."""

    #: Maps the scheduler's internal event key to a canonical ``EventType``.
    _EVENT_TYPE_BY_KEY: dict[str, EventType] = {
        "task_started": EventType.TASK_STARTED,
        "task_scheduled": EventType.TASK_QUEUED,
        "task_completed": EventType.TASK_COMPLETED,
        "task_failed": EventType.TASK_FAILED,
        "task_timeout": EventType.TASK_FAILED,
        "task_cancelled": EventType.SYSTEM_WARNING,
        "task_retry": EventType.TASK_QUEUED,
    }

    def __init__(
        self,
        event_bus: EventBus,
        handler_registry: HandlerRegistry | None = None,
        max_concurrent: int = 10,
    ) -> None:
        self.event_bus = event_bus
        self.handler_registry = handler_registry
        self.tasks: dict[str, Task] = {}
        self.task_queue: list[Task] = []
        self.running_tasks: dict[str, Task] = {}
        #: The asyncio task currently running each executing task so a RUNNING
        #: task can actually be cancelled (a portmanteau that previously only
        #: forgot its state, leaving the handler to resurrect it as COMPLETED).
        self._running_asyncio: dict[str, asyncio.Task] = {}
        self.completed_tasks: list[Task] = []
        self.failed_tasks: list[Task] = []
        #: Recovered-but-dormant tasks that must not run until requeued.
        self._quarantined: set[str] = set()
        #: In-flight retry backoff sleeps, kept strong + cancellable.
        self._retry_tasks: list[asyncio.Task] = []

        # Scheduling
        self._running = False
        self._scheduler_task: asyncio.Task | None = None
        self._max_concurrent = max_concurrent
        self._cleanup_interval = 300  # 5 minutes

        # Statistics
        self.stats = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "running_tasks": 0,
            "scheduled_tasks": 0,
            "average_execution_time": 0.0
        }

    async def start(self, resume_pending: bool = False) -> None:
        """Start the task scheduler and rehydrate persisted tasks.

        Args:
            resume_pending: When ``True`` (``NEXUS_TASKS_RESUME_PENDING``), run
                recovered write-effect tasks. When ``False`` (default) they are
                quarantined instead. Read-only handlers resume either way.
        """
        if self._running:
            return

        self._running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("TaskScheduler started")

        # Restore persisted custom tasks from database
        await self._load_persistent_tasks(resume_pending=resume_pending)

    def _rehydrate_task(self, data: dict[str, Any], handler_name: str | None) -> Task:
        """Rebuild a :class:`Task` from a persisted row, re-attaching its handler."""
        task = Task(
            task_id=data["id"],
            name=data.get("name", ""),
            task_type=_coerce_enum(TaskType, data.get("task_type", "monitoring"), TaskType.MONITORING),
            priority=_coerce_enum(TaskPriority, data.get("priority", "normal"), TaskPriority.NORMAL),
            status=_coerce_enum(TaskStatus, data.get("status", "pending"), TaskStatus.PENDING),
            handler_name=handler_name,
            handler=(
                self.handler_registry.resolve_callable(handler_name)
                if self.handler_registry
                else None
            ),
            parameters=_parse_json(data.get("parameters_json"), {}),
            dependencies=set(_parse_json(data.get("dependencies_json"), [])),
            retry_count=int(data.get("retry_count") or 0),
            max_retries=data.get("max_retries") if data.get("max_retries") is not None else 3,
            timeout=data.get("timeout") if data.get("timeout") is not None else 300,
            interval=data.get("interval"),
            auto_retry=bool(data.get("auto_retry", True)),
            result=_parse_json(data.get("result_json"), None),
            error=data.get("error"),
            execution_time=float(data.get("execution_time") or 0.0),
            metadata=_parse_json(data.get("metadata_json"), {}),
            source=data.get("source", "custom"),
        )
        for attr, key in (
            ("scheduled_at", "scheduled_at"),
            ("started_at", "started_at"),
            ("completed_at", "completed_at"),
        ):
            val = data.get(key)
            if val:
                with contextlib.suppress(Exception):
                    setattr(
                        task,
                        attr,
                        datetime.fromisoformat(str(val).replace("Z", "+00:00")),
                    )
        return task

    async def _load_persistent_tasks(self, resume_pending: bool = False) -> None:
        """Load persistent custom tasks on startup and apply the resume policy.

        Tasks are inventoried (``metadata['recovered_at']``) and classified as:

        * **unregistered handler** -> FAILED explicitly, persisted, event
          ``task_failed`` emitted, kept out of the queue (never re-run).
        * **interrupted** -> the row was left ``running`` by a process that died
          mid-execution. It is *never* auto-run: a handler may already have
          applied half of its side effects. It becomes WAITING/quarantined so an
          operator can inspect and requeue it (read-only handlers, which cannot
          have side effects, resume like any other read-only task).
        * **resumed** -> re-enqueued when due (immediately, or when their
          ``scheduled_at`` arrives). Requires ``resume_pending`` for write
          handlers; read-only handlers resume regardless.
        * **quarantined** -> held in WAITING, out of the queue, until the
          operator calls :meth:`requeue_task`.

        A row whose id is already known in this process is skipped: the live
        object (and its queue entry) is authoritative, and re-hydrating it would
        enqueue the same task twice.
        """
        try:
            tasks_data = load_scheduled_tasks(source="custom")
        except Exception as e:
            logger.warning("Failed to load persistent tasks: %s", e)
            return

        now = datetime.now()
        recovered_at = now.isoformat()
        resumed = quarantined = failed = 0
        for data in tasks_data:
            task_id = data.get("id", "unknown")
            handler_name = data.get("handler")
            if task_id in self.tasks:
                # Already loaded (or created) in this process: keep the live
                # instance. Re-adding it would run the same task twice.
                logger.debug("Persisted task already known in this process: %s", task_id)
                continue
            try:
                task = self._rehydrate_task(data, handler_name)
            except Exception as e:
                logger.warning("Failed to load task %s: %s", task_id, e)
                continue

            task.metadata["recovered_at"] = recovered_at

            registered = (
                self.handler_registry is not None
                and self.handler_registry.resolve_callable(handler_name) is not None
            )
            if not registered:
                await self._fail_unregistered(task, handler_name, recovered_at)
                failed += 1
                continue

            self.tasks[task.task_id] = task
            recovered_status = task.status
            if recovered_status not in _RESUMABLE_STATUSES:
                # Loaded but not runnable (defensive; the query already filters).
                task.metadata["recovered_state"] = "dormant"
                self._persist_recovery(task)
                quarantined += 1
                logger.info("Recovered task left dormant: %s (%s)", task.name, task.task_id)
                continue

            read_only = self.handler_registry.is_read_only(handler_name)
            # An interrupted task is never auto-run, not even under
            # NEXUS_TASKS_RESUME_PENDING: its handler may have applied half of
            # its side effects, so only an explicit requeue re-arms it.
            was_interrupted = task.metadata.get("recovered_state") == "interrupted"
            can_run = (resume_pending or read_only) and not was_interrupted
            if not can_run:
                task.status = TaskStatus.WAITING
                task.metadata["quarantined"] = True
                task.metadata["recovered_state"] = (
                    "interrupted" if was_interrupted else "quarantined"
                )
                self._quarantined.add(task.task_id)
                self._persist_recovery(task)
                quarantined += 1
                logger.info(
                    "Recovered task quarantined (set NEXUS_TASKS_RESUME_PENDING=true "
                    "or requeue to run): %s (%s)", task.name, task.task_id
                )
                continue

            if recovered_status == TaskStatus.RETRYING:
                # A RETRYING task was mid-backoff when the process died. Reset
                # its run fields so it starts clean rather than as a zombie.
                task.started_at = None
                task.completed_at = None
                task.result = None
                task.error = None
                task.execution_time = 0.0

            if task.scheduled_at is not None and task.scheduled_at > now:
                task.status = TaskStatus.SCHEDULED
            else:
                task.status = TaskStatus.PENDING
                self.task_queue.append(task)
                self.task_queue.sort(key=lambda t: (
                    self._get_priority_value(t.priority),
                    t.scheduled_at or now,
                ))
            task.metadata["recovered_state"] = "resumed"
            self._persist_recovery(task)
            resumed += 1
            logger.info("Recovered task resumed: %s (%s)", task.name, task.task_id)

        logger.info(
            "Loaded %d persistent task(s): resumed=%d quarantined=%d failed=%d",
            len(tasks_data), resumed, quarantined, failed,
        )

        interrupted = self._load_interrupted_tasks()
        for data in interrupted:
            task_id = data.get("id", "unknown")
            handler_name = data.get("handler")
            if task_id in self.tasks:
                continue
            try:
                task = self._rehydrate_task(data, handler_name)
            except Exception as e:
                logger.warning("Failed to load interrupted task %s: %s", task_id, e)
                continue

            task.metadata["recovered_at"] = recovered_at

            if (self.handler_registry is None
                    or self.handler_registry.resolve_callable(handler_name) is None):
                await self._fail_unregistered(task, handler_name, recovered_at)
                failed += 1
                continue

            self.tasks[task.task_id] = task
            # Interrupted == the previous process died with the handler running.
            # Only a handler that provably cannot have side effects may resume
            # on its own; anything else waits for an explicit operator requeue.
            if self.handler_registry.is_read_only(handler_name):
                task.status = TaskStatus.PENDING
                task.started_at = None
                task.completed_at = None
                task.result = None
                task.error = None
                task.execution_time = 0.0
                task.metadata["recovered_state"] = "resumed"
                self.task_queue.append(task)
                self.task_queue.sort(key=lambda t: (
                    self._get_priority_value(t.priority),
                    t.scheduled_at or now,
                ))
                self._persist_recovery(task)
                resumed += 1
                logger.info(
                    "Interrupted read-only task resumed: %s (%s)", task.name, task.task_id
                )
                continue

            task.status = TaskStatus.WAITING
            task.metadata["interrupted"] = True
            task.metadata["recovered_state"] = "interrupted"
            self._quarantined.add(task.task_id)
            self._persist_recovery(task)
            quarantined += 1
            logger.warning(
                "Task %s (%s) was interrupted mid-execution by the previous "
                "process: quarantined until requeued (never auto-run, so it "
                "cannot execute twice)", task.name, task.task_id,
            )

        if interrupted:
            logger.info(
                "Recovered %d interrupted task(s) (status '%s' in the DB)",
                len(interrupted), _INTERRUPTED_DB_STATUS,
            )

    def _load_interrupted_tasks(self) -> list[dict[str, Any]]:
        """Load custom rows still marked ``running`` in the database.

        ``load_scheduled_tasks`` deliberately excludes ``running`` (those rows
        are not runnable work), so an interrupted task would otherwise be
        invisible after a restart and stay ``running`` forever. This is the only
        place that looks at them, and it never enqueues one automatically.
        """
        try:
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT * FROM scheduled_tasks WHERE source = ? AND status = ? "
                    "ORDER BY created_at ASC",
                    ("custom", _INTERRUPTED_DB_STATUS),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("Failed to load interrupted tasks: %s", e)
            return []

    def _persist_recovery(self, task: Task) -> None:
        """Persist a task's recovered status, retry_count and metadata."""
        try:
            update_scheduled_task_status(
                task.task_id,
                task.status.value,
                retry_count=task.retry_count,
                error=task.error,
                metadata_json=json.dumps(task.metadata),
            )
        except Exception as e:
            logger.warning("Failed to persist recovery for task %s: %s", task.task_id, e)

    async def _fail_unregistered(
        self, task: Task, handler_name: str | None, recovered_at: str
    ) -> None:
        """Mark a recovered task FAILED because its handler is missing here."""
        label = handler_name or "<none>"
        task.status = TaskStatus.FAILED
        task.error = f"handler '{label}' not registered in this build"
        task.auto_retry = False
        task.completed_at = datetime.now()
        task.updated_at = datetime.now()
        task.metadata["recovered_at"] = recovered_at
        task.metadata["recovered_state"] = "unregistered_handler"

        self.tasks[task.task_id] = task
        if task not in self.failed_tasks:
            self.failed_tasks.append(task)
        self.stats["total_tasks"] += 1
        self.stats["failed_tasks"] += 1

        try:
            update_scheduled_task_status(
                task.task_id,
                "failed",
                error=task.error,
                completed_at=task.completed_at.isoformat(),
                retry_count=task.retry_count,
            )
        except Exception as e:
            logger.warning("Failed to persist unregistered task %s: %s", task.task_id, e)

        await self._emit_task_event("task_failed", task)
        logger.error(
            "Recovered task %s (%s) failed: %s",
            task.name, task.task_id, task.error,
        )

    async def stop(self) -> None:
        """Stop the task scheduler and cancel all in-flight work."""
        self._running = False

        if self._scheduler_task:
            self._scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler_task
            self._scheduler_task = None

        # Retry backoff sleeps.
        for retry_task in list(self._retry_tasks):
            retry_task.cancel()
        if self._retry_tasks:
            await asyncio.gather(*self._retry_tasks, return_exceptions=True)
        self._retry_tasks.clear()

        # In-flight executions: cancel the wrappers. Their ``_execute_task``
        # finally frees slots without overwriting a terminal state.
        in_flight = list(self.running_tasks.values())
        executing = list(self._running_asyncio.values())
        for task in executing:
            task.cancel()
        if executing:
            await asyncio.gather(*executing, return_exceptions=True)
        self._running_asyncio.clear()
        self.running_tasks.clear()
        self._mark_interrupted(in_flight)
        # ``_quarantined`` is intentionally NOT cleared: a task held here must
        # stay held if this same manager is started again, otherwise a
        # shutdown-then-restart would silently run a task twice.
        self.stats["running_tasks"] = 0

        logger.info("TaskScheduler stopped")

    def _mark_interrupted(self, tasks: list[Task]) -> None:
        """Persist WAITING for tasks cancelled mid-flight by a shutdown.

        A handler cancelled by ``stop()`` may have applied part of its side
        effects, so the row must not stay runnable: it becomes ``waiting``
        (quarantined) and only an explicit :meth:`requeue_task` runs it again.
        """
        for task in tasks:
            # Only a task that was mid-handler is "interrupted". A RETRYING task
            # already has a durable state of its own (its backoff sleep was
            # cancelled above) and recovery re-evaluates it, so leave it alone.
            if task.status != TaskStatus.RUNNING:
                continue
            task.status = TaskStatus.WAITING
            task.completed_at = None
            task.updated_at = datetime.now()
            task.metadata["interrupted_at"] = task.updated_at.isoformat()
            task.metadata["recovered_state"] = "interrupted"
            self._quarantined.add(task.task_id)
            try:
                update_scheduled_task_status(
                    task.task_id,
                    TaskStatus.WAITING.value,
                    metadata_json=json.dumps(task.metadata),
                )
            except Exception as e:
                logger.warning(
                    "Failed to persist interrupted task %s: %s", task.task_id, e
                )
            logger.warning(
                "Task %s (%s) interrupted by shutdown: quarantined until requeued",
                task.name, task.task_id,
            )

    async def schedule_task(self, task: Task) -> str:
        """Schedule a new autonomous task."""
        if not task.name:
            raise ValueError("Task name is required")

        if not task.handler:
            if task.handler_name and self.handler_registry is not None:
                task.handler = self.handler_registry.resolve_callable(task.handler_name)
            if not task.handler and not task.handler_name:
                raise ValueError("Task handler is required")

        self.tasks[task.task_id] = task
        self.stats["total_tasks"] += 1
        self.stats["scheduled_tasks"] += 1

        now = datetime.now()
        task.updated_at = now
        if task.scheduled_at is not None and task.scheduled_at > now:
            # Future task: wait as SCHEDULED; do not enqueue until it is due.
            task.status = TaskStatus.SCHEDULED
        else:
            task.status = TaskStatus.PENDING
            self.task_queue.append(task)

        # Sort queue by priority then due time.
        self.task_queue.sort(key=lambda t: (
            self._get_priority_value(t.priority),
            t.scheduled_at or now,
        ))

        await self._emit_task_event("task_scheduled", task)
        logger.info(f"Task scheduled: {task.name} ({task.task_id})")

        try:
            save_scheduled_task(task.to_dict())
        except Exception as e:
            logger.warning("Failed to persist task %s: %s", task.task_id, e)

        return task.task_id

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task, cancelling its asyncio execution if still running."""
        if task_id not in self.tasks:
            return False

        task = self.tasks[task_id]

        if task.status in (TaskStatus.RUNNING, TaskStatus.RETRYING):
            async_task = self._running_asyncio.get(task_id)
            if async_task is not None and not async_task.done():
                async_task.cancel()
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]
                self.stats["running_tasks"] = max(0, self.stats["running_tasks"] - 1)
            self._running_asyncio.pop(task_id, None)

        # Never resurrect an already-terminal task.
        if task.status in _TERMINAL_STATUSES:
            if task in self.task_queue:
                self.task_queue.remove(task)
            return True

        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.now()
        task.updated_at = datetime.now()

        if task in self.task_queue:
            self.task_queue.remove(task)
        self._quarantined.discard(task_id)

        if task not in self.completed_tasks:
            self.completed_tasks.append(task)

        await self._emit_task_event("task_cancelled", task)
        logger.info(f"Task cancelled: {task.name} ({task_id})")

        try:
            delete_scheduled_task(task_id)
        except Exception as e:
            logger.warning("Failed to delete task %s from DB: %s", task_id, e)

        return True

    async def requeue_task(self, task_id: str) -> str:
        """Re-arm a quarantined/dormant/failed task for execution.

        Returns one of ``requeued``, ``not_found``, ``running`` or
        ``unregistered`` so the caller can map it to an HTTP status.
        """
        task = self.tasks.get(task_id)
        if task is None:
            return "not_found"
        if task.status == TaskStatus.RUNNING:
            return "running"

        handler_name = task.handler_name
        if self.handler_registry is None or self.handler_registry.resolve_callable(handler_name) is None:
            task.status = TaskStatus.FAILED
            task.error = f"handler '{handler_name or '<none>'}' not registered in this build"
            task.auto_retry = False
            task.completed_at = datetime.now()
            task.updated_at = datetime.now()
            if task not in self.failed_tasks:
                self.failed_tasks.append(task)
            self._quarantined.discard(task_id)
            try:
                update_scheduled_task_status(
                    task_id,
                    "failed",
                    error=task.error,
                    completed_at=task.completed_at.isoformat(),
                )
            except Exception as e:
                logger.warning("Failed to persist requeue-failure %s: %s", task_id, e)
            await self._emit_task_event("task_failed", task)
            return "unregistered"

        if not task.handler:
            task.handler = self.handler_registry.resolve_callable(handler_name)

        task.error = None
        task.result = None
        task.started_at = None
        task.completed_at = None
        task.execution_time = 0.0
        task.updated_at = datetime.now()
        task.metadata.pop("quarantined", None)
        task.metadata.pop("interrupted", None)
        task.metadata["recovered_state"] = "requeued"
        task.metadata["requeued_at"] = datetime.now().isoformat()
        self._quarantined.discard(task_id)
        if task in self.completed_tasks:
            self.completed_tasks.remove(task)
        if task in self.failed_tasks:
            self.failed_tasks.remove(task)

        now = datetime.now()
        if task.scheduled_at is not None and task.scheduled_at > now:
            task.status = TaskStatus.SCHEDULED
        else:
            task.status = TaskStatus.PENDING
            if task not in self.task_queue:
                self.task_queue.append(task)
            self.task_queue.sort(key=lambda t: (
                self._get_priority_value(t.priority),
                t.scheduled_at or now,
            ))

        try:
            save_scheduled_task(task.to_dict())
        except Exception as e:
            logger.warning("Failed to persist requeued task %s: %s", task_id, e)

        await self._emit_task_event("task_scheduled", task)
        logger.info(f"Task requeued: {task.name} ({task_id})")
        return "requeued"

    async def get_task(self, task_id: str) -> Task | None:
        """Get task by ID."""
        return self.tasks.get(task_id)

    async def get_tasks(self, status: TaskStatus | str | None = None,
                     task_type: TaskType | str | None = None,
                     limit: int = 100) -> list[Task]:
        """Get tasks with optional filtering.

        ``status``/``task_type`` accept either an enum member or its string
        value. An unrecognised string is *not* an error: it yields ``[]``.
        """
        tasks = list(self.tasks.values())

        if status is not None:
            status_enum = self._coerce_status(status)
            if status_enum is None:
                return []
            tasks = [t for t in tasks if t.status == status_enum]

        if task_type is not None:
            type_enum = self._coerce_type(task_type)
            if type_enum is None:
                return []
            tasks = [t for t in tasks if t.task_type == type_enum]

        tasks.sort(key=lambda t: t.updated_at, reverse=True)
        return tasks[:limit]

    @classmethod
    def _coerce_status(cls, status: TaskStatus | str) -> TaskStatus | None:
        if isinstance(status, TaskStatus):
            return status
        if isinstance(status, str):
            try:
                return TaskStatus(status.strip().lower())
            except ValueError:
                return None
        return None

    @classmethod
    def _coerce_type(cls, task_type: TaskType | str) -> TaskType | None:
        if isinstance(task_type, TaskType):
            return task_type
        if isinstance(task_type, str):
            try:
                return TaskType(task_type.strip().lower())
            except ValueError:
                return None
        return None

    async def get_stats(self) -> dict[str, Any]:
        """Get scheduler statistics."""
        if self.stats["completed_tasks"] > 0:
            total_time = sum(t.execution_time for t in self.completed_tasks)
            self.stats["average_execution_time"] = total_time / self.stats["completed_tasks"]

        return {
            "running": self._running,
            "max_concurrent": self._max_concurrent,
            "queue_size": len(self.task_queue),
            "quarantined_count": len(self._quarantined),
            **self.stats,
            "task_types": {
                task_type.value: len([t for t in self.tasks.values() if t.task_type == task_type])
                for task_type in TaskType
            },
            "task_priorities": {
                priority.value: len([t for t in self.tasks.values() if t.priority == priority])
                for priority in TaskPriority
            }
        }

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                await self._process_pending_tasks()
                await self._process_scheduled_tasks()
                await self._cleanup_completed_tasks()

                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(5)

    async def _process_pending_tasks(self) -> None:
        """Process pending tasks in the queue."""
        while (self.task_queue and
               len(self.running_tasks) < self._max_concurrent and
               self._running):

            task = self.task_queue.pop(0)

            if task.task_id in self._quarantined:
                # Safety net: a quarantined task never enters execution.
                task.status = TaskStatus.WAITING
                continue

            if not await self._check_dependencies(task):
                self.task_queue.append(task)
                break

            async_task = asyncio.create_task(self._execute_task(task))
            self._running_asyncio[task.task_id] = async_task

    async def _process_scheduled_tasks(self) -> None:
        """Promote SCHEDULED tasks whose due time has arrived to PENDING."""
        current_time = datetime.now()

        for task in self.tasks.values():
            if task.task_id in self._quarantined:
                continue
            if (task.status == TaskStatus.SCHEDULED and
                task.scheduled_at and
                task.scheduled_at <= current_time and
                task not in self.task_queue):

                task.status = TaskStatus.PENDING
                task.updated_at = current_time
                self.task_queue.append(task)
                self.task_queue.sort(key=lambda t: (
                    self._get_priority_value(t.priority),
                    t.scheduled_at or current_time,
                ))

    async def _execute_task(self, task: Task) -> None:
        """Execute a task, owning its running-slot lifetime."""
        # Reset the circuit breaker so a failure streak in a prior task
        # does not lock tools for this task execution.
        session_id = task.parameters.get("session_id")
        with contextlib.suppress(Exception):
            from backend.tools.registry import reset_tool_failures

            reset_tool_failures(session_id)

        # Durable claim: the persisted row flips to 'running' *before* the
        # handler is invoked. That single conditional UPDATE is what makes
        # execution exactly-once -- it tells a restart (and any other worker
        # sharing this database) that this task already started.
        if not await self._claim_execution(task):
            self._defer_claimed_elsewhere(task)
            return

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        task.updated_at = task.started_at
        self.running_tasks[task.task_id] = task
        self.stats["running_tasks"] += 1
        self._running_asyncio[task.task_id] = asyncio.current_task()

        await self._emit_task_event("task_started", task)

        start_time = time.time()

        try:
            try:
                result = await self._invoke_handler(task)
            except asyncio.CancelledError:
                # External cancellation (cancel_task) or shutdown. A terminal
                # state such as CANCELLED is authoritative; never overwrite it.
                logger.info(
                    "Task execution cancelled: %s (%s)", task.name, task.task_id
                )
                raise
            except TimeoutError:
                await self._finalize_failure(
                    task, "Task execution timeout", start_time, timeout=True
                )
            except Exception as e:
                await self._finalize_failure(task, str(e), start_time)
            else:
                await self._finalize_success(task, result, start_time)
        finally:
            # Free the running slot exactly once, even on cancellation.
            self._running_asyncio.pop(task.task_id, None)
            if task.task_id in self.running_tasks:
                del self.running_tasks[task.task_id]
                self.stats["running_tasks"] = max(0, self.stats["running_tasks"] - 1)

    async def _claim_execution(self, task: Task) -> bool:
        """Claim the persisted row so the task runs at most once.

        The conditional UPDATE is atomic, so two schedulers loading the same
        database cannot both win: the loser keeps status ``running`` (or a
        terminal status) and skips execution.

        Returns ``True`` when this worker owns the run. ``False`` means another
        worker already started this task, or it already finished. A task that
        is not persisted at all (in-memory only) has nothing to claim and is
        allowed through, as is a database failure: availability over a strict
        guarantee the queue already made.
        """
        placeholders = ", ".join("?" for _ in _CLAIMABLE_DB_STATUSES)
        statement = (
            "UPDATE scheduled_tasks SET status = 'running', started_at = ?, "
            f"updated_at = ? WHERE id = ? AND status IN ({placeholders})"
        )
        try:
            with get_db() as conn:
                now = datetime.now().isoformat()
                cursor = conn.execute(
                    statement,
                    (now, now, task.task_id, *_CLAIMABLE_DB_STATUSES),
                )
                if cursor.rowcount == 1:
                    return True
                persisted = conn.execute(
                    "SELECT 1 FROM scheduled_tasks WHERE id = ?", (task.task_id,)
                ).fetchone()
                # No row -> never persisted -> nothing to claim.
                return persisted is None
        except Exception as e:
            logger.warning("Failed to claim task %s for execution: %s", task.task_id, e)
            return True

    def _defer_claimed_elsewhere(self, task: Task) -> None:
        """Park a task another worker owns so it is not re-queued forever."""
        task.status = TaskStatus.WAITING
        task.updated_at = datetime.now()
        task.metadata["claimed_elsewhere"] = task.updated_at.isoformat()
        self._quarantined.add(task.task_id)
        self.task_queue = [t for t in self.task_queue if t is not task]
        # Drop our own execution wrapper: it is about to return.
        self._running_asyncio.pop(task.task_id, None)
        logger.warning(
            "Task %s (%s) not executed: its persisted row is already running "
            "elsewhere or finished (duplicate-run guard)", task.name, task.task_id,
        )

    async def _invoke_handler(self, task: Task) -> Any:
        """Invoke the task's handler (live callable, timeout-guarded)."""
        handler = task.handler
        if handler is None and self.handler_registry is not None:
            handler = self.handler_registry.resolve_callable(task.handler_name)
            if handler is not None:
                task.handler = handler
        if handler is None:
            raise RuntimeError(
                f"handler '{task.handler_name or '<none>'}' not available at execution"
            )

        if task.timeout:
            return await asyncio.wait_for(handler(**task.parameters), timeout=task.timeout)
        return await handler(**task.parameters)

    async def _finalize_success(self, task: Task, result: Any, start_time: float) -> None:
        task.result = result
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        task.execution_time = time.time() - start_time
        task.updated_at = datetime.now()

        self.stats["completed_tasks"] += 1
        self.completed_tasks.append(task)

        await self._emit_task_event("task_completed", task)
        logger.info(
            f"Task completed: {task.name} ({task.task_id}) in {task.execution_time:.2f}s"
        )

        try:
            update_scheduled_task_status(
                task.task_id,
                "completed",
                completed_at=task.completed_at.isoformat() if task.completed_at else None,
                execution_time=task.execution_time,
                retry_count=task.retry_count,
            )
        except Exception as e:
            logger.warning("Failed to update task %s in DB: %s", task.task_id, e)

        if task.interval and task.status == TaskStatus.COMPLETED:
            await self._schedule_recurring_task(task)

    async def _finalize_failure(
        self, task: Task, error: str, start_time: float, *, timeout: bool = False
    ) -> None:
        task.status = TaskStatus.FAILED
        task.error = error
        task.completed_at = datetime.now()
        task.execution_time = time.time() - start_time
        task.updated_at = datetime.now()

        self.stats["failed_tasks"] += 1
        self.failed_tasks.append(task)

        await self._emit_task_event("task_timeout" if timeout else "task_failed", task)

        try:
            update_scheduled_task_status(
                task.task_id,
                "failed",
                error=task.error,
                completed_at=task.completed_at.isoformat() if task.completed_at else None,
                retry_count=task.retry_count,
            )
        except Exception as e:
            logger.warning("Failed to update task %s in DB: %s", task.task_id, e)

        if timeout:
            logger.error(f"Task timed out: {task.name} ({task.task_id})")
        else:
            logger.error(f"Task failed: {task.name} ({task.task_id}): {error}")

        # Schedule a retry *after* returning, so the running slot is freed
        # before the (possibly 300s) backoff. The backoff runs in a detached
        # task rather than blocking this coroutine.
        if task.auto_retry and task.retry_count < task.max_retries:
            self._start_retry(task)
        elif task.retry_count >= task.max_retries:
            logger.error(
                "Task failed permanently after %d attempt(s): %s (%s)",
                task.retry_count, task.name, task.task_id,
            )

    def _start_retry(self, task: Task) -> None:
        """Arm an exponential-backoff retry without holding the running slot."""
        task.retry_count += 1
        task.status = TaskStatus.RETRYING
        task.updated_at = datetime.now()
        backoff = min(300, 60 * (2 ** task.retry_count))  # 120, 240, 300, ...
        task.metadata["_retry_backoff_seconds"] = backoff

        if task in self.failed_tasks:
            self.failed_tasks.remove(task)

        try:
            update_scheduled_task_status(
                task.task_id, "retrying", retry_count=task.retry_count
            )
        except Exception as e:
            logger.warning("Failed to persist retry state %s: %s", task.task_id, e)

        retry_task = asyncio.create_task(self._retry_after_backoff(task, backoff))
        self._retry_tasks.append(retry_task)

    async def _retry_after_backoff(self, task: Task, backoff: int) -> None:
        """Sleep the backoff *outside* the running slot, then re-enqueue."""
        try:
            await asyncio.sleep(backoff)
        except asyncio.CancelledError:
            return

        task.status = TaskStatus.PENDING
        task.started_at = None
        task.completed_at = None
        task.result = None
        task.error = None
        task.execution_time = 0.0
        task.updated_at = datetime.now()

        if task not in self.task_queue:
            self.task_queue.append(task)
            self.task_queue.sort(key=lambda t: (
                self._get_priority_value(t.priority),
                t.scheduled_at or datetime.now(),
            ))

        await self._emit_task_event("task_retry", task)
        logger.info(
            f"Task retry scheduled: {task.name} ({task.task_id}) "
            f"- attempt {task.retry_count} after {backoff}s backoff"
        )

    async def _check_dependencies(self, task: Task) -> bool:
        """Check if task dependencies are satisfied."""
        for dep_id in task.dependencies:
            dep_task = self.tasks.get(dep_id)
            if not dep_task:
                logger.error(f"Dependency not found: {dep_id}")
                return False

            if dep_task.status not in [TaskStatus.COMPLETED]:
                logger.info(f"Dependency not ready: {dep_id} (status: {dep_task.status.value})")
                return False

        return True

    async def _schedule_recurring_task(self, task: Task) -> None:
        """Schedule the next run of a recurring task, respecting its interval."""
        if not task.interval:
            return

        next_time = datetime.now() + timedelta(seconds=task.interval)

        new_task = Task(
            name=task.name,
            task_type=task.task_type,
            priority=task.priority,
            handler=task.handler,
            handler_name=task.handler_name,
            parameters=task.parameters,
            dependencies=set(task.dependencies),
            max_retries=task.max_retries,
            timeout=task.timeout,
            interval=task.interval,
            auto_retry=task.auto_retry,
            metadata=dict(task.metadata),
            source=task.source,
        )

        new_task.scheduled_at = next_time
        await self.schedule_task(new_task)

        logger.info(
            f"Recurring task scheduled: {task.name} ({task.task_id}) at {next_time}"
        )

    async def _cleanup_completed_tasks(self) -> None:
        """Clean up old completed tasks."""
        cutoff_time = datetime.now() - timedelta(hours=24)

        old_tasks = [t for t in self.completed_tasks if t.completed_at and t.completed_at < cutoff_time]
        for task in old_tasks:
            self._quarantined.discard(task.task_id)
            self.tasks.pop(task.task_id, None)

        self.completed_tasks = [t for t in self.completed_tasks if t not in old_tasks]

        old_tasks = [t for t in self.failed_tasks if t.completed_at and t.completed_at < cutoff_time]
        for task in old_tasks:
            self._quarantined.discard(task.task_id)
            self.tasks.pop(task.task_id, None)

        self.failed_tasks = [t for t in self.failed_tasks if t not in old_tasks]

        if old_tasks:
            logger.info(f"Cleaned up {len(old_tasks)} old tasks")

    def _get_priority_value(self, priority: TaskPriority) -> int:
        """Get numeric value for priority."""
        priority_values = {
            TaskPriority.LOW: 1,
            TaskPriority.NORMAL: 2,
            TaskPriority.HIGH: 3,
            TaskPriority.CRITICAL: 4,
            TaskPriority.URGENT: 5
        }
        return priority_values.get(priority, 2)

    async def _emit_task_event(self, event_type: str, task: Task) -> None:
        """Emit a task-related event with the correct canonical EventType."""
        if not self.event_bus:
            return

        try:
            resolved = self._EVENT_TYPE_BY_KEY.get(event_type, EventType.SYSTEM_INFO)
            priority = EventPriority.HIGH if resolved == EventType.TASK_FAILED else EventPriority.NORMAL
            event = Event(
                event_type=resolved,
                source="task_scheduler",
                priority=priority,
                payload={
                    "event_type": event_type,
                    "task": task.to_dict()
                },
                metadata={
                    "component": "task_scheduler",
                    "timestamp": datetime.now().isoformat()
                }
            )
            await self.event_bus.publish(event)
        except Exception as e:
            logger.error(f"Failed to emit task event {event_type}: {e}")


class AutonomousTaskManager:
    """Manages autonomous task execution and self-improvement."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

        # The registry is the authority for handler names -> live callables.
        self.handlers = HandlerRegistry()
        self.handlers.register("health_monitoring", self._health_monitoring_handler, read_only=True)
        self.handlers.register("system_cleanup", self._system_cleanup_handler, read_only=False)

        self.scheduler = TaskScheduler(event_bus, handler_registry=self.handlers)
        self._running = False

    @property
    def task_handlers(self) -> dict[str, Callable]:
        """Backwards-compatible view of the registered handlers."""
        return self.handlers.callables()

    async def start(self, resume_pending: bool | None = None) -> None:
        """Start the autonomous task manager.

        Args:
            resume_pending: Tri-state. ``None`` reads
                ``NEXUS_TASKS_RESUME_PENDING`` (default ``False``); an explicit
                bool overrides it.
        """
        if self._running:
            return

        if resume_pending is None:
            resume_pending = _env_flag("NEXUS_TASKS_RESUME_PENDING", default=False)
        self._running = True

        await self.scheduler.start(resume_pending=resume_pending)
        await self._schedule_builtin_tasks()

        logger.info("AutonomousTaskManager started (resume_pending=%s)", resume_pending)

    async def stop(self) -> None:
        """Stop the autonomous task manager."""
        self._running = False
        await self.scheduler.stop()
        logger.info("AutonomousTaskManager stopped")

    async def _schedule_builtin_tasks(self) -> None:
        """Schedule the built-in autonomous tasks that have real implementations.

        Only read-only/verified handlers are scheduled. Handlers that remain
        simulated (performance_tuning/auto_optimization/error_recovery/
        learning_update) are intentionally *not* scheduled and are not
        registered, so any reference to them fails explicitly on recovery.
        """
        now = datetime.now()

        # Health monitoring (read-only; safe to run immediately at boot).
        await self.scheduler.schedule_task(Task(
            name="System Health Monitoring",
            task_type=TaskType.HEALTH_CHECK,
            priority=TaskPriority.HIGH,
            handler=self.task_handlers["health_monitoring"],
            handler_name="health_monitoring",
            interval=60,  # Every minute
            parameters={"detailed": False},
            source="builtin",
        ))

        # System cleanup (writes: prunes structured logs). Its first run is
        # scheduled one interval out, never at boot.
        await self.scheduler.schedule_task(Task(
            name="System Cleanup",
            task_type=TaskType.MAINTENANCE,
            priority=TaskPriority.LOW,
            handler=self.task_handlers["system_cleanup"],
            handler_name="system_cleanup",
            interval=3600,  # Every hour
            scheduled_at=now + timedelta(seconds=3600),
            parameters={"deep_clean": False},
            source="builtin",
        ))

        logger.info("Built-in autonomous tasks scheduled")

    async def create_custom_task(self, name: str, task_type: TaskType,
                           handler: Callable | None = None,
                           handler_name: str | None = None,
                           parameters: dict[str, Any] | None = None,
                           priority: TaskPriority = TaskPriority.NORMAL,
                           interval: int | None = None,
                           max_retries: int = 3,
                           timeout: int = 300,
                           auto_retry: bool = True,
                           scheduled_at: datetime | None = None) -> str:
        """Create and schedule a custom autonomous task.

        Resolves the handler by ``handler_name`` from the registry (preferred,
        so the task survives a restart) or falls back to a live ``handler``.
        """
        resolved_name = handler_name
        resolved_handler: Callable | None = None
        if resolved_name is not None:
            entry = self.handlers.resolve(resolved_name)
            if entry is None:
                raise ValueError(f"handler '{resolved_name}' not registered in this build")
            resolved_handler = entry.call
        elif handler is not None:
            resolved_handler = handler
            resolved_name = getattr(handler, "__name__", None)
        else:
            raise ValueError("handler or handler_name is required")

        task = Task(
            name=name,
            task_type=task_type,
            priority=priority,
            handler=resolved_handler,
            handler_name=resolved_name,
            parameters=parameters or {},
            max_retries=max_retries,
            timeout=timeout,
            interval=interval,
            auto_retry=auto_retry,
            scheduled_at=scheduled_at,
        )

        return await self.scheduler.schedule_task(task)

    # -- Task access delegation ------------------------------------------
    async def get_tasks(self, status: TaskStatus | str | None = None,
                     task_type: TaskType | str | None = None,
                     limit: int = 100) -> list[Task]:
        return await self.scheduler.get_tasks(status=status, task_type=task_type, limit=limit)

    async def get_task(self, task_id: str) -> Task | None:
        return await self.scheduler.get_task(task_id)

    async def cancel_task(self, task_id: str) -> bool:
        return await self.scheduler.cancel_task(task_id)

    async def requeue_task(self, task_id: str) -> str:
        return await self.scheduler.requeue_task(task_id)

    # -- Built-in handlers ------------------------------------------------
    async def _health_monitoring_handler(self, **kwargs) -> dict[str, Any]:
        """Read-only health check backed by real system metrics (psutil)."""
        detailed = bool(kwargs.get("detailed", False))
        metrics = await asyncio.to_thread(self._collect_system_metrics)

        overall = "healthy"
        thresholds_hit: list[str] = []
        if metrics["memory_percent"] >= 90:
            overall = "degraded"
            thresholds_hit.append("memory>=90%")
        if metrics["disk_percent"] >= 90:
            overall = "degraded"
            thresholds_hit.append("disk>=90%")
        if (metrics.get("cpu_percent") or 0.0) >= 95:
            overall = "degraded"
            thresholds_hit.append("cpu>=95%")

        result: dict[str, Any] = {
            "overall": overall,
            "read_only": True,
            "metrics": metrics,
            "components": {
                "event_bus": "healthy" if self.event_bus else "unavailable",
                "task_scheduler": "healthy" if self.scheduler._running else "stopped",
            },
            "timestamp": datetime.now().isoformat(),
        }
        if thresholds_hit:
            result["thresholds_hit"] = thresholds_hit

        if detailed:
            result["detailed_checks"] = {
                "queued_tasks": len(self.scheduler.task_queue),
                "running_tasks": len(self.scheduler.running_tasks),
                "known_tasks": len(self.scheduler.tasks),
            }

        return result

    @staticmethod
    def _collect_system_metrics() -> dict[str, Any]:
        """Collect system metrics synchronously (run via ``asyncio.to_thread``)."""
        import psutil

        cpu = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        try:
            uptime = time.time() - psutil.boot_time()
        except Exception:
            uptime = None

        return {
            "cpu_percent": round(float(cpu), 2),
            "memory_percent": round(float(vm.percent), 2),
            "memory_available_bytes": int(vm.available),
            "disk_percent": round(float(disk.percent), 2),
            "disk_free_bytes": int(disk.free),
            "uptime_seconds": round(uptime, 2) if uptime is not None else None,
        }

    async def _system_cleanup_handler(self, **kwargs) -> dict[str, Any]:
        """Real cleanup: prune structured logs older than the retention window."""
        deep_clean = bool(kwargs.get("deep_clean", False))
        retention_days = 7 if deep_clean else 30

        from backend.observability.log_store import get_log_store

        logs_pruned = await get_log_store().prune_old_logs(days=retention_days)

        return {
            "cleanup_completed": True,
            "operation": "prune_old_logs",
            "logs_pruned": logs_pruned,
            "retention_days": retention_days,
            "deep_clean": deep_clean,
            "cleanup_time": datetime.now().isoformat(),
        }

    async def get_task_manager_stats(self) -> dict[str, Any]:
        """Get task manager statistics."""
        scheduler_stats = await self.scheduler.get_stats()
        available = set(self.task_handlers)

        return {
            "task_manager": {
                "running": self._running,
                "builtin_handlers": len(self.handlers.primary_names()),
                "available_handlers": self.handlers.names(),
                "custom_tasks": len([
                    t for t in self.scheduler.tasks.values()
                    if t.handler_name not in available
                ]),
                "quarantined_tasks": len(self.scheduler._quarantined),
            },
            **scheduler_stats
        }


# Global task manager instance
_task_manager: AutonomousTaskManager | None = None


async def get_autonomous_task_manager(event_bus: EventBus) -> AutonomousTaskManager:
    """Get the global autonomous task manager instance."""
    global _task_manager
    if _task_manager is None:
        _task_manager = AutonomousTaskManager(event_bus)
    return _task_manager


async def shutdown_autonomous_task_manager() -> None:
    """Shutdown the autonomous task manager."""
    global _task_manager
    if _task_manager:
        await _task_manager.stop()
        _task_manager = None
