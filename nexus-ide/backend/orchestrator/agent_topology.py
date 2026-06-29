"""AgentTopology — topology visualization and graph management for agent networks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentNode:
    """A node representing an agent in the topology."""

    agent_id: str
    agent_type: str
    role: str
    status: str = "active"
    capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentEdge:
    """An edge representing a relationship between agents."""

    source_id: str
    target_id: str
    relationship: str
    weight: float = 1.0
    bidirectional: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentTopology:
    """Manages agent network topology for visualization and analysis.

    Provides graph structures for rendering agent relationships,
    hierarchies, and communication patterns.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, AgentNode] = {}
        self._edges: list[AgentEdge] = []

    def add_node(self, node: AgentNode) -> None:
        self._nodes[node.agent_id] = node

    def remove_node(self, agent_id: str) -> bool:
        if agent_id not in self._nodes:
            return False
        del self._nodes[agent_id]
        self._edges = [e for e in self._edges if e.source_id != agent_id and e.target_id != agent_id]
        return True

    def add_edge(self, edge: AgentEdge) -> None:
        self._edges.append(edge)

    def remove_edge(self, source_id: str, target_id: str) -> bool:
        for i, e in enumerate(self._edges):
            if e.source_id == source_id and e.target_id == target_id:
                self._edges.pop(i)
                return True
        return False

    def get_node(self, agent_id: str) -> AgentNode | None:
        return self._nodes.get(agent_id)

    def get_neighbors(self, agent_id: str) -> list[AgentNode]:
        """Get all agents directly connected to the given agent."""
        neighbor_ids = set()
        for e in self._edges:
            if e.source_id == agent_id:
                neighbor_ids.add(e.target_id)
            if e.target_id == agent_id and e.bidirectional:
                neighbor_ids.add(e.source_id)
        return [self._nodes[nid] for nid in neighbor_ids if nid in self._nodes]

    def get_edges_for_node(self, agent_id: str) -> list[AgentEdge]:
        return [e for e in self._edges if e.source_id == agent_id or e.target_id == agent_id]

    def to_dict(self) -> dict[str, Any]:
        """Export topology as a serializable graph structure."""
        return {
            "nodes": [
                {
                    "id": n.agent_id,
                    "type": n.agent_type,
                    "role": n.role,
                    "status": n.status,
                    "capabilities": n.capabilities,
                }
                for n in self._nodes.values()
            ],
            "edges": [
                {
                    "source": e.source_id,
                    "target": e.target_id,
                    "relationship": e.relationship,
                    "weight": e.weight,
                    "bidirectional": e.bidirectional,
                }
                for e in self._edges
            ],
        }

    def get_hierarchy(self, root_id: str) -> dict[str, Any]:
        """Build a hierarchical tree view from the topology."""
        root = self._nodes.get(root_id)
        if not root:
            return {}

        def build_tree(node_id: str, visited: set[str]) -> dict[str, Any]:
            if node_id in visited:
                return {"id": node_id, "cycle": True}
            visited.add(node_id)
            node = self._nodes.get(node_id)
            if not node:
                return {"id": node_id, "missing": True}

            children = []
            for e in self._edges:
                if e.source_id == node_id and e.relationship in ("manages", "supervises", "leads"):
                    children.append(build_tree(e.target_id, visited.copy()))

            return {
                "id": node_id,
                "type": node.agent_type,
                "role": node.role,
                "status": node.status,
                "children": children,
            }

        return build_tree(root_id, set())

    def stats(self) -> dict[str, Any]:
        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "active_nodes": sum(1 for n in self._nodes.values() if n.status == "active"),
            "relationship_types": list(set(e.relationship for e in self._edges)),
        }
