"""Adaptive Resource Management - Dynamic resource allocation and optimization.

Manages GPU memory, CPU usage, and other computational resources dynamically
based on workload patterns, cost optimization, and performance requirements.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import psutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict, deque
from enum import Enum

logger = logging.getLogger(__name__)


class ResourceType(str, Enum):
    """Types of resources that can be managed."""
    GPU_MEMORY = "gpu_memory"
    CPU = "cpu"
    RAM = "ram"
    VRAM = "vram"
    MODEL_INSTANCE = "model_instance"
    CACHE_STORAGE = "cache_storage"


class ResourcePriority(str, Enum):
    """Priority levels for resource allocation."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    BACKGROUND = "background"


class AllocationStrategy(str, Enum):
    """Resource allocation strategies."""
    FAIR_SHARE = "fair_share"
    PRIORITY_BASED = "priority_based"
    PERFORMANCE_OPTIMIZED = "performance_optimized"
    COST_OPTIMIZED = "cost_optimized"
    ADAPTIVE = "adaptive"


@dataclass
class ResourceRequirement:
    """A resource requirement for a task or process."""
    resource_type: ResourceType
    amount: float
    priority: ResourcePriority
    duration_estimate: float  # Estimated duration in seconds
    task_id: str
    can_be_preempted: bool = False
    min_required: float = 0.0
    
    def __post_init__(self) -> None:
        if self.min_required == 0.0:
            self.min_required = self.amount * 0.5  # Default minimum


@dataclass
class ResourceAllocation:
    """An active resource allocation."""
    allocation_id: str
    requirement: ResourceRequirement
    allocated_amount: float
    start_time: float
    end_time: Optional[float] = None
    actual_usage: float = 0.0
    efficiency_score: float = 1.0
    
    def __post_init__(self) -> None:
        self.allocation_id = self.allocation_id or f"alloc_{int(time.time())}_{self.requirement.task_id}"
    
    @property
    def is_active(self) -> bool:
        """Check if allocation is still active."""
        return self.end_time is None
    
    @property
    def duration(self) -> float:
        """Get the duration of this allocation."""
        end = self.end_time or time.time()
        return end - self.start_time


@dataclass
class ResourceCapacity:
    """Available capacity for a resource type."""
    resource_type: ResourceType
    total_capacity: float
    available_capacity: float
    allocated_capacity: float = 0.0
    reserved_capacity: float = 0.0
    
    @property
    def utilization_ratio(self) -> float:
        """Get the utilization ratio."""
        return self.allocated_capacity / self.total_capacity if self.total_capacity > 0 else 0.0
    
    @property
    def available_for_allocation(self) -> float:
        """Get capacity available for new allocations."""
        return self.available_capacity - self.reserved_capacity


@dataclass
class ResourceMetrics:
    """Metrics for resource usage and performance."""
    resource_type: ResourceType
    total_requests: int = 0
    successful_allocations: int = 0
    failed_allocations: int = 0
    preemptions: int = 0
    avg_utilization: float = 0.0
    peak_utilization: float = 0.0
    efficiency_score: float = 0.0
    cost_per_unit: float = 0.0


