"""ResourceAllocator — allocates agent resources to tasks based on capabilities and load."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentResource:
    """Represents an available agent resource."""

    agent_id: str
    name: str
    capabilities: list[str] = field(default_factory=list)
    current_load: float = 0.0  # 0.0 to 1.0
    max_capacity: float = 1.0
    health_status: str = "healthy"
    last_assignment: float = 0.0


class ResourceAllocator:
    """Allocates agent resources to tasks based on capabilities and current load.

    Uses a simple scoring system:
    - Capability match: +1 per matching capability
    - Load penalty: -2 * current_load
    - Health bonus: +1 if healthy
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentResource] = {}

    def register_agent(
        self,
        agent_id: str,
        name: str,
        capabilities: list[str],
        max_capacity: float = 1.0,
    ) -> AgentResource:
        agent = AgentResource(
            agent_id=agent_id,
            name=name,
            capabilities=capabilities,
            max_capacity=max_capacity,
        )
        self._agents[agent_id] = agent
        logger.info("Agent registered: %s with capabilities %s", name, capabilities)
        return agent

    def unregister_agent(self, agent_id: str) -> bool:
        if agent_id in self._agents:
            del self._agents[agent_id]
            return True
        return False

    def update_load(self, agent_id: str, load: float) -> AgentResource | None:
        agent = self._agents.get(agent_id)
        if agent:
            agent.current_load = max(0.0, min(agent.max_capacity, load))
        return agent

    def update_health(self, agent_id: str, status: str) -> AgentResource | None:
        agent = self._agents.get(agent_id)
        if agent:
            agent.health_status = status
        return agent

    def allocate(
        self,
        required_capabilities: list[str],
        min_capacity: float = 0.3,
    ) -> AgentResource | None:
        """Find the best agent for a task based on capabilities and load."""
        candidates: list[tuple[float, AgentResource]] = []

        for agent in self._agents.values():
            # Skip unhealthy agents
            if agent.health_status != "healthy":
                continue

            # Check available capacity
            available = agent.max_capacity - agent.current_load
            if available < min_capacity:
                continue

            # Score based on capability match
            matched = sum(1 for cap in required_capabilities if cap in agent.capabilities)
            if not matched and required_capabilities:
                continue

            score = matched * 1.0 - agent.current_load * 2.0
            if agent.health_status == "healthy":
                score += 1.0

            candidates.append((score, agent))

        if not candidates:
            logger.warning("No available agents for capabilities: %s", required_capabilities)
            return None

        # Sort by score descending
        candidates.sort(key=lambda x: x[0], reverse=True)
        best = candidates[0][1]
        logger.info(
            "Allocated %s for %s (score=%.2f, load=%.2f)",
            best.name, required_capabilities, candidates[0][0], best.current_load
        )
        return best

    def allocate_multiple(
        self,
        required_capabilities: list[str],
        count: int = 1,
    ) -> list[AgentResource]:
        """Allocate multiple agents for a task."""
        allocated: list[AgentResource] = []
        temp_agents = dict(self._agents)

        for _ in range(count):
            candidates = []
            for agent in temp_agents.values():
                if agent.health_status != "healthy":
                    continue
                available = agent.max_capacity - agent.current_load
                if available < 0.3:
                    continue
                matched = sum(1 for cap in required_capabilities if cap in agent.capabilities)
                if not matched and required_capabilities:
                    continue
                score = matched * 1.0 - agent.current_load * 2.0
                candidates.append((score, agent))

            if not candidates:
                break

            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0][1]
            allocated.append(best)
            # Simulate load increase for next iteration
            best.current_load += 0.3

        return allocated

    def get_all_agents(self) -> list[AgentResource]:
        return list(self._agents.values())

    def stats(self) -> dict[str, Any]:
        total = len(self._agents)
        if not total:
            return {"total_agents": 0, "avg_load": 0.0, "healthy": 0}
        loads = [a.current_load for a in self._agents.values()]
        healthy = sum(1 for a in self._agents.values() if a.health_status == "healthy")
        return {
            "total_agents": total,
            "avg_load": sum(loads) / len(loads),
            "max_load": max(loads),
            "healthy": healthy,
            "unhealthy": total - healthy,
        }
