from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.core.disk_guard import WorkerOwnershipGuard
from backend.llm.circuit_breaker import get_breaker, reset_all_breakers
from backend.observability.routes.health import health_check, readiness_check
from backend.orchestrator.main import _cleanup_failed_lifespan


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


async def test_failed_startup_releases_claims_even_when_shutdown_fails() -> None:
    guard = WorkerOwnershipGuard()
    guard.release("failure-injection-worker")
    assert guard.acquire("failure-injection-worker") is True

    class FailingService:
        async def stop(self) -> None:
            raise RuntimeError("injected stop failure")

    app = SimpleNamespace(
        state=SimpleNamespace(
            worker_ownership={"failure-injection-worker"},
            guardian_agent=FailingService(),
        )
    )

    await _cleanup_failed_lifespan(app)

    assert guard.acquire("failure-injection-worker") is True
    guard.release("failure-injection-worker")


async def test_mounted_health_payloads_include_disk_pressure() -> None:
    assert "disk_pressure" in await health_check()
    assert "disk_pressure" in await readiness_check()
