"""Redis-backed EventBus for multi-worker deployments.

Implements distributed pub/sub with persistence, replay, and consumer groups.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from .events import Event

logger = logging.getLogger(__name__)

Subscriber = Callable[[Event], Any]


@dataclass
class EventMessage:
    """Structured event message for Redis pub/sub."""
    event_id: str = field(default_factory=lambda: f"evt-{int(time.time() * 1000)}")
    event_type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    agent: str = ""
    priority: int = 0  # 0=low, 1=normal, 2=high, 3=critical
    version: str = "1.0"
    
    def to_event(self) -> Event:
        return Event(
            type=self.event_type,
            agent=self.agent,
            payload=self.payload,
        )
    
    @classmethod
    def from_event(cls, event: Event, priority: int = 0) -> EventMessage:
        return cls(
            event_type=event.type,
            payload=event.payload or {},
            agent=event.agent or "",
            priority=priority,
        )
    
    def serialize(self) -> str:
        return json.dumps({
            "event_id": self.event_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "agent": self.agent,
            "priority": self.priority,
            "version": self.version,
        })
    
    @classmethod
    def deserialize(cls, data: str) -> EventMessage:
        obj = json.loads(data)
        return cls(**obj)


class RedisEventBus:
    """Redis-backed distributed event bus with pub/sub, persistence, and replay."""
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        max_queue_size: int = 1000,
        persistence_ttl: int = 3600,  # 1 hour
        consumer_group: str = "nexus_default",
    ) -> None:
        if not REDIS_AVAILABLE:
            raise ImportError("redis-py is required. Install: pip install redis[hiredis]")
        
        self.redis_url = redis_url
        self.max_queue_size = max_queue_size
        self.persistence_ttl = persistence_ttl
        self.consumer_group = consumer_group
        self._redis: redis.Redis | None = None
        self._pubsub: redis.PubSub | None = None
        self._subscribers: dict[str, list[Callable]] = {}
        self._running = False
        self._consumer_tasks: list[asyncio.Task] = []
        
    async def connect(self) -> None:
        """Connect to Redis and setup pub/sub."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        self._pubsub = self._redis.pubsub()
        
        # Test connection
        await self._redis.ping()
        logger.info("Connected to Redis EventBus at %s", self.redis_url)
        
        # Start consumer tasks
        self._running = True
        await self._start_consumers()
        
    async def disconnect(self) -> None:
        """Disconnect from Redis and cleanup."""
        self._running = False
        
        # Cancel consumer tasks
        for task in self._consumer_tasks:
            task.cancel()
        
        if self._pubsub:
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
            
        logger.info("Disconnected from Redis EventBus")
        
    async def _start_consumers(self) -> None:
        """Start consumer tasks for each subscription."""
        for topic_pattern in self._subscribers:
            task = asyncio.create_task(self._consume_topic(topic_pattern))
            self._consumer_tasks.append(task)
            
    async def _consume_topic(self, topic_pattern: str) -> None:
        """Consume events for a topic pattern."""
        channel = f"events:{topic_pattern}"
        
        try:
            # Subscribe to channel
            await self._pubsub.subscribe(channel)
            logger.info("Subscribed to Redis channel: %s", channel)
            
            while self._running:
                try:
                    message = await self._pubsub.get_message(timeout=1.0)
                    if message and message["type"] == "message":
                        event_msg = EventMessage.deserialize(message["data"])
                        event = event_msg.to_event()
                        
                        # Notify subscribers
                        for subscriber in self._subscribers.get(topic_pattern, []):
                            try:
                                if asyncio.iscoroutinefunction(subscriber):
                                    await subscriber(event)
                                else:
                                    subscriber(event)
                            except Exception as exc:
                                logger.error("Subscriber error for %s: %s", topic_pattern, exc)
                                
                except redis.ConnectionError:
                    logger.warning("Redis connection lost, reconnecting...")
                    await asyncio.sleep(1.0)
                    # Reconnect and resubscribe
                    await self.connect()
                    await self._pubsub.subscribe(channel)
                    
        except asyncio.CancelledError:
            logger.info("Consumer task cancelled for topic: %s", topic_pattern)
        except Exception as exc:
            logger.error("Consumer task error for %s: %s", topic_pattern, exc)
            
    async def publish(self, event: Event, priority: int = 0) -> None:
        """Publish an event to Redis with priority and persistence."""
        if not self._redis:
            raise RuntimeError("EventBus not connected")
            
        event_msg = EventMessage.from_event(event, priority)
        
        # Determine channels based on event type
        channels = []
        
        # Exact match
        channels.append(f"events:{event.type}")
        
        # Pattern matches
        parts = event.type.split(".")
        for i in range(len(parts)):
            pattern = ".".join(parts[:i]) + ".*"
            channels.append(f"events:{pattern}")
            
        # Global channel
        channels.append("events:*")
        
        # Publish to all matching channels
        serialized = event_msg.serialize()
        
        for channel in channels:
            try:
                await self._redis.publish(channel, serialized)
            except Exception as exc:
                logger.error("Failed to publish to %s: %s", channel, exc)
                
        # Persist event for replay
        await self._persist_event(event_msg)
        
    async def _persist_event(self, event_msg: EventMessage) -> None:
        """Persist event for replay capability."""
        if not self._redis:
            return
            
        key = f"events:persist:{event_msg.event_id}"
        try:
            await self._redis.setex(
                key,
                self.persistence_ttl,
                event_msg.serialize()
            )
        except Exception as exc:
            logger.error("Failed to persist event %s: %s", event_msg.event_id, exc)
            
    async def subscribe(self, topic_pattern: str, subscriber: Subscriber) -> None:
        """Subscribe to events matching a topic pattern."""
        if topic_pattern not in self._subscribers:
            self._subscribers[topic_pattern] = []
            # Start consumer task for new pattern
            if self._running:
                task = asyncio.create_task(self._consume_topic(topic_pattern))
                self._consumer_tasks.append(task)
                
        self._subscribers[topic_pattern].append(subscriber)
        logger.info("Added subscriber for pattern: %s", topic_pattern)
        
    async def unsubscribe(self, topic_pattern: str, subscriber: Subscriber) -> None:
        """Unsubscribe from events matching a topic pattern."""
        if topic_pattern in self._subscribers:
            try:
                self._subscribers[topic_pattern].remove(subscriber)
                if not self._subscribers[topic_pattern]:
                    del self._subscribers[topic_pattern]
                    # Cancel consumer task
                    for task in self._consumer_tasks:
                        if task.get_name() == f"consume_{topic_pattern}":
                            task.cancel()
                            break
            except ValueError:
                pass
                
    async def replay_events(
        self,
        since: float | None = None,
        event_type: str | None = None,
        limit: int = 1000,
    ) -> AsyncIterator[Event]:
        """Replay persisted events."""
        if not self._redis:
            raise RuntimeError("EventBus not connected")
            
        pattern = "events:persist:*"
        if since:
            # Use Redis SCAN with timestamp filter
            cursor = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(
                    cursor=cursor,
                    match=pattern,
                    count=100
                )
                
                for key in keys:
                    try:
                        data = await self._redis.get(key)
                        if data:
                            event_msg = EventMessage.deserialize(data)
                            
                            # Filter by timestamp
                            if since and event_msg.timestamp < since:
                                continue
                                
                            # Filter by event type
                            if event_type and event_msg.event_type != event_type:
                                continue
                                
                            yield event_msg.to_event()
                            
                            limit -= 1
                            if limit <= 0:
                                return
                                
                    except Exception as exc:
                        logger.error("Failed to replay event %s: %s", key, exc)
                        
        await asyncio.sleep(0)  # Yield control
        
    async def get_stats(self) -> dict[str, Any]:
        """Get EventBus statistics."""
        if not self._redis:
            return {"connected": False}
            
        try:
            # Count persisted events
            pattern = "events:persist:*"
            cursor = 0
            count = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(
                    cursor=cursor,
                    match=pattern,
                    count=1000
                )
                count += len(keys)
                
            # Get Redis info
            info = await self._redis.info()
            
            return {
                "connected": True,
                "persisted_events": count,
                "subscribers": {
                    pattern: len(subs) for pattern, subs in self._subscribers.items()
                },
                "redis_memory": info.get("used_memory_human"),
                "redis_connected_clients": info.get("connected_clients"),
            }
            
        except Exception as exc:
            logger.error("Failed to get stats: %s", exc)
            return {"connected": True, "error": str(exc)}


