"""Real-time in-memory event bus for dashboard and observability.

Pub/sub with async subscribers, topic-based filtering,
and backpressure handling via ring buffers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Optional

from .events import Event

logger = logging.getLogger(__name__)

Subscriber = Callable[[Event], Any]


@dataclass
class RedisConfig:
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    pubsub_channel: str = "nexus_events"
    max_connections: int = 10
    connection_timeout: int = 5
    retry_on_timeout: bool = True
    socket_keepalive: bool = True


@dataclass
class PersistenceConfig:
    enabled: bool = True
    ttl_seconds: int = 86400
    max_events: int = 10000
    replay_enabled: bool = True
    persistence_key_prefix: str = "event_store"


class EventPersistence:
    def __init__(self, redis_client: Any, config: PersistenceConfig):
        self.redis = redis_client
        self.config = config
        self.key_prefix = config.persistence_key_prefix

    async def store_event(self, event_type: str, event_data: dict[str, Any]) -> None:
        """Store an event in Redis sorted set with timestamp as score."""
        if not self.config.enabled:
            return

        try:
            timestamp = time.time()
            event = {
                "type": event_type,
                "data": event_data,
                "timestamp": timestamp
            }

            key = f"{self.key_prefix}:{event_type}"

            # Add to sorted set with timestamp as score
            self.redis.zadd(key, {json.dumps(event): timestamp})

            # Set TTL
            self.redis.expire(key, self.config.ttl_seconds)

            # Trim to max_events
            self.redis.zremrangebyrank(key, 0, -self.config.max_events - 1)

            logger.debug(f"Stored event {event_type} at {timestamp}")

        except Exception as e:
            logger.error(f"Failed to store event {event_type}: {e}")

    async def get_events(
        self,
        event_type: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100
    ) -> list[dict]:
        """Retrieve events within time range."""
        if not self.config.replay_enabled:
            return []

        try:
            key = f"{self.key_prefix}:{event_type}"

            # Determine score range
            min_score = start_time if start_time else "-inf"
            max_score = end_time if end_time else "+inf"

            # Get events in range
            events = self.redis.zrangebyscore(
                key,
                min_score,
                max_score,
                start=0,
                num=limit,
                withscores=False
            )

            # Parse and return
            parsed_events = []
            for event_str in events:
                try:
                    event = json.loads(event_str)
                    parsed_events.append(event)
                except Exception as e:
                    logger.error(f"Failed to parse event: {e}")

            return parsed_events

        except Exception as e:
            logger.error(f"Failed to retrieve events for {event_type}: {e}")
            return []

    async def replay_events(
        self,
        event_type: str,
        callback: Callable,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> int:
        """Replay events to a callback function."""
        if not self.config.replay_enabled:
            return 0

        events = await self.get_events(event_type, start_time, end_time)

        replayed_count = 0
        for event in events:
            try:
                await callback(event["data"])
                replayed_count += 1
            except Exception as e:
                logger.error(f"Error replaying event: {e}")

        logger.info(f"Replayed {replayed_count} events for {event_type}")
        return replayed_count

    async def clear_events(self, event_type: Optional[str] = None) -> int:
        """Clear persisted events."""
        try:
            if event_type:
                key = f"{self.key_prefix}:{event_type}"
                count = self.redis.zcard(key)
                self.redis.delete(key)
                logger.info(f"Cleared {count} events for {event_type}")
                return count
            else:
                # Clear all event types
                pattern = f"{self.key_prefix}:*"
                keys = self.redis.keys(pattern)
                total_count = 0
                for key in keys:
                    count = self.redis.zcard(key)
                    total_count += count
                    self.redis.delete(key)
                logger.info(f"Cleared {total_count} events for all types")
                return total_count

        except Exception as e:
            logger.error(f"Failed to clear events: {e}")
            return 0

    async def get_event_stats(self) -> dict[str, int]:
        """Get statistics about stored events."""
        try:
            pattern = f"{self.key_prefix}:*"
            keys = self.redis.keys(pattern)

            stats = {}
            for key in keys:
                event_type = key.replace(f"{self.key_prefix}:", "")
                count = self.redis.zcard(key)
                stats[event_type] = count

            return stats

        except Exception as e:
            logger.error(f"Failed to get event stats: {e}")
            return {}


class RedisPubSubBackend:
    def __init__(self, config: RedisConfig):
        self.config = config
        self.redis_client: Optional[Any] = None
        self.pubsub: Optional[Any] = None
        self.subscribers: dict[str, list[Callable]] = {}
        self._connected = False

    async def connect(self) -> None:
        """Establish Redis connection and initialize pub/sub."""
        if self._connected:
            return

        try:
            import redis

            self.redis_client = redis.Redis(
                host=self.config.host,
                port=self.config.port,
                db=self.config.db,
                password=self.config.password,
                max_connections=self.config.max_connections,
                socket_timeout=self.config.connection_timeout,
                retry_on_timeout=self.config.retry_on_timeout,
                socket_keepalive=self.config.socket_keepalive,
                decode_responses=True
            )

            # Test connection
            self.redis_client.ping()

            # Initialize pub/sub
            self.pubsub = self.redis_client.pubsub()
            self.pubsub.subscribe(self.config.pubsub_channel)

            self._connected = True
            logger.info(f"Redis Pub/Sub connected to {self.config.host}:{self.config.port}")

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self.pubsub:
            await self.pubsub.close()
        if self.redis_client:
            await self.redis_client.close()
        self._connected = False
        logger.info("Redis Pub/Sub disconnected")

    async def publish(self, event_type: str, event_data: dict[str, Any]) -> None:
        """Publish an event to Redis."""
        if not self._connected:
            await self.connect()

        message = {
            "type": event_type,
            "data": event_data,
            "timestamp": time.time()
        }

        try:
            self.redis_client.publish(
                self.config.pubsub_channel,
                json.dumps(message)
            )
            logger.debug(f"Published event: {event_type}")
        except Exception as e:
            logger.error(f"Failed to publish event {event_type}: {e}")
            raise

    async def subscribe(self, event_type: str, callback: Callable) -> None:
        """Subscribe to an event type."""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)
        logger.debug(f"Subscribed to event: {event_type}")

    async def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Unsubscribe from an event type."""
        if event_type in self.subscribers:
            self.subscribers[event_type].remove(callback)
            if not self.subscribers[event_type]:
                del self.subscribers[event_type]
        logger.debug(f"Unsubscribed from event: {event_type}")

    async def listen(self) -> None:
        """Listen for incoming messages and dispatch to subscribers."""
        if not self._connected:
            await self.connect()

        for message in self.pubsub.listen():
            if message["type"] == "message":
                try:
                    event = json.loads(message["data"])
                    event_type = event["type"]
                    event_data = event["data"]

                    if event_type in self.subscribers:
                        for callback in self.subscribers[event_type]:
                            try:
                                await callback(event_data)
                            except Exception as e:
                                logger.error(f"Error in callback for {event_type}: {e}")

                except Exception as e:
                    logger.error(f"Error processing message: {e}")


