"""Memory Dashboard Integration - Real-time memory system monitoring.

This module provides:
- Real-time memory system monitoring
- Memory usage analytics
- Memory performance metrics
- Memory health tracking
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from backend.observability.event_system import EventBus, Event, EventType, EventPriority

logger = logging.getLogger(__name__)


@dataclass
class MemoryMetrics:
    """Memory system metrics."""
    total_memories: int = 0
    active_memories: int = 0
    total_entries: int = 0
    memory_usage_mb: float = 0.0
    avg_access_time_ms: float = 0.0
    cache_hit_rate: float = 0.0
    error_rate: float = 0.0
    last_update: datetime = field(default_factory=datetime.now)


class MemoryDashboard:
    """Memory system dashboard integration."""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.metrics = MemoryMetrics()
        self.memory_systems: Dict[str, Any] = {}
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
    async def start(self) -> None:
        """Start memory dashboard monitoring."""
        if self._running:
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_memory_systems())
        logger.info("MemoryDashboard started")
    
    async def stop(self) -> None:
        """Stop memory dashboard monitoring."""
        self._running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        
        logger.info("MemoryDashboard stopped")
    
    async def register_memory_system(self, name: str, memory_system: Any) -> None:
        """Register a memory system for monitoring."""
        self.memory_systems[name] = memory_system
        self.metrics.total_memories += 1
        
        await self._emit_memory_event("memory_system_registered", {
            "system_name": name,
            "total_systems": self.metrics.total_memories
        })
    
    async def update_memory_metrics(self, system_name: str, metrics: Dict[str, Any]) -> None:
        """Update memory system metrics."""
        if system_name not in self.memory_systems:
            await self.register_memory_system(system_name, None)
        
        # Update global metrics
        self.metrics.total_entries = sum(
            m.get("total_entries", 0) 
            for m in self.memory_systems.values()
        )
        
        self.metrics.memory_usage_mb = sum(
            m.get("memory_usage_mb", 0) 
            for m in self.memory_systems.values()
        )
        
        self.metrics.active_memories = len([
            m for m in self.memory_systems.values() 
            if m.get("is_active", False)
        ])
        
        # Calculate averages
        access_times = [
            m.get("avg_access_time_ms", 0) 
            for m in self.memory_systems.values()
        ]
        if access_times:
            self.metrics.avg_access_time_ms = sum(access_times) / len(access_times)
        
        hit_rates = [
            m.get("cache_hit_rate", 0) 
            for m in self.memory_systems.values()
        ]
        if hit_rates:
            self.metrics.cache_hit_rate = sum(hit_rates) / len(hit_rates)
        
        error_rates = [
            m.get("error_rate", 0) 
            for m in self.memory_systems.values()
        ]
        if error_rates:
            self.metrics.error_rate = sum(error_rates) / len(error_rates)
        
        self.metrics.last_update = datetime.now()
        
        # Emit update event
        await self._emit_memory_event("memory_metrics_updated", {
            "system_name": system_name,
            "global_metrics": self.metrics.__dict__,
            "system_metrics": metrics
        })
    
    async def get_memory_status(self) -> Dict[str, Any]:
        """Get current memory system status."""
        return {
            "metrics": self.metrics.__dict__,
            "systems": {
                name: {
                    "is_active": system.get("is_active", False),
                    "total_entries": system.get("total_entries", 0),
                    "memory_usage_mb": system.get("memory_usage_mb", 0),
                    "cache_hit_rate": system.get("cache_hit_rate", 0),
                    "avg_access_time_ms": system.get("avg_access_time_ms", 0),
                    "error_rate": system.get("error_rate", 0)
                }
                for name, system in self.memory_systems.items()
            }
        }
    
    async def _monitor_memory_systems(self) -> None:
        """Monitor memory systems and collect metrics."""
        while self._running:
            try:
                # Simulate memory system monitoring
                for name, system in self.memory_systems.items():
                    if hasattr(system, 'get_metrics'):
                        try:
                            metrics = await system.get_metrics()
                            await self.update_memory_metrics(name, metrics)
                        except Exception as e:
                            logger.error(f"Failed to get metrics for {name}: {e}")
                            await self._emit_memory_event("memory_system_error", {
                                "system_name": name,
                                "error": str(e)
                            })
                
                # Sleep for monitoring interval
                await asyncio.sleep(10)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in memory monitoring: {e}")
                await asyncio.sleep(5)
    
    async def _emit_memory_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Emit memory-related event."""
        if not self.event_bus:
            return
        
        try:
            event = Event(
                event_type=EventType.MEMORY_UPDATE,
                source="memory_dashboard",
                priority=EventPriority.NORMAL,
                payload={
                    "event_type": event_type,
                    **payload
                },
                metadata={
                    "component": "memory_dashboard",
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            await self.event_bus.publish(event)
            
        except Exception as e:
            logger.error(f"Failed to emit memory event: {e}")


# Global memory dashboard instance
_memory_dashboard: Optional[MemoryDashboard] = None


async def get_memory_dashboard(event_bus: EventBus) -> MemoryDashboard:
    """Get the global memory dashboard instance."""
    global _memory_dashboard
    if _memory_dashboard is None:
        _memory_dashboard = MemoryDashboard(event_bus)
        await _memory_dashboard.start()
    return _memory_dashboard


async def shutdown_memory_dashboard() -> None:
    """Shutdown the memory dashboard."""
    global _memory_dashboard
    if _memory_dashboard:
        await _memory_dashboard.stop()
        _memory_dashboard = None