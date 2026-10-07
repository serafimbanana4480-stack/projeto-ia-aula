"""MessageBus — structured inter-agent communication protocol.

Supports hierarchical (Supreme → Team → Worker) and peer-to-peer messaging
with request/response correlation and broadcast discovery.

Features:
- Local EventBus for in-process messaging
- Redis Pub/Sub for distributed messaging and persistence
- Automatic fallback to local-only if Redis unavailable
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from backend.observability.event_bus import EventBus
from backend.observability.events import Event

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None  # type: ignore


@dataclass
class AgentMessage:
    """Structured message between agents."""

    msg_type: str  # DELEGATE, CONSULT, REPORT, CONFLICT, APPROVE
    sender: str
    recipient: str
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=lambda: asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0)

    def to_event(self) -> Event:
        return Event(
            type=f"msg.{self.msg_type}",
            agent=self.sender,
            payload={
                "recipient": self.recipient,
                "correlation_id": self.correlation_id,
                "data": self.payload,
            },
        )

    def to_json(self) -> str:
        """Serialize message to JSON for Redis transmission."""
        return json.dumps({
            "msg_type": self.msg_type,
            "sender": self.sender,
            "recipient": self.recipient,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
        })

    @classmethod
    def from_json(cls, data: str) -> AgentMessage:
        """Deserialize message from JSON."""
        obj = json.loads(data)
        return cls(
            msg_type=obj["msg_type"],
            sender=obj["sender"],
            recipient=obj["recipient"],
            payload=obj.get("payload", {}),
            correlation_id=obj["correlation_id"],
            timestamp=obj.get("timestamp", 0),
        )


class MessageBus:
    """Structured messaging with Redis Pub/Sub support.
    
    Falls back to local EventBus if Redis is unavailable.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        redis_url: str = "redis://localhost:6379",
        use_redis: bool = True,
    ) -> None:
        self._bus = event_bus or EventBus()
        self._pending: dict[str, asyncio.Queue[AgentMessage]] = {}
        self._redis_url = redis_url
        self._use_redis = use_redis and REDIS_AVAILABLE
        self._redis: redis.Redis | None = None
        self._pubsub: Any | None = None
        self._redis_connected = False
        self._message_queues: dict[str, asyncio.Queue[AgentMessage]] = {}
        self._listener_task: asyncio.Task | None = None

    async def connect_redis(self) -> bool:
        """Connect to Redis for distributed messaging.
        
        Returns:
            True if connected successfully, False otherwise.
        """
        if not self._use_redis:
            return False
            
        try:
            self._redis = redis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe("nexus:messages")
            self._redis_connected = True
            
            # Start listener task
            self._listener_task = asyncio.create_task(self._redis_listener())
            
            logger.info("MessageBus connected to Redis at %s", self._redis_url)
            return True
        except Exception as e:
            logger.warning("Failed to connect MessageBus to Redis: %s. Using local only.", e)
            self._redis_connected = False
            return False

    async def disconnect_redis(self) -> None:
        """Disconnect from Redis."""
        if self._listener_task:
            self._listener_task.cancel()
            self._listener_task = None
            
        if self._pubsub:
            await self._pubsub.unsubscribe()
            self._pubsub = None
            
        if self._redis:
            await self._redis.close()
            self._redis = None
            
        self._redis_connected = False
        logger.info("MessageBus disconnected from Redis")

    async def _redis_listener(self) -> None:
        """Listen for messages from Redis Pub/Sub."""
        if not self._pubsub:
            return
            
        while True:
            try:
                message = await self._pubsub.get_message(timeout=1.0)
                if message and message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, str):
                        msg = AgentMessage.from_json(data)
                        # Put in recipient's queue
                        if msg.recipient in self._message_queues:
                            await self._message_queues[msg.recipient].put(msg)
                        # Also put in wildcard queue
                        if "*" in self._message_queues:
                            await self._message_queues["*"].put(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in Redis listener: %s", e)
                await asyncio.sleep(1.0)

    async def send(self, message: AgentMessage) -> None:
        """Send a message to a specific recipient.
        
        Uses Redis if connected, otherwise falls back to local EventBus.
        """
        # Always publish to local EventBus
        await self._bus.publish(message.to_event())
        
        # Also publish to Redis if connected
        if self._redis_connected and self._redis:
            try:
                await self._redis.publish("nexus:messages", message.to_json())
            except Exception as e:
                logger.warning("Failed to publish to Redis: %s", e)
                
        logger.debug("Message %s: %s -> %s", message.msg_type, message.sender, message.recipient)

    async def request(
        self,
        message: AgentMessage,
        timeout: float = 30.0,
    ) -> AgentMessage | None:
        """Send a request and wait for response.

        Args:
            message: Request message.
            timeout: Max wait time.

        Returns:
            Response message or None on timeout.
        """
        response_queue: asyncio.Queue[AgentMessage] = asyncio.Queue()
        self._pending[message.correlation_id] = response_queue

        try:
            await self.send(message)
            return await asyncio.wait_for(response_queue.get(), timeout=timeout)
        except TimeoutError:
            logger.warning("Request timeout: %s", message.correlation_id)
            return None
        finally:
            self._pending.pop(message.correlation_id, None)

    async def respond(self, request_id: str, message: AgentMessage) -> None:
        """Send a response to a pending request."""
        if request_id in self._pending:
            await self._pending[request_id].put(message)
        else:
            await self.send(message)

    async def broadcast(self, sender: str, query: str) -> list[AgentMessage]:
        """Broadcast a discovery query and collect responses.

        Args:
            sender: Sending agent name.
            query: Capability query (e.g., "Who can optimize Python?").

        Returns:
            List of response messages.
        """
        message = AgentMessage(
            msg_type="CONSULT",
            sender=sender,
            recipient="*",
            payload={"query": query, "broadcast": True},
        )

        responses: list[AgentMessage] = []

        async def collect() -> None:
            async for event in self._bus.subscribe("msg.CONSULT"):
                # Filter responses to our query
                data = event.payload.get("data", {})
                if data.get("in_response_to") == message.correlation_id:
                    responses.append(AgentMessage(
                        msg_type="REPORT",
                        sender=event.agent or "unknown",
                        recipient=sender,
                        payload=data,
                    ))
                if len(responses) >= 5:
                    break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.05)
        await self.send(message)

        try:
            await asyncio.wait_for(task, timeout=5.0)
        except TimeoutError:
            task.cancel()

        return responses

    async def subscribe_messages(self, agent_name: str) -> AsyncIterator[AgentMessage]:
        """Subscribe to messages directed at a specific agent.
        
        Uses Redis queue if connected, otherwise falls back to local EventBus.
        """
        # Create queue for this agent
        queue: asyncio.Queue[AgentMessage] = asyncio.Queue()
        self._message_queues[agent_name] = queue
        
        try:
            # If Redis is connected, also listen from local EventBus for local messages
            if self._redis_connected:
                # Combine Redis queue and local EventBus
                local_subscriber = self._bus.subscribe("msg.*")
                
                while True:
                    # Check both Redis queue and local EventBus
                    try:
                        # Non-blocking check for Redis messages
                        msg = queue.get_nowait()
                        yield msg
                        continue
                    except asyncio.QueueEmpty:
                        pass
                    
                    # Check local EventBus with small timeout
                    try:
                        async for event in local_subscriber:
                            payload = event.payload or {}
                            if payload.get("recipient") in (agent_name, "*"):
                                yield AgentMessage(
                                    msg_type=event.type.replace("msg.", ""),
                                    sender=event.agent or "unknown",
                                    recipient=payload.get("recipient", ""),
                                    payload=payload.get("data", {}),
                                    correlation_id=payload.get("correlation_id", ""),
                                )
                            break  # Check Redis queue again
                    except Exception:
                        pass
                    
                    # Small delay to prevent busy loop
                    await asyncio.sleep(0.01)
            else:
                # Local only mode
                async for event in self._bus.subscribe("msg.*"):
                    payload = event.payload or {}
                    if payload.get("recipient") in (agent_name, "*"):
                        yield AgentMessage(
                            msg_type=event.type.replace("msg.", ""),
                            sender=event.agent or "unknown",
                            recipient=payload.get("recipient", ""),
                            payload=payload.get("data", {}),
                            correlation_id=payload.get("correlation_id", ""),
                        )
        finally:
            # Clean up queue
            self._message_queues.pop(agent_name, None)
