"""Real-time Dashboard System for AI Operating System Monitoring.

Implements WebSocket-based real-time updates, metrics collection,
visualization data, and interactive monitoring interface.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import websockets
from websockets.server import WebSocketServerProtocol

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """Types of metrics."""
    COUNTER = "counter"  # Cumulative counter
    GAUGE = "gauge"     # Current value
    HISTOGRAM = "histogram"  # Distribution of values
    TIMER = "timer"     # Timing measurements
    RATE = "rate"       # Rate per second


class AlertLevel(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class DashboardEventType(str, Enum):
    """Dashboard event types."""
    METRIC_UPDATE = "metric_update"
    AGENT_STATUS = "agent_status"
    SYSTEM_EVENT = "system_event"
    ALERT = "alert"
    PERFORMANCE_UPDATE = "performance_update"
    RESOURCE_UPDATE = "resource_update"


@dataclass
class Metric:
    """Metric data point."""
    metric_id: str = field(default_factory=lambda: f"metric-{uuid.uuid4().hex[:12]}")
    name: str = ""
    metric_type: MetricType = MetricType.GAUGE
    value: int | float = 0.0
    labels: dict[str, str] = field(default_factory=dict)
    
    # Timestamps
    timestamp: float = field(default_factory=time.time)
    interval: float | None = None  # For rates
    
    # Additional data
    unit: str = ""
    description: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "name": self.name,
            "metric_type": self.metric_type.value,
            "value": self.value,
            "labels": self.labels,
            "timestamp": self.timestamp,
            "interval": self.interval,
            "unit": self.unit,
            "description": self.description,
        }


@dataclass
class Alert:
    """System alert notification."""
    alert_id: str = field(default_factory=lambda: f"alert-{uuid.uuid4().hex[:12]}")
    title: str = ""
    message: str = ""
    level: AlertLevel = AlertLevel.INFO
    
    # Context
    source: str = ""
    component: str = ""
    metric_name: str | None = None
    
    # Timestamps
    created_at: float = field(default_factory=time.time)
    acknowledged_at: float | None = None
    resolved_at: float | None = None
    
    # Status
    is_acknowledged: bool = False
    is_resolved: bool = False
    
    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "title": self.title,
            "message": self.message,
            "level": self.level.value,
            "source": self.source,
            "component": self.component,
            "metric_name": self.metric_name,
            "created_at": self.created_at,
            "acknowledged_at": self.acknowledged_at,
            "resolved_at": self.resolved_at,
            "is_acknowledged": self.is_acknowledged,
            "is_resolved": self.is_resolved,
            "metadata": self.metadata,
        }


@dataclass
class AgentStatus:
    """Agent status information."""
    agent_id: str = ""
    name: str = ""
    status: str = "idle"  # idle, busy, error, maintenance
    health: float = 1.0  # 0.0-1.0
    
    # Performance metrics
    tasks_completed: int = 0
    tasks_failed: int = 0
    average_task_time: float = 0.0
    current_load: float = 0.0  # 0.0-1.0
    
    # Resource usage
    cpu_usage: float = 0.0  # 0.0-1.0
    memory_usage: float = 0.0  # 0.0-1.0
    
    # Timestamps
    last_heartbeat: float = field(default_factory=time.time)
    last_task_completed: float | None = None
    
    # Capabilities
    capabilities: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "status": self.status,
            "health": self.health,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "average_task_time": self.average_task_time,
            "current_load": self.current_load,
            "cpu_usage": self.cpu_usage,
            "memory_usage": self.memory_usage,
            "last_heartbeat": self.last_heartbeat,
            "last_task_completed": self.last_task_completed,
            "capabilities": self.capabilities,
        }


@dataclass
class DashboardEvent:
    """Dashboard event for WebSocket transmission."""
    event_id: str = field(default_factory=lambda: f"event-{uuid.uuid4().hex[:12]}")
    event_type: DashboardEventType = DashboardEventType.METRIC_UPDATE
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class MetricsCollector:
    """Collects and manages system metrics."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: redis.Redis | None = None
        
        # Metrics storage
        self.metrics: dict[str, list[Metric]] = {}
        self.metric_definitions: dict[str, dict[str, Any]] = {}
        
        # Alert rules
        self.alert_rules: list[dict[str, Any]] = []
        
    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        # Load existing metrics
        await self._load_metrics()
        
        logger.info("MetricsCollector connected")
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            
    async def _load_metrics(self) -> None:
        """Load existing metrics from Redis."""
        try:
            cursor = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match="metrics:*", count=100)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        metric_data = json.loads(data)
                        metric_name = key.split(":")[-1]
                        
                        if metric_name not in self.metrics:
                            self.metrics[metric_name] = []
                            
                        metric = Metric(**metric_data)
                        self.metrics[metric_name].append(metric)
                        
                        # Keep only last 1000 points
                        if len(self.metrics[metric_name]) > 1000:
                            self.metrics[metric_name] = self.metrics[metric_name][-1000:]
                            
        except Exception as exc:
            logger.error("Failed to load metrics: %s", exc)
            
    async def record_metric(
        self,
        name: str,
        value: int | float,
        metric_type: MetricType = MetricType.GAUGE,
        labels: dict[str, str] | None = None,
        unit: str = "",
        description: str = ""
    ) -> None:
        """Record a metric value."""
        metric = Metric(
            name=name,
            metric_type=metric_type,
            value=value,
            labels=labels or {},
            unit=unit,
            description=description,
        )
        
        # Store in memory
        if name not in self.metrics:
            self.metrics[name] = []
        self.metrics[name].append(metric)
        
        # Keep only last 1000 points
        if len(self.metrics[name]) > 1000:
            self.metrics[name] = self.metrics[name][-1000:]
            
        # Store in Redis
        if self._redis:
            key = f"metrics:{name}"
            await self._redis.setex(key, 86400, json.dumps(metric.to_dict()))  # 24 hours
            
        # Check alert rules
        await self._check_alert_rules(metric)
        
    async def _check_alert_rules(self, metric: Metric) -> None:
        """Check if metric triggers any alert rules."""
        for rule in self.alert_rules:
            if rule["metric_name"] == metric.name and self._evaluate_rule(rule, metric):
                await self._trigger_alert(rule, metric)
                    
    def _evaluate_rule(self, rule: dict[str, Any], metric: Metric) -> bool:
        """Evaluate alert rule against metric."""
        operator = rule["operator"]
        threshold = rule["threshold"]
        
        if operator == "gt":
            return metric.value > threshold
        elif operator == "lt":
            return metric.value < threshold
        elif operator == "eq":
            return metric.value == threshold
        elif operator == "gte":
            return metric.value >= threshold
        elif operator == "lte":
            return metric.value <= threshold
        else:
            return False
            
    async def _trigger_alert(self, rule: dict[str, Any], metric: Metric) -> None:
        """Trigger alert for rule."""
        # This would integrate with alert system
        logger.warning("Alert triggered: %s - %s %s %s", 
                      rule["name"], metric.name, rule["operator"], rule["threshold"])
        
    def get_metric_history(
        self,
        name: str,
        start_time: float | None = None,
        end_time: float | None = None,
        limit: int = 100
    ) -> list[Metric]:
        """Get metric history."""
        if name not in self.metrics:
            return []
            
        metrics = self.metrics[name]
        
        # Filter by time range
        if start_time or end_time:
            filtered = []
            for metric in metrics:
                if start_time and metric.timestamp < start_time:
                    continue
                if end_time and metric.timestamp > end_time:
                    continue
                filtered.append(metric)
            metrics = filtered
            
        # Sort by timestamp and limit
        metrics.sort(key=lambda m: m.timestamp, reverse=True)
        return metrics[:limit]
        
    def get_metric_summary(self, name: str) -> dict[str, Any]:
        """Get metric summary statistics."""
        if name not in self.metrics or not self.metrics[name]:
            return {}
            
        values = [m.value for m in self.metrics[name]]
        
        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "latest": values[-1] if values else None,
            "first": values[0] if values else None,
        }


