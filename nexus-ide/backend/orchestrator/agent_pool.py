"""Agent pool with per-agent concurrency semaphores.

Concurrency limits live in `config/models.yaml` under `concurrency:`.
See ARCHITECTURE.md §4.4.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

# Default concurrency per agent if not configured
DEFAULT_CONCURRENCY = 4


def _load_concurrency_limits() -> dict[str, int]:
    """Load concurrency limits from config/models.yaml."""
    try:
        config_path = Path("config/models.yaml")
        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            limits: dict[str, int] = {}
            for agent_name, agent_cfg in config.get("agents", {}).items():
                if isinstance(agent_cfg, dict) and "concurrency" in agent_cfg:
                    limits[agent_name] = int(agent_cfg["concurrency"])
            return limits
    except Exception as exc:
        logger.warning("Failed to load concurrency limits: %s", exc)
    return {}


@dataclass
class AgentPool:
    """Manages semaphores per agent id for concurrency control.

    Each agent gets an asyncio.Semaphore limiting how many concurrent
    invocations can run simultaneously. Limits are loaded from
    ``config/models.yaml`` or default to DEFAULT_CONCURRENCY.
    """

    semaphores: dict[str, asyncio.Semaphore] = field(default_factory=dict)
    _active: dict[str, int] = field(default_factory=dict)

    def _get_semaphore(self, agent_id: str) -> asyncio.Semaphore:
        """Get or create a semaphore for the given agent."""
        if agent_id not in self.semaphores:
            limits = _load_concurrency_limits()
            limit = limits.get(agent_id, DEFAULT_CONCURRENCY)
            self.semaphores[agent_id] = asyncio.Semaphore(limit)
            self._active[agent_id] = 0
            logger.debug("Created semaphore for %s with limit %d", agent_id, limit)
        return self.semaphores[agent_id]

    async def acquire(self, agent_id: str) -> None:
        """Acquire a slot for the given agent. Blocks if at capacity."""
        sem = self._get_semaphore(agent_id)
        await sem.acquire()
        self._active[agent_id] = self._active.get(agent_id, 0) + 1
        logger.debug("Acquired slot for %s (active: %d)", agent_id, self._active.get(agent_id, 0))

    async def release(self, agent_id: str) -> None:
        """Release a slot for the given agent."""
        if agent_id in self.semaphores:
            self.semaphores[agent_id].release()
            self._active[agent_id] = max(0, self._active.get(agent_id, 0) - 1)
            logger.debug("Released slot for %s (active: %d)", agent_id, self._active.get(agent_id, 0))

    @asynccontextmanager
    async def slot(self, agent_id: str):
        """Context manager for acquiring/releasing an agent slot."""
        await self.acquire(agent_id)
        try:
            yield
        finally:
            await self.release(agent_id)

    def active_count(self, agent_id: str) -> int:
        """Return the number of currently active invocations for an agent."""
        return self._active.get(agent_id, 0)


# Global singleton
_pool: AgentPool | None = None


def get_agent_pool() -> AgentPool:
    """Get the global AgentPool instance."""
    global _pool
    if _pool is None:
        _pool = AgentPool()
    return _pool
