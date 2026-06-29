"""Distributed Orchestration Architecture - Multi-instance coordination.

Enables horizontal scaling of the NEXUS IDE orchestration system across multiple
instances with message queues, load balancing, and distributed state management.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from collections import defaultdict
from enum import Enum
import socket

from backend.tools.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class NodeStatus(str, Enum):
    """Status of orchestration nodes."""
    STARTING = "starting"
    ACTIVE = "active"
    BUSY = "busy"
    IDLE = "idle"
    SHUTTING_DOWN = "shutting_down"
    FAILED = "failed"


class TaskStatus(str, Enum):
    """Status of distributed tasks."""
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MessageType(str, Enum):
    """Types of messages in the distributed system."""
    TASK_ASSIGNMENT = "task_assignment"
    TASK_RESULT = "task_result"
    HEARTBEAT = "heartbeat"
    NODE_JOIN = "node_join"
    NODE_LEAVE = "node_leave"
    LOAD_BALANCE = "load_balance"
    STATE_SYNC = "state_sync"
    HEALTH_CHECK = "health_check"


@dataclass
class OrchestrationNode:
    """A node in the distributed orchestration system."""
    node_id: str
    host: str
    port: int
    status: NodeStatus
    capabilities: Set[str]
    current_load: int = 0
    max_load: int = 10
    last_heartbeat: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        self.node_id = self.node_id or self._generate_node_id()
    
    def _generate_node_id(self) -> str:
        """Generate a unique node ID."""
        return f"{socket.gethostname()}:{self.port}:{uuid.uuid4().hex[:8]}"
    
    @property
    def is_available(self) -> bool:
        """Check if node is available for tasks."""
        return (self.status == NodeStatus.ACTIVE and 
                self.current_load < self.max_load and
                (time.time() - self.last_heartbeat) < 30)  # 30s heartbeat timeout
    
    @property
    def load_ratio(self) -> float:
        """Get the current load ratio."""
        return self.current_load / self.max_load if self.max_load > 0 else 1.0


@dataclass
class DistributedTask:
    """A task that can be distributed across nodes."""
    task_id: str
    task_type: str
    payload: Dict[str, Any]
    priority: int = 0
    required_capabilities: Set[str] = field(default_factory=set)
    assigned_node_id: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    assigned_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3


@dataclass
class DistributedMessage:
    """A message in the distributed system."""
    message_id: str
    message_type: MessageType
    sender_id: str
    recipient_id: Optional[str]  # None for broadcast
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    
    def __post_init__(self) -> None:
        self.message_id = self.message_id or uuid.uuid4().hex


class DistributedOrchestrator:
    """Distributed orchestration system for horizontal scaling.
    
    Features:
    - Multi-node coordination
    - Load balancing
    - Fault tolerance
    - Distributed state management
    - Message queuing
    - Health monitoring
    """
    
    def __init__(
        self,
        ollama_client: OllamaClient,
        *,
        node_host: str = "localhost",
        node_port: int = 8000,
        max_nodes: int = 10,
        heartbeat_interval: float = 10.0,
        task_timeout: float = 300.0,
        enable_state_sync: bool = True,
    ) -> None:
        self.ollama = ollama_client
        self.node_host = node_host
        self.node_port = node_port
        self.max_nodes = max_nodes
        self.heartbeat_interval = heartbeat_interval
        self.task_timeout = task_timeout
        self.enable_state_sync = enable_state_sync
        
        # Node information
        self.local_node = OrchestrationNode(
            node_id="",
            host=node_host,
            port=node_port,
            status=NodeStatus.STARTING,
            capabilities={"orchestration", "agent_execution", "model_management"}
        )
        
        # Distributed state
        self._nodes: Dict[str, OrchestrationNode] = {}
        self._tasks: Dict[str, DistributedTask] = {}
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        
        # Load balancing
        self._load_balancer = LoadBalancer(self._nodes)
        
        # Background tasks
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._task_processor_task: Optional[asyncio.Task] = None
        self._health_monitor_task: Optional[asyncio.Task] = None
        self._message_processor_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Lock for thread safety
        self._lock = asyncio.Lock()
    
    async def start(self) -> None:
        """Start the distributed orchestrator."""
        if self._running:
            return
        
        self._running = True
        
        # Add local node
        self._nodes[self.local_node.node_id] = self.local_node
        self.local_node.status = NodeStatus.ACTIVE
        
        # Start background tasks
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._task_processor_task = asyncio.create_task(self._task_processor_loop())
        self._health_monitor_task = asyncio.create_task(self._health_monitor_loop())
        self._message_processor_task = asyncio.create_task(self._message_processor_loop())
        
        # Announce node join
        await self._broadcast_message(
            MessageType.NODE_JOIN,
            {"node": self._node_to_dict(self.local_node)}
        )
        
        logger.info(
            "Distributed Orchestrator started on %s:%s (node_id: %s)",
            self.node_host, self.node_port, self.local_node.node_id
        )
    
    async def stop(self) -> None:
        """Stop the distributed orchestrator."""
        self._running = False
        self.local_node.status = NodeStatus.SHUTTING_DOWN
        
        # Announce node leave
        await self._broadcast_message(
            MessageType.NODE_LEAVE,
            {"node_id": self.local_node.node_id}
        )
        
        # Cancel background tasks
        tasks = [
            self._heartbeat_task,
            self._task_processor_task,
            self._health_monitor_task,
            self._message_processor_task
        ]
        
        for task in tasks:
            if task:
                task.cancel()
        
        # Wait for tasks to complete
        await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.info("Distributed Orchestrator stopped")
    
    async def submit_task(
        self,
        task_type: str,
        payload: Dict[str, Any],
        priority: int = 0,
        required_capabilities: Optional[Set[str]] = None
    ) -> str:
        """Submit a task for distributed execution."""
        task = DistributedTask(
            task_id=uuid.uuid4().hex,
            task_type=task_type,
            payload=payload,
            priority=priority,
            required_capabilities=required_capabilities or set()
        )
        
        async with self._lock:
            self._tasks[task.task_id] = task
            # Add to priority queue (negative priority for max-heap behavior)
            await self._task_queue.put((-priority, task.task_id))
        
        logger.debug("Submitted task %s of type %s", task.task_id, task_type)
        return task.task_id
    
    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of a task."""
        async with self._lock:
            if task_id not in self._tasks:
                return None
            
            task = self._tasks[task_id]
            return {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "status": task.status.value,
                "assigned_node_id": task.assigned_node_id,
                "created_at": task.created_at,
                "assigned_at": task.assigned_at,
                "completed_at": task.completed_at,
                "error": task.error,
                "retry_count": task.retry_count,
            }
    
    async def get_cluster_status(self) -> Dict[str, Any]:
        """Get the status of the entire cluster."""
        async with self._lock:
            active_nodes = sum(1 for node in self._nodes.values() if node.is_available)
            total_load = sum(node.current_load for node in self._nodes.values())
            max_capacity = sum(node.max_load for node in self._nodes.values())
            
            return {
                "local_node_id": self.local_node.node_id,
                "total_nodes": len(self._nodes),
                "active_nodes": active_nodes,
                "total_tasks": len(self._tasks),
                "pending_tasks": sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING),
                "running_tasks": sum(1 for t in self._tasks.values() if t.status == TaskStatus.RUNNING),
                "completed_tasks": sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED),
                "failed_tasks": sum(1 for t in self._tasks.values() if t.status == TaskStatus.FAILED),
                "total_load": total_load,
                "max_capacity": max_capacity,
                "utilization": total_load / max_capacity if max_capacity > 0 else 0.0,
                "nodes": {
                    node_id: {
                        "host": node.host,
                        "port": node.port,
                        "status": node.status.value,
                        "load": node.current_load,
                        "max_load": node.max_load,
                        "load_ratio": node.load_ratio,
                        "capabilities": list(node.capabilities),
                        "last_heartbeat": node.last_heartbeat,
                    }
                    for node_id, node in self._nodes.items()
                }
            }
    
    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to other nodes."""
        while self._running:
            try:
                self.local_node.last_heartbeat = time.time()
                
                await self._broadcast_message(
                    MessageType.HEARTBEAT,
                    {
                        "node_id": self.local_node.node_id,
                        "load": self.local_node.current_load,
                        "status": self.local_node.status.value
                    }
                )
                
                await asyncio.sleep(self.heartbeat_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat loop error: %s", e)
                await asyncio.sleep(self.heartbeat_interval)
    
    async def _task_processor_loop(self) -> None:
        """Process tasks from the queue."""
        while self._running:
            try:
                # Get next task (blocking)
                priority_neg, task_id = await self._task_queue.get()
                
                async with self._lock:
                    if task_id not in self._tasks:
                        continue
                    
                    task = self._tasks[task_id]
                    
                    if task.status != TaskStatus.PENDING:
                        continue
                
                # Find suitable node
                suitable_node = await self._find_suitable_node(task)
                
                if suitable_node:
                    await self._assign_task_to_node(task, suitable_node)
                else:
                    # No suitable node available, requeue with delay
                    await asyncio.sleep(5.0)
                    await self._task_queue.put((-priority_neg, task_id))
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Task processor loop error: %s", e)
                await asyncio.sleep(1.0)
    
    async def _health_monitor_loop(self) -> None:
        """Monitor health of all nodes."""
        while self._running:
            try:
                current_time = time.time()
                
                async with self._lock:
                    # Check for failed nodes
                    failed_nodes = []
                    for node_id, node in self._nodes.items():
                        if (node_id != self.local_node.node_id and
                            (current_time - node.last_heartbeat) > (self.heartbeat_interval * 3)):
                            failed_nodes.append(node_id)
                    
                    # Handle failed nodes
                    for node_id in failed_nodes:
                        await self._handle_node_failure(node_id)
                    
                    # Check for timed out tasks
                    timed_out_tasks = []
                    for task_id, task in self._tasks.items():
                        if (task.status == TaskStatus.RUNNING and
                            task.assigned_at and
                            (current_time - task.assigned_at) > self.task_timeout):
                            timed_out_tasks.append(task_id)
                    
                    # Handle timed out tasks
                    for task_id in timed_out_tasks:
                        await self._handle_task_timeout(task_id)
                
                await asyncio.sleep(self.heartbeat_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Health monitor loop error: %s", e)
                await asyncio.sleep(self.heartbeat_interval)
    
    async def _message_processor_loop(self) -> None:
        """Process messages from the queue."""
        while self._running:
            try:
                # Get next message (blocking)
                message = await self._message_queue.get()
                await self._process_message(message)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Message processor loop error: %s", e)
                await asyncio.sleep(1.0)
    
    async def _find_suitable_node(self, task: DistributedTask) -> Optional[OrchestrationNode]:
        """Find a suitable node for the task."""
        suitable_nodes = [
            node for node in self._nodes.values()
            if (node.is_available and
                task.required_capabilities.issubset(node.capabilities))
        ]
        
        if not suitable_nodes:
            return None
        
        # Use load balancer to select best node
        return self._load_balancer.select_node(suitable_nodes)
    
    async def _assign_task_to_node(self, task: DistributedTask, node: OrchestrationNode) -> None:
        """Assign a task to a specific node."""
        async with self._lock:
            task.assigned_node_id = node.node_id
            task.assigned_at = time.time()
            task.status = TaskStatus.ASSIGNED
            
            node.current_load += 1
        
        # Send task assignment message
        if node.node_id == self.local_node.node_id:
            # Local assignment
            await self._execute_local_task(task)
        else:
            # Remote assignment
            await self._send_message_to_node(
                node.node_id,
                MessageType.TASK_ASSIGNMENT,
                {"task": self._task_to_dict(task)}
            )
    
    async def _execute_local_task(self, task: DistributedTask) -> None:
        """Execute a task locally."""
        async with self._lock:
            task.status = TaskStatus.RUNNING
        
        try:
            # Execute task based on type
            if task.task_type == "agent_execution":
                result = await self._execute_agent_task(task.payload)
            elif task.task_type == "model_management":
                result = await self._execute_model_task(task.payload)
            else:
                result = {"error": f"Unknown task type: {task.task_type}"}
            
            # Task completed successfully
            await self._complete_task(task, result)
            
        except Exception as e:
            logger.error("Local task execution failed: %s", e)
            await self._fail_task(task, str(e))
    
    async def _execute_agent_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an agent task."""
        # This would integrate with the existing agent system
        # For now, return a mock result
        return {
            "agent": payload.get("agent", "unknown"),
            "response": "Task executed successfully",
            "execution_time_ms": 1000,
            "tokens_used": 500
        }
    
    async def _execute_model_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a model management task."""
        # This would integrate with the model pool system
        # For now, return a mock result
        return {
            "model": payload.get("model", "unknown"),
            "operation": payload.get("operation", "unknown"),
            "result": "Model operation completed successfully"
        }
    
    async def _complete_task(self, task: DistributedTask, result: Dict[str, Any]) -> None:
        """Mark a task as completed."""
        async with self._lock:
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            task.result = result
            
            # Update node load
            if task.assigned_node_id and task.assigned_node_id in self._nodes:
                self._nodes[task.assigned_node_id].current_load -= 1
        
        # Broadcast task completion
        await self._broadcast_message(
            MessageType.TASK_RESULT,
            {
                "task_id": task.task_id,
                "status": "completed",
                "result": result
            }
        )
        
        logger.info("Task %s completed successfully", task.task_id)
    
    async def _fail_task(self, task: DistributedTask, error: str) -> None:
        """Mark a task as failed."""
        async with self._lock:
            task.status = TaskStatus.FAILED
            task.error = error
            
            # Update node load
            if task.assigned_node_id and task.assigned_node_id in self._nodes:
                self._nodes[task.assigned_node_id].current_load -= 1
            
            # Check if we should retry
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                task.status = TaskStatus.PENDING
                task.assigned_node_id = None
                task.assigned_at = None
                
                # Requeue for retry
                await self._task_queue.put((-task.priority, task.task_id))
                logger.info("Task %s queued for retry (%d/%d)", task.task_id, task.retry_count, task.max_retries)
        
        # Broadcast task failure
        await self._broadcast_message(
            MessageType.TASK_RESULT,
            {
                "task_id": task.task_id,
                "status": "failed",
                "error": error,
                "retry_count": task.retry_count
            }
        )
        
        logger.error("Task %s failed: %s", task.task_id, error)
    
    async def _handle_node_failure(self, node_id: str) -> None:
        """Handle failure of a node."""
        async with self._lock:
            if node_id not in self._nodes:
                return
            
            failed_node = self._nodes[node_id]
            failed_node.status = NodeStatus.FAILED
            
            # Reassign failed node's tasks
            failed_tasks = [
                task for task in self._tasks.values()
                if task.assigned_node_id == node_id and task.status == TaskStatus.RUNNING
            ]
            
            for task in failed_tasks:
                task.status = TaskStatus.PENDING
                task.assigned_node_id = None
                task.assigned_at = None
                
                # Requeue task
                await self._task_queue.put((-task.priority, task.task_id))
            
            # Remove failed node
            del self._nodes[node_id]
        
        logger.warning("Node %s failed, reassigned %d tasks", node_id, len(failed_tasks))
    
    async def _handle_task_timeout(self, task_id: str) -> None:
        """Handle a timed out task."""
        async with self._lock:
            if task_id not in self._tasks:
                return
            
            task = self._tasks[task_id]
            await self._fail_task(task, "Task timed out")
    
    async def _process_message(self, message: DistributedMessage) -> None:
        """Process an incoming message."""
        try:
            if message.message_type == MessageType.HEARTBEAT:
                await self._handle_heartbeat(message)
            elif message.message_type == MessageType.NODE_JOIN:
                await self._handle_node_join(message)
            elif message.message_type == MessageType.NODE_LEAVE:
                await self._handle_node_leave(message)
            elif message.message_type == MessageType.TASK_ASSIGNMENT:
                await self._handle_task_assignment(message)
            elif message.message_type == MessageType.TASK_RESULT:
                await self._handle_task_result(message)
            elif message.message_type == MessageType.LOAD_BALANCE:
                await self._handle_load_balance(message)
            else:
                logger.warning("Unknown message type: %s", message.message_type)
        
        except Exception as e:
            logger.error("Message processing error: %s", e)
    
    async def _handle_heartbeat(self, message: DistributedMessage) -> None:
        """Handle heartbeat message."""
        payload = message.payload
        node_id = payload.get("node_id")
        
        if node_id and node_id in self._nodes:
            self._nodes[node_id].last_heartbeat = time.time()
            self._nodes[node_id].current_load = payload.get("load", 0)
            self._nodes[node_id].status = NodeStatus(payload.get("status", "active"))
    
    async def _handle_node_join(self, message: DistributedMessage) -> None:
        """Handle node join message."""
        payload = message.payload
        node_data = payload.get("node")
        
        if node_data:
            node = self._dict_to_node(node_data)
            if node.node_id != self.local_node.node_id:
                self._nodes[node.node_id] = node
                logger.info("Node %s joined the cluster", node.node_id)
    
    async def _handle_node_leave(self, message: DistributedMessage) -> None:
        """Handle node leave message."""
        payload = message.payload
        node_id = payload.get("node_id")
        
        if node_id and node_id in self._nodes:
            del self._nodes[node_id]
            logger.info("Node %s left the cluster", node_id)
    
    async def _handle_task_assignment(self, message: DistributedMessage) -> None:
        """Handle task assignment message."""
        payload = message.payload
        task_data = payload.get("task")
        
        if task_data:
            task = self._dict_to_task(task_data)
            await self._execute_local_task(task)
    
    async def _handle_task_result(self, message: DistributedMessage) -> None:
        """Handle task result message."""
        payload = message.payload
        task_id = payload.get("task_id")
        status = payload.get("status")
        
        if task_id and task_id in self._tasks:
            task = self._tasks[task_id]
            
            if status == "completed":
                task.result = payload.get("result")
                await self._complete_task(task, task.result)
            elif status == "failed":
                await self._fail_task(task, payload.get("error", "Unknown error"))
    
    async def _handle_load_balance(self, message: DistributedMessage) -> None:
        """Handle load balance message."""
        # Implement load balancing logic
        pass
    
    async def _broadcast_message(self, message_type: MessageType, payload: Dict[str, Any]) -> None:
        """Broadcast a message to all nodes."""
        message = DistributedMessage(
            message_id="",
            message_type=message_type,
            sender_id=self.local_node.node_id,
            recipient_id=None,  # Broadcast
            payload=payload
        )
        
        # Add to local message queue
        await self._message_queue.put(message)
        
        # In a real implementation, this would send to other nodes via network
        # For now, we just log it
        logger.debug("Broadcast message: %s", message_type.value)
    
    async def _send_message_to_node(self, node_id: str, message_type: MessageType, payload: Dict[str, Any]) -> None:
        """Send a message to a specific node."""
        message = DistributedMessage(
            message_id="",
            message_type=message_type,
            sender_id=self.local_node.node_id,
            recipient_id=node_id,
            payload=payload
        )
        
        # In a real implementation, this would send to the target node via network
        # For now, we just log it
        logger.debug("Sent message to node %s: %s", node_id, message_type.value)
    
    def _node_to_dict(self, node: OrchestrationNode) -> Dict[str, Any]:
        """Convert node to dictionary."""
        return {
            "node_id": node.node_id,
            "host": node.host,
            "port": node.port,
            "status": node.status.value,
            "capabilities": list(node.capabilities),
            "current_load": node.current_load,
            "max_load": node.max_load,
            "metadata": node.metadata
        }
    
    def _dict_to_node(self, data: Dict[str, Any]) -> OrchestrationNode:
        """Convert dictionary to node."""
        return OrchestrationNode(
            node_id=data["node_id"],
            host=data["host"],
            port=data["port"],
            status=NodeStatus(data["status"]),
            capabilities=set(data["capabilities"]),
            current_load=data["current_load"],
            max_load=data["max_load"],
            metadata=data.get("metadata", {})
        )
    
    def _task_to_dict(self, task: DistributedTask) -> Dict[str, Any]:
        """Convert task to dictionary."""
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "payload": task.payload,
            "priority": task.priority,
            "required_capabilities": list(task.required_capabilities),
            "assigned_node_id": task.assigned_node_id,
            "status": task.status.value,
            "created_at": task.created_at,
            "assigned_at": task.assigned_at,
            "completed_at": task.completed_at,
            "result": task.result,
            "error": task.error,
            "retry_count": task.retry_count,
            "max_retries": task.max_retries
        }
    
    def _dict_to_task(self, data: Dict[str, Any]) -> DistributedTask:
        """Convert dictionary to task."""
        return DistributedTask(
            task_id=data["task_id"],
            task_type=data["task_type"],
            payload=data["payload"],
            priority=data["priority"],
            required_capabilities=set(data["required_capabilities"]),
            assigned_node_id=data.get("assigned_node_id"),
            status=TaskStatus(data["status"]),
            created_at=data["created_at"],
            assigned_at=data.get("assigned_at"),
            completed_at=data.get("completed_at"),
            result=data.get("result"),
            error=data.get("error"),
            retry_count=data["retry_count"],
            max_retries=data["max_retries"]
        )


class LoadBalancer:
    """Load balancer for distributing tasks across nodes."""
    
    def __init__(self, nodes: Dict[str, OrchestrationNode]) -> None:
        self._nodes = nodes
    
    def select_node(self, suitable_nodes: List[OrchestrationNode]) -> OrchestrationNode:
        """Select the best node for a task using load balancing algorithm."""
        if not suitable_nodes:
            raise ValueError("No suitable nodes available")
        
        # Sort by load ratio (ascending)
        suitable_nodes.sort(key=lambda node: node.load_ratio)
        
        # Select the node with lowest load
        return suitable_nodes[0]


# Global distributed orchestrator instance
_distributed_orchestrator: Optional[DistributedOrchestrator] = None


def get_distributed_orchestrator(
    ollama_client: OllamaClient,
    **kwargs
) -> DistributedOrchestrator:
    """Get the global distributed orchestrator instance."""
    global _distributed_orchestrator
    if _distributed_orchestrator is None:
        _distributed_orchestrator = DistributedOrchestrator(ollama_client, **kwargs)
    return _distributed_orchestrator
