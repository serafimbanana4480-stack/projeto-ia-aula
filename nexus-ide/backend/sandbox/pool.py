"""Sandbox Pool — warm pool of pre-initialized containers for fast execution.

Reduces cold-start latency by maintaining a pool of stopped containers
that can be restarted quickly instead of created from scratch.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

from docker.models.containers import Container

import docker
from backend.sandbox.executor import SandboxConfig

logger = logging.getLogger(__name__)


@dataclass
class PoolConfig:
    """Configuration for sandbox warm pool."""

    pool_size: int = 3
    max_pool_size: int = 10
    container_ttl_seconds: int = 300
    image: str = "nexus-sandbox:latest"


class SandboxPool:
    """Manages a warm pool of Docker containers for fast sandbox execution.

    The pool maintains stopped containers that can be restarted quickly,
    reducing cold-start time from ~2-5s to <1s.
    """

    def __init__(
        self,
        sandbox_config: SandboxConfig | None = None,
        pool_config: PoolConfig | None = None,
    ) -> None:
        self._sandbox_config = sandbox_config or SandboxConfig()
        self._pool_config = pool_config or PoolConfig()
        self._client: docker.DockerClient | None = None
        self._warm_pool: deque[Container] = deque()
        self._lock = asyncio.Lock()
        self._initialized = False

    def _get_client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    async def initialize(self) -> None:
        """Initialize the pool by pre-creating containers."""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            logger.info(
                "Initializing warm pool with %d containers...",
                self._pool_config.pool_size,
            )
            tasks = [
                self._create_container()
                for _ in range(self._pool_config.pool_size)
            ]
            containers = await asyncio.gather(*tasks, return_exceptions=True)
            for c in containers:
                if isinstance(c, Container):
                    self._warm_pool.append(c)
                else:
                    logger.warning("Failed to create warm container: %s", c)

            self._initialized = True
            logger.info(
                "Warm pool ready: %d containers",
                len(self._warm_pool),
            )

    async def _create_container(self) -> Container:
        """Create a new sandbox container."""
        client = self._get_client()
        config = self._sandbox_config

        container = client.containers.create(
            image=self._pool_config.image,
            command=["sleep", "infinity"],  # Keep container alive until used
            network_mode="none",
            mem_limit=f"{config.max_memory_mb}m",
            cpu_quota=int(config.max_cpu_cores * 100000),
            pids_limit=64,
            read_only=True,
            tmpfs={
                "/workspace": "rw,noexec,nosuid,size=100m",
                "/tmp": "rw,nosuid,size=50m",
            },
            security_opt=["no-new-privileges:true"],
            cap_drop=["ALL"],
            cap_add=["CHOWN", "DAC_OVERRIDE", "SETGID", "SETUID"],
            user="nobody",
            working_dir="/workspace",
            labels={
                "nexus.sandbox": "true",
                "nexus.sandbox.warm": "true",
            },
        )
        return container

    async def acquire(self, language: str = "python") -> Container:
        """Acquire a sandbox container from the warm pool.

        If a warm container is available, start and return it.
        Otherwise, create a new container on demand.
        """
        async with self._lock:
            # Try to get a warm container
            while self._warm_pool:
                container = self._warm_pool.popleft()
                try:
                    container.reload()
                    if container.status in ("created", "exited"):
                        container.start()
                        logger.debug(
                            "Acquired warm container %s for %s",
                            container.short_id,
                            language,
                        )
                        return container
                except Exception as exc:
                    logger.warning(
                        "Warm container %s failed, removing: %s",
                        container.short_id,
                        exc,
                    )
                    with contextlib.suppress(Exception):
                        container.remove(force=True)

        # No warm container available — create new one
        logger.info("No warm containers available, creating new one for %s", language)
        container = await self._create_container()
        container.start()
        return container

    async def release(
        self,
        container: Container,
        destroy: bool = False,
    ) -> None:
        """Return a container to the warm pool or destroy it.

        Args:
            container: The container to release.
            destroy: If True, destroy the container instead of returning to pool.
        """
        if destroy:
            try:
                container.remove(force=True)
                logger.debug("Destroyed container %s", container.short_id)
            except Exception as exc:
                logger.warning("Failed to destroy container: %s", exc)
            return

        async with self._lock:
            if len(self._warm_pool) >= self._pool_config.max_pool_size:
                # Pool is full — destroy the container
                with contextlib.suppress(Exception):
                    container.remove(force=True)
                return

            # Stop the container cleanly for reuse
            try:
                container.stop(timeout=1)
                self._warm_pool.append(container)
                logger.debug(
                    "Returned container %s to warm pool (size=%d)",
                    container.short_id,
                    len(self._warm_pool),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to return container to pool: %s",
                    exc,
                )
                with contextlib.suppress(Exception):
                    container.remove(force=True)

    async def drain(self) -> None:
        """Remove all containers from the warm pool."""
        async with self._lock:
            while self._warm_pool:
                container = self._warm_pool.popleft()
                with contextlib.suppress(Exception):
                    container.remove(force=True)
            self._initialized = False
            logger.info("Warm pool drained")

    async def __aenter__(self) -> SandboxPool:
        await self.initialize()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.drain()

    @property
    def pool_size(self) -> int:
        """Current number of warm containers."""
        return len(self._warm_pool)
