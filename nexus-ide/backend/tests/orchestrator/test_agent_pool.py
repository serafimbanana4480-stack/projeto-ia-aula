"""Tests for backend.orchestrator.agent_pool — AgentPool semaphores."""
from __future__ import annotations

import pytest

from backend.orchestrator.agent_pool import AgentPool


class TestAgentPool:
    def test_initial_state(self) -> None:
        pool = AgentPool()
        assert pool.semaphores == {}

    def test_acquire_raises_not_implemented(self) -> None:
        pool = AgentPool()
        import asyncio

        with pytest.raises(NotImplementedError):
            asyncio.run(pool.acquire("nano"))

    def test_release_raises_not_implemented(self) -> None:
        pool = AgentPool()
        import asyncio

        with pytest.raises(NotImplementedError):
            asyncio.run(pool.release("nano"))