# Backward compatibility wrapper
class EventBus:
    """Wrapper that uses RedisEventBus if available, falls back to in-memory."""
    
    def __init__(self, max_queue_size: int = 1000, redis_url: str = "redis://localhost:6379"):
        self._redis_bus = None
        self._fallback_bus = None
        self._max_queue_size = max_queue_size
        self._redis_url = redis_url
        
    async def _ensure_connected(self) -> None:
        """Ensure Redis bus is connected, fall back to in-memory if needed."""
        if self._redis_bus is None:
            try:
                self._redis_bus = RedisEventBus(
                    redis_url=self._redis_url,
                    max_queue_size=self._max_queue_size
                )
                await self._redis_bus.connect()
                logger.info("Using Redis EventBus")
            except Exception as exc:
                logger.warning("Redis EventBus failed, using in-memory fallback: %s", exc)
                self._redis_bus = None
                from .event_bus import InMemoryEventBus
                self._fallback_bus = InMemoryEventBus(self._max_queue_size)
                
    async def publish(self, event: Event, priority: int = 0) -> None:
        await self._ensure_connected()
        if self._redis_bus:
            await self._redis_bus.publish(event, priority)
        else:
            await self._fallback_bus.publish(event)
            
    async def subscribe(self, topic_pattern: str, subscriber: Subscriber) -> None:
        await self._ensure_connected()
        if self._redis_bus:
            await self._redis_bus.subscribe(topic_pattern, subscriber)
        else:
            await self._fallback_bus.subscribe(topic_pattern, subscriber)
            
    async def unsubscribe(self, topic_pattern: str, subscriber: Subscriber) -> None:
        await self._ensure_connected()
        if self._redis_bus:
            await self._redis_bus.unsubscribe(topic_pattern, subscriber)
        else:
            await self._fallback_bus.unsubscribe(topic_pattern, subscriber)
            
    async def replay_events(
        self,
        since: float | None = None,
        event_type: str | None = None,
        limit: int = 1000,
    ) -> AsyncIterator[Event]:
        await self._ensure_connected()
        if self._redis_bus:
            async for event in self._redis_bus.replay_events(since, event_type, limit):
                yield event
        else:
            # Fallback: yield nothing for in-memory
            return
            
    async def get_stats(self) -> dict[str, Any]:
        await self._ensure_connected()
        if self._redis_bus:
            return await self._redis_bus.get_stats()
        else:
            return {"connected": False, "fallback": True}