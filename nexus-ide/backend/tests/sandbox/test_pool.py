"""Tests for the Sandbox Pool system.

Covers:
- Warm pool initialization
- Container acquisition and reuse
- Pool draining
"""
from __future__ import annotations

import pytest


def _docker_available() -> bool:
    """Return True only if the Docker daemon is reachable."""
    try:
        import docker
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


# Skip the entire module when Docker Desktop is not running.
pytestmark = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker daemon not available — start Docker Desktop to run pool tests",
)

from backend.sandbox.executor import SandboxConfig
from backend.sandbox.pool import PoolConfig, SandboxPool


@pytest.fixture
def pool_config() -> PoolConfig:
    return PoolConfig(pool_size=2, max_pool_size=4)


@pytest.fixture
def sandbox_config() -> SandboxConfig:
    return SandboxConfig(image="nexus-sandbox:latest")


class TestSandboxPool:
    @pytest.mark.asyncio
    async def test_pool_initialization(
        self, pool_config: PoolConfig, sandbox_config: SandboxConfig
    ) -> None:
        pool = SandboxPool(sandbox_config, pool_config)
        await pool.initialize()
        assert pool.pool_size == 2
        await pool.drain()

    @pytest.mark.asyncio
    async def test_pool_acquire_returns_container(
        self, pool_config: PoolConfig, sandbox_config: SandboxConfig
    ) -> None:
        pool = SandboxPool(sandbox_config, pool_config)
        await pool.initialize()
        container = await pool.acquire("python")
        assert container is not None
        assert container.short_id is not None
        await pool.release(container, destroy=True)
        await pool.drain()

    @pytest.mark.asyncio
    async def test_pool_release_returns_to_pool(
        self, pool_config: PoolConfig, sandbox_config: SandboxConfig
    ) -> None:
        pool = SandboxPool(sandbox_config, pool_config)
        await pool.initialize()
        container = await pool.acquire("python")
        await pool.release(container)
        assert pool.pool_size == 2  # Should return to pool
        await pool.drain()

    @pytest.mark.asyncio
    async def test_pool_acquire_reuses_warm_container(
        self, pool_config: PoolConfig, sandbox_config: SandboxConfig
    ) -> None:
        pool = SandboxPool(sandbox_config, pool_config)
        await pool.initialize()
        c1 = await pool.acquire("python")
        short_id = c1.short_id
        await pool.release(c1)
        c2 = await pool.acquire("python")
        assert c2.short_id == short_id  # Same container reused
        await pool.release(c2, destroy=True)
        await pool.drain()

    @pytest.mark.asyncio
    async def test_pool_drain_removes_all(
        self, pool_config: PoolConfig, sandbox_config: SandboxConfig
    ) -> None:
        pool = SandboxPool(sandbox_config, pool_config)
        await pool.initialize()
        assert pool.pool_size == 2
        await pool.drain()
        assert pool.pool_size == 0

    @pytest.mark.asyncio
    async def test_pool_context_manager(
        self, pool_config: PoolConfig, sandbox_config: SandboxConfig
    ) -> None:
        async with SandboxPool(sandbox_config, pool_config) as pool:
            assert pool.pool_size == 2
            container = await pool.acquire("python")
            assert container is not None
            await pool.release(container)
        # After exit, pool should be drained
        assert pool.pool_size == 0