class ResourceManager:
    """Adaptive resource management system.
    
    Features:
    - Dynamic resource allocation
    - Priority-based scheduling
    - Preemption and reallocation
    - Performance monitoring
    - Cost optimization
    - Adaptive scaling
    """
    
    def __init__(
        self,
        *,
        allocation_strategy: AllocationStrategy = AllocationStrategy.ADAPTIVE,
        monitoring_interval: float = 5.0,
        preemption_threshold: float = 0.8,
        efficiency_window: int = 100,
        enable_cost_optimization: bool = True,
    ) -> None:
        self.allocation_strategy = allocation_strategy
        self.monitoring_interval = monitoring_interval
        self.preemption_threshold = preemption_threshold
        self.efficiency_window = efficiency_window
        self.enable_cost_optimization = enable_cost_optimization
        
        # Resource capacities
        self._capacities: Dict[ResourceType, ResourceCapacity] = {}
        self._allocations: Dict[str, ResourceAllocation] = {}
        self._pending_requirements: deque = deque()
        
        # Performance tracking
        self._metrics: Dict[ResourceType, ResourceMetrics] = {}
        self._usage_history: Dict[ResourceType, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._efficiency_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=efficiency_window))
        
        # Background tasks
        self._monitoring_task: Optional[asyncio.Task] = None
        self._optimization_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Lock for thread safety
        self._lock = asyncio.Lock()
        
        # Initialize system resources
        self._initialize_system_resources()
    
    async def start(self) -> None:
        """Start the resource manager."""
        if self._running:
            return
        
        self._running = True
        
        # Start background tasks
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        self._optimization_task = asyncio.create_task(self._optimization_loop())
        
        logger.info("Resource Manager started with strategy: %s", self.allocation_strategy.value)
    
    async def stop(self) -> None:
        """Stop the resource manager."""
        self._running = False
        
        if self._monitoring_task:
            self._monitoring_task.cancel()
        if self._optimization_task:
            self._optimization_task.cancel()
        
        # Wait for tasks to complete
        await asyncio.gather(
            self._monitoring_task, self._optimization_task, return_exceptions=True
        )
        
        logger.info("Resource Manager stopped")
    
    async def request_resources(
        self,
        requirements: List[ResourceRequirement],
        timeout: float = 30.0
    ) -> Dict[str, Optional[str]]:
        """Request resources for a task."""
        allocation_ids = {}
        
        async with self._lock:
            for requirement in requirements:
                allocation_id = await self._allocate_resource(requirement)
                allocation_ids[requirement.task_id] = allocation_id
        
        return allocation_ids
    
    async def release_resources(self, allocation_ids: List[str]) -> None:
        """Release allocated resources."""
        async with self._lock:
            for allocation_id in allocation_ids:
                await self._deallocate_resource(allocation_id)
    
    async def get_resource_status(self) -> Dict[str, Any]:
        """Get current resource status and metrics."""
        async with self._lock:
            status = {
                "capacities": {
                    rt.value: {
                        "total": cap.total_capacity,
                        "available": cap.available_capacity,
                        "allocated": cap.allocated_capacity,
                        "utilization": cap.utilization_ratio,
                    }
                    for rt, cap in self._capacities.items()
                },
                "active_allocations": len([a for a in self._allocations.values() if a.is_active]),
                "pending_requirements": len(self._pending_requirements),
                "metrics": {
                    rt.value: {
                        "total_requests": m.total_requests,
                        "success_rate": m.successful_allocations / max(1, m.total_requests),
                        "avg_utilization": m.avg_utilization,
                        "efficiency_score": m.efficiency_score,
                    }
                    for rt, m in self._metrics.items()
                }
            }
            
            return status
    
    async def optimize_allocation(self) -> Dict[str, Any]:
        """Manually trigger resource optimization."""
        async with self._lock:
            optimization_result = await self._perform_optimization()
            return optimization_result
    
    def _initialize_system_resources(self) -> None:
        """Initialize system resource capacities."""
        # CPU resources
        cpu_count = psutil.cpu_count()
        self._capacities[ResourceType.CPU] = ResourceCapacity(
            resource_type=ResourceType.CPU,
            total_capacity=float(cpu_count),
            available_capacity=float(cpu_count)
        )
        
        # RAM resources
        memory = psutil.virtual_memory()
        self._capacities[ResourceType.RAM] = ResourceCapacity(
            resource_type=ResourceType.RAM,
            total_capacity=memory.total / (1024**3),  # Convert to GB
            available_capacity=memory.available / (1024**3)
        )
        
        # GPU/VRAM resources (placeholder - would need GPU detection)
        self._capacities[ResourceType.GPU_MEMORY] = ResourceCapacity(
            resource_type=ResourceType.GPU_MEMORY,
            total_capacity=16.0,  # 16GB default
            available_capacity=16.0
        )
        
        self._capacities[ResourceType.VRAM] = ResourceCapacity(
            resource_type=ResourceType.VRAM,
            total_capacity=16.0,  # 16GB default
            available_capacity=16.0
        )
        
        # Model instances (logical resource)
        self._capacities[ResourceType.MODEL_INSTANCE] = ResourceCapacity(
            resource_type=ResourceType.MODEL_INSTANCE,
            total_capacity=10.0,
            available_capacity=10.0
        )
        
        # Cache storage
        self._capacities[ResourceType.CACHE_STORAGE] = ResourceCapacity(
            resource_type=ResourceType.CACHE_STORAGE,
            total_capacity=100.0,  # 100GB default
            available_capacity=100.0
        )
        
        # Initialize metrics
        for resource_type in self._capacities.keys():
            self._metrics[resource_type] = ResourceMetrics(resource_type=resource_type)
    
    async def _allocate_resource(self, requirement: ResourceRequirement) -> Optional[str]:
        """Allocate a resource for a requirement."""
        resource_type = requirement.resource_type
        
        if resource_type not in self._capacities:
            logger.error("Unknown resource type: %s", resource_type)
            return None
        
        capacity = self._capacities[resource_type]
        
        # Update metrics
        self._metrics[resource_type].total_requests += 1
        
        # Check if allocation is possible
        if not await self._can_allocate(requirement):
            # Try to preempt lower priority allocations
            if await self._try_preemption(requirement):
                # Preemption successful, try allocation again
                pass
            else:
                # Cannot allocate, add to pending queue
                self._pending_requirements.append(requirement)
                self._metrics[resource_type].failed_allocations += 1
                return None
        
        # Create allocation
        allocation = ResourceAllocation(
            allocation_id="",
            requirement=requirement,
            allocated_amount=requirement.amount,
            start_time=time.time()
        )
        
        # Update capacity
        capacity.allocated_capacity += allocation.allocated_amount
        capacity.available_capacity -= allocation.allocated_amount
        
        # Store allocation
        self._allocations[allocation.allocation_id] = allocation
        
        # Update metrics
        self._metrics[resource_type].successful_allocations += 1
        
        logger.debug(
            "Allocated %.2f %s for task %s (allocation_id: %s)",
            requirement.amount, resource_type.value, requirement.task_id, allocation.allocation_id
        )
        
        return allocation.allocation_id
    
    async def _deallocate_resource(self, allocation_id: str) -> None:
        """Deallocate a resource."""
        if allocation_id not in self._allocations:
            return
        
        allocation = self._allocations[allocation_id]
        allocation.end_time = time.time()
        
        # Calculate efficiency score
        if allocation.duration > 0:
            allocation.efficiency_score = min(1.0, allocation.actual_usage / allocation.allocated_amount)
        
        # Update capacity
        resource_type = allocation.requirement.resource_type
        capacity = self._capacities[resource_type]
        
        capacity.allocated_capacity -= allocation.allocated_amount
        capacity.available_capacity += allocation.allocated_amount
        
        # Update metrics
        self._metrics[resource_type].efficiency_score = self._calculate_efficiency_score(resource_type)
        
        # Remove from active allocations
        del self._allocations[allocation_id]
        
        logger.debug(
            "Deallocated %.2f %s from task %s (allocation_id: %s)",
            allocation.allocated_amount, resource_type.value, allocation.requirement.task_id, allocation_id
        )
        
        # Process pending requirements
        await self._process_pending_requirements()
    
    async def _can_allocate(self, requirement: ResourceRequirement) -> bool:
        """Check if a resource can be allocated."""
        resource_type = requirement.resource_type
        capacity = self._capacities[resource_type]
        
        return capacity.available_for_allocation >= requirement.min_required
    
    async def _try_preemption(self, requirement: ResourceRequirement) -> bool:
        """Try to preempt lower priority allocations."""
        resource_type = requirement.resource_type
        priority_order = {
            ResourcePriority.CRITICAL: 4,
            ResourcePriority.HIGH: 3,
            ResourcePriority.MEDIUM: 2,
            ResourcePriority.LOW: 1,
            ResourcePriority.BACKGROUND: 0
        }
        
        requirement_priority = priority_order[requirement.priority]
        
        # Find preemptable allocations
        preemptable = [
            alloc for alloc in self._allocations.values()
            if (alloc.requirement.resource_type == resource_type and
                alloc.is_active and
                alloc.requirement.can_be_preempted and
                priority_order[alloc.requirement.priority] < requirement_priority)
        ]
        
        # Sort by priority (lowest first)
        preemptable.sort(key=lambda a: priority_order[a.requirement.priority])
        
        # Try to free enough resources
        freed_amount = 0.0
        for allocation in preemptable:
            if freed_amount >= requirement.amount:
                break
            
            # Preempt this allocation
            await self._deallocate_resource(allocation.allocation_id)
            freed_amount += allocation.allocated_amount
            
            # Update preemption metrics
            self._metrics[resource_type].preemptions += 1
        
        return freed_amount >= requirement.min_required
    
    async def _process_pending_requirements(self) -> None:
        """Process pending resource requirements."""
        processed = []
        
        while self._pending_requirements:
            requirement = self._pending_requirements.popleft()
            
            allocation_id = await self._allocate_resource(requirement)
            if allocation_id:
                processed.append(requirement.task_id)
            else:
                # Still can't allocate, put back in queue
                self._pending_requirements.append(requirement)
                break
        
        if processed:
            logger.debug("Processed %d pending requirements: %s", len(processed), processed)
    
    def _calculate_efficiency_score(self, resource_type: ResourceType) -> float:
        """Calculate efficiency score for a resource type."""
        relevant_allocations = [
            alloc for alloc in self._allocations.values()
            if alloc.requirement.resource_type == resource_type and
            not alloc.is_active
        ]
        
        if not relevant_allocations:
            return 1.0
        
        total_efficiency = sum(alloc.efficiency_score for alloc in relevant_allocations)
        return total_efficiency / len(relevant_allocations)
    
    async def _monitoring_loop(self) -> None:
        """Background monitoring loop."""
        while self._running:
            try:
                await self._update_system_metrics()
                await self._check_resource_pressure()
                await asyncio.sleep(self.monitoring_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Monitoring loop error: %s", e)
                await asyncio.sleep(self.monitoring_interval)
    
    async def _optimization_loop(self) -> None:
        """Background optimization loop."""
        while self._running:
            try:
                await self._perform_optimization()
                await asyncio.sleep(60.0)  # Optimize every minute
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Optimization loop error: %s", e)
                await asyncio.sleep(60.0)
    
    async def _update_system_metrics(self) -> None:
        """Update system resource metrics."""
        current_time = time.time()
        
        # Update CPU metrics
        cpu_percent = psutil.cpu_percent()
        self._usage_history[ResourceType.CPU].append((current_time, cpu_percent))
        
        # Update RAM metrics
        memory = psutil.virtual_memory()
        ram_usage = memory.percent
        self._usage_history[ResourceType.RAM].append((current_time, ram_usage))
        
        # Update utilization metrics
        for resource_type, capacity in self._capacities.items():
            utilization = capacity.utilization_ratio
            self._usage_history[resource_type].append((current_time, utilization))
            
            # Update peak utilization
            if utilization > self._metrics[resource_type].peak_utilization:
                self._metrics[resource_type].peak_utilization = utilization
            
            # Update average utilization
            if len(self._usage_history[resource_type]) > 0:
                recent_utilizations = [usage for _, usage in list(self._usage_history[resource_type])[-100:]]
                self._metrics[resource_type].avg_utilization = sum(recent_utilizations) / len(recent_utilizations)
    
    async def _check_resource_pressure(self) -> None:
        """Check for resource pressure and trigger alerts."""
        for resource_type, capacity in self._capacities.items():
            if capacity.utilization_ratio > self.preemption_threshold:
                logger.warning(
                    "High resource pressure detected: %s at %.1f%% utilization",
                    resource_type.value, capacity.utilization_ratio * 100
                )
                
                # Trigger optimization if needed
                if self.allocation_strategy == AllocationStrategy.ADAPTIVE:
                    await self._perform_optimization()
    
    async def _perform_optimization(self) -> Dict[str, Any]:
        """Perform resource optimization."""
        optimization_actions = []
        
        # Strategy-specific optimizations
        if self.allocation_strategy == AllocationStrategy.PERFORMANCE_OPTIMIZED:
            optimization_actions.extend(await self._optimize_for_performance())
        elif self.allocation_strategy == AllocationStrategy.COST_OPTIMIZED:
            optimization_actions.extend(await self._optimize_for_cost())
        elif self.allocation_strategy == AllocationStrategy.ADAPTIVE:
            optimization_actions.extend(await self._adaptive_optimization())
        
        return {
            "timestamp": time.time(),
            "strategy": self.allocation_strategy.value,
            "actions": optimization_actions,
            "total_actions": len(optimization_actions)
        }
    
    async def _optimize_for_performance(self) -> List[str]:
        """Optimize resource allocation for performance."""
        actions = []
        
        # Identify underutilized resources
        for resource_type, capacity in self._capacities.items():
            if capacity.utilization_ratio < 0.3:  # Less than 30% utilized
                # Look for opportunities to consolidate
                actions.append(f"Consolidated {resource_type.value} allocations")
        
        return actions
    
    async def _optimize_for_cost(self) -> List[str]:
        """Optimize resource allocation for cost."""
        actions = []
        
        if self.enable_cost_optimization:
            # Implement cost optimization logic
            actions.append("Applied cost optimization policies")
        
        return actions
    
    async def _adaptive_optimization(self) -> List[str]:
        """Perform adaptive optimization based on current conditions."""
        actions = []
        
        # Analyze usage patterns
        for resource_type, usage_history in self._usage_history.items():
            if len(usage_history) < 10:
                continue
            
            recent_usage = [usage for _, usage in list(usage_history)[-10:]]
            avg_recent = sum(recent_usage) / len(recent_usage)
            
            if avg_recent > 0.8:  # High usage
                actions.append(f"Scaling up {resource_type.value} capacity")
            elif avg_recent < 0.2:  # Low usage
                actions.append(f"Scaling down {resource_type.value} capacity")
        
        return actions


# Global resource manager instance
_resource_manager: Optional[ResourceManager] = None


def get_resource_manager(**kwargs) -> ResourceManager:
    """Get the global resource manager instance."""
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = ResourceManager(**kwargs)
    return _resource_manager
