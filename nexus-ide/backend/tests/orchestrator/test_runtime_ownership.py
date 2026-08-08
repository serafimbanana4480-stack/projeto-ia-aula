from __future__ import annotations

import asyncio

from backend.core.disk_guard import WorkerOwnershipGuard
from backend.llm.circuit_breaker import get_breaker, reset_all_breakers


def test_worker_ownership_rejects_duplicate_and_releases() -> None:
    guard = WorkerOwnershipGuard()
    guard.release("focused-test-worker")

    assert guard.acquire("focused-test-worker") is True
    assert guard.acquire("focused-test-worker") is False

    guard.release("focused-test-worker")
    assert guard.acquire("focused-test-worker") is True
    guard.release("focused-test-worker")


def test_circuit_breaker_registry_can_cross_event_loops() -> None:
    reset_all_breakers()

    async def use_breaker() -> None:
        breaker = get_breaker("cross-loop", failure_threshold=1)
        assert await breaker.is_call_permitted() is True
        await breaker.record_failure()
        assert await breaker.is_call_permitted() is False
        await breaker.record_success()
        assert await breaker.is_call_permitted() is True

    asyncio.run(use_breaker())
    asyncio.run(use_breaker())
    reset_all_breakers()
