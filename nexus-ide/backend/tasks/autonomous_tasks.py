"""Autonomous Tasks System - Self-executing tasks for NEXUS OMEGA.

This system provides:
- Autonomous task scheduling
- Task lifecycle management
- Self-healing capabilities
- Task dependency resolution
- Autonomous decision making
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Callable
from dataclasses import dataclass, field
from enum import Enum
import uuid

from backend.observability.event_system import EventBus, Event, EventType, EventPriority

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task execution status."""
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"
    WAITING = "waiting"


class TaskPriority(str, Enum):
    """Task priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"
    URGENT = "urgent"


class TaskType(str, Enum):
    """Types of autonomous tasks."""
    MONITORING = "monitoring"
    OPTIMIZATION = "optimization"
    MAINTENANCE = "maintenance"
    ANALYSIS = "analysis"
    LEARNING = "learning"
    CLEANUP = "cleanup"
    HEALTH_CHECK = "health_check"
    PERFORMANCE_TUNING = "performance_tuning"
    ERROR_RECOVERY = "error_recovery"


@dataclass
class Task:
    """Autonomous task definition."""
    task_id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:12]}")
    name: str = ""
    task_type: TaskType = TaskType.MONITORING
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    
    # Scheduling
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Execution
    handler: Optional[Callable] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    dependencies: Set[str] = field(default_factory=set)
    
    # Configuration
    retry_count: int = 0
    max_retries: int = 3
    timeout: int = 300  # seconds
    interval: Optional[int] = None  # For recurring tasks
    auto_retry: bool = True
    
    # Results
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary."""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "task_type": self.task_type.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "handler": self.handler.__name__ if self.handler else None,
            "parameters": self.parameters,
            "dependencies": list(self.dependencies),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
            "interval": self.interval,
            "auto_retry": self.auto_retry,
            "result": self.result,
            "error": self.error,
            "execution_time": self.execution_time,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata
        }


