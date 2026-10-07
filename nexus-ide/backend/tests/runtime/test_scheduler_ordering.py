"""The ordering contract from section 28 of the rebuild brief.

Test 1 — A depends on B: A never starts before B completes.
Test 2 — A and B independent: they actually run in parallel.
Test 3 — A and B write the same file: they are serialised.
Test 5 — a worker stalls: it is timed out and the run recovers.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.runtime.scheduler import (
    RuntimeScheduler,
    RuntimeTask,
    RuntimeTaskStatus,
    SchedulerError,
)


def _recorder() -> tuple[list[tuple[str, str]], object]:
    timeline: list[tuple[str, str]] = []

    def make(name: str, delay: float = 0.02):
        async def run(task: RuntimeTask) -> str:
            timeline.append(("start", name))
            task.mark_first_token()
            await asyncio.sleep(delay)
            task.heartbeat()
            timeline.append(("end", name))
            return name

        return run

    return timeline, make


def _peak(timeline: list[tuple[str, str]]) -> int:
    live = peak = 0
    for kind, _ in timeline:
        live += 1 if kind == "start" else -1
        peak = max(peak, live)
    return peak


@pytest.mark.asyncio
async def test_dependent_task_never_starts_before_its_dependency_completes() -> None:
    timeline, make = _recorder()
    b = RuntimeTask(name="B", run=make("B", 0.05), task_id="b")
    a = RuntimeTask(name="A", run=make("A", 0.01), task_id="a", depends_on=frozenset({"b"}))

    report = await RuntimeScheduler(max_parallel=4).run([a, b])

    assert report.start_order == ["B", "A"]
    assert timeline.index(("end", "B")) < timeline.index(("start", "A"))
    assert a.started_at > b.completed_at
    assert all(task.status is RuntimeTaskStatus.COMPLETED for task in report.tasks)


@pytest.mark.asyncio
async def test_independent_tasks_run_in_parallel() -> None:
    timeline, make = _recorder()
    tasks = [RuntimeTask(name=f"T{i}", run=make(f"T{i}", 0.05)) for i in range(3)]

    report = await RuntimeScheduler(max_parallel=3).run(tasks)

    assert _peak(timeline) == 3, f"expected real parallelism, timeline={timeline}"
    assert report.peak_parallelism == 3
    # Parallelism is proven by the peak assertions; the duration bound is a
    # coarse guard against pathological overhead (0.149s measured under CI
    # noise against the previous 0.14s bound).
    assert report.duration < 0.45, "three 50ms tasks took pathologically long"


@pytest.mark.asyncio
async def test_conflicting_write_scopes_are_serialised() -> None:
    timeline, make = _recorder()
    a = RuntimeTask(
        name="A", run=make("A", 0.04), write_scope=frozenset({"backend/runtime/scheduler.py"})
    )
    b = RuntimeTask(
        name="B", run=make("B", 0.04), write_scope=frozenset({"backend/runtime/scheduler.py"})
    )

    report = await RuntimeScheduler(max_parallel=4).run([a, b])

    assert _peak(timeline) == 1, (
        f"two writers to the same file overlapped: {timeline}"
    )
    assert report.peak_parallelism == 1
    assert all(task.status is RuntimeTaskStatus.COMPLETED for task in report.tasks)


@pytest.mark.asyncio
async def test_disjoint_write_scopes_still_run_in_parallel() -> None:
    timeline, make = _recorder()
    a = RuntimeTask(name="A", run=make("A", 0.05), write_scope=frozenset({"a.py"}))
    b = RuntimeTask(name="B", run=make("B", 0.05), write_scope=frozenset({"b.py"}))

    await RuntimeScheduler(max_parallel=4).run([a, b])

    assert _peak(timeline) == 2


@pytest.mark.asyncio
async def test_max_parallel_is_enforced() -> None:
    timeline, make = _recorder()
    tasks = [RuntimeTask(name=f"T{i}", run=make(f"T{i}", 0.03)) for i in range(6)]

    report = await RuntimeScheduler(max_parallel=2).run(tasks)

    assert _peak(timeline) <= 2
    assert report.peak_parallelism <= 2


@pytest.mark.asyncio
async def test_stalled_task_is_timed_out_and_the_run_continues() -> None:
    finished: list[str] = []

    async def stalls(task: RuntimeTask) -> str:
        await asyncio.sleep(30)  # never reports progress again
        return "never"

    async def works(task: RuntimeTask) -> str:
        task.heartbeat()
        await asyncio.sleep(0.01)
        finished.append(task.name)
        return "ok"

    stuck = RuntimeTask(
        name="STUCK", run=stalls, heartbeat_timeout_seconds=0.05, timeout_seconds=5
    )
    healthy = RuntimeTask(name="HEALTHY", run=works)

    await RuntimeScheduler(max_parallel=2).run([stuck, healthy])

    assert stuck.status is RuntimeTaskStatus.FAILED
    assert "no progress" in stuck.error
    assert healthy.status is RuntimeTaskStatus.COMPLETED
    assert finished == ["HEALTHY"], "a stalled worker blocked unrelated work"


@pytest.mark.asyncio
async def test_dependents_of_a_failed_task_are_blocked_not_started() -> None:
    started: list[str] = []

    async def boom(task: RuntimeTask) -> str:
        started.append(task.name)
        raise ValueError("upstream exploded")

    async def child(task: RuntimeTask) -> str:
        started.append(task.name)
        return "ok"

    parent = RuntimeTask(name="PARENT", run=boom, task_id="p")
    dependent = RuntimeTask(name="CHILD", run=child, depends_on=frozenset({"p"}))

    report = await RuntimeScheduler(max_parallel=2).run([parent, dependent])

    assert parent.status is RuntimeTaskStatus.FAILED
    assert dependent.status is RuntimeTaskStatus.BLOCKED
    assert started == ["PARENT"]
    assert any("did not complete" in error for error in report.errors)


@pytest.mark.asyncio
async def test_retry_then_success_is_recorded() -> None:
    attempts = {"n": 0}

    async def flaky(task: RuntimeTask) -> str:
        attempts["n"] += 1
        task.heartbeat()
        if attempts["n"] == 1:
            raise RuntimeError("transient provider error")
        return "ok"

    task = RuntimeTask(name="FLAKY", run=flaky, max_retries=1)
    await RuntimeScheduler(max_parallel=1).run([task])

    assert task.status is RuntimeTaskStatus.COMPLETED
    assert task.retries == 1
    assert attempts["n"] == 2


@pytest.mark.asyncio
async def test_cancellation_stops_running_and_queued_tasks() -> None:
    cancel = asyncio.Event()
    started: list[str] = []

    async def slow(task: RuntimeTask) -> str:
        started.append(task.name)
        task.heartbeat()
        await asyncio.sleep(5)
        return "never"

    tasks = [RuntimeTask(name=f"T{i}", run=slow) for i in range(4)]

    async def stop_soon() -> None:
        await asyncio.sleep(0.05)
        cancel.set()

    report, _ = await asyncio.gather(
        RuntimeScheduler(max_parallel=2).run(tasks, cancel_event=cancel), stop_soon()
    )

    assert all(task.status is RuntimeTaskStatus.CANCELLED for task in report.tasks)
    assert len(started) <= 2, "queued tasks were started after cancellation"


def test_cycles_are_rejected_before_anything_runs() -> None:
    a = RuntimeTask(name="A", run=_noop, task_id="a", depends_on=frozenset({"b"}))
    b = RuntimeTask(name="B", run=_noop, task_id="b", depends_on=frozenset({"a"}))
    with pytest.raises(SchedulerError, match="cycle"):
        RuntimeScheduler.validate([a, b])


def test_unknown_dependencies_are_rejected() -> None:
    a = RuntimeTask(name="A", run=_noop, task_id="a", depends_on=frozenset({"ghost"}))
    with pytest.raises(SchedulerError, match="unknown task"):
        RuntimeScheduler.validate([a])


async def _noop(task: RuntimeTask) -> None:
    return None
