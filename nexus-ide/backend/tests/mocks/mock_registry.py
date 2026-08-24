"""Mock Agent Registry for testing."""
from __future__ import annotations

from typing import Any
from dataclasses import dataclass


@dataclass
class MockAgent:
    """Mock agent."""
    id: str
    name: str
    model_key: str
    status: str = "idle"
    performance: float = 0.9


class MockAgentRegistry:
    """Mock Agent Registry for testing."""
    
    def __init__(self):
        self._agents = {
            "router": MockAgent("router", "Router Agent", "micro", "active", 0.95),
            "architect": MockAgent("architect", "Architect Agent", "coder", "idle", 0.88),
            "researcher": MockAgent("researcher", "Researcher Agent", "fast", "idle", 0.92),
            "coder": MockAgent("coder", "Coder Agent", "coder", "active", 0.91),
            "debugger": MockAgent("debugger", "Debugger Agent", "coder", "idle", 0.85),
            "documenter": MockAgent("documenter", "Documenter Agent", "micro", "idle", 0.89),
        }
    
    def get_agent(self, agent_id: str) -> MockAgent | None:
        """Get agent by ID."""
        return self._agents.get(agent_id)
    
    def list_agents(self) -> list[MockAgent]:
        """List all agents."""
        return list(self._agents.values())
    
    def get_topology(self) -> dict[str, Any]:
        """Get agent topology."""
        nodes = [
            {
                "id": agent.id,
                "label": agent.name,
                "x": 100 + i * 100,
                "y": 150,
                "color": "#a78bfa",
                "status": agent.status,
                "size": 25,
                "cpu": 35,
                "memory": 40,
            }
            for i, agent in enumerate(self._agents.values())
        ]
        
        links = [
            {
                "source": "router",
                "target": agent_id,
                "value": 1.0,
                "active": True,
            }
            for agent_id in self._agents
            if agent_id != "router"
        ]
        
        return {"nodes": nodes, "links": links}
    
    def update_agent_status(self, agent_id: str, status: str) -> bool:
        """Update agent status."""
        if agent_id in self._agents:
            self._agents[agent_id].status = status
            return True
        return False