class AlertManager:
    """Manages system alerts and notifications."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: redis.Redis | None = None
        
        # Alert storage
        self.active_alerts: dict[str, Alert] = {}
        self.alert_history: list[Alert] = []
        
        # Alert handlers
        self.alert_handlers: list[Callable] = []
        
    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        # Load existing alerts
        await self._load_alerts()
        
        logger.info("AlertManager connected")
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            
    async def _load_alerts(self) -> None:
        """Load existing alerts from Redis."""
        try:
            cursor = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match="alerts:*", count=100)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        alert_data = json.loads(data)
                        alert = Alert(**alert_data)
                        
                        if not alert.is_resolved:
                            self.active_alerts[alert.alert_id] = alert
                        else:
                            self.alert_history.append(alert)
                            
        except Exception as exc:
            logger.error("Failed to load alerts: %s", exc)
            
    async def create_alert(
        self,
        title: str,
        message: str,
        level: AlertLevel = AlertLevel.INFO,
        source: str = "",
        component: str = "",
        metric_name: str | None = None,
        metadata: dict[str, Any] | None = None
    ) -> str:
        """Create a new alert."""
        alert = Alert(
            title=title,
            message=message,
            level=level,
            source=source,
            component=component,
            metric_name=metric_name,
            metadata=metadata or {},
        )
        
        # Store alert
        self.active_alerts[alert.alert_id] = alert
        
        # Store in Redis
        if self._redis:
            key = f"alerts:{alert.alert_id}"
            await self._redis.setex(key, 86400 * 7, json.dumps(alert.to_dict()))  # 7 days
            
        # Notify handlers
        await self._notify_handlers(alert)
        
        logger.info("Created alert: %s - %s", alert.alert_id, alert.title)
        return alert.alert_id
        
    async def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        if alert_id not in self.active_alerts:
            return False
            
        alert = self.active_alerts[alert_id]
        alert.is_acknowledged = True
        alert.acknowledged_at = time.time()
        
        # Update Redis
        if self._redis:
            key = f"alerts:{alert_id}"
            await self._redis.setex(key, 86400 * 7, json.dumps(alert.to_dict()))
            
        logger.info("Acknowledged alert: %s", alert_id)
        return True
        
    async def resolve_alert(self, alert_id: str) -> bool:
        """Resolve an alert."""
        if alert_id not in self.active_alerts:
            return False
            
        alert = self.active_alerts[alert_id]
        alert.is_resolved = True
        alert.resolved_at = time.time()
        
        # Move to history
        self.alert_history.append(alert)
        del self.active_alerts[alert_id]
        
        # Update Redis
        if self._redis:
            key = f"alerts:{alert_id}"
            await self._redis.setex(key, 86400 * 7, json.dumps(alert.to_dict()))
            
        logger.info("Resolved alert: %s", alert_id)
        return True
        
    async def _notify_handlers(self, alert: Alert) -> None:
        """Notify alert handlers."""
        for handler in self.alert_handlers:
            try:
                await handler(alert)
            except Exception as exc:
                logger.error("Alert handler error: %s", exc)
                
    def get_active_alerts(self, level: AlertLevel | None = None) -> list[Alert]:
        """Get active alerts."""
        alerts = list(self.active_alerts.values())
        
        if level:
            alerts = [a for a in alerts if a.level == level]
            
        # Sort by creation time
        alerts.sort(key=lambda a: a.created_at, reverse=True)
        return alerts
        
    def get_alert_statistics(self) -> dict[str, Any]:
        """Get alert statistics."""
        active_by_level = {}
        for alert in self.active_alerts.values():
            active_by_level[alert.level.value] = active_by_level.get(alert.level.value, 0) + 1
            
        total_resolved = len(self.alert_history)
        
        return {
            "active_alerts": len(self.active_alerts),
            "active_by_level": active_by_level,
            "total_resolved": total_resolved,
            "resolution_rate": total_resolved / (total_resolved + len(self.active_alerts)) if (total_resolved + len(self.active_alerts)) > 0 else 0.0,
        }


class RealtimeDashboard:
    """Real-time dashboard system."""
    
    def __init__(self, host: str = "localhost", port: int = 8765, redis_url: str = "redis://localhost:6379"):
        self.host = host
        self.port = port
        self.redis_url = redis_url
        
        # Components
        self.metrics_collector = MetricsCollector(redis_url)
        self.alert_manager = AlertManager(redis_url)
        
        # WebSocket connections
        self.connections: set[WebSocketServerProtocol] = set()
        
        # Agent status tracking
        self.agent_statuses: dict[str, AgentStatus] = {}
        
        # Background tasks
        self.server_task: asyncio.Task | None = None
        self.update_task: asyncio.Task | None = None
        
    async def start(self) -> None:
        """Start the dashboard server."""
        # Initialize components
        await self.metrics_collector.connect()
        await self.alert_manager.connect()
        
        # Start WebSocket server
        self.server_task = asyncio.create_task(self._start_server())
        
        # Start background updates
        self.update_task = asyncio.create_task(self._update_loop())
        
        logger.info("RealtimeDashboard started on %s:%d", self.host, self.port)
        
    async def stop(self) -> None:
        """Stop the dashboard server."""
        if self.server_task:
            self.server_task.cancel()
        if self.update_task:
            self.update_task.cancel()
            
        # Close all connections
        for connection in self.connections:
            await connection.close()
            
        # Shutdown components
        await self.metrics_collector.disconnect()
        await self.alert_manager.disconnect()
        
        logger.info("RealtimeDashboard stopped")
        
    async def _start_server(self) -> None:
        """Start WebSocket server."""
        async def handle_client(websocket: WebSocketServerProtocol, path: str):
            await self._handle_client(websocket, path)
            
        start_server = websockets.serve(handle_client, self.host, self.port)
        await start_server
        
    async def _handle_client(self, websocket: WebSocketServerProtocol, path: str) -> None:
        """Handle WebSocket client connection."""
        logger.info("Client connected: %s", websocket.remote_address)
        
        # Add to connections
        self.connections.add(websocket)
        
        try:
            # Send initial data
            await self._send_initial_data(websocket)
            
            # Handle messages
            async for message in websocket:
                await self._handle_message(websocket, message)
                
        except websockets.exceptions.ConnectionClosed:
            logger.info("Client disconnected: %s", websocket.remote_address)
        finally:
            # Remove from connections
            self.connections.discard(websocket)
            
    async def _send_initial_data(self, websocket: WebSocketServerProtocol) -> None:
        """Send initial dashboard data to client."""
        # Send system overview
        overview = await self._get_system_overview()
        await websocket.send(json.dumps({
            "type": "initial_data",
            "data": overview
        }))
        
        # Send active alerts
        alerts = self.alert_manager.get_active_alerts()
        await websocket.send(json.dumps({
            "type": "alerts",
            "data": [alert.to_dict() for alert in alerts]
        }))
        
        # Send agent statuses
        agent_statuses = list(self.agent_statuses.values())
        await websocket.send(json.dumps({
            "type": "agent_statuses",
            "data": [status.to_dict() for status in agent_statuses]
        }))
        
    async def _handle_message(self, websocket: WebSocketServerProtocol, message: str) -> None:
        """Handle client message."""
        try:
            data = json.loads(message)
            message_type = data.get("type")
            
            if message_type == "get_metrics":
                await self._handle_get_metrics(websocket, data)
            elif message_type == "acknowledge_alert":
                await self._handle_acknowledge_alert(websocket, data)
            elif message_type == "resolve_alert":
                await self._handle_resolve_alert(websocket, data)
            else:
                logger.warning("Unknown message type: %s", message_type)
                
        except Exception as exc:
            logger.error("Message handling error: %s", exc)
            
    async def _handle_get_metrics(self, websocket: WebSocketServerProtocol, data: dict[str, Any]) -> None:
        """Handle get metrics request."""
        metric_name = data.get("metric_name")
        start_time = data.get("start_time")
        end_time = data.get("end_time")
        limit = data.get("limit", 100)
        
        metrics = self.metrics_collector.get_metric_history(
            metric_name, start_time, end_time, limit
        )
        
        await websocket.send(json.dumps({
            "type": "metrics_data",
            "data": {
                "metric_name": metric_name,
                "metrics": [m.to_dict() for m in metrics]
            }
        }))
        
    async def _handle_acknowledge_alert(self, websocket: WebSocketServerProtocol, data: dict[str, Any]) -> None:
        """Handle acknowledge alert request."""
        alert_id = data.get("alert_id")
        success = await self.alert_manager.acknowledge_alert(alert_id)
        
        await websocket.send(json.dumps({
            "type": "alert_acknowledged",
            "data": {
                "alert_id": alert_id,
                "success": success
            }
        }))
        
    async def _handle_resolve_alert(self, websocket: WebSocketServerProtocol, data: dict[str, Any]) -> None:
        """Handle resolve alert request."""
        alert_id = data.get("alert_id")
        success = await self.alert_manager.resolve_alert(alert_id)
        
        await websocket.send(json.dumps({
            "type": "alert_resolved",
            "data": {
                "alert_id": alert_id,
                "success": success
            }
        }))
        
    async def _update_loop(self) -> None:
        """Background update loop."""
        while True:
            try:
                await asyncio.sleep(5)  # Update every 5 seconds
                
                # Update metrics
                await self._update_system_metrics()
                
                # Update agent statuses
                await self._update_agent_statuses()
                
                # Broadcast updates
                await self._broadcast_updates()
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Update loop error: %s", exc)
                await asyncio.sleep(1.0)
                
    async def _update_system_metrics(self) -> None:
        """Update system metrics."""
        # Record system metrics
        import psutil
        
        # CPU usage
        cpu_percent = psutil.cpu_percent()
        await self.metrics_collector.record_metric(
            "system_cpu_usage",
            cpu_percent / 100.0,
            MetricType.GAUGE,
            unit="percent",
            description="System CPU usage"
        )
        
        # Memory usage
        memory = psutil.virtual_memory()
        await self.metrics_collector.record_metric(
            "system_memory_usage",
            memory.percent / 100.0,
            MetricType.GAUGE,
            unit="percent",
            description="System memory usage"
        )
        
        # Disk usage
        disk = psutil.disk_usage('/')
        await self.metrics_collector.record_metric(
            "system_disk_usage",
            disk.percent / 100.0,
            MetricType.GAUGE,
            unit="percent",
            description="System disk usage"
        )
        
        # Active connections
        await self.metrics_collector.record_metric(
            "dashboard_active_connections",
            len(self.connections),
            MetricType.GAUGE,
            description="Active dashboard connections"
        )
        
    async def _update_agent_statuses(self) -> None:
        """Update agent statuses."""
        current_time = time.time()
        
        for _agent_id, status in list(self.agent_statuses.items()):
            # Check if agent is stale
            if current_time - status.last_heartbeat > 60:  # 1 minute timeout
                status.status = "offline"
                status.health = 0.0
                
    async def _broadcast_updates(self) -> None:
        """Broadcast updates to all connected clients."""
        if not self.connections:
            return
            
        # Get latest metrics
        latest_metrics = {}
        for name in ["system_cpu_usage", "system_memory_usage", "system_disk_usage"]:
            metrics = self.metrics_collector.get_metric_history(name, limit=1)
            if metrics:
                latest_metrics[name] = metrics[0]
                
        # Create update event
        event = DashboardEvent(
            event_type=DashboardEventType.PERFORMANCE_UPDATE,
            data={
                "metrics": {name: metric.to_dict() for name, metric in latest_metrics.items()},
                "agent_statuses": [status.to_dict() for status in self.agent_statuses.values()],
                "timestamp": time.time()
            }
        )
        
        # Broadcast to all connections
        message = json.dumps(event.to_dict())
        disconnected = set()
        
        for connection in self.connections:
            try:
                await connection.send(message)
            except Exception:
                disconnected.add(connection)
                
        # Remove disconnected connections
        self.connections -= disconnected
        
    async def _get_system_overview(self) -> dict[str, Any]:
        """Get system overview data."""
        return {
            "system_info": {
                "hostname": "nexus-omega",
                "uptime": time.time(),
                "version": "2.0.0",
            },
            "metrics_summary": {
                "cpu_usage": self.metrics_collector.get_metric_summary("system_cpu_usage"),
                "memory_usage": self.metrics_collector.get_metric_summary("system_memory_usage"),
                "disk_usage": self.metrics_collector.get_metric_summary("system_disk_usage"),
            },
            "alert_stats": self.alert_manager.get_alert_statistics(),
            "agent_count": len(self.agent_statuses),
            "active_connections": len(self.connections),
        }
        
    async def update_agent_status(self, status: AgentStatus) -> None:
        """Update agent status."""
        self.agent_statuses[status.agent_id] = status
        
        # Broadcast update
        if self.connections:
            event = DashboardEvent(
                event_type=DashboardEventType.AGENT_STATUS,
                data=status.to_dict()
            )
            
            message = json.dumps(event.to_dict())
            for connection in self.connections:
                with contextlib.suppress(Exception):
                    await connection.send(message)
                    
    async def create_alert(
        self,
        title: str,
        message: str,
        level: AlertLevel = AlertLevel.INFO,
        source: str = "",
        component: str = "",
        metric_name: str | None = None
    ) -> str:
        """Create and broadcast alert."""
        alert_id = await self.alert_manager.create_alert(
            title, message, level, source, component, metric_name
        )
        
        # Broadcast alert
        if self.connections:
            alert = self.alert_manager.active_alerts.get(alert_id)
            if alert:
                event = DashboardEvent(
                    event_type=DashboardEventType.ALERT,
                    data=alert.to_dict()
                )
                
                message = json.dumps(event.to_dict())
                for connection in self.connections:
                    with contextlib.suppress(Exception):
                        await connection.send(message)
                        
        return alert_id
        
    def get_dashboard_stats(self) -> dict[str, Any]:
        """Get dashboard statistics."""
        return {
            "active_connections": len(self.connections),
            "total_agents": len(self.agent_statuses),
            "active_alerts": len(self.alert_manager.active_alerts),
            "metrics_count": len(self.metrics_collector.metrics),
            "uptime": time.time(),
        }


# Global dashboard instance
realtime_dashboard: RealtimeDashboard | None = None