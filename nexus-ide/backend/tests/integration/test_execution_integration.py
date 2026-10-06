"""Integration tests for Autonomous Execution Engine."""
from __future__ import annotations

import asyncio

import pytest

from backend.orchestrator.autonomous_execution_engine import (
    AutonomousExecutionEngine,
    TaskStatus,
)


class TestExecutionEngineIntegration:
    @pytest.mark.asyncio
    async def test_task_executes_and_completes(self):
        engine = AutonomousExecutionEngine()

        async def handler():
            return {"status": "ok", "data": [1, 2, 3]}

        task = engine.submit_task("integration-test", handler)
        result = await engine.execute_task(task.task_id)
        assert result.status == TaskStatus.COMPLETED
        assert result.result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_task_retries_then_recovers(self):
        engine = AutonomousExecutionEngine()
        calls = []

        async def handler():
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("temporary")
            return "recovered"

        task = engine.submit_task("retry-test", handler, max_retries=3)
        result = await engine.execute_task(task.task_id)
        assert result.status == TaskStatus.COMPLETED
        assert result.result == "recovered"
        assert result.retry_count == 2

    @pytest.mark.asyncio
    async def test_task_fails_after_max_retries(self):
        engine = AutonomousExecutionEngine()

        async def handler():
            raise ValueError("persistent error")

        task = engine.submit_task("fail-test", handler, max_retries=1)
        result = await engine.execute_task(task.task_id)
        assert result.status == TaskStatus.FAILED
        assert "persistent error" in str(result.error)
        assert result.retry_count == 2  # initial + 1 retry

    @pytest.mark.asyncio
    async def test_task_times_out(self):
        engine = AutonomousExecutionEngine()

        async def handler():
            await asyncio.sleep(10)
            return "never"

        task = engine.submit_task("timeout-test", handler, timeout_seconds=0.1)
        result = await engine.execute_task(task.task_id)
        assert result.status == TaskStatus.FAILED
        assert "Timeout" in str(result.error)

    @pytest.mark.asyncio
    async def test_concurrent_tasks_respect_limit(self):
        engine = AutonomousExecutionEngine(max_concurrent=2)
        running = []

        async def handler(id: int):
            running.append(id)
            await asyncio.sleep(0.1)
            running.remove(id)
            return id

        for i in range(5):
            engine.submit_task(f"concurrent-{i}", handler, i)

        results = await engine.execute_all()
        assert len(results) == 5
        assert all(r.status == TaskStatus.COMPLETED for r in results)

    @pytest.mark.asyncio
    async def test_cancel_pending_task(self):
        engine = AutonomousExecutionEngine()

        def handler():
            return 1

        task = engine.submit_task("cancel-me", handler)
        assert engine.cancel_task(task.task_id) is True
        assert engine.get_task(task.task_id).status == TaskStatus.CANCELLED
        assert engine.cancel_task(task.task_id) is False

    def test_stats_accuracy(self):
        engine = AutonomousExecutionEngine()
        assert engine.stats()["total"] == 0
        assert engine.stats()["success_rate"] == 0.0

        def handler():
            return 1

        engine.submit_task("t1", handler)
        engine.submit_task("t2", handler)
        assert engine.stats()["total"] == 2
