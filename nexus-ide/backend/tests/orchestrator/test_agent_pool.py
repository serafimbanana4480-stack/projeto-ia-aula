"""Tests for backend.orchestrator.agent_pool — AgentPool semaphores."""

from __future__ import annotations

import asyncio

from backend.orchestrator.agent_pool import AgentPool


class TestAgentPool:
    def test_initial_state(self) -> None:
        pool = AgentPool()
        assert pool.semaphores == {}

    def test_acquire_and_release(self) -> None:
        """Test that acquire and release work correctly."""
        pool = AgentPool()

        async def _test():
            await pool.acquire("test_agent")
            assert pool.active_count("test_agent") == 1
            await pool.release("test_agent")
            assert pool.active_count("test_agent") == 0

        asyncio.run(_test())

    def test_slot_context_manager(self) -> None:
        """Test the slot context manager."""
        pool = AgentPool()

        async def _test():
            async with pool.slot("test_agent"):
                assert pool.active_count("test_agent") == 1
            assert pool.active_count("test_agent") == 0

        asyncio.run(_test())

    def test_concurrency_limit(self) -> None:
        """Test that semaphore limits concurrent access."""
        pool = AgentPool()
        # Manually set a very low limit
        pool.semaphores["limited"] = asyncio.Semaphore(1)
        pool._active["limited"] = 0

        results: list[str] = []

        async def _worker(worker_id: str):
            async with pool.slot("limited"):
                results.append(f"{worker_id}-start")
                await asyncio.sleep(0.05)
                results.append(f"{worker_id}-end")

        async def _test():
            # Launch two workers; second should wait
            await asyncio.gather(_worker("a"), _worker("b"))

        asyncio.run(_test())
        # One worker should fully complete before the other starts
        assert results[0].endswith("-start")
        assert results[1].endswith("-end")
        assert results[2].endswith("-start")
        assert results[3].endswith("-end")
