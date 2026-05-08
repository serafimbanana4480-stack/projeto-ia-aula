"""Agent pool with per-agent concurrency semaphores.

Concurrency limits live in `config/models.yaml` under `concurrency:`.
See ARCHITECTURE.md §4.4.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class AgentPool:
    """Manages semaphores and a Redis-backed queue per agent.

    TODO:
    - Load concurrency limits from `models.yaml`.
    - Create asyncio.Semaphore per agent id.
    - Expose acquire() / release() context managers.
    - Integrate with Redis queue for overflow with configurable timeout.
    """

    semaphores: dict[str, asyncio.Semaphore] = field(default_factory=dict)

    async def acquire(self, agent_id: str) -> None:
        raise NotImplementedError

    async def release(self, agent_id: str) -> None:
        raise NotImplementedError