class TaskScheduler:
    """Schedules and manages autonomous tasks."""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.tasks: Dict[str, Task] = {}
        self.task_queue: List[Task] = []
        self.running_tasks: Dict[str, Task] = {}
        self.completed_tasks: List[Task] = []
        self.failed_tasks: List[Task] = []
        
        # Scheduling
        self._running = False
        self._scheduler_task: Optional[asyncio.Task] = None
        self._max_concurrent = 10
        self._cleanup_interval = 300  # 5 minutes
        
        # Statistics
        self.stats = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "running_tasks": 0,
            "scheduled_tasks": 0,
            "average_execution_time": 0.0
        }
    
    async def start(self) -> None:
        """Start the task scheduler."""
        if self._running:
            return
        
        self._running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("TaskScheduler started")
    
    async def stop(self) -> None:
        """Stop the task scheduler."""
        self._running = False
        
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            self._scheduler_task = None
        
        # Cancel running tasks
        for task in list(self.running_tasks.values()):
            await self.cancel_task(task.task_id)
        
        logger.info("TaskScheduler stopped")
    
    async def schedule_task(self, task: Task) -> str:
        """Schedule a new autonomous task."""
        # Validate task
        if not task.name:
            raise ValueError("Task name is required")
        
        if not task.handler:
            raise ValueError("Task handler is required")
        
        # Add to tasks
        self.tasks[task.task_id] = task
        self.task_queue.append(task)
        self.stats["total_tasks"] += 1
        self.stats["scheduled_tasks"] += 1
        
        # Update status
        task.status = TaskStatus.SCHEDULED
        task.updated_at = datetime.now()
        
        # Sort queue by priority
        self.task_queue.sort(key=lambda t: (
            self._get_priority_value(t.priority),
            t.scheduled_at or datetime.now()
        ))
        
        # Emit scheduling event
        await self._emit_task_event("task_scheduled", task)
        
        logger.info(f"Task scheduled: {task.name} ({task.task_id})")
        return task.task_id
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        
        if task.status in [TaskStatus.RUNNING, TaskStatus.RETRYING]:
            # Cancel running task
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]
                self.stats["running_tasks"] -= 1
        
        task.status = TaskStatus.CANCELLED
        task.updated_at = datetime.now()
        
        # Remove from queue if pending
        if task in self.task_queue:
            self.task_queue.remove(task)
        
        # Add to completed tasks
        self.completed_tasks.append(task)
        
        # Emit cancellation event
        await self._emit_task_event("task_cancelled", task)
        
        logger.info(f"Task cancelled: {task.name} ({task_id})")
        return True
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        return self.tasks.get(task_id)
    
    async def get_tasks(self, status: Optional[TaskStatus] = None, 
                     task_type: Optional[TaskType] = None,
                     limit: int = 100) -> List[Task]:
        """Get tasks with optional filtering."""
        tasks = list(self.tasks.values())
        
        # Apply filters
        if status:
            tasks = [t for t in tasks if t.status == status]
        if task_type:
            tasks = [t for t in tasks if t.task_type == task_type]
        
        # Sort and limit
        tasks.sort(key=lambda t: t.updated_at, reverse=True)
        return tasks[:limit]
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get scheduler statistics."""
        # Calculate average execution time
        if self.stats["completed_tasks"] > 0:
            total_time = sum(t.execution_time for t in self.completed_tasks)
            self.stats["average_execution_time"] = total_time / self.stats["completed_tasks"]
        
        return {
            "running": self._running,
            "max_concurrent": self._max_concurrent,
            "queue_size": len(self.task_queue),
            **self.stats,
            "task_types": {
                task_type.value: len([t for t in self.tasks.values() if t.task_type == task_type])
                for task_type in TaskType
            },
            "task_priorities": {
                priority.value: len([t for t in tasks.values() if t.priority == priority])
                for priority in TaskPriority
            }
        }
    
    async def _scheduler_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                # Check for pending tasks
                await self._process_pending_tasks()
                
                # Check for scheduled tasks
                await self._process_scheduled_tasks()
                
                # Cleanup old completed tasks
                await self._cleanup_completed_tasks()
                
                # Sleep for scheduler interval
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(5)
    
    async def _process_pending_tasks(self) -> None:
        """Process pending tasks in the queue."""
        while (self.task_queue and 
               len(self.running_tasks) < self._max_concurrent and
               self._running):
            
            task = self.task_queue.pop(0)
            
            # Check dependencies
            if not await self._check_dependencies(task):
                # Put back in queue
                self.task_queue.append(task)
                break
            
            # Start task execution
            asyncio.create_task(self._execute_task(task))
    
    async def _process_scheduled_tasks(self) -> None:
        """Process scheduled tasks."""
        current_time = datetime.now()
        
        for task in self.tasks.values():
            if (task.status == TaskStatus.SCHEDULED and
                task.scheduled_at and
                task.scheduled_at <= current_time):
                
                # Move to queue
                if task not in self.task_queue:
                    self.task_queue.append(task)
                    task.status = TaskStatus.PENDING
                    task.updated_at = current_time
                    
                    # Sort queue
                    self.task_queue.sort(key=lambda t: (
                        self._get_priority_value(t.priority),
                        t.scheduled_at or current_time
                    ))
    
    async def _execute_task(self, task: Task) -> None:
        """Execute a task."""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        task.updated_at = datetime.now()
        self.running_tasks[task.task_id] = task
        self.stats["running_tasks"] += 1
        
        # Emit execution start event
        await self._emit_task_event("task_started", task)
        
        start_time = time.time()
        
        try:
            # Execute task with timeout
            if task.timeout:
                result = await asyncio.wait_for(
                    task.handler(**task.parameters),
                    timeout=task.timeout
                )
            else:
                result = await task.handler(**task.parameters)
            
            # Task completed successfully
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            task.execution_time = time.time() - start_time
            task.updated_at = datetime.now()
            
            self.stats["completed_tasks"] += 1
            
            # Move to completed tasks
            self.completed_tasks.append(task)
            
            # Emit completion event
            await self._emit_task_event("task_completed", task)
            
            logger.info(f"Task completed: {task.name} ({task.task_id}) in {task.execution_time:.2f}s")
            
            # Schedule recurring task if applicable
            if task.interval and task.status == TaskStatus.COMPLETED:
                await self._schedule_recurring_task(task)
            
        except asyncio.TimeoutError:
            # Task timed out
            task.status = TaskStatus.FAILED
            task.error = "Task execution timeout"
            task.completed_at = datetime.now()
            task.execution_time = time.time() - start_time
            task.updated_at = datetime.now()
            
            self.stats["failed_tasks"] += 1
            self.failed_tasks.append(task)
            
            # Emit timeout event
            await self._emit_task_event("task_timeout", task)
            
            # Auto-retry if enabled
            if task.auto_retry and task.retry_count < task.max_retries:
                await self._retry_task(task)
            
            logger.error(f"Task timed out: {task.name} ({task.task_id})")
            
        except Exception as e:
            # Task failed
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now()
            task.execution_time = time.time() - start_time
            task.updated_at = datetime.now()
            
            self.stats["failed_tasks"] += 1
            self.failed_tasks.append(task)
            
            # Emit failure event
            await self._emit_task_event("task_failed", task)
            
            # Auto-retry if enabled
            if task.auto_retry and task.retry_count < task.max_retries:
                await self._retry_task(task)
            
            logger.error(f"Task failed: {task.name} ({task.task_id}): {e}")
        
        finally:
            # Remove from running tasks
            if task.task_id in self.running_tasks:
                del self.running_tasks[task.task_id]
                self.stats["running_tasks"] -= 1
    
    async def _check_dependencies(self, task: Task) -> bool:
        """Check if task dependencies are satisfied."""
        for dep_id in task.dependencies:
            dep_task = self.tasks.get(dep_id)
            if not dep_task:
                logger.error(f"Dependency not found: {dep_id}")
                return False
            
            if dep_task.status not in [TaskStatus.COMPLETED]:
                logger.info(f"Dependency not ready: {dep_id} (status: {dep_task.status.value})")
                return False
        
        return True
    
    async def _retry_task(self, task: Task) -> None:
        """Retry a failed task."""
        task.retry_count += 1
        task.status = TaskStatus.RETRYING
        task.updated_at = datetime.now()
        
        # Add delay for retry
        delay = min(300, 60 * (2 ** task.retry_count))  # Exponential backoff
        await asyncio.sleep(delay)
        
        # Reset for retry
        task.started_at = None
        task.completed_at = None
        task.result = None
        task.error = None
        task.execution_time = 0.0
        
        # Add back to queue
        self.task_queue.append(task)
        
        # Emit retry event
        await self._emit_task_event("task_retry", task)
        
        logger.info(f"Task retry scheduled: {task.name} ({task.task_id}) - attempt {task.retry_count}")
    
    async def _schedule_recurring_task(self, task: Task) -> None:
        """Schedule a recurring task."""
        if not task.interval:
            return
        
        # Calculate next execution time
        next_time = datetime.now() + timedelta(seconds=task.interval)
        
        # Create new task instance
        new_task = Task(
            name=task.name,
            task_type=task.task_type,
            priority=task.priority,
            handler=task.handler,
            parameters=task.parameters,
            dependencies=task.dependencies,
            max_retries=task.max_retries,
            timeout=task.timeout,
            interval=task.interval,
            auto_retry=task.auto_retry,
            metadata=task.metadata
        )
        
        # Schedule for next execution
        new_task.scheduled_at = next_time
        await self.schedule_task(new_task)
        
        logger.info(f"Recurring task scheduled: {task.name} ({task.task_id}) at {next_time}")
    
    async def _cleanup_completed_tasks(self) -> None:
        """Clean up old completed tasks."""
        cutoff_time = datetime.now() - timedelta(hours=24)
        
        # Remove old completed tasks
        old_tasks = [t for t in self.completed_tasks if t.completed_at and t.completed_at < cutoff_time]
        for task in old_tasks:
            del self.tasks[task.task_id]
        
        self.completed_tasks = [t for t in self.completed_tasks if t not in old_tasks]
        
        # Remove old failed tasks
        old_tasks = [t for t in self.failed_tasks if t.completed_at and t.completed_at < cutoff_time]
        for task in old_tasks:
            del self.tasks[task.task_id]
        
        self.failed_tasks = [t for t in self.failed_tasks if t not in old_tasks]
        
        if old_tasks:
            logger.info(f"Cleaned up {len(old_tasks)} old tasks")
    
    def _get_priority_value(self, priority: TaskPriority) -> int:
        """Get numeric value for priority."""
        priority_values = {
            TaskPriority.LOW: 1,
            TaskPriority.NORMAL: 2,
            TaskPriority.HIGH: 3,
            TaskPriority.CRITICAL: 4,
            TaskPriority.URGENT: 5
        }
        return priority_values.get(priority, 2)
    
    async def _emit_task_event(self, event_type: str, task: Task) -> None:
        """Emit task-related event."""
        if not self.event_bus:
            return
        
        try:
            event = Event(
                event_type=EventType.TASK_STARTED if event_type == "task_started" else EventType.TASK_COMPLETED,
                source="task_scheduler",
                priority=EventPriority.NORMAL,
                payload={
                    "event_type": event_type,
                    "task": task.to_dict()
                },
                metadata={
                    "component": "task_scheduler",
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            await self.event_bus.publish(event)
            
        except Exception as e:
            logger.error(f"Failed to emit task event: {e}")


class AutonomousTaskManager:
    """Manages autonomous task execution and self-improvement."""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.scheduler = TaskScheduler(event_bus)
        self._running = False
        self._self_improvement_task: Optional[Task] = None
        
        # Built-in task handlers
        self.task_handlers = {
            "auto_optimization": self._auto_optimization_handler,
            "health_monitoring": self._health_monitoring_handler,
            "performance_tuning": self._performance_tuning_handler,
            "error_recovery": self._error_recovery_handler,
            "learning_update": self._learning_update_handler,
            "system_cleanup": self._system_cleanup_handler
        }
    
    async def start(self) -> None:
        """Start the autonomous task manager."""
        if self._running:
            return
        
        self._running = True
        
        # Start scheduler
        await self.scheduler.start()
        
        # Schedule built-in tasks
        await self._schedule_builtin_tasks()
        
        logger.info("AutonomousTaskManager started")
    
    async def stop(self) -> None:
        """Stop the autonomous task manager."""
        self._running = False
        await self.scheduler.stop()
        logger.info("AutonomousTaskManager stopped")
    
    async def _schedule_builtin_tasks(self) -> None:
        """Schedule built-in autonomous tasks."""
        
        # Health monitoring task
        await self.scheduler.schedule_task(Task(
            name="System Health Monitoring",
            task_type=TaskType.HEALTH_CHECK,
            priority=TaskPriority.HIGH,
            handler=self.task_handlers["health_monitoring"],
            interval=60,  # Every minute
            parameters={"detailed": False}
        ))
        
        # Performance monitoring task
        await self.scheduler.schedule_task(Task(
            name="Performance Monitoring",
            task_type=TaskType.MONITORING,
            priority=TaskPriority.NORMAL,
            handler=self.task_handlers["performance_tuning"],
            interval=300,  # Every 5 minutes
            parameters={"collect_metrics": True}
        ))
        
        # Auto-optimization task
        await self.scheduler.schedule_task(Task(
            name="System Auto-Optimization",
            task_type=TaskType.OPTIMIZATION,
            priority=TaskPriority.NORMAL,
            handler=self.task_handlers["auto_optimization"],
            interval=1800,  # Every 30 minutes
            parameters={"aggressive": False}
        ))
        
        # System cleanup task
        await self.scheduler.schedule_task(Task(
            name="System Cleanup",
            task_type=TaskType.MAINTENANCE,
            priority=TaskPriority.LOW,
            handler=self.task_handlers["system_cleanup"],
            interval=3600,  # Every hour
            parameters={"deep_clean": False}
        ))
        
        logger.info("Built-in autonomous tasks scheduled")
    
    async def create_custom_task(self, name: str, task_type: TaskType, 
                           handler: Callable, parameters: Dict[str, Any] = None,
                           priority: TaskPriority = TaskPriority.NORMAL,
                           interval: Optional[int] = None,
                           max_retries: int = 3,
                           timeout: int = 300) -> str:
        """Create and schedule a custom autonomous task."""
        
        task = Task(
            name=name,
            task_type=task_type,
            priority=priority,
            handler=handler,
            parameters=parameters or {},
            max_retries=max_retries,
            timeout=timeout,
            interval=interval,
            auto_retry=True
        )
        
        return await self.scheduler.schedule_task(task)
    
    async def _auto_optimization_handler(self, **kwargs) -> Dict[str, Any]:
        """Handler for auto-optimization tasks."""
        # Simulate optimization analysis
        await asyncio.sleep(2)
        
        return {
            "optimizations_applied": 3,
            "performance_improvement": 15.5,
            "recommendations": [
                "Increase cache size",
                "Optimize database queries",
                "Enable compression"
            ],
            "optimization_time": datetime.now().isoformat()
        }
    
    async def _health_monitoring_handler(self, **kwargs) -> Dict[str, Any]:
        """Handler for health monitoring tasks."""
        detailed = kwargs.get("detailed", False)
        
        # Simulate health checks
        await asyncio.sleep(1)
        
        health_status = {
            "overall": "healthy",
            "components": {
                "event_bus": "healthy",
                "websocket_server": "healthy",
                "metrics_collector": "healthy",
                "task_scheduler": "healthy"
            },
            "metrics": {
                "cpu_usage": 45.2,
                "memory_usage": 67.8,
                "disk_usage": 23.1
            },
            "timestamp": datetime.now().isoformat()
        }
        
        if detailed:
            health_status["detailed_checks"] = {
                "event_bus_events_per_second": 15.2,
                "websocket_active_connections": 3,
                "metrics_collection_rate": 1.0,
                "task_queue_size": 2,
                "error_rate": 0.01
            }
        
        return health_status
    
    async def _performance_tuning_handler(self, **kwargs) -> Dict[str, Any]:
        """Handler for performance tuning tasks."""
        collect_metrics = kwargs.get("collect_metrics", False)
        
        # Simulate performance analysis
        await asyncio.sleep(3)
        
        if collect_metrics:
            # Simulate metrics collection
            metrics = {
                "response_time_p95": 250.5,
                "throughput": 45.2,
                "error_rate": 0.02,
                "resource_utilization": 0.75
            }
        else:
            metrics = {
                "response_time_p95": 280.3,
                "throughput": 42.1,
                "error_rate": 0.03,
                "resource_utilization": 0.78
            }
        
        return {
            "tuning_applied": True,
            "performance_improvement": 8.3,
            "metrics": metrics,
            "recommendations": [
                "Increase worker pool size",
                "Optimize database connections",
                "Enable response caching"
            ],
            "tuning_time": datetime.now().isoformat()
        }
    
    async def _error_recovery_handler(self, **kwargs) -> Dict[str, Any]:
        """Handler for error recovery tasks."""
        await asyncio.sleep(2)
        
        return {
            "errors_detected": 2,
            "errors_recovered": 2,
            "recovery_actions": [
                "Restarted failed service",
                "Cleared error cache",
                "Reset connection pool"
            ],
            "recovery_time": datetime.now().isoformat()
        }
    
    async def _learning_update_handler(self, **kwargs) -> Dict[str, Any]:
        """Handler for learning update tasks."""
        await asyncio.sleep(4)
        
        return {
            "models_updated": 5,
            "accuracy_improvement": 3.2,
            "new_patterns_learned": 12,
            "knowledge_base_size": 15420,
            "learning_time": datetime.now().isoformat()
        }
    
    async def _system_cleanup_handler(self, **kwargs) -> Dict[str, Any]:
        """Handler for system cleanup tasks."""
        deep_clean = kwargs.get("deep_clean", False)
        
        # Simulate cleanup process
        await asyncio.sleep(5 if deep_clean else 2)
        
        return {
            "cleanup_completed": True,
            "files_cleaned": 150 if deep_clean else 50,
            "cache_cleared": True,
            "logs_rotated": True,
            "memory_freed": 256 if deep_clean else 128,
            "cleanup_time": datetime.now().isoformat()
        }
    
    async def get_task_manager_stats(self) -> Dict[str, Any]:
        """Get task manager statistics."""
        scheduler_stats = await self.scheduler.get_stats()
        
        return {
            "task_manager": {
                "running": self._running,
                "builtin_handlers": len(self.task_handlers),
                "custom_tasks": len([t for t in self.scheduler.tasks.values() if t.handler not in self.task_handlers.values()]),
                "self_improvement_active": self._self_improvement_task is not None
            },
            **scheduler_stats
        }


# Global task manager instance
_task_manager: Optional[AutonomousTaskManager] = None


async def get_autonomous_task_manager(event_bus: EventBus) -> AutonomousTaskManager:
    """Get the global autonomous task manager instance."""
    global _task_manager
    if _task_manager is None:
        _task_manager = AutonomousTaskManager(event_bus)
    return _task_manager


async def shutdown_autonomous_task_manager() -> None:
    """Shutdown the autonomous task manager."""
    global _task_manager
    if _task_manager:
        await _task_manager.stop()
        _task_manager = None
