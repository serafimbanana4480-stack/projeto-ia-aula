"""WebSocket Server - Real-time dashboard communication.

This server provides:
- WebSocket connections for dashboard
- Real-time event streaming
- Client connection management
- Message broadcasting
- Connection health monitoring
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import websockets
from websockets.server import WebSocketServerProtocol

from backend.observability.event_system import Event, EventBus

logger = logging.getLogger(__name__)


class ClientType(str, Enum):
    """Types of WebSocket clients."""
    DASHBOARD = "dashboard"
    AGENT = "agent"
    MONITOR = "monitor"
    API = "api"


class MessageType(str, Enum):
    """WebSocket message types."""
    EVENT = "event"
    STATE = "state"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    METRICS = "metrics"
    HEARTBEAT = "heartbeat"


@dataclass
class WebSocketClient:
    """WebSocket client connection."""
    client_id: str = field(default_factory=lambda: f"client-{uuid.uuid4().hex[:12]}")
    websocket: WebSocketServerProtocol = None
    client_type: ClientType = ClientType.DASHBOARD
    connected_at: datetime = field(default_factory=datetime.now)
    last_heartbeat: datetime = field(default_factory=datetime.now)
    subscriptions: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def is_alive(self) -> bool:
        """Check if client is still alive."""
        return (datetime.now() - self.last_heartbeat).seconds < 60
    
    def to_dict(self) -> dict[str, Any]:
        """Convert client to dictionary."""
        return {
            "client_id": self.client_id,
            "client_type": self.client_type.value,
            "connected_at": self.connected_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "subscriptions": list(self.subscriptions),
            "metadata": self.metadata,
            "is_alive": self.is_alive()
        }


@dataclass
class WebSocketMessage:
    """WebSocket message."""
    message_id: str = field(default_factory=lambda: f"msg-{uuid.uuid4().hex[:12]}")
    message_type: MessageType = MessageType.EVENT
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    client_id: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert message to dictionary."""
        return {
            "message_id": self.message_id,
            "message_type": self.message_type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "client_id": self.client_id
        }
    
    def to_json(self) -> str:
        """Convert message to JSON string."""
        return json.dumps(self.to_dict())


