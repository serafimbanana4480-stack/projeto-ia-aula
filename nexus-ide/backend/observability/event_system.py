"""Event System - Centralized event management for NEXUS OMEGA.

This system provides:
- Centralized event bus with Redis pub/sub
- Event persistence and replay
- Event filtering and routing
- Real-time event streaming
- Event aggregation and analytics
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import Enum
import uuid

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Types of events in the system."""
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    AGENT_HEARTBEAT = "agent.heartbeat"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_QUEUED = "task.queued"
    SYSTEM_ERROR = "system.error"
    SYSTEM_WARNING = "system.warning"
    SYSTEM_INFO = "system.info"
    METRIC_UPDATE = "metric.update"
    CHAT_MESSAGE = "chat.message"
    CHAT_RESPONSE = "chat.response"
    MEMORY_UPDATE = "memory.update"
    SECURITY_EVENT = "security.event"
    PERFORMANCE_UPDATE = "performance.update"


class EventPriority(str, Enum):
    """Event priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Event:
    """System event."""
    event_id: str = field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:12]}")
    event_type: EventType = EventType.SYSTEM_INFO
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = ""
    agent: Optional[str] = None
    session_id: Optional[str] = None
    priority: EventPriority = EventPriority.NORMAL
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "agent": self.agent,
            "session_id": self.session_id,
            "priority": self.priority.value,
            "payload": self.payload,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Event':
        """Create event from dictionary."""
        return cls(
            event_id=data.get("event_id", f"evt-{uuid.uuid4().hex[:12]}"),
            event_type=EventType(data.get("event_type", "system.info")),
            timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat())),
            source=data.get("source", ""),
            agent=data.get("agent"),
            session_id=data.get("session_id"),
            priority=EventPriority(data.get("priority", "normal")),
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {}),
        )


class EventSubscriber:
    """Event subscriber with filtering capabilities."""
    
    def __init__(self, 
                 event_types: Optional[List[EventType]] = None,
                 agent_filter: Optional[str] = None,
                 session_filter: Optional[str] = None,
                 priority_filter: Optional[EventPriority] = None):
        self.event_types = set(event_types) if event_types else None
        self.agent_filter = agent_filter
        self.session_filter = session_filter
        self.priority_filter = priority_filter
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    
    def matches(self, event: Event) -> bool:
        """Check if event matches subscriber filters."""
        if self.event_types and event.event_type not in self.event_types:
            return False
        if self.agent_filter and event.agent != self.agent_filter:
            return False
        if self.session_filter and event.session_id != self.session_filter:
            return False
        if self.priority_filter and event.priority != self.priority_filter:
            return False
        return True
    
    async def put(self, event: Event) -> None:
        """Put event in subscriber queue."""
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(f"Subscriber queue full, dropping event {event.event_id}")
    
    async def get(self) -> Event:
        """Get event from subscriber queue."""
        return await self.queue.get()


class EventBus:
    """Centralized event bus with Redis pub/sub support."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        self._subscribers: List[EventSubscriber] = []
        self._event_history: List[Event] = []
        self._max_history = 10000
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stats = {
            "events_published": 0,
            "events_delivered": 0,
            "subscribers": 0,
            "errors": 0
        }
    
    async def start(self) -> None:
        """Start the event bus."""
        if self._running:
            return
        
        self._running = True
        
        # Connect to Redis
        if REDIS_AVAILABLE:
            try:
                self._redis = redis.from_url(self.redis_url, decode_responses=True)
                await self._redis.ping()
                logger.info("EventBus connected to Redis")
                
                # Start Redis subscriber task
                self._task = asyncio.create_task(self._redis_subscriber())
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}")
                self._redis = None
        
        logger.info("EventBus started")
    
    async def stop(self) -> None:
        """Stop the event bus."""
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        
        if self._redis:
            await self._redis.close()
            self._redis = None
        
        logger.info("EventBus stopped")
    
    async def publish(self, event: Event) -> None:
        """Publish an event."""
        try:
            # Add to history
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history = self._event_history[-self._max_history:]
            
            # Update stats
            self._stats["events_published"] += 1
            
            # Publish to Redis
            if self._redis:
                await self._redis.publish("nexus_events", json.dumps(event.to_dict()))
            
            # Deliver to local subscribers
            delivered = 0
            for subscriber in self._subscribers:
                if subscriber.matches(event):
                    await subscriber.put(event)
                    delivered += 1
            
            self._stats["events_delivered"] += delivered
            
            logger.debug(f"Event {event.event_id} published to {delivered} subscribers")
            
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Failed to publish event {event.event_id}: {e}")
    
    async def subscribe(self, 
                       event_types: Optional[List[EventType]] = None,
                       agent_filter: Optional[str] = None,
                       session_filter: Optional[str] = None,
                       priority_filter: Optional[EventPriority] = None) -> AsyncIterator[Event]:
        """Subscribe to events with filtering."""
        subscriber = EventSubscriber(event_types, agent_filter, session_filter, priority_filter)
        self._subscribers.append(subscriber)
        self._stats["subscribers"] += 1
        
        try:
            while self._running:
                event = await subscriber.get()
                yield event
        finally:
            self._subscribers.remove(subscriber)
            self._stats["subscribers"] -= 1
    
    async def get_events(self, 
                       limit: int = 100,
                       event_type: Optional[EventType] = None,
                       agent: Optional[str] = None,
                       session_id: Optional[str] = None) -> List[Event]:
        """Get events from history with filtering."""
        events = self._event_history.copy()
        
        # Apply filters
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if agent:
            events = [e for e in events if e.agent == agent]
        if session_id:
            events = [e for e in events if e.session_id == session_id]
        
        # Sort by timestamp (newest first) and limit
        events.sort(key=lambda x: x.timestamp, reverse=True)
        return events[:limit]
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get event bus statistics."""
        return {
            "running": self._running,
            "subscribers": len(self._subscribers),
            "history_size": len(self._event_history),
            "redis_connected": self._redis is not None,
            **self._stats
        }
    
    async def _redis_subscriber(self) -> None:
        """Subscribe to Redis events."""
        if not self._redis:
            return
        
        try:
            pubsub = self._redis.pubsub()
            await pubsub.subscribe("nexus_events")
            
            async for message in pubsub.listen():
                if not self._running:
                    break
                
                if message["type"] == "message":
                    try:
                        event_data = json.loads(message["data"])
                        event = Event.from_dict(event_data)
                        
                        # Deliver to local subscribers
                        delivered = 0
                        for subscriber in self._subscribers:
                            if subscriber.matches(event):
                                await subscriber.put(event)
                                delivered += 1
                        
                        self._stats["events_delivered"] += delivered
                        
                    except Exception as e:
                        self._stats["errors"] += 1
                        logger.error(f"Failed to process Redis event: {e}")
                        
        except Exception as e:
            logger.error(f"Redis subscriber error: {e}")


class EventAggregator:
    """Aggregates events for analytics and monitoring."""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._aggregations: Dict[str, Dict[str, Any]] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start the event aggregator."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._aggregate_events())
        logger.info("EventAggregator started")
    
    async def stop(self) -> None:
        """Stop the event aggregator."""
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        
        logger.info("EventAggregator stopped")
    
    async def _aggregate_events(self) -> None:
        """Aggregate events in real-time."""
        async for event in self.event_bus.subscribe():
            if not self._running:
                break
            
            # Aggregate by event type
            event_type = event.event_type.value
            if event_type not in self._aggregations:
                self._aggregations[event_type] = {
                    "count": 0,
                    "last_seen": None,
                    "agents": set(),
                    "sessions": set(),
                    "priority_counts": {p.value: 0 for p in EventPriority}
                }
            
            agg = self._aggregations[event_type]
            agg["count"] += 1
            agg["last_seen"] = event.timestamp
            agg["priority_counts"][event.priority.value] += 1
            
            if event.agent:
                agg["agents"].add(event.agent)
            if event.session_id:
                agg["sessions"].add(event.session_id)
    
    async def get_aggregations(self) -> Dict[str, Any]:
        """Get event aggregations."""
        result = {}
        for event_type, agg in self._aggregations.items():
            result[event_type] = {
                "count": agg["count"],
                "last_seen": agg["last_seen"].isoformat() if agg["last_seen"] else None,
                "unique_agents": len(agg["agents"]),
                "unique_sessions": len(agg["sessions"]),
                "priority_distribution": agg["priority_counts"]
            }
        return result
    
    async def get_event_rate(self, window_seconds: int = 60) -> float:
        """Get event rate per second."""
        if not self._aggregations:
            return 0.0
        
        total_events = sum(agg["count"] for agg in self._aggregations.values())
        return total_events / window_seconds


# Global event bus instance
_event_bus: Optional[EventBus] = None
_event_aggregator: Optional[EventAggregator] = None


async def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
        await _event_bus.start()
    return _event_bus


async def get_event_aggregator() -> EventAggregator:
    """Get the global event aggregator instance."""
    global _event_aggregator
    if _event_aggregator is None:
        event_bus = await get_event_bus()
        _event_aggregator = EventAggregator(event_bus)
        await _event_aggregator.start()
    return _event_aggregator


async def shutdown_event_system() -> None:
    """Shutdown the event system."""
    global _event_bus, _event_aggregator
    
    if _event_aggregator:
        await _event_aggregator.stop()
        _event_aggregator = None
    
    if _event_bus:
        await _event_bus.stop()
        _event_bus = None