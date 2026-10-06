"""AutonomousExecutionEngine — executes tasks with retry, monitoring, and self-healing."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


@dataclass
class ExecutionTask:
    """A task to be executed autonomously."""

    task_id: str
    name: str
    handler: Callable[..., Any] = field(repr=False)
    args: tuple = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    retry_count: int = 0
    max_retries: int = 3
    result: Any = None
    error: str | None = None
    timeout_seconds: float = 300.0


class AutonomousExecutionEngine:
    """Executes tasks autonomously with retry, monitoring, and self-healing.

    Features:
    - Automatic retry with exponential backoff
    - Timeout handling
    - Failure tracking and alerting
    - Concurrent task execution
    """

    def __init__(self, max_concurrent: int = 5) -> None:
        self._tasks: dict[str, ExecutionTask] = {}
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running: bool = False

    def submit_task(
        self,
        name: str,
        handler: Callable[..., Any],
        *args: Any,
        max_retries: int = 3,
        timeout_seconds: float = 300.0,
        **kwargs: Any,
    ) -> ExecutionTask:
        task = ExecutionTask(
            task_id=f"task-{uuid.uuid4().hex[:8]}",
            name=name,
            handler=handler,
            args=args,
            kwargs=kwargs,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
        )
        self._tasks[task.task_id] = task
        logger.info("Task submitted: %s (%s)", name, task.task_id)
        return task

    async def execute_task(self, task_id: str) -> ExecutionTask:
        """Execute a single task with retry logic."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        async with self._semaphore:
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()

            while task.retry_count <= task.max_retries:
                try:
                    # Execute with timeout
                    result = await asyncio.wait_for(
                        self._run_handler(task),
                        timeout=task.timeout_seconds,
                    )
                    task.result = result
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = time.time()
                    logger.info("Task completed: %s", task.task_id)
                    return task

                except TimeoutError:
                    task.error = f"Timeout after {task.timeout_seconds}s"
                    logger.warning("Task timed out: %s", task.task_id)
                    task.retry_count += 1
                    if task.retry_count <= task.max_retries:
                        wait = 2 ** task.retry_count
                        logger.info("Retrying %s in %ds (attempt %d/%d)",
                                    task.task_id, wait, task.retry_count, task.max_retries)
                        await asyncio.sleep(wait)
                        task.status = TaskStatus.RETRYING
                    else:
                        task.status = TaskStatus.FAILED
                        return task

                except Exception as e:
                    task.error = str(e)
                    logger.error("Task failed: %s — %s", task.task_id, e)
                    task.retry_count += 1
                    if task.retry_count <= task.max_retries:
                        wait = 2 ** task.retry_count
                        logger.info("Retrying %s in %ds (attempt %d/%d)",
                                    task.task_id, wait, task.retry_count, task.max_retries)
                        await asyncio.sleep(wait)
                        task.status = TaskStatus.RETRYING
                    else:
                        task.status = TaskStatus.FAILED
                        return task

            task.status = TaskStatus.FAILED
            return task

    async def _run_handler(self, task: ExecutionTask) -> Any:
        """Run the task handler."""
        if asyncio.iscoroutinefunction(task.handler):
            return await task.handler(*task.args, **task.kwargs)
        else:
            # Run sync function in thread pool
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: task.handler(*task.args, **task.kwargs))

    async def execute_all(self) -> list[ExecutionTask]:
        """Execute all pending tasks concurrently."""
        pending = [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]
        if not pending:
            return []
        results = await asyncio.gather(
            *[self.execute_task(t.task_id) for t in pending],
            return_exceptions=True,
        )
        return [r if isinstance(r, ExecutionTask) else None for r in results]  # type: ignore

    def get_task(self, task_id: str) -> ExecutionTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self, status: TaskStatus | None = None) -> list[ExecutionTask]:
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    def cancel_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.RETRYING):
            task.status = TaskStatus.CANCELLED
            return True
        return False

    def stats(self) -> dict[str, Any]:
        by_status = {s.value: 0 for s in TaskStatus}
        for t in self._tasks.values():
            by_status[t.status.value] += 1
        total = len(self._tasks)
        completed = by_status[TaskStatus.COMPLETED.value]
        failed = by_status[TaskStatus.FAILED.value]
        success_rate = completed / total if total > 0 else 0.0
        return {
            "total": total,
            "by_status": by_status,
            "success_rate": success_rate,
            "failed": failed,
            "retried": sum(1 for t in self._tasks.values() if t.retry_count > 0),
        }
