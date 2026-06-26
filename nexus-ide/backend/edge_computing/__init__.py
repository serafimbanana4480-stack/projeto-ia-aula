"""Edge Computing Module — Distributed processing system for edge nodes.

This module provides comprehensive edge computing capabilities:
- Edge node management and orchestration
- Distributed task execution
- Edge-cloud coordination
- Latency optimization
- Resource management across edge nodes
- Failover and load balancing
"""

from .edge_computing import (
    EdgeComputingOrchestrator,
    EdgeNode,
    EdgeTask,
    EdgeDeployment,
    EdgeNodeType,
    EdgeNodeStatus,
    TaskPriority,
    LoadBalancingStrategy
)

__all__ = [
    "EdgeComputingOrchestrator",
    "EdgeNode",
    "EdgeTask",
    "EdgeDeployment",
    "EdgeNodeType",
    "EdgeNodeStatus",
    "TaskPriority",
    "LoadBalancingStrategy"
]