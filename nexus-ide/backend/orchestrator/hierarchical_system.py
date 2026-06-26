"""Hierarchical Agent System with Supervisor → Team → Worker structure.

Implements real delegation, sub-agent spawning, capability inheritance,
and multi-level coordination.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from .team_leader import TeamLeader, TeamCapability
from ..agents.base import AgentBase, AgentRequest
from ..observability.events import Event
from ..observability.event_bus import EventBus

logger = logging.getLogger(__name__)


class AgentRole(str, Enum):
    """Agent roles in hierarchy."""
    SUPREME = "supreme"
    SUPERVISOR = "supervisor"
    TEAM_LEADER = "team_leader"
    SPECIALIST = "specialist"
    WORKER = "worker"
    MICRO = "micro"


@dataclass
class AgentNode:
    """Node in agent hierarchy with relationships and capabilities."""
    node_id: str = field(default_factory=lambda: f"node-{uuid.uuid4().hex[:8]}")
    agent: Optional[AgentBase] = None
    role: AgentRole = AgentRole.WORKER
    parent_id: Optional[str] = None
    children_ids: Set[str] = field(default_factory=set)
    capabilities: List[str] = field(default_factory=list)
    status: str = "idle"  # idle, busy, failed, offline
    load: float = 0.0  # Current load (0.0-1.0)
    max_concurrent: int = 1
    current_tasks: Set[str] = field(default_factory=set)
    
    def can_handle(self, capability: str) -> bool:
        """Check if agent can handle a capability."""
        return capability in self.capabilities
    
    def is_available(self) -> bool:
        """Check if agent is available for new tasks."""
        return (self.status == "idle" and 
                len(self.current_tasks) < self.max_concurrent and
                self.load < 0.8)


class HierarchicalOrchestrator:
    """Hierarchical agent orchestration with delegation and spawning."""
    
    def __init__(
        self,
        agent_registry: Dict[str, AgentBase],
        event_bus: Optional[EventBus] = None,
        max_depth: int = 5,
        max_nodes: int = 100,
    ):
        self.agent_registry = agent_registry
        self.event_bus = event_bus or EventBus()
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        
        # Agent hierarchy
        self.nodes: Dict[str, AgentNode] = {}
        self.root_nodes: Set[str] = set()
        
        # Task tracking
        self.active_tasks: Dict[str, Dict[str, Any]] = {}
        self.task_dependencies: Dict[str, Set[str]] = {}
        
        # Spawning control
        self.temporal_agents: Dict[str, AgentNode] = {}
        self.spawn_lock = asyncio.Lock()
        
        # Initialize hierarchy
        self._initialize_hierarchy()
        
    def _initialize_hierarchy(self) -> None:
        """Initialize the agent hierarchy from registry."""
        # Create root node for Supreme Orchestrator
        supreme_node = AgentNode(
            node_id="supreme",
            role=AgentRole.SUPREME,
            capabilities=["orchestration", "planning", "coordination"],
            max_concurrent=10,
        )
        self.nodes["supreme"] = supreme_node
        self.root_nodes.add("supreme")
        
        # Create supervisor nodes
        supervisors = {
            "development": AgentNode(
                node_id="dev_supervisor",
                role=AgentRole.SUPERVISOR,
                capabilities=["development", "coding", "testing"],
                max_concurrent=5,
            ),
            "research": AgentNode(
                node_id="research_supervisor",
                role=AgentRole.SUPERVISOR,
                capabilities=["research", "analysis", "documentation"],
                max_concurrent=3,
            ),
            "operations": AgentNode(
                node_id="ops_supervisor",
                role=AgentRole.SUPERVISOR,
                capabilities=["operations", "deployment", "monitoring"],
                max_concurrent=3,
            ),
        }
        
        for supervisor in supervisors.values():
            self.nodes[supervisor.node_id] = supervisor
            supervisor.parent_id = "supreme"
            supreme_node.children_ids.add(supervisor.node_id)
            
        # Create team leader nodes
        for agent_name, agent in self.agent_registry.items():
            # Determine role based on agent type
            role = self._determine_agent_role(agent_name)
            
            node = AgentNode(
                node_id=f"{agent_name}_node",
                agent=agent,
                role=role,
                capabilities=self._get_agent_capabilities(agent_name),
                max_concurrent=self._get_concurrency_limit(agent_name),
            )
            
            self.nodes[node.node_id] = node
            
            # Attach to appropriate supervisor
            supervisor_id = self._find_supervisor_for_agent(agent_name)
            if supervisor_id:
                node.parent_id = supervisor_id
                supervisor = self.nodes[supervisor_id]
                supervisor.children_ids.add(node.node_id)
            else:
                # Attach to supreme if no supervisor found
                node.parent_id = "supreme"
                supreme_node.children_ids.add(node.node_id)
                
        logger.info("Initialized hierarchy with %d nodes", len(self.nodes))
        
    def _determine_agent_role(self, agent_name: str) -> AgentRole:
        """Determine agent role based on name and capabilities."""
        if agent_name in ["ARCHITECT", "ANALYZER"]:
            return AgentRole.TEAM_LEADER
        elif agent_name in ["CODER", "DEBUGGER", "OPTIMIZER", "RESEARCHER", "DOCUMENTER"]:
            return AgentRole.SPECIALIST
        elif agent_name == "MICRO":
            return AgentRole.MICRO
        else:
            return AgentRole.WORKER
            
    def _get_agent_capabilities(self, agent_name: str) -> List[str]:
        """Get capabilities for an agent."""
        capability_map = {
            "ARCHITECT": ["design", "architecture", "planning", "system_design"],
            "CODER": ["code_generation", "implementation", "refactoring", "debugging"],
            "DEBUGGER": ["debugging", "error_analysis", "troubleshooting", "root_cause"],
            "ANALYZER": ["analysis", "code_review", "security_audit", "performance_analysis"],
            "RESEARCHER": ["research", "investigation", "documentation", "web_search"],
            "DOCUMENTER": ["documentation", "writing", "explanation", "tutorials"],
            "OPTIMIZER": ["optimization", "performance", "caching", "resource_management"],
            "MICRO": ["quick_response", "classification", "routing", "simple_tasks"],
        }
        return capability_map.get(agent_name, ["general"])
        
    def _get_concurrency_limit(self, agent_name: str) -> int:
        """Get concurrency limit for an agent."""
        limits = {
            "MICRO": 10,
            "CODER": 3,
            "DEBUGGER": 2,
            "ANALYZER": 2,
            "ARCHITECT": 1,
            "RESEARCHER": 2,
            "DOCUMENTER": 2,
            "OPTIMIZER": 2,
        }
        return limits.get(agent_name, 1)
        
    def _find_supervisor_for_agent(self, agent_name: str) -> Optional[str]:
        """Find appropriate supervisor for an agent."""
        agent_caps = self._get_agent_capabilities(agent_name)
        
        # Development supervisor
        dev_caps = self.nodes["dev_supervisor"].capabilities
        if any(cap in dev_caps for cap in agent_caps):
            return "dev_supervisor"
            
        # Research supervisor
        research_caps = self.nodes["research_supervisor"].capabilities
        if any(cap in research_caps for cap in agent_caps):
            return "research_supervisor"
            
        # Operations supervisor
        ops_caps = self.nodes["ops_supervisor"].capabilities
        if any(cap in ops_caps for cap in agent_caps):
            return "ops_supervisor"
            
        return None
        
    async def execute_task(
        self,
        task_id: str,
        task_type: str,
        description: str,
        context: Optional[Dict[str, Any]] = None,
        priority: int = 0,
    ) -> Dict[str, Any]:
        """Execute a task through the hierarchical system."""
        logger.info("Executing task %s: %s", task_id, task_type)
        
        # Create task record
        task_record = {
            "task_id": task_id,
            "task_type": task_type,
            "description": description,
            "context": context or {},
            "priority": priority,
            "status": "pending",
            "created_at": asyncio.get_event_loop().time(),
            "assigned_node": None,
            "result": None,
            "error": None,
        }
        
        self.active_tasks[task_id] = task_record
        
        try:
            # Find capable nodes
            capable_nodes = self._find_capable_nodes(task_type)
            
            if not capable_nodes:
                # Try to spawn a temporary agent
                temp_node = await self._spawn_temporary_agent(task_type)
                if temp_node:
                    capable_nodes = [temp_node]
                else:
                    raise ValueError(f"No agent available for task type: {task_type}")
                    
            # Select best node (load balancing)
            best_node = self._select_best_node(capable_nodes)
            
            # Assign task
            task_record["assigned_node"] = best_node.node_id
            task_record["status"] = "assigned"
            
            # Execute task
            result = await self._execute_node_task(best_node, task_record)
            
            # Update task record
            task_record["result"] = result
            task_record["status"] = "completed"
            
            await self._publish_task_event("task_completed", task_record)
            
            return {
                "task_id": task_id,
                "status": "completed",
                "result": result,
                "node_id": best_node.node_id,
            }
            
        except Exception as exc:
            logger.error("Task %s failed: %s", task_id, exc)
            task_record["error"] = str(exc)
            task_record["status"] = "failed"
            
            await self._publish_task_event("task_failed", task_record)
            
            return {
                "task_id": task_id,
                "status": "failed",
                "error": str(exc),
            }
            
    def _find_capable_nodes(self, task_type: str) -> List[AgentNode]:
        """Find nodes that can handle a task type."""
        capable = []
        
        for node in self.nodes.values():
            if node.can_handle(task_type) and node.is_available():
                capable.append(node)
                
        return capable
        
    def _select_best_node(self, nodes: List[AgentNode]) -> AgentNode:
        """Select best node based on load and capability."""
        if not nodes:
            raise ValueError("No available nodes")
            
        # Sort by load (ascending) and capability match
        return min(nodes, key=lambda n: (n.load, len(n.current_tasks)))
        
    async def _execute_node_task(
        self,
        node: AgentNode,
        task_record: Dict[str, Any],
    ) -> Any:
        """Execute task on a specific node."""
        node.status = "busy"
        node.current_tasks.add(task_record["task_id"])
        
        try:
            if node.agent:
                # Execute with real agent
                result = await self._execute_agent_task(node, task_record)
            else:
                # Execute with delegation
                result = await self._execute_delegated_task(node, task_record)
                
            return result
            
        finally:
            node.status = "idle"
            node.current_tasks.discard(task_record["task_id"])
            
    async def _execute_agent_task(
        self,
        node: AgentNode,
        task_record: Dict[str, Any],
    ) -> Any:
        """Execute task with real agent."""
        if not node.agent:
            raise ValueError("No agent available")
            
        # Create agent request
        request = AgentRequest(
            session_id=task_record["task_id"],
            query=task_record["description"],
            client=node.agent._client if hasattr(node.agent, '_client') else None,
            context=task_record["context"],
            max_iterations=7,
            enable_thinking=True,
        )
        
        # Execute agent
        result_parts = []
        async for chunk in node.agent.run(request):
            result_parts.append(chunk)
            
        return "".join(result_parts)
        
    async def _execute_delegated_task(
        self,
        node: AgentNode,
        task_record: Dict[str, Any],
    ) -> Any:
        """Execute task through delegation to child nodes."""
        # Find capable child nodes
        capable_children = [
            child_id for child_id in node.children_ids
            if self.nodes[child_id].can_handle(task_record["task_type"])
        ]
        
        if not capable_children:
            raise ValueError(f"No capable children for task: {task_record['task_type']}")
            
        # Delegate to best child
        best_child_id = min(capable_children, key=lambda cid: self.nodes[cid].load)
        best_child = self.nodes[best_child_id]
        
        # Create subtask
        subtask_id = f"{task_record['task_id']}_sub_{uuid.uuid4().hex[:8]}"
        subtask_record = task_record.copy()
        subtask_record["task_id"] = subtask_id
        subtask_record["parent_task"] = task_record["task_id"]
        
        # Execute subtask
        result = await self._execute_node_task(best_child, subtask_record)
        
        return result
        
    async def _spawn_temporary_agent(self, task_type: str) -> Optional[AgentNode]:
        """Spawn a temporary agent for a specific task type."""
        async with self.spawn_lock:
            if len(self.temporal_agents) >= 10:  # Limit temporal agents
                return None
                
            # Find agent template for task type
            template_agent = self._find_template_agent(task_type)
            if not template_agent:
                return None
                
            # Create temporary node
            temp_node = AgentNode(
                node_id=f"temp_{uuid.uuid4().hex[:8]}",
                agent=template_agent,
                role=AgentRole.WORKER,
                capabilities=[task_type],
                max_concurrent=1,
            )
            
            self.temporal_agents[temp_node.node_id] = temp_node
            self.nodes[temp_node.node_id] = temp_node
            
            logger.info("Spawned temporary agent %s for task %s", temp_node.node_id, task_type)
            
            return temp_node
            
    def _find_template_agent(self, task_type: str) -> Optional[AgentBase]:
        """Find a template agent for spawning."""
        # Simple mapping - in real system would be more sophisticated
        if task_type in ["code_generation", "implementation"]:
            return self.agent_registry.get("CODER")
        elif task_type in ["debugging", "troubleshooting"]:
            return self.agent_registry.get("DEBUGGER")
        elif task_type in ["analysis", "review"]:
            return self.agent_registry.get("ANALYZER")
        else:
            return self.agent_registry.get("CODER")  # Default
            
    async def _publish_task_event(self, event_type: str, task_data: Dict[str, Any]) -> None:
        """Publish task-related event."""
        if self.event_bus:
            from ..observability.events import Event
            event = Event(type=event_type, payload=task_data)
            await self.event_bus.publish(event)
            
    def get_hierarchy_stats(self) -> Dict[str, Any]:
        """Get hierarchy statistics."""
        stats = {
            "total_nodes": len(self.nodes),
            "temporal_agents": len(self.temporal_agents),
            "active_tasks": len(self.active_tasks),
            "nodes_by_role": {},
            "nodes_by_status": {},
            "load_distribution": {},
        }
        
        for node in self.nodes.values():
            # Count by role
            role = node.role.value
            stats["nodes_by_role"][role] = stats["nodes_by_role"].get(role, 0) + 1
            
            # Count by status
            status = node.status
            stats["nodes_by_status"][status] = stats["nodes_by_status"].get(status, 0) + 1
            
            # Load distribution
            stats["load_distribution"][node.node_id] = node.load
            
        return stats
        
    async def cleanup_temporal_agents(self) -> None:
        """Clean up inactive temporal agents."""
        async with self.spawn_lock:
            to_remove = []
            
            for node_id, node in self.temporal_agents.items():
                if (node.status == "idle" and 
                    len(node.current_tasks) == 0 and
                    time.time() - node.load > 300):  # 5 minutes idle
                    to_remove.append(node_id)
                    
            for node_id in to_remove:
                del self.temporal_agents[node_id]
                del self.nodes[node_id]
                logger.info("Cleaned up temporal agent %s", node_id)