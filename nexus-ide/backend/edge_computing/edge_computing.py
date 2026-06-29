"""Edge Computing — Distributed processing system for edge nodes.

This module provides:
- Edge node management and orchestration
- Distributed task execution
- Edge-cloud coordination
- Latency optimization
- Resource management across edge nodes
- Failover and load balancing
"""

from __future__ import annotations

import asyncio
import logging
import json
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
import uuid
import numpy as np
from collections import defaultdict
import statistics

from backend.observability.event_bus import EventBus
from backend.observability.events import Event

logger = logging.getLogger(__name__)


class EdgeNodeType(Enum):
    """Types of edge nodes."""
    GATEWAY = "gateway"                 # Edge gateway node
    COMPUTE = "compute"                 # Edge compute node
    STORAGE = "storage"                 # Edge storage node
    SENSOR = "sensor"                  # Edge sensor node
    ACTUATOR = "actuator"              # Edge actuator node
    HYBRID = "hybrid"                  # Hybrid edge node


class EdgeNodeStatus(Enum):
    """Status of edge nodes."""
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    ERROR = "error"


class TaskPriority(Enum):
    """Priority levels for edge tasks."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    REAL_TIME = "real_time"


class LoadBalancingStrategy(Enum):
    """Load balancing strategies."""
    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_connections"
    RESOURCE_BASED = "resource_based"
    LATENCY_BASED = "latency_based"
    GEOGRAPHIC = "geographic"
    ADAPTIVE = "adaptive"


@dataclass
class EdgeNode:
    """Represents an edge computing node."""
    node_id: str
    name: str
    node_type: EdgeNodeType
    location: Dict[str, Any]
    capabilities: List[str]
    resources: Dict[str, Any]
    status: EdgeNodeStatus
    last_heartbeat: datetime
    performance_metrics: Dict[str, float]
    network_info: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EdgeTask:
    """Represents a task to be executed on edge nodes."""
    task_id: str
    name: str
    task_type: str
    requirements: Dict[str, Any]
    priority: TaskPriority
    estimated_duration: timedelta
    deadline: Optional[datetime]
    payload: Dict[str, Any]
    constraints: Dict[str, Any]
    created_at: datetime
    assigned_node: Optional[str] = None
    status: str = "pending"
    progress: float = 0.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class EdgeDeployment:
    """Represents a deployment configuration for edge nodes."""
    deployment_id: str
    name: str
    target_nodes: List[str]
    deployment_config: Dict[str, Any]
    resource_requirements: Dict[str, Any]
    network_requirements: Dict[str, Any]
    security_requirements: Dict[str, Any]
    created_at: datetime
    deployed_at: Optional[datetime]
    status: str = "pending"


class EdgeComputingOrchestrator:
    """Orchestrates edge computing operations across distributed nodes."""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        
        # Edge nodes
        self.edge_nodes: Dict[str, EdgeNode] = {}
        self.node_groups: Dict[str, List[str]] = defaultdict(list)
        
        # Tasks and deployments
        self.edge_tasks: Dict[str, EdgeTask] = {}
        self.task_queue: List[str] = []
        self.edge_deployments: Dict[str, EdgeDeployment] = {}
        
        # Load balancing
        self.load_balancer: LoadBalancingStrategy = LoadBalancingStrategy.RESOURCE_BASED
        self.node_loads: Dict[str, Dict[str, Any]] = defaultdict(dict)
        
        # Network topology
        self.network_topology: Dict[str, List[str]] = defaultdict(list)
        self.latency_matrix: Dict[str, Dict[str, float]] = defaultdict(dict)
        
        # Resource management
        self.resource_pools: Dict[str, Dict[str, Any]] = {}
        self.resource_allocation: Dict[str, Dict[str, Any]] = defaultdict(dict)
        
        # Performance tracking
        self.performance_metrics: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        
        # Start background tasks
        self._heartbeat_monitor_task = asyncio.create_task(self._monitor_heartbeats())
        self._task_scheduler_task = asyncio.create_task(self._schedule_tasks())
        self._load_balancer_task = asyncio.create_task(self._balance_load())
        self._performance_monitor_task = asyncio.create_task(self._monitor_performance())
    
    async def register_edge_node(self, node_id: str, name: str, node_type: EdgeNodeType,
                                location: Dict[str, Any], capabilities: List[str],
                                resources: Dict[str, Any], network_info: Dict[str, Any]) -> None:
        """Register a new edge node."""
        
        edge_node = EdgeNode(
            node_id=node_id,
            name=name,
            node_type=node_type,
            location=location,
            capabilities=capabilities,
            resources=resources,
            status=EdgeNodeStatus.ONLINE,
            last_heartbeat=datetime.now(),
            performance_metrics={},
            network_info=network_info,
            metadata={"registered_at": datetime.now().isoformat()}
        )
        
        # Store node
        self.edge_nodes[node_id] = edge_node
        
        # Initialize node load tracking
        self.node_loads[node_id] = {
            "cpu_usage": 0.0,
            "memory_usage": 0.0,
            "network_usage": 0.0,
            "active_tasks": 0,
            "total_capacity": resources.get("cpu_capacity", 1.0)
        }
        
        # Add to node groups
        group_key = f"{node_type.value}_{location.get('region', 'default')}"
        self.node_groups[group_key].append(node_id)
        
        # Update network topology
        self._update_network_topology(node_id, network_info)
        
        # Emit registration event
        await self.event_bus.emit(Event(
            type="edge_node_registered",
            data={
                "node_id": node_id,
                "name": name,
                "node_type": node_type.value,
                "location": location,
                "capabilities": capabilities
            }
        ))
        
        logger.info(f"Edge node registered: {node_id} ({name})")
    
    async def submit_edge_task(self, name: str, task_type: str, requirements: Dict[str, Any],
                             priority: TaskPriority, estimated_duration: timedelta,
                             payload: Dict[str, Any], constraints: Dict[str, Any] = None,
                             deadline: datetime = None) -> str:
        """Submit a task for edge execution."""
        
        task_id = str(uuid.uuid4())
        
        edge_task = EdgeTask(
            task_id=task_id,
            name=name,
            task_type=task_type,
            requirements=requirements,
            priority=priority,
            estimated_duration=estimated_duration,
            deadline=deadline,
            payload=payload,
            constraints=constraints or {},
            created_at=datetime.now()
        )
        
        # Store task
        self.edge_tasks[task_id] = edge_task
        
        # Add to queue
        self.task_queue.append(task_id)
        
        # Sort queue by priority
        priority_order = {
            TaskPriority.REAL_TIME: 0,
            TaskPriority.CRITICAL: 1,
            TaskPriority.HIGH: 2,
            TaskPriority.MEDIUM: 3,
            TaskPriority.LOW: 4
        }
        
        self.task_queue.sort(key=lambda tid: priority_order[self.edge_tasks[tid].priority])
        
        # Emit task submission event
        await self.event_bus.emit(Event(
            type="edge_task_submitted",
            data={
                "task_id": task_id,
                "name": name,
                "task_type": task_type,
                "priority": priority.value,
                "estimated_duration": estimated_duration.total_seconds()
            }
        ))
        
        logger.info(f"Edge task submitted: {task_id} ({name})")
        
        return task_id
    
    async def deploy_to_edge(self, deployment_config: Dict[str, Any]) -> str:
        """Deploy a service to edge nodes."""
        
        deployment_id = str(uuid.uuid4())
        
        # Select target nodes based on requirements
        target_nodes = await self._select_deployment_targets(deployment_config)
        
        edge_deployment = EdgeDeployment(
            deployment_id=deployment_id,
            name=deployment_config.get("name", "edge_deployment"),
            target_nodes=target_nodes,
            deployment_config=deployment_config,
            resource_requirements=deployment_config.get("resource_requirements", {}),
            network_requirements=deployment_config.get("network_requirements", {}),
            security_requirements=deployment_config.get("security_requirements", {}),
            created_at=datetime.now()
        )
        
        # Store deployment
        self.edge_deployments[deployment_id] = edge_deployment
        
        # Execute deployment
        await self._execute_deployment(deployment_id)
        
        # Emit deployment event
        await self.event_bus.emit(Event(
            type="edge_deployment_created",
            data={
                "deployment_id": deployment_id,
                "name": edge_deployment.name,
                "target_nodes": target_nodes,
                "resource_requirements": edge_deployment.resource_requirements
            }
        ))
        
        logger.info(f"Edge deployment created: {deployment_id}")
        
        return deployment_id
    
    async def _select_deployment_targets(self, config: Dict[str, Any]) -> List[str]:
        """Select target nodes for deployment based on requirements."""
        
        target_nodes = []
        
        # Filter by node type
        required_types = config.get("node_types", [])
        required_capabilities = config.get("capabilities", [])
        location_constraints = config.get("location_constraints", {})
        resource_requirements = config.get("resource_requirements", {})
        
        for node_id, node in self.edge_nodes.items():
            # Check node status
            if node.status != EdgeNodeStatus.ONLINE:
                continue
            
            # Check node type
            if required_types and node.node_type.value not in required_types:
                continue
            
            # Check capabilities
            if required_capabilities:
                if not all(cap in node.capabilities for cap in required_capabilities):
                    continue
            
            # Check location constraints
            if location_constraints:
                node_location = node.location
                if "region" in location_constraints:
                    if node_location.get("region") != location_constraints["region"]:
                        continue
                if "country" in location_constraints:
                    if node_location.get("country") != location_constraints["country"]:
                        continue
            
            # Check resource requirements
            if resource_requirements:
                node_resources = node.resources
                if "cpu_min" in resource_requirements:
                    if node_resources.get("cpu_capacity", 0) < resource_requirements["cpu_min"]:
                        continue
                if "memory_min" in resource_requirements:
                    if node_resources.get("memory_capacity", 0) < resource_requirements["memory_min"]:
                        continue
                if "storage_min" in resource_requirements:
                    if node_resources.get("storage_capacity", 0) < resource_requirements["storage_min"]:
                        continue
            
            target_nodes.append(node_id)
        
        return target_nodes
    
    async def _execute_deployment(self, deployment_id: str) -> None:
        """Execute deployment on target nodes."""
        
        if deployment_id not in self.edge_deployments:
            return
        
        deployment = self.edge_deployments[deployment_id]
        
        # Deploy to each target node
        deployment_results = []
        
        for node_id in deployment.target_nodes:
            if node_id not in self.edge_nodes:
                continue
            
            node = self.edge_nodes[node_id]
            
            try:
                # Simulate deployment
                await asyncio.sleep(0.1)  # Simulate deployment time
                
                # Update node capabilities
                deployment_capabilities = deployment.deployment_config.get("capabilities", [])
                node.capabilities.extend(deployment_capabilities)
                node.capabilities = list(set(node.capabilities))  # Remove duplicates
                
                deployment_results.append({
                    "node_id": node_id,
                    "status": "success",
                    "deployed_at": datetime.now().isoformat()
                })
                
                logger.info(f"Deployment successful on node: {node_id}")
                
            except Exception as e:
                deployment_results.append({
                    "node_id": node_id,
                    "status": "failed",
                    "error": str(e),
                    "deployed_at": datetime.now().isoformat()
                })
                
                logger.error(f"Deployment failed on node {node_id}: {e}")
        
        # Update deployment status
        deployment.deployed_at = datetime.now()
        deployment.metadata["deployment_results"] = deployment_results
        
        # Check if all deployments succeeded
        success_count = sum(1 for r in deployment_results if r["status"] == "success")
        deployment.status = "completed" if success_count == len(deployment.target_nodes) else "partial"
        
        # Emit deployment completion event
        await self.event_bus.emit(Event(
            type="edge_deployment_completed",
            data={
                "deployment_id": deployment_id,
                "status": deployment.status,
                "success_count": success_count,
                "total_nodes": len(deployment.target_nodes)
            }
        ))
    
    async def _schedule_tasks(self) -> None:
        """Background task to schedule tasks to appropriate edge nodes."""
        
        while True:
            try:
                if not self.task_queue:
                    await asyncio.sleep(1)
                    continue
                
                # Get next task
                task_id = self.task_queue.pop(0)
                task = self.edge_tasks[task_id]
                
                # Select appropriate node
                selected_node = await self._select_node_for_task(task)
                
                if selected_node:
                    # Assign task to node
                    task.assigned_node = selected_node
                    task.status = "assigned"
                    
                    # Update node load
                    self.node_loads[selected_node]["active_tasks"] += 1
                    
                    # Execute task
                    await self._execute_task(task_id, selected_node)
                else:
                    # No suitable node available, requeue
                    task.status = "pending"
                    self.task_queue.append(task_id)
                    
                    # Wait before retrying
                    await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Error in task scheduling: {e}")
                await asyncio.sleep(1)
    
    async def _select_node_for_task(self, task: EdgeTask) -> Optional[str]:
        """Select the best edge node for a task."""
        
        suitable_nodes = []
        
        # Find suitable nodes based on requirements
        for node_id, node in self.edge_nodes.items():
            if node.status != EdgeNodeStatus.ONLINE:
                continue
            
            # Check task requirements
            if not self._check_node_suitability(node, task):
                continue
            
            # Check node load
            node_load = self.node_loads[node_id]
            if node_load["cpu_usage"] > 0.8:  # Skip overloaded nodes
                continue
            
            suitable_nodes.append(node_id)
        
        if not suitable_nodes:
            return None
        
        # Select node based on load balancing strategy
        if self.load_balancer == LoadBalancingStrategy.RESOURCE_BASED:
            return self._select_by_resources(suitable_nodes, task)
        elif self.load_balancer == LoadBalancingStrategy.LEAST_CONNECTIONS:
            return self._select_by_connections(suitable_nodes)
        elif self.load_balancer == LoadBalancingStrategy.LATENCY_BASED:
            return self._select_by_latency(suitable_nodes)
        else:
            # Default to resource-based
            return self._select_by_resources(suitable_nodes, task)
    
    def _check_node_suitability(self, node: EdgeNode, task: EdgeTask) -> bool:
        """Check if a node is suitable for a task."""
        
        # Check capabilities
        required_capabilities = task.requirements.get("capabilities", [])
        if required_capabilities:
            if not all(cap in node.capabilities for cap in required_capabilities):
                return False
        
        # Check resources
        resource_requirements = task.requirements.get("resources", {})
        node_resources = node.resources
        
        if "cpu_min" in resource_requirements:
            if node_resources.get("cpu_capacity", 0) < resource_requirements["cpu_min"]:
                return False
        
        if "memory_min" in resource_requirements:
            if node_resources.get("memory_capacity", 0) < resource_requirements["memory_min"]:
                return False
        
        if "storage_min" in resource_requirements:
            if node_resources.get("storage_capacity", 0) < resource_requirements["storage_min"]:
                return False
        
        # Check constraints
        constraints = task.constraints
        if "location" in constraints:
            required_location = constraints["location"]
            node_location = node.location
            
            if "region" in required_location:
                if node_location.get("region") != required_location["region"]:
                    return False
        
        return True
    
    def _select_by_resources(self, nodes: List[str], task: EdgeTask) -> str:
        """Select node based on resource availability."""
        
        best_node = None
        best_score = -1
        
        for node_id in nodes:
            node = self.edge_nodes[node_id]
            node_load = self.node_loads[node_id]
            
            # Calculate resource score
            cpu_score = 1.0 - node_load["cpu_usage"]
            memory_score = 1.0 - node_load["memory_usage"]
            network_score = 1.0 - node_load["network_usage"]
            
            # Weighted score
            total_score = (cpu_score * 0.4 + memory_score * 0.3 + network_score * 0.3)
            
            if total_score > best_score:
                best_score = total_score
                best_node = node_id
        
        return best_node
    
    def _select_by_connections(self, nodes: List[str]) -> str:
        """Select node with least active connections."""
        
        best_node = None
        min_connections = float('inf')
        
        for node_id in nodes:
            active_tasks = self.node_loads[node_id]["active_tasks"]
            
            if active_tasks < min_connections:
                min_connections = active_tasks
                best_node = node_id
        
        return best_node
    
    def _select_by_latency(self, nodes: List[str]) -> str:
        """Select node with lowest latency."""
        
        best_node = None
        min_latency = float('inf')
        
        for node_id in nodes:
            # Use average latency to other nodes
            latencies = [latency for latency in self.latency_matrix[node_id].values()]
            avg_latency = statistics.mean(latencies) if latencies else 0
            
            if avg_latency < min_latency:
                min_latency = avg_latency
                best_node = node_id
        
        return best_node
    
    async def _execute_task(self, task_id: str, node_id: str) -> None:
        """Execute a task on an edge node."""
        
        if task_id not in self.edge_tasks:
            return
        
        task = self.edge_tasks[task_id]
        node = self.edge_nodes[node_id]
        
        try:
            # Update task status
            task.status = "running"
            task.progress = 0.0
            
            # Simulate task execution
            duration_seconds = task.estimated_duration.total_seconds()
            steps = 10
            
            for i in range(steps):
                await asyncio.sleep(duration_seconds / steps)
                
                # Update progress
                task.progress = (i + 1) / steps * 100
                
                # Update node load
                self._update_node_load(node_id, task)
                
                # Emit progress event
                await self.event_bus.emit(Event(
                    type="edge_task_progress",
                    data={
                        "task_id": task_id,
                        "node_id": node_id,
                        "progress": task.progress
                    }
                ))
            
            # Task completed
            task.status = "completed"
            task.progress = 100.0
            task.result = {
                "node_id": node_id,
                "execution_time": duration_seconds,
                "completed_at": datetime.now().isoformat()
            }
            
            # Update node load
            self.node_loads[node_id]["active_tasks"] -= 1
            
            # Update node performance metrics
            node.performance_metrics["tasks_completed"] = node.performance_metrics.get("tasks_completed", 0) + 1
            node.performance_metrics["avg_execution_time"] = self._calculate_avg_execution_time(node_id, duration_seconds)
            
            # Emit completion event
            await self.event_bus.emit(Event(
                type="edge_task_completed",
                data={
                    "task_id": task_id,
                    "node_id": node_id,
                    "result": task.result
                }
            ))
            
            logger.info(f"Task completed: {task_id} on node {node_id}")
            
        except Exception as e:
            # Task failed
            task.status = "failed"
            task.error = str(e)
            
            # Update node load
            self.node_loads[node_id]["active_tasks"] -= 1
            
            # Update node performance metrics
            node.performance_metrics["tasks_failed"] = node.performance_metrics.get("tasks_failed", 0) + 1
            
            # Emit failure event
            await self.event_bus.emit(Event(
                type="edge_task_failed",
                data={
                    "task_id": task_id,
                    "node_id": node_id,
                    "error": str(e)
                }
            ))
            
            logger.error(f"Task failed: {task_id} on node {node_id}: {e}")
    
    def _update_node_load(self, node_id: str, task: EdgeTask) -> None:
        """Update node load metrics."""
        
        node = self.edge_nodes[node_id]
        node_load = self.node_loads[node_id]
        
        # Simulate resource usage based on task requirements
        task_resources = task.requirements.get("resources", {})
        
        cpu_usage = task_resources.get("cpu_usage", 0.1)
        memory_usage = task_resources.get("memory_usage", 0.1)
        network_usage = task_resources.get("network_usage", 0.05)
        
        # Update load (simplified)
        node_load["cpu_usage"] = min(1.0, node_load["cpu_usage"] + cpu_usage * 0.1)
        node_load["memory_usage"] = min(1.0, node_load["memory_usage"] + memory_usage * 0.1)
        node_load["network_usage"] = min(1.0, node_load["network_usage"] + network_usage * 0.1)
        
        # Gradually decrease load (simulate resource release)
        asyncio.create_task(self._gradually_decrease_load(node_id))
    
    async def _gradually_decrease_load(self, node_id: str) -> None:
        """Gradually decrease node load after task completion."""
        
        await asyncio.sleep(10)  # Wait for resource cleanup
        
        node_load = self.node_loads[node_id]
        
        # Decrease load gradually
        node_load["cpu_usage"] = max(0.0, node_load["cpu_usage"] * 0.9)
        node_load["memory_usage"] = max(0.0, node_load["memory_usage"] * 0.9)
        node_load["network_usage"] = max(0.0, node_load["network_usage"] * 0.9)
    
    def _calculate_avg_execution_time(self, node_id: str, execution_time: float) -> float:
        """Calculate average execution time for a node."""
        
        node = self.edge_nodes[node_id]
        current_avg = node.performance_metrics.get("avg_execution_time", execution_time)
        completed_tasks = node.performance_metrics.get("tasks_completed", 1)
        
        # Exponential moving average
        alpha = 0.1
        new_avg = (1 - alpha) * current_avg + alpha * execution_time
        
        return new_avg
    
    def _update_network_topology(self, node_id: str, network_info: Dict[str, Any]) -> None:
        """Update network topology with new node."""
        
        # Add connections to other nodes
        connected_nodes = network_info.get("connected_nodes", [])
        self.network_topology[node_id] = connected_nodes
        
        # Update latency matrix (simulated)
        for connected_node in connected_nodes:
            if connected_node in self.edge_nodes:
                # Simulate latency based on location
                latency = self._calculate_latency(node_id, connected_node)
                self.latency_matrix[node_id][connected_node] = latency
                self.latency_matrix[connected_node][node_id] = latency
    
    def _calculate_latency(self, node1_id: str, node2_id: str) -> float:
        """Calculate latency between two nodes (simulated)."""
        
        node1 = self.edge_nodes[node1_id]
        node2 = self.edge_nodes[node2_id]
        
        # Calculate distance-based latency
        location1 = node1.location
        location2 = node2.location
        
        # Simple distance calculation
        if "lat" in location1 and "lon" in location1 and "lat" in location2 and "lon" in location2:
            lat1, lon1 = location1["lat"], location1["lon"]
            lat2, lon2 = location2["lat"], location2["lon"]
            
            # Haversine distance (simplified)
            distance = abs(lat1 - lat2) + abs(lon1 - lon2)
            
            # Base latency + distance factor
            base_latency = 1.0  # 1ms base latency
            distance_factor = distance * 10  # 10ms per degree
            
            return base_latency + distance_factor
        else:
            # Default latency
            return 5.0  # 5ms default
    
    async def _monitor_heartbeats(self) -> None:
        """Background task to monitor node heartbeats."""
        
        while True:
            try:
                now = datetime.now()
                timeout = timedelta(minutes=5)  # 5 minute timeout
                
                offline_nodes = []
                
                for node_id, node in self.edge_nodes.items():
                    if now - node.last_heartbeat > timeout:
                        node.status = EdgeNodeStatus.OFFLINE
                        offline_nodes.append(node_id)
                        
                        logger.warning(f"Node offline: {node_id}")
                        
                        # Emit offline event
                        await self.event_bus.emit(Event(
                            type="edge_node_offline",
                            data={"node_id": node_id}
                        ))
                
                # Clean up tasks on offline nodes
                for node_id in offline_nodes:
                    await self._cleanup_node_tasks(node_id)
                
                # Sleep for 30 seconds
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error(f"Error in heartbeat monitoring: {e}")
                await asyncio.sleep(10)
    
    async def _cleanup_node_tasks(self, node_id: str) -> None:
        """Clean up tasks on an offline node."""
        
        # Find tasks assigned to this node
        affected_tasks = []
        
        for task_id, task in self.edge_tasks.items():
            if task.assigned_node == node_id and task.status in ["assigned", "running"]:
                task.status = "failed"
                task.error = f"Node {node_id} went offline"
                affected_tasks.append(task_id)
        
        # Update node load
        if node_id in self.node_loads:
            self.node_loads[node_id]["active_tasks"] = 0
        
        # Emit cleanup event
        if affected_tasks:
            await self.event_bus.emit(Event(
                type="edge_node_tasks_cleaned",
                data={
                    "node_id": node_id,
                    "affected_tasks": affected_tasks
                }
            ))
    
    async def _balance_load(self) -> None:
        """Background task to balance load across nodes."""
        
        while True:
            try:
                # Calculate load imbalance
                loads = [load["cpu_usage"] for load in self.node_loads.values()]
                
                if len(loads) > 1:
                    avg_load = statistics.mean(loads)
                    max_load = max(loads)
                    
                    # If imbalance is significant, rebalance
                    if max_load - avg_load > 0.3:  # 30% imbalance threshold
                        await self._rebalance_load()
                
                # Sleep for 2 minutes
                await asyncio.sleep(120)
                
            except Exception as e:
                logger.error(f"Error in load balancing: {e}")
                await asyncio.sleep(30)
    
    async def _rebalance_load(self) -> None:
        """Rebalance load across nodes."""
        
        # Find overloaded and underloaded nodes
        overloaded_nodes = []
        underloaded_nodes = []
        
        avg_load = statistics.mean([load["cpu_usage"] for load in self.node_loads.values()])
        
        for node_id, load in self.node_loads.items():
            if load["cpu_usage"] > avg_load + 0.2:
                overloaded_nodes.append((node_id, load["cpu_usage"]))
            elif load["cpu_usage"] < avg_load - 0.2:
                underloaded_nodes.append((node_id, load["cpu_usage"]))
        
        # Migrate tasks from overloaded to underloaded nodes
        for overloaded_node, _ in overloaded_nodes:
            if not underloaded_nodes:
                break
            
            # Find tasks that can be migrated
            migratable_tasks = []
            
            for task_id, task in self.edge_tasks.items():
                if (task.assigned_node == overloaded_node and 
                    task.status == "running" and
                    task.priority != TaskPriority.REAL_TIME):  # Don't migrate real-time tasks
                    migratable_tasks.append(task_id)
            
            # Migrate some tasks
            for task_id in migratable_tasks[:2]:  # Migrate up to 2 tasks
                if not underloaded_nodes:
                    break
                
                # Select best underloaded node
                underloaded_node, _ = min(underloaded_nodes, key=lambda x: x[1])
                
                # Migrate task
                await self._migrate_task(task_id, overloaded_node, underloaded_node)
                
                # Update underloaded nodes list
                underloaded_nodes = [(nid, load) for nid, load in underloaded_nodes if nid != underloaded_node]
                
                logger.info(f"Migrated task {task_id} from {overloaded_node} to {underloaded_node}")
    
    async def _migrate_task(self, task_id: str, from_node: str, to_node: str) -> None:
        """Migrate a task from one node to another."""
        
        if task_id not in self.edge_tasks:
            return
        
        task = self.edge_tasks[task_id]
        
        # Update task assignment
        task.assigned_node = to_node
        
        # Update node loads
        self.node_loads[from_node]["active_tasks"] -= 1
        self.node_loads[to_node]["active_tasks"] += 1
        
        # Emit migration event
        await self.event_bus.emit(Event(
            type="edge_task_migrated",
            data={
                "task_id": task_id,
                "from_node": from_node,
                "to_node": to_node
            }
        ))
    
    async def _monitor_performance(self) -> None:
        """Background task to monitor edge computing performance."""
        
        while True:
            try:
                # Collect performance metrics
                for node_id, node in self.edge_nodes.items():
                    if node.status == EdgeNodeStatus.ONLINE:
                        metrics = {
                            "timestamp": datetime.now().isoformat(),
                            "cpu_usage": self.node_loads[node_id]["cpu_usage"],
                            "memory_usage": self.node_loads[node_id]["memory_usage"],
                            "network_usage": self.node_loads[node_id]["network_usage"],
                            "active_tasks": self.node_loads[node_id]["active_tasks"],
                            "tasks_completed": node.performance_metrics.get("tasks_completed", 0),
                            "tasks_failed": node.performance_metrics.get("tasks_failed", 0),
                            "avg_execution_time": node.performance_metrics.get("avg_execution_time", 0)
                        }
                        
                        self.performance_metrics[node_id].append(metrics)
                        
                        # Keep only last 100 metrics
                        if len(self.performance_metrics[node_id]) > 100:
                            self.performance_metrics[node_id] = self.performance_metrics[node_id][-100:]
                
                # Sleep for 1 minute
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Error in performance monitoring: {e}")
                await asyncio.sleep(15)
    
    async def get_edge_computing_stats(self) -> Dict[str, Any]:
        """Get comprehensive edge computing statistics."""
        
        stats = {
            "nodes": {
                "total": len(self.edge_nodes),
                "online": len([n for n in self.edge_nodes.values() if n.status == EdgeNodeStatus.ONLINE]),
                "offline": len([n for n in self.edge_nodes.values() if n.status == EdgeNodeStatus.OFFLINE]),
                "by_type": {
                    node_type.value: len([n for n in self.edge_nodes.values() if n.node_type == node_type])
                    for node_type in EdgeNodeType
                }
            },
            "tasks": {
                "total": len(self.edge_tasks),
                "pending": len([t for t in self.edge_tasks.values() if t.status == "pending"]),
                "running": len([t for t in self.edge_tasks.values() if t.status == "running"]),
                "completed": len([t for t in self.edge_tasks.values() if t.status == "completed"]),
                "failed": len([t for t in self.edge_tasks.values() if t.status == "failed"]),
                "queue_length": len(self.task_queue)
            },
            "deployments": {
                "total": len(self.edge_deployments),
                "completed": len([d for d in self.edge_deployments.values() if d.status == "completed"]),
                "pending": len([d for d in self.edge_deployments.values() if d.status == "pending"])
            },
            "performance": {
                "avg_cpu_usage": statistics.mean([load["cpu_usage"] for load in self.node_loads.values()]) if self.node_loads else 0,
                "avg_memory_usage": statistics.mean([load["memory_usage"] for load in self.node_loads.values()]) if self.node_loads else 0,
                "avg_network_usage": statistics.mean([load["network_usage"] for load in self.node_loads.values()]) if self.node_loads else 0,
                "total_active_tasks": sum(load["active_tasks"] for load in self.node_loads.values())
            },
            "load_balancing": {
                "strategy": self.load_balancer.value,
                "imbalance_score": self._calculate_load_imbalance()
            }
        }
        
        return stats
    
    def _calculate_load_imbalance(self) -> float:
        """Calculate load imbalance score."""
        
        loads = [load["cpu_usage"] for load in self.node_loads.values()]
        
        if not loads:
            return 0.0
        
        avg_load = statistics.mean(loads)
        
        if avg_load == 0:
            return 0.0
        
        # Calculate coefficient of variation
        std_dev = statistics.stdev(loads) if len(loads) > 1 else 0
        imbalance_score = std_dev / avg_load
        
        return imbalance_score
    
    async def shutdown(self) -> None:
        """Shutdown the edge computing orchestrator."""
        
        # Cancel background tasks
        if self._heartbeat_monitor_task:
            self._heartbeat_monitor_task.cancel()
            try:
                await self._heartbeat_monitor_task
            except asyncio.CancelledError:
                pass
        
        if self._task_scheduler_task:
            self._task_scheduler_task.cancel()
            try:
                await self._task_scheduler_task
            except asyncio.CancelledError:
                pass
        
        if self._load_balancer_task:
            self._load_balancer_task.cancel()
            try:
                await self._load_balancer_task
            except asyncio.CancelledError:
                pass
        
        if self._performance_monitor_task:
            self._performance_monitor_task.cancel()
            try:
                await self._performance_monitor_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Edge computing orchestrator shutdown completed")