class EventBus:
    """In-process pub/sub with async subscribers.

    Note: For multi-worker deployments, consider backing this with Redis Pub/Sub.
    The current in-process implementation is sufficient for single-node deployments.
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        redis_config: Optional[RedisConfig] = None,
        persistence_config: Optional[PersistenceConfig] = None,
        use_redis: bool = True
    ) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[Event]]] = {}
        self._max_queue_size = max_queue_size
        self._lock = asyncio.Lock()
        self.use_redis = use_redis
        self.redis_backend: Optional[RedisPubSubBackend] = None
        self.persistence: Optional[EventPersistence] = None

        if self.use_redis and redis_config:
            self.redis_backend = RedisPubSubBackend(redis_config)

        if persistence_config and persistence_config.enabled:
            self.persistence_config = persistence_config
            self.persistence: Optional[EventPersistence] = None
        else:
            self.persistence_config = None
            self.persistence = None

        self._listen_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Initialize the event bus (connect to Redis if configured)."""
        if self.redis_backend:
            await self.redis_backend.connect()

            # Initialize persistence after Redis is connected
            if self.persistence_config:
                self.persistence = EventPersistence(
                    self.redis_backend.redis_client,
                    self.persistence_config
                )

            # Start background listener
            self._listen_task = asyncio.create_task(self._listen_redis())

    async def shutdown(self) -> None:
        """Shutdown the event bus."""
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        if self.redis_backend:
            await self.redis_backend.disconnect()

    async def _listen_redis(self) -> None:
        """Background task to listen for Redis messages."""
        if self.redis_backend:
            await self.redis_backend.listen()

    async def emit(self, event: Event) -> None:
        """Alias for :meth:`publish`.

        This is the bus actually held by ``ReflectionSystem``,
        ``MetaCognition``, the human-oversight queues and the cross-session
        memory — all of which call ``self.event_bus.emit(...)``. Without the
        alias every one of those calls raised ``AttributeError`` and was
        swallowed by the surrounding ``except Exception``, so the features
        appeared wired up while publishing nothing.
        """
        await self.publish(event)

    async def publish(self, event: Event) -> None:
        """Publish an event to all matching subscribers.

        Topic matching supports wildcards:
        - Exact match: "agent.coder" matches "agent.coder"
        - Prefix wildcard: "agent.*" matches "agent.coder", "agent.tester"
        - Global: "*" matches everything
        """
        # Persist event if enabled
        if self.persistence:
            await self.persistence.store_event(event.type, event.data)

        # Publish to Redis if enabled
        if self.redis_backend:
            await self.redis_backend.publish(event.type, event.data)

        # Fall back to in-memory for local subscribers
        async with self._lock:
            for topic_pattern, queues in list(self._subscribers.items()):
                if self._match(event.type, topic_pattern):
                    for queue in list(queues):
                        if queue.full():
                            # Backpressure: drop oldest
                            try:
                                queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                        try:
                            queue.put_nowait(event)
                        except asyncio.QueueFull:
                            pass

    async def subscribe(self, topic: str = "*") -> AsyncIterator[Event]:
        """Async generator yielding events matching `topic`.

        Usage:
            async for event in bus.subscribe("agent.*"):
                print(event)
        """
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._max_queue_size)

        async with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = []
            self._subscribers[topic].append(queue)

        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            async with self._lock:
                if topic in self._subscribers and queue in self._subscribers[topic]:
                    self._subscribers[topic].remove(queue)
                    if not self._subscribers[topic]:
                        del self._subscribers[topic]

    @staticmethod
    def _match(event_type: str, pattern: str) -> bool:
        """Match event type against topic pattern."""
        if pattern == "*" or pattern == "#":
            return True
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            return event_type == prefix or event_type.startswith(prefix + ".")
        return event_type == pattern

    async def subscriber_count(self, topic: str = "*") -> int:
        """Return number of active subscribers for a topic."""
        async with self._lock:
            return len(self._subscribers.get(topic, []))

    async def replay_events(
        self,
        event_type: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> int:
        """Replay persisted events to current subscribers."""
        if not self.persistence:
            return 0

        # Replay to in-memory subscribers
        replayed_count = 0
        async with self._lock:
            for topic_pattern, queues in list(self._subscribers.items()):
                if self._match(event_type, topic_pattern):
                    events = await self.persistence.get_events(event_type, start_time, end_time)
                    for event_data in events:
                        event = Event(type=event_type, data=event_data.get("data", {}))
                        for queue in queues:
                            try:
                                queue.put_nowait(event)
                                replayed_count += 1
                            except asyncio.QueueFull:
                                pass

        return replayed_count

    async def get_event_history(
        self,
        event_type: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100
    ) -> list[dict]:
        """Get event history for debugging."""
        if self.persistence:
            return await self.persistence.get_events(
                event_type,
                start_time,
                end_time,
                limit
            )
        return []

    async def clear_event_history(self, event_type: Optional[str] = None) -> int:
        """Clear event history."""
        if self.persistence:
            return await self.persistence.clear_events(event_type)
        return 0

    async def get_event_stats(self) -> dict[str, int]:
        """Get statistics about stored events."""
        if self.persistence:
            return await self.persistence.get_event_stats()
        return {}

    async def stream_events(self, event_types: Optional[list[str]] = None) -> AsyncIterator[Event]:
        """Stream events matching the given types.

        This is used by SSE endpoints to stream events to clients.

        Args:
            event_types: List of event types to stream. If None, streams all events.

        Yields:
            Events matching the specified types.
        """
        # Subscribe to all events if no specific types requested
        topic = "*" if not event_types else "*"
        
        async for event in self.subscribe(topic):
            if event_types is None or event.type in event_types:
                yield event
