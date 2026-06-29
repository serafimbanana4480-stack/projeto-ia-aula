import asyncio
import pytest
from backend.orchestrator.autonomous_execution_engine import (
    AutonomousExecutionEngine,
    ExecutionTask,
    TaskStatus,
)


def test_submit_task():
    engine = AutonomousExecutionEngine()

    def handler(x, y):
        return x + y

    task = engine.submit_task("test", handler, 1, y=2)
    assert isinstance(task, ExecutionTask)
    assert task.name == "test"
    assert task.status == TaskStatus.PENDING
    assert task.args == (1,)
    assert task.kwargs == {"y": 2}
    assert task.max_retries == 3


@pytest.mark.asyncio
async def test_execute_task_success():
    engine = AutonomousExecutionEngine()

    async def handler():
        return 42

    task = engine.submit_task("success", handler)
    result = await engine.execute_task(task.task_id)
    assert result.status == TaskStatus.COMPLETED
    assert result.result == 42
    assert result.retry_count == 0


@pytest.mark.asyncio
async def test_execute_task_failure_with_retry():
    engine = AutonomousExecutionEngine()
    calls = []

    async def handler():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("temporary failure")
        return "recovered"

    task = engine.submit_task("retry", handler, max_retries=3)
    result = await engine.execute_task(task.task_id)
    assert result.status == TaskStatus.COMPLETED
    assert result.result == "recovered"
    assert result.retry_count == 2


@pytest.mark.asyncio
async def test_execute_task_max_retries_exceeded():
    engine = AutonomousExecutionEngine()

    async def handler():
        raise ValueError("persistent failure")

    task = engine.submit_task("fail", handler, max_retries=2)
    result = await engine.execute_task(task.task_id)
    assert result.status == TaskStatus.FAILED
    assert result.retry_count == 3  # initial + 2 retries
    assert "persistent failure" in str(task.error)


@pytest.mark.asyncio
async def test_execute_task_timeout():
    engine = AutonomousExecutionEngine()

    async def handler():
        await asyncio.sleep(10)
        return "never"

    task = engine.submit_task("timeout", handler, timeout_seconds=0.1)
    result = await engine.execute_task(task.task_id)
    assert result.status == TaskStatus.FAILED
    assert "Timeout" in str(result.error)


@pytest.mark.asyncio
async def test_execute_all():
    engine = AutonomousExecutionEngine()

    async def handler(x):
        await asyncio.sleep(0.01)
        return x * 2

    for i in range(3):
        engine.submit_task(f"task-{i}", handler, i)

    results = await engine.execute_all()
    assert len(results) == 3
    assert all(r.status == TaskStatus.COMPLETED for r in results)
    assert results[0].result == 0
    assert results[1].result == 2
    assert results[2].result == 4


def test_list_and_cancel():
    engine = AutonomousExecutionEngine()

    def handler():
        return 1

    t1 = engine.submit_task("t1", handler)
    t2 = engine.submit_task("t2", handler)

    pending = engine.list_tasks(TaskStatus.PENDING)
    assert len(pending) == 2

    assert engine.cancel_task(t1.task_id) is True
    assert engine.get_task(t1.task_id).status == TaskStatus.CANCELLED
    assert engine.cancel_task(t1.task_id) is False  # Already cancelled


def test_stats():
    engine = AutonomousExecutionEngine()
    stats = engine.stats()
    assert stats["total"] == 0
    assert stats["success_rate"] == 0.0
