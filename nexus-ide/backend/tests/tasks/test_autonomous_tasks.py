"""Unit tests for the autonomous task scheduler (P0.4 correctness pass).

Covers the recovery contract (handler registry rehydration, unregistered-handler
failure, resume/quarantine policy), scheduling/retry/cancel behaviour and event
mapping. Each test runs against the per-test temp DB from the global conftest.
"""
from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from datetime import datetime, timedelta

import pytest

from backend.observability.event_system import EventBus, EventType
from backend.persistence import db as db_module
from backend.persistence.db import (
    load_scheduled_tasks,
    save_scheduled_task,
    update_scheduled_task_status,
)
from backend.tasks.autonomous_tasks import (
    AutonomousTaskManager,
    Task,
    TaskStatus,
    TaskType,
)


async def _wait_until(predicate, *, timeout: float = 4.0, step: float = 0.02) -> bool:
    """Poll *predicate* on the running loop until it passes or *timeout* elapses."""
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        await asyncio.sleep(step)
        waited += step
    return predicate()


def _make_manager() -> AutonomousTaskManager:
    return AutonomousTaskManager(EventBus())


def _db_row(task_id: str) -> tuple | None:
    """Read (status, error) straight from SQLite, bypassing the scheduler."""
    with contextlib.closing(sqlite3.connect(str(db_module.DB_PATH))) as conn:
        return conn.execute(
            "SELECT status, error FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()


def _counter_handler(calls: list[int], gate: asyncio.Event | None = None):
    """A write-effect handler that records every invocation."""

    async def handler(**_kwargs) -> dict[str, bool]:
        calls.append(1)
        if gate is not None:
            await gate.wait()
        return {"ok": True}

    return handler



# ---------------------------------------------------------------------------
# Rehydration / resume policy
# ---------------------------------------------------------------------------


async def test_rehydration_with_registered_handler_executes() -> None:
    """A recovered task whose handler is registered resumes and runs."""
    calls: list[int] = []

    async def probe(**_kwargs) -> dict[str, bool]:
        calls.append(1)
        return {"ok": True}

    writer = _make_manager()
    writer.handlers.register("probe", probe, read_only=False)
    task_id = await writer.create_custom_task(
        name="probe-task",
        task_type=TaskType.MONITORING,
        handler_name="probe",
        parameters={"n": 1},
    )

    # A brand-new instance recovers the persisted task and runs it on resume.
    recovered = _make_manager()
    recovered.handlers.register("probe", probe, read_only=False)
    try:
        await recovered.start(resume_pending=True)
        done = await _wait_until(
            lambda: _task_status(recovered, task_id) == TaskStatus.COMPLETED
        )
        assert done, "recovered task did not execute"
        task = await recovered.get_task(task_id)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.result == {"ok": True}
        assert calls == [1]
    finally:
        await recovered.stop()


async def test_unknown_handler_fails_explicitly_and_is_persisted() -> None:
    """A task whose handler is missing in this build fails loudly, not silently."""
    save_scheduled_task(
        {
            "task_id": "task-ghost",
            "name": "ghost job",
            "task_type": "monitoring",
            "priority": "normal",
            "status": "pending",
            "handler": "ghost_handler",
            "parameters": {},
            "dependencies": [],
            "retry_count": 0,
            "max_retries": 3,
            "timeout": 60,
            "interval": None,
            "auto_retry": True,
            "source": "custom",
        }
    )

    manager = _make_manager()
    try:
        await manager.start(resume_pending=True)
        task = await manager.get_task("task-ghost")
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert task.error is not None and "ghost_handler" in task.error
        assert "not registered in this build" in task.error
        assert task.auto_retry is False
        assert task.task_id not in {t.task_id for t in manager.scheduler.task_queue}
        assert task.task_id not in manager.scheduler.running_tasks
    finally:
        await manager.stop()

    # The FAILED state must be persisted so it is never re-run on a later boot.
    with contextlib.closing(sqlite3.connect(str(db_module.DB_PATH))) as conn:
        row = conn.execute(
            "SELECT status, error FROM scheduled_tasks WHERE id = ?", ("task-ghost",)
        ).fetchone()
    assert row is not None
    assert row[0] == "failed"
    assert row[1] and "ghost_handler" in row[1]


async def test_write_handler_quarantined_without_resume_flag() -> None:
    """Default resume (false) keeps recovered write-effect tasks dormant."""

    async def probe(**_kwargs) -> dict[str, bool]:
        return {"ok": True}

    writer = _make_manager()
    writer.handlers.register("probe", probe, read_only=False)
    task_id = await writer.create_custom_task(
        name="quarantine-me", task_type=TaskType.MONITORING, handler_name="probe"
    )

    recovered = _make_manager()
    recovered.handlers.register("probe", probe, read_only=False)
    try:
        await recovered.start(resume_pending=False)
        await asyncio.sleep(0.1)
        task = await recovered.get_task(task_id)
        assert task is not None
        assert task.status == TaskStatus.WAITING
        assert task.task_id in recovered.scheduler._quarantined
        assert task.task_id not in {t.task_id for t in recovered.scheduler.task_queue}

        # The operator gate approves the task -> it runs.
        result = await recovered.requeue_task(task_id)
        assert result == "requeued"
        done = await _wait_until(
            lambda: _task_status(recovered, task_id) == TaskStatus.COMPLETED
        )
        assert done
    finally:
        await recovered.stop()


async def test_handler_name_roundtrips_through_handler_column() -> None:
    """The persisted handler name survives in the ``handler`` column."""
    manager = _make_manager()
    task_id = await manager.create_custom_task(
        name="roundtrip",
        task_type=TaskType.MAINTENANCE,
        handler_name="system_cleanup",
    )
    rows = [r for r in load_scheduled_tasks(source="custom") if r["id"] == task_id]
    assert rows, "task should be persisted"
    assert rows[0]["handler"] == "system_cleanup"


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


async def test_get_tasks_status_coercion() -> None:
    """status accepts a string, an enum, and returns [] for unknown strings."""
    scheduler = _make_manager().scheduler
    running = Task(name="r", task_type=TaskType.MONITORING, status=TaskStatus.RUNNING)
    completed = Task(
        name="c", task_type=TaskType.MONITORING, status=TaskStatus.COMPLETED
    )
    scheduler.tasks[running.task_id] = running
    scheduler.tasks[completed.task_id] = completed

    by_str = await scheduler.get_tasks(status="running")
    by_enum = await scheduler.get_tasks(status=TaskStatus.RUNNING)
    bogus = await scheduler.get_tasks(status="bogus")

    assert [t.task_id for t in by_str] == [running.task_id]
    assert [t.task_id for t in by_enum] == [running.task_id]
    assert bogus == []


# ---------------------------------------------------------------------------
# Scheduling / retry / cancel
# ---------------------------------------------------------------------------


async def test_future_scheduled_at_is_not_run_immediately() -> None:
    """A task scheduled in the future stays SCHEDULED and is not enqueued."""
    scheduler = _make_manager().scheduler
    ran: list[int] = []

    async def handler(**_kwargs) -> dict[str, bool]:
        ran.append(1)
        return {"ok": True}

    task = Task(
        name="future",
        task_type=TaskType.MONITORING,
        handler=handler,
        handler_name="handler",
        scheduled_at=datetime.now() + timedelta(seconds=300),
    )
    await scheduler.schedule_task(task)

    assert task.status == TaskStatus.SCHEDULED
    assert task not in scheduler.task_queue

    await scheduler._process_scheduled_tasks()
    assert task not in scheduler.task_queue
    assert ran == []


async def test_recurring_task_respects_interval() -> None:
    """A recurring task's next run is scheduled an interval out, not enqueued."""
    scheduler = _make_manager().scheduler

    async def handler(**_kwargs) -> dict[str, bool]:
        return {"ok": True}

    before = datetime.now()
    task = Task(
        name="recurring",
        task_type=TaskType.MONITORING,
        handler=handler,
        handler_name="handler",
        interval=300,
    )
    scheduler.tasks[task.task_id] = task
    await scheduler._execute_task(task)

    follow_ons = [t for t in scheduler.tasks.values() if t is not task]
    assert follow_ons, "a follow-on run should be scheduled"
    next_run = max(follow_ons, key=lambda t: t.created_at)
    assert next_run.status == TaskStatus.SCHEDULED
    assert next_run.scheduled_at is not None
    assert next_run.scheduled_at >= before + timedelta(seconds=290)
    assert next_run not in scheduler.task_queue


async def test_retry_backoff_sequence_releases_slot(monkeypatch) -> None:
    """Backoff is 120/240/300 and the running slot is freed before each sleep."""
    recorded: list[int] = []

    async def fake_sleep(delay: float, *_args, **_kwargs) -> None:
        recorded.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    scheduler = _make_manager().scheduler

    async def boom(**_kwargs) -> None:
        raise RuntimeError("boom")

    task = Task(
        name="boom",
        task_type=TaskType.MONITORING,
        handler=boom,
        handler_name="boom",
        auto_retry=True,
        max_retries=3,
    )
    scheduler.tasks[task.task_id] = task

    for _ in range(3):
        await scheduler._execute_task(task)
        # Slot must be released synchronously (finally) before the backoff.
        assert task.task_id not in scheduler.running_tasks
        assert scheduler.stats["running_tasks"] == 0
        assert scheduler._running_asyncio == {}
        # Flush the detached backoff sleep and the re-enqueue it performs.
        await asyncio.gather(*scheduler._retry_tasks)
        scheduler._retry_tasks.clear()

    assert recorded == [120, 240, 300]
    assert task.retry_count == 3


async def test_cancel_running_task_does_not_resurrect_completed() -> None:
    """Cancelling a RUNNING task cannot be overwritten by a late COMPLETED."""
    scheduler = _make_manager().scheduler
    release = asyncio.Event()

    async def slow(**_kwargs) -> dict[str, bool]:
        await release.wait()
        return {"done": True}

    task = Task(
        name="slow", task_type=TaskType.MONITORING, handler=slow, handler_name="slow"
    )
    scheduler.tasks[task.task_id] = task
    exec_task = asyncio.create_task(scheduler._execute_task(task))

    assert await _wait_until(lambda: task.status == TaskStatus.RUNNING)
    assert task.task_id in scheduler.running_tasks

    ok = await scheduler.cancel_task(task.task_id)
    assert ok is True
    assert task.status == TaskStatus.CANCELLED

    with contextlib.suppress(asyncio.CancelledError):
        await exec_task

    # Let the handler's gate open and the loop settle; state must stay CANCELLED.
    release.set()
    await asyncio.sleep(0.05)
    assert task.status == TaskStatus.CANCELLED
    assert task.result is None
    assert task.task_id not in scheduler.running_tasks


# ---------------------------------------------------------------------------
# Event mapping
# ---------------------------------------------------------------------------


async def test_emit_task_event_maps_event_types() -> None:
    """_emit_task_event maps each internal key to the right EventType."""
    manager = _make_manager()
    bus = manager.scheduler.event_bus
    task = Task(name="evt")

    cases = {
        "task_started": EventType.TASK_STARTED,
        "task_scheduled": EventType.TASK_QUEUED,
        "task_completed": EventType.TASK_COMPLETED,
        "task_failed": EventType.TASK_FAILED,
        "task_timeout": EventType.TASK_FAILED,
        "task_cancelled": EventType.SYSTEM_WARNING,
        "task_retry": EventType.TASK_QUEUED,
    }
    for key, expected in cases.items():
        await manager.scheduler._emit_task_event(key, task)
        assert bus._event_history[-1].event_type == expected, key


# ---------------------------------------------------------------------------
# Helpers used by the poll predicates
# ---------------------------------------------------------------------------


def _task_status(manager: AutonomousTaskManager, task_id: str) -> TaskStatus | None:
    task = manager.scheduler.tasks.get(task_id)
    return task.status if task is not None else None


# ---------------------------------------------------------------------------
# Restart / crash recovery (P0.4 critical)
# ---------------------------------------------------------------------------


async def test_restart_resume_executes_exactly_once(monkeypatch) -> None:
    """Full restart simulation: persist -> stop -> NEW manager -> resume.

    ``NEXUS_TASKS_RESUME_PENDING=true`` is read from the environment (the
    manager is started without an explicit argument) so the flag itself is
    exercised, not just the parameter.
    """
    calls: list[int] = []
    handler = _counter_handler(calls)

    # 1) First process: registered handler, task created and persisted.
    first = _make_manager()
    first.handlers.register("probe", handler, read_only=False)
    task_id = await first.create_custom_task(
        name="survive-restart",
        task_type=TaskType.MONITORING,
        handler_name="probe",
        parameters={"n": 1},
    )
    assert _db_row(task_id) is not None, "task must be persisted"
    assert _db_row(task_id)[0] == "pending"
    assert calls == [], "the task must not have run before the restart"

    # 2) Stop it, exactly as a process shutdown (or lifespan teardown) would.
    await first.stop()

    # 3) A brand-new instance (never reuses the first manager's objects).
    second = _make_manager()
    assert second is not first
    second.handlers.register("probe", handler, read_only=False)
    monkeypatch.setenv("NEXUS_TASKS_RESUME_PENDING", "true")

    try:
        await second.start()  # resume_pending=None -> reads the env flag

        recovered = await second.get_task(task_id)
        assert recovered is not None, "recovered task must be visible"
        # Handler rehydration: the persisted name resolves to the live callable.
        assert recovered.handler is not None
        assert recovered.handler is handler
        assert recovered.handler_name == "probe"

        assert await _wait_until(
            lambda: _task_status(second, task_id) == TaskStatus.COMPLETED
        ), "recovered task did not execute"

        # Exactly-once: one execution across the restart.
        assert calls == [1]

        # No recoverable task is failed because of the restart.
        assert [t for t in second.scheduler.tasks.values()
                if t.status == TaskStatus.FAILED] == []
        task = await second.get_task(task_id)
        assert task is not None and task.status == TaskStatus.COMPLETED
        assert task.result == {"ok": True}
        assert _db_row(task_id)[0] == "completed"
    finally:
        await second.stop()


async def test_restart_does_not_requeue_task_known_to_this_process() -> None:
    """A task created before start() is not enqueued twice by recovery."""
    calls: list[int] = []
    handler = _counter_handler(calls)

    manager = _make_manager()
    manager.handlers.register("probe", handler, read_only=False)
    task_id = await manager.create_custom_task(
        name="created-before-start",
        task_type=TaskType.MONITORING,
        handler_name="probe",
    )
    queued_before = sum(
        1 for t in manager.scheduler.task_queue if t.task_id == task_id
    )
    assert queued_before == 1

    try:
        await manager.start(resume_pending=True)
        queued_after = sum(
            1 for t in manager.scheduler.task_queue if t.task_id == task_id
        )
        assert queued_after == 1, "recovery must not enqueue an already-known task"
        assert await _wait_until(
            lambda: _task_status(manager, task_id) == TaskStatus.COMPLETED
        )
        assert calls == [1], "one task must execute exactly once"
    finally:
        await manager.stop()


async def test_interrupted_running_task_is_not_reexecuted_after_restart() -> None:
    """A row left 'running' by a dead process never runs twice.

    It is recovered as quarantined/interrupted (visible, requeueable) instead of
    being silently dropped and left 'running' forever.
    """
    calls: list[int] = []
    handler = _counter_handler(calls)

    writer = _make_manager()
    writer.handlers.register("probe", handler, read_only=False)
    task_id = await writer.create_custom_task(
        name="interrupted-mid-run",
        task_type=TaskType.MONITORING,
        handler_name="probe",
    )
    # The process claimed the task and died before the handler returned.
    update_scheduled_task_status(
        task_id, "running", started_at=datetime.now().isoformat()
    )
    assert _db_row(task_id)[0] == "running"

    recovered = _make_manager()
    recovered.handlers.register("probe", handler, read_only=False)
    try:
        # Even with the resume opt-in, an interrupted task is not auto-run.
        await recovered.start(resume_pending=True)
        await asyncio.sleep(0.2)

        assert calls == [], "an interrupted task must not be executed again"
        task = await recovered.get_task(task_id)
        assert task is not None, "an interrupted task must stay recoverable"
        assert task.status == TaskStatus.WAITING
        assert task.task_id in recovered.scheduler._quarantined
        assert task.task_id not in {t.task_id for t in recovered.scheduler.task_queue}
        assert task.task_id not in recovered.scheduler.running_tasks
        assert _db_row(task_id)[0] == "waiting"
        assert task.status != TaskStatus.FAILED

        # The operator gate is what re-arms it, and then it runs exactly once.
        assert await recovered.requeue_task(task_id) == "requeued"
        assert await _wait_until(
            lambda: _task_status(recovered, task_id) == TaskStatus.COMPLETED
        )
        assert calls == [1]
    finally:
        await recovered.stop()


async def test_execution_claims_the_row_before_running_the_handler() -> None:
    """While a handler runs, its persisted row says 'running' (durable claim)."""
    gate = asyncio.Event()
    calls: list[int] = []
    handler = _counter_handler(calls, gate)

    manager = _make_manager()
    manager.handlers.register("probe", handler, read_only=False)
    task_id = await manager.create_custom_task(
        name="claimed",
        task_type=TaskType.MONITORING,
        handler_name="probe",
    )
    try:
        await manager.start(resume_pending=True)
        assert await _wait_until(lambda: calls == [1])
        assert _db_row(task_id)[0] == "running"
        gate.set()
        assert await _wait_until(
            lambda: _task_status(manager, task_id) == TaskStatus.COMPLETED
        )
        assert _db_row(task_id)[0] == "completed"
    finally:
        gate.set()
        await manager.stop()


async def test_two_managers_do_not_execute_the_same_task_twice() -> None:
    """Two schedulers sharing the DB: the atomic claim picks exactly one winner."""
    gate = asyncio.Event()
    calls: list[int] = []
    handler = _counter_handler(calls, gate)

    first = _make_manager()
    first.handlers.register("probe", handler, read_only=False)
    task_id = await first.create_custom_task(
        name="shared",
        task_type=TaskType.MONITORING,
        handler_name="probe",
    )
    second = _make_manager()
    second.handlers.register("probe", handler, read_only=False)

    try:
        await first.start(resume_pending=True)
        await second.start(resume_pending=True)
        assert await _wait_until(lambda: calls == [1], timeout=4.0)
        await asyncio.sleep(0.2)
        gate.set()
        await asyncio.sleep(0.1)

        assert calls == [1], "the same persisted task must run once, not twice"
        winners = [
            manager
            for manager in (first, second)
            if _task_status(manager, task_id) == TaskStatus.COMPLETED
        ]
        assert len(winners) == 1
        assert _db_row(task_id)[0] == "completed"
    finally:
        gate.set()
        await first.stop()
        await second.stop()


async def test_interrupted_row_with_unknown_handler_fails_explicitly() -> None:
    """An interrupted row whose handler is gone fails loudly, like any other."""
    writer = _make_manager()
    writer.handlers.register("probe", _counter_handler([]), read_only=False)
    task_id = await writer.create_custom_task(
        name="ghost-interrupted",
        task_type=TaskType.MONITORING,
        handler_name="probe",
    )
    update_scheduled_task_status(task_id, "running")

    recovered = _make_manager()  # 'probe' is not registered in this build
    try:
        await recovered.start(resume_pending=True)
        task = await recovered.get_task(task_id)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert "probe" in (task.error or "")
        assert "not registered in this build" in (task.error or "")
        assert _db_row(task_id)[0] == "failed"
    finally:
        await recovered.stop()


async def test_interrupted_read_only_task_resumes_automatically() -> None:
    """A read-only handler cannot have side effects, so it may resume."""
    calls: list[int] = []
    handler = _counter_handler(calls)

    writer = _make_manager()
    writer.handlers.register("health_probe", handler, read_only=True)
    task_id = await writer.create_custom_task(
        name="interrupted-read-only",
        task_type=TaskType.HEALTH_CHECK,
        handler_name="health_probe",
    )
    update_scheduled_task_status(task_id, "running")

    recovered = _make_manager()
    recovered.handlers.register("health_probe", handler, read_only=True)
    try:
        # No resume flag at all: read-only handlers are exempt.
        await recovered.start(resume_pending=False)
        assert await _wait_until(
            lambda: _task_status(recovered, task_id) == TaskStatus.COMPLETED
        )
        assert calls == [1]
    finally:
        await recovered.stop()


async def test_in_memory_only_task_still_executes_without_a_persisted_row() -> None:
    scheduler = _make_manager().scheduler
    calls: list[int] = []

    async def handler(**_kwargs) -> dict[str, bool]:
        calls.append(1)
        return {"ok": True}

    task = Task(name="ephemeral", task_type=TaskType.MONITORING, handler=handler)
    scheduler.tasks[task.task_id] = task
    await scheduler._execute_task(task)

    assert calls == [1]
    assert task.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


async def test_stop_drains_running_tasks_as_interrupted() -> None:
    """stop() cancels in-flight work and persists it as interrupted/quarantined."""
    gate = asyncio.Event()
    calls: list[int] = []
    handler = _counter_handler(calls, gate)

    manager = _make_manager()
    manager.handlers.register("probe", handler, read_only=False)
    task_id = await manager.create_custom_task(
        name="drain-me",
        task_type=TaskType.MONITORING,
        handler_name="probe",
    )
    scheduler = manager.scheduler
    try:
        await manager.start(resume_pending=True)
        assert await _wait_until(lambda: calls == [1])
        assert _task_status(manager, task_id) == TaskStatus.RUNNING
        assert task_id in scheduler.running_tasks

        await manager.stop()

        # Drained: no slot, no wrapper, no RUNNING zombie.
        assert scheduler.running_tasks == {}
        assert scheduler._running_asyncio == {}
        assert scheduler.stats["running_tasks"] == 0

        task = await manager.get_task(task_id)
        assert task is not None
        assert task.status == TaskStatus.WAITING, "must be interrupted, not RUNNING"
        assert task.status != TaskStatus.FAILED
        assert task_id in scheduler._quarantined
        assert _db_row(task_id)[0] == "waiting"

        # And it does not come back to life on the next boot.
        gate.set()
        calls.clear()
        restarted = _make_manager()
        restarted.handlers.register("probe", handler, read_only=False)
        await restarted.start(resume_pending=True)
        await asyncio.sleep(0.2)
        assert calls == []
        assert _task_status(restarted, task_id) == TaskStatus.WAITING
        assert await restarted.requeue_task(task_id) == "requeued"
        assert await _wait_until(
            lambda: _task_status(restarted, task_id) == TaskStatus.COMPLETED
        )
        assert calls == [1]
        await restarted.stop()
    finally:
        gate.set()


async def test_stop_keeps_terminal_state_of_finished_task() -> None:
    """A task that completed before stop() is never rewritten to interrupted."""
    calls: list[int] = []
    handler = _counter_handler(calls)

    manager = _make_manager()
    manager.handlers.register("probe", handler, read_only=False)
    task_id = await manager.create_custom_task(
        name="already-done",
        task_type=TaskType.MONITORING,
        handler_name="probe",
    )
    try:
        await manager.start(resume_pending=True)
        assert await _wait_until(
            lambda: _task_status(manager, task_id) == TaskStatus.COMPLETED
        )
        await manager.stop()
        task = await manager.get_task(task_id)
        assert task is not None and task.status == TaskStatus.COMPLETED
        assert _db_row(task_id)[0] == "completed"
    finally:
        await manager.stop()


@pytest.mark.parametrize("resume_flag", ["1", "true", "TRUE", "yes", "on"])
async def test_resume_pending_env_flag_truthy_values(monkeypatch, resume_flag) -> None:
    """NEXUS_TASKS_RESUME_PENDING accepts the documented truthy spellings."""
    calls: list[int] = []
    handler = _counter_handler(calls)

    writer = _make_manager()
    writer.handlers.register("probe", handler, read_only=False)
    task_id = await writer.create_custom_task(
        name="flagged",
        task_type=TaskType.MONITORING,
        handler_name="probe",
    )
    await writer.stop()

    recovered = _make_manager()
    recovered.handlers.register("probe", handler, read_only=False)
    monkeypatch.setenv("NEXUS_TASKS_RESUME_PENDING", resume_flag)
    try:
        await recovered.start()
        assert await _wait_until(
            lambda: _task_status(recovered, task_id) == TaskStatus.COMPLETED
        )
        assert calls == [1]
    finally:
        await recovered.stop()


async def test_resume_pending_defaults_to_false(monkeypatch) -> None:
    """With the flag unset, a recovered write task is quarantined, not run."""
    calls: list[int] = []
    handler = _counter_handler(calls)

    writer = _make_manager()
    writer.handlers.register("probe", handler, read_only=False)
    task_id = await writer.create_custom_task(
        name="default-off",
        task_type=TaskType.MONITORING,
        handler_name="probe",
    )
    await writer.stop()

    recovered = _make_manager()
    recovered.handlers.register("probe", handler, read_only=False)
    monkeypatch.delenv("NEXUS_TASKS_RESUME_PENDING", raising=False)
    try:
        await recovered.start()
        await asyncio.sleep(0.2)
        assert calls == []
        assert _task_status(recovered, task_id) == TaskStatus.WAITING
        assert _db_row(task_id)[0] == "waiting"
        assert task_id in recovered.scheduler._quarantined
    finally:
        await recovered.stop()

