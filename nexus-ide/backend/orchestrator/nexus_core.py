"""NexusCore — central integration point for all v3.0 subsystems.

Wires together:
- Agent pool, allocator, and router
- Communication bus for inter-agent messaging
- Execution engine for autonomous task running
- Debate visualizer for agent parliament
- Topology manager for agent network graphs
- Neural dashboard for system health
- Self-improvement loop for autonomous optimization
- Docker sandbox for secure code execution
- Worktree manager for isolated git environments
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from backend.orchestrator.agent_pool import AgentPool
from backend.orchestrator.allocator import AgentAllocator
from backend.orchestrator.smart_router import SmartRouter
from backend.orchestrator.autonomous_execution_engine import AutonomousExecutionEngine
from backend.orchestrator.agent_communication_bus import AgentCommunicationBus
from backend.orchestrator.debate_visualizer import DebateVisualizer
from backend.orchestrator.agent_topology import AgentTopology
from backend.orchestrator.neural_dashboard import NeuralDashboard
from backend.orchestrator.self_improvement_loop import SelfImprovementLoop
from backend.orchestrator.supreme import SupremeOrchestrator
from backend.infrastructure.docker_sandbox import DockerSandbox
from backend.infrastructure.worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


class NexusCore:
    """Central integration hub for the NEXUS v3.0 system.

    Provides unified access to all subsystems and coordinates
    their interactions for a cohesive multi-agent experience.
    """

    def __init__(self) -> None:
        # Core orchestration
        self.pool = AgentPool()
        self.allocator = AgentAllocator(self.pool)
        self.router = SmartRouter()
        self.supreme = SupremeOrchestrator(self.pool)

        # v3.0 subsystems
        self.execution_engine = AutonomousExecutionEngine()
        self.communication_bus = AgentCommunicationBus()
        self.debate_visualizer = DebateVisualizer()
        self.topology = AgentTopology()
        self.dashboard = NeuralDashboard()
        self.self_improvement = SelfImprovementLoop()

        # Infrastructure
        self.docker_sandbox: Optional[DockerSandbox] = None
        self.worktree_manager: Optional[WorktreeManager] = None

        logger.info("NexusCore initialized with all v3.0 subsystems")

    async def initialize(self) -> None:
        """Initialize all subsystems that require async setup."""
        logger.info("Initializing NEXUS v3.0 subsystems...")
        # Future: start background tasks, connect to external services, etc.

    def register_agent(self, agent_id: str, agent_type: str, role: str,
                       capabilities: list[str] | None = None) -> None:
        """Register an agent with the topology and dashboard."""
        from backend.orchestrator.agent_topology import AgentNode
        from backend.orchestrator.neural_dashboard import AgentHealth

        self.topology.add_node(
            AgentNode(
                agent_id=agent_id,
                agent_type=agent_type,
                role=role,
                capabilities=capabilities or [],
            )
        )
        self.dashboard.update_agent_health(
            AgentHealth(agent_id=agent_id, status="healthy")
        )
        logger.debug("Registered agent %s (%s)", agent_id, role)

    def connect_agents(self, source_id: str, target_id: str,
                      relationship: str, bidirectional: bool = False) -> None:
        """Create a relationship edge between two agents."""
        from backend.orchestrator.agent_topology import AgentEdge
        self.topology.add_edge(
            AgentEdge(
                source_id=source_id,
                target_id=target_id,
                relationship=relationship,
                bidirectional=bidirectional,
            )
        )

    def get_system_status(self) -> dict[str, Any]:
        """Get a comprehensive system status summary."""
        return {
            "orchestrator": {
                "pool_agents": len(self.pool._instances) if hasattr(self.pool, '_instances') else 0,
            },
            "execution": self.execution_engine.stats(),
            "communication": self.communication_bus.stats(),
            "topology": self.topology.stats(),
            "dashboard": self.dashboard.get_system_overview(),
            "self_improvement": self.self_improvement.stats(),
            "debates": len(self.debate_visualizer.list_sessions()),
        }
