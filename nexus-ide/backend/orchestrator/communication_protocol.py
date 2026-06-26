"""Professional Agent Communication Protocol with streaming, priorities, and acknowledgements.

Implements structured messaging, versioning, validation, compression,
context transfer, and memory sharing between agents.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
import zlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union
from datetime import datetime

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """Message types with priority levels."""
    # High priority - system messages
    SYSTEM = "system"
    ERROR = "error"
    URGENT = "urgent"
    
    # Normal priority - agent communication
    DELEGATE = "delegate"
    CONSULT = "consult"
    REPORT = "report"
    REQUEST = "request"
    RESPONSE = "response"
    
    # Low priority - notifications
    NOTIFY = "notify"
    STATUS = "status"
    LOG = "log"
    
    # Streaming
    STREAM_START = "stream_start"
    STREAM_CHUNK = "stream_chunk"
    STREAM_END = "stream_end"


class MessagePriority(str, Enum):
    """Message priority levels for queuing."""
    CRITICAL = 3
    HIGH = 2
    NORMAL = 1
    LOW = 0


@dataclass
class MessageEnvelope:
    """Structured message envelope with metadata and routing."""
    message_id: str = field(default_factory=lambda: f"msg-{uuid.uuid4().hex[:16]}")
    message_type: MessageType = MessageType.REQUEST
    sender_id: str = ""
    recipient_id: str = ""
    correlation_id: Optional[str] = None  # For request/response correlation
    parent_message_id: Optional[str] = None  # For message threads
    priority: MessagePriority = MessagePriority.NORMAL
    timestamp: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    
    # Content
    payload: Dict[str, Any] = field(default_factory=dict)
    context: Optional[Dict[str, Any]] = None
    attachments: List[str] = field(default_factory=list)  # File/memory references
    
    # Protocol metadata
    version: str = "1.0"
    compression: str = "none"  # none, gzip, lz4
    encoding: str = "utf-8"
    
    # Routing metadata
    routing_key: Optional[str] = None
    topic: Optional[str] = None
    tags: Set[str] = field(default_factory=set)
    
    # Delivery metadata
    delivery_attempts: int = 0
    max_attempts: int = 3
    timeout: float = 30.0
    require_ack: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "message_id": self.message_id,
            "message_type": self.message_type.value,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "correlation_id": self.correlation_id,
            "parent_message_id": self.parent_message_id,
            "priority": self.priority.value,
            "timestamp": self.timestamp,
            "expires_at": self.expires_at,
            "payload": self.payload,
            "context": self.context,
            "attachments": self.attachments,
            "version": self.version,
            "compression": self.compression,
            "encoding": self.encoding,
            "routing_key": self.routing_key,
            "topic": self.topic,
            "tags": list(self.tags),
            "delivery_attempts": self.delivery_attempts,
            "max_attempts": self.max_attempts,
            "timeout": self.timeout,
            "require_ack": self.require_ack,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageEnvelope":
        """Create from dictionary."""
        envelope = cls(
            message_id=data["message_id"],
            message_type=MessageType(data["message_type"]),
            sender_id=data["sender_id"],
            recipient_id=data["recipient_id"],
            correlation_id=data.get("correlation_id"),
            parent_message_id=data.get("parent_message_id"),
            priority=MessagePriority(data["priority"]),
            timestamp=data["timestamp"],
            expires_at=data.get("expires_at"),
            payload=data["payload"],
            context=data.get("context"),
            attachments=data.get("attachments", []),
            version=data["version"],
            compression=data["compression"],
            encoding=data["encoding"],
            routing_key=data.get("routing_key"),
            topic=data.get("topic"),
            tags=set(data.get("tags", [])),
            delivery_attempts=data["delivery_attempts"],
            max_attempts=data["max_attempts"],
            timeout=data["timeout"],
            require_ack=data["require_ack"],
        )
        return envelope
        
    def is_expired(self) -> bool:
        """Check if message has expired."""
        if self.expires_at:
            return time.time() > self.expires_at
        return False
        
    def should_retry(self) -> bool:
        """Check if message should be retried."""
        return self.delivery_attempts < self.max_attempts
        
    def increment_attempt(self) -> None:
        """Increment delivery attempt counter."""
        self.delivery_attempts += 1


@dataclass
class Acknowledgement:
    """Message acknowledgement with status."""
    message_id: str
    status: str  # delivered, processed, failed, timeout
    timestamp: float = field(default_factory=time.time)
    error: Optional[str] = None
    processing_time: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "status": self.status,
            "timestamp": self.timestamp,
            "error": self.error,
            "processing_time": self.processing_time,
            "metadata": self.metadata,
        }


class MessageValidator:
    """Message validation and schema enforcement."""
    
    def __init__(self):
        self.schemas: Dict[str, Dict[str, Any]] = {
            "1.0": {
                "required_fields": ["message_id", "message_type", "sender_id", "timestamp"],
                "message_types": [t.value for t in MessageType],
                "priorities": [p.value for p in MessagePriority],
                "max_payload_size": 10 * 1024 * 1024,  # 10MB
                "max_attachments": 100,
            }
        }
        
    def validate(self, envelope: MessageEnvelope) -> List[str]:
        """Validate message envelope and return errors."""
        errors = []
        
        # Check schema version
        schema = self.schemas.get(envelope.version)
        if not schema:
            errors.append(f"Unknown schema version: {envelope.version}")
            return errors
            
        # Check required fields
        for field in schema["required_fields"]:
            if not getattr(envelope, field, None):
                errors.append(f"Missing required field: {field}")
                
        # Check message type
        if envelope.message_type.value not in schema["message_types"]:
            errors.append(f"Invalid message type: {envelope.message_type}")
            
        # Check priority
        if envelope.priority.value not in schema["priorities"]:
            errors.append(f"Invalid priority: {envelope.priority}")
            
        # Check payload size
        payload_size = len(json.dumps(envelope.payload))
        if payload_size > schema["max_payload_size"]:
            errors.append(f"Payload too large: {payload_size} bytes")
            
        # Check attachments
        if len(envelope.attachments) > schema["max_attachments"]:
            errors.append(f"Too many attachments: {len(envelope.attachments)}")
            
        # Check expiration
        if envelope.expires_at and envelope.expires_at < time.time():
            errors.append("Message already expired")
            
        return errors


class MessageCompressor:
    """Message compression and decompression."""
    
    @staticmethod
    def compress(data: str, algorithm: str = "gzip") -> bytes:
        """Compress message data."""
        if algorithm == "gzip":
            return zlib.compress(data.encode('utf-8'))
        else:
            return data.encode('utf-8')
            
    @staticmethod
    def decompress(data: bytes, algorithm: str = "gzip") -> str:
        """Decompress message data."""
        if algorithm == "gzip":
            return zlib.decompress(data).decode('utf-8')
        else:
            return data.decode('utf-8')


class MessageProtocol:
    """Professional message protocol with validation, compression, and routing."""
    
    def __init__(self):
        self.validator = MessageValidator()
        self.compressor = MessageCompressor()
        self.message_handlers: Dict[str, callable] = {}
        self.subscribers: Dict[str, List[callable]] = {}
        
        # Message tracking
        self.sent_messages: Dict[str, MessageEnvelope] = {}
        self.received_messages: Dict[str, MessageEnvelope] = {}
        self.acknowledgements: Dict[str, Acknowledgement] = {}
        
    def register_handler(self, message_type: str, handler: callable) -> None:
        """Register handler for message type."""
        self.message_handlers[message_type] = handler
        
    def subscribe(self, topic: str, callback: callable) -> None:
        """Subscribe to topic."""
        if topic not in self.subscribers:
            self.subscribers[topic] = []
        self.subscribers[topic].append(callback)
        
    async def send_message(
        self,
        envelope: MessageEnvelope,
        validate: bool = True,
        compress: bool = True,
    ) -> str:
        """Send a message with validation and compression."""
        # Validate message
        if validate:
            errors = self.validator.validate(envelope)
            if errors:
                raise ValueError(f"Message validation failed: {errors}")
                
        # Compress payload if needed
        if compress and len(json.dumps(envelope.payload)) > 1024:
            envelope.compression = "gzip"
            compressed_payload = self.compressor.compress(json.dumps(envelope.payload))
            envelope.payload = {"_compressed": True, "data": compressed_payload.hex()}
            
        # Track message
        self.sent_messages[envelope.message_id] = envelope
        
        # Route message
        await self._route_message(envelope)
        
        return envelope.message_id
        
    async def _route_message(self, envelope: MessageEnvelope) -> None:
        """Route message to appropriate handlers."""
        # Check for direct recipient
        if envelope.recipient_id:
            await self._deliver_to_recipient(envelope)
        else:
            # Route by topic
            if envelope.topic:
                await self._deliver_to_topic(envelope)
                
        # Route by message type
        handler = self.message_handlers.get(envelope.message_type.value)
        if handler:
            await handler(envelope)
            
    async def _deliver_to_recipient(self, envelope: MessageEnvelope) -> None:
        """Deliver message to specific recipient."""
        # In real implementation, this would deliver to the recipient's queue
        logger.debug("Delivering message %s to recipient %s", 
                    envelope.message_id, envelope.recipient_id)
        
        # Simulate delivery
        await self._simulate_delivery(envelope)
        
    async def _deliver_to_topic(self, envelope: MessageEnvelope) -> None:
        """Deliver message to topic subscribers."""
        subscribers = self.subscribers.get(envelope.topic, [])
        
        for subscriber in subscribers:
            try:
                await subscriber(envelope)
            except Exception as exc:
                logger.error("Subscriber error for topic %s: %s", envelope.topic, exc)
                
    async def _simulate_delivery(self, envelope: MessageEnvelope) -> None:
        """Simulate message delivery with processing time."""
        # Simulate processing time based on message size
        processing_time = len(json.dumps(envelope.to_dict())) * 0.001
        await asyncio.sleep(processing_time)
        
        # Send acknowledgement if required
        if envelope.require_ack:
            ack = Acknowledgement(
                message_id=envelope.message_id,
                status="delivered",
                processing_time=processing_time,
            )
            self.acknowledgements[envelope.message_id] = ack
            
    async def receive_message(
        self,
        message_data: Union[str, Dict[str, Any]],
        validate: bool = True,
    ) -> MessageEnvelope:
        """Receive and process incoming message."""
        # Parse message
        if isinstance(message_data, str):
            try:
                data = json.loads(message_data)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON message data")
        else:
            data = message_data
            
        # Create envelope
        envelope = MessageEnvelope.from_dict(data)
        
        # Decompress if needed
        if envelope.payload.get("_compressed"):
            compressed_data = bytes.fromhex(envelope.payload["data"])
            envelope.payload = json.loads(self.compressor.decompress(compressed_data))
            envelope.compression = "gzip"
            
        # Validate message
        if validate:
            errors = self.validator.validate(envelope)
            if errors:
                raise ValueError(f"Message validation failed: {errors}")
                
        # Check expiration
        if envelope.is_expired():
            raise ValueError("Message has expired")
            
        # Track message
        self.received_messages[envelope.message_id] = envelope
        
        return envelope
        
    def get_message_status(self, message_id: str) -> Dict[str, Any]:
        """Get message status and metadata."""
        status = {
            "message_id": message_id,
            "sent": message_id in self.sent_messages,
            "received": message_id in self.received_messages,
            "acknowledged": message_id in self.acknowledgements,
        }
        
        if message_id in self.sent_messages:
            envelope = self.sent_messages[message_id]
            status["sent_at"] = envelope.timestamp
            status["delivery_attempts"] = envelope.delivery_attempts
            
        if message_id in self.received_messages:
            envelope = self.received_messages[message_id]
            status["received_at"] = envelope.timestamp
            
        if message_id in self.acknowledgements:
            ack = self.acknowledgements[message_id]
            status["acknowledged_at"] = ack.timestamp
            status["ack_status"] = ack.status
            status["processing_time"] = ack.processing_time
            
        return status
        
    def get_protocol_stats(self) -> Dict[str, Any]:
        """Get protocol statistics."""
        return {
            "sent_messages": len(self.sent_messages),
            "received_messages": len(self.received_messages),
            "acknowledgements": len(self.acknowledgements),
            "registered_handlers": len(self.message_handlers),
            "active_subscriptions": {
                topic: len(subs) for topic, subs in self.subscribers.items()
            },
            "compression_stats": self._get_compression_stats(),
        }
        
    def _get_compression_stats(self) -> Dict[str, Any]:
        """Get compression statistics."""
        compressed_count = sum(
            1 for msg in self.sent_messages.values()
            if msg.compression == "gzip"
        )
        
        return {
            "total_messages": len(self.sent_messages),
            "compressed_messages": compressed_count,
            "compression_ratio": compressed_count / len(self.sent_messages) if self.sent_messages else 0,
        }


# Global protocol instance
protocol = MessageProtocol()