class WebSocketServer:
    """WebSocket server for dashboard communication."""
    
    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.clients: dict[str, WebSocketClient] = {}
        self.event_bus: EventBus | None = None
        self._running = False
        self._server: websockets.WebSocketServer | None = None
        self._stats = {
            "total_connections": 0,
            "active_connections": 0,
            "messages_sent": 0,
            "messages_received": 0,
            "errors": 0
        }
        self._heartbeat_task: asyncio.Task | None = None
    
    async def start(self, event_bus: EventBus) -> None:
        """Start the WebSocket server."""
        if self._running:
            return
        
        self.event_bus = event_bus
        self._running = True
        
        # Start heartbeat task
        self._heartbeat_task = asyncio.create_task(self._heartbeat_monitor())
        
        # Start WebSocket server
        self._server = await websockets.serve(
            self.handle_client,
            self.host,
            self.port,
            ping_interval=30,
            ping_timeout=10
        )
        
        logger.info(f"WebSocket server started on {self.host}:{self.port}")
    
    async def stop(self) -> None:
        """Stop the WebSocket server."""
        self._running = False
        
        # Cancel heartbeat task
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None
        
        # Close all client connections
        for client in list(self.clients.values()):
            with contextlib.suppress(Exception):
                await client.websocket.close()
        
        # Close server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        
        logger.info("WebSocket server stopped")
    
    async def handle_client(self, websocket: WebSocketServerProtocol, path: str) -> None:
        """Handle a new WebSocket client connection."""
        client = WebSocketClient(websocket=websocket)
        self.clients[client.client_id] = client
        self._stats["total_connections"] += 1
        self._stats["active_connections"] += 1
        
        logger.info(f"Client {client.client_id} connected from {websocket.remote_address}")
        
        try:
            # Send welcome message
            await self.send_message(client, WebSocketMessage(
                message_type=MessageType.STATE,
                data={
                    "status": "connected",
                    "client_id": client.client_id,
                    "server_time": datetime.now().isoformat()
                }
            ))
            
            # Handle client messages
            async for message in websocket:
                await self.handle_message(client, message)
                
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client {client.client_id} disconnected")
        except Exception as e:
            logger.error(f"Error handling client {client.client_id}: {e}")
            self._stats["errors"] += 1
        finally:
            # Clean up client
            if client.client_id in self.clients:
                del self.clients[client.client_id]
                self._stats["active_connections"] -= 1
    
    async def handle_message(self, client: WebSocketClient, message: str) -> None:
        """Handle a message from a client."""
        try:
            data = json.loads(message)
            message_type = MessageType(data.get("type", "event"))
            
            self._stats["messages_received"] += 1
            
            if message_type == MessageType.PING:
                await self.send_message(client, WebSocketMessage(
                    message_type=MessageType.PONG,
                    data={"timestamp": datetime.now().isoformat()}
                ))
            elif message_type == MessageType.SUBSCRIBE:
                subscriptions = data.get("subscriptions", [])
                for sub in subscriptions:
                    client.subscriptions.add(sub)
                await self.send_message(client, WebSocketMessage(
                    message_type=MessageType.STATE,
                    data={"subscriptions": list(client.subscriptions)}
                ))
            elif message_type == MessageType.UNSUBSCRIBE:
                subscriptions = data.get("subscriptions", [])
                for sub in subscriptions:
                    client.subscriptions.discard(sub)
                await self.send_message(client, WebSocketMessage(
                    message_type=MessageType.STATE,
                    data={"subscriptions": list(client.subscriptions)}
                ))
            elif message_type == MessageType.HEARTBEAT:
                client.last_heartbeat = datetime.now()
                await self.send_message(client, WebSocketMessage(
                    message_type=MessageType.HEARTBEAT,
                    data={"timestamp": datetime.now().isoformat()}
                ))
            
        except Exception as e:
            logger.error(f"Error handling message from {client.client_id}: {e}")
            self._stats["errors"] += 1
            await self.send_message(client, WebSocketMessage(
                message_type=MessageType.ERROR,
                data={"error": str(e)}
            ))
    
    async def send_message(self, client: WebSocketClient, message: WebSocketMessage) -> None:
        """Send a message to a client."""
        try:
            await client.websocket.send(message.to_json())
            self._stats["messages_sent"] += 1
        except Exception as e:
            logger.error(f"Error sending message to {client.client_id}: {e}")
            self._stats["errors"] += 1
    
    async def broadcast_event(self, event: Event) -> None:
        """Broadcast an event to all subscribed clients."""
        message = WebSocketMessage(
            message_type=MessageType.EVENT,
            data=event.to_dict()
        )
        
        # Send to all clients
        disconnected_clients = []
        for client_id, client in self.clients.items():
            try:
                # Check if client is subscribed to this event type
                if not client.subscriptions or event.event_type.value in client.subscriptions:
                    await self.send_message(client, message)
            except Exception as e:
                logger.error(f"Error broadcasting to {client_id}: {e}")
                disconnected_clients.append(client_id)
                self._stats["errors"] += 1
        
        # Remove disconnected clients
        for client_id in disconnected_clients:
            if client_id in self.clients:
                del self.clients[client_id]
                self._stats["active_connections"] -= 1
    
    async def broadcast_to_type(self, client_type: ClientType, message: WebSocketMessage) -> None:
        """Broadcast a message to all clients of a specific type."""
        for client in self.clients.values():
            if client.client_type == client_type:
                await self.send_message(client, message)
    
    async def get_client_stats(self) -> dict[str, Any]:
        """Get client statistics."""
        return {
            "total_clients": len(self.clients),
            "clients_by_type": {
                client_type.value: len([c for c in self.clients.values() if c.client_type == client_type])
                for client_type in ClientType
            },
            "active_clients": len([c for c in self.clients.values() if c.is_alive()]),
            "average_session_time": self._calculate_average_session_time(),
            "clients": [client.to_dict() for client in self.clients.values()]
        }
    
    def _calculate_average_session_time(self) -> float:
        """Calculate average session time in seconds."""
        if not self.clients:
            return 0.0
        
        now = datetime.now()
        total_time = sum((now - client.connected_at).seconds for client in self.clients.values())
        return total_time / len(self.clients)
    
    async def _heartbeat_monitor(self) -> None:
        """Monitor client heartbeats and clean up dead connections."""
        while self._running:
            try:
                # Check for dead clients
                dead_clients = []
                for client_id, client in self.clients.items():
                    if not client.is_alive():
                        dead_clients.append(client_id)
                        with contextlib.suppress(Exception):
                            await client.websocket.close()
                
                # Remove dead clients
                for client_id in dead_clients:
                    del self.clients[client_id]
                    self._stats["active_connections"] -= 1
                    logger.info(f"Removed dead client {client_id}")
                
                # Send heartbeat to all clients
                heartbeat_message = WebSocketMessage(
                    message_type=MessageType.HEARTBEAT,
                    data={"timestamp": datetime.now().isoformat()}
                )
                
                for client in self.clients.values():
                    await self.send_message(client, heartbeat_message)
                
                # Sleep for 30 seconds
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error(f"Error in heartbeat monitor: {e}")
                await asyncio.sleep(5)
    
    async def get_stats(self) -> dict[str, Any]:
        """Get server statistics."""
        return {
            "running": self._running,
            "host": self.host,
            "port": self.port,
            "clients": await self.get_client_stats(),
            **self._stats
        }


# Global WebSocket server instance
_websocket_server: WebSocketServer | None = None


async def get_websocket_server() -> WebSocketServer:
    """Get the global WebSocket server instance."""
    global _websocket_server
    if _websocket_server is None:
        _websocket_server = WebSocketServer()
    return _websocket_server


async def start_websocket_server(event_bus: EventBus) -> WebSocketServer:
    """Start the WebSocket server with event bus."""
    server = await get_websocket_server()
    await server.start(event_bus)
    return server


async def stop_websocket_server() -> None:
    """Stop the WebSocket server."""
    global _websocket_server
    if _websocket_server:
        await _websocket_server.stop()
        _websocket_server = None