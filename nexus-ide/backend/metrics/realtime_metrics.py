"""Real-time Metrics Collection System for NEXUS OMEGA.

This system provides:
- Real-time system metrics collection
- Performance monitoring
- Resource usage tracking
- Token analytics
- Model performance metrics
- Agent performance tracking
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import psutil

from backend.observability.event_system import Event, EventBus, EventType

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """Types of metrics."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    RATE = "rate"
    TIMER = "timer"


class MetricCategory(str, Enum):
    """Categories of metrics."""
    SYSTEM = "system"
    AGENT = "agent"
    MODEL = "model"
    TOKEN = "token"
    TASK = "task"
    MEMORY = "memory"
    NETWORK = "network"
    SECURITY = "security"
    PERFORMANCE = "performance"


@dataclass
class MetricPoint:
    """Single metric data point."""
    metric_id: str = field(default_factory=lambda: f"metric-{uuid.uuid4().hex[:12]}")
    name: str = ""
    category: MetricCategory = MetricCategory.SYSTEM
    metric_type: MetricType = MetricType.GAUGE
    value: float = 0.0
    labels: dict[str, str] = field(default_factory=dict)
    unit: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert metric to dictionary."""
        return {
            "metric_id": self.metric_id,
            "name": self.name,
            "category": self.category.value,
            "metric_type": self.metric_type.value,
            "value": self.value,
            "labels": self.labels,
            "unit": self.unit,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class MetricAggregation:
    """Aggregated metric data."""
    name: str
    category: MetricCategory
    metric_type: MetricType
    count: int = 0
    sum: float = 0.0
    min: float = 0.0
    max: float = 0.0
    avg: float = 0.0
    last_value: float = 0.0
    trend: str = "stable"
    timestamp: datetime = field(default_factory=datetime.now)

    def update(self, value: float) -> None:
        """Update aggregation with new value."""
        self.count += 1
        self.sum += value
        self.last_value = value

        if self.count == 1:
            self.min = value
            self.max = value
            self.avg = value
        else:
            self.min = min(self.min, value)
            self.max = max(self.max, value)
            self.avg = self.sum / self.count

        # Calculate trend
        if self.count >= 2:
            if value > self.avg * 1.1:
                self.trend = "increasing"
            elif value < self.avg * 0.9:
                self.trend = "decreasing"
            else:
                self.trend = "stable"

    def to_dict(self) -> dict[str, Any]:
        """Convert aggregation to dictionary."""
        return {
            "name": self.name,
            "category": self.category.value,
            "metric_type": self.metric_type.value,
            "count": self.count,
            "sum": self.sum,
            "min": self.min,
            "max": self.max,
            "avg": self.avg,
            "last_value": self.last_value,
            "trend": self.trend,
            "timestamp": self.timestamp.isoformat()
        }


class SystemMetricsCollector:
    """Collects system-level metrics."""

    def __init__(self):
        self.last_cpu_check = time.time()
        self.cpu_history: list[float] = []
        self.max_history_size = 60  # Keep 60 data points

    async def collect_cpu_usage(self) -> float:
        """Collect CPU usage percentage."""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            self.cpu_history.append(cpu_percent)

            # Keep only recent history
            if len(self.cpu_history) > self.max_history_size:
                self.cpu_history = self.cpu_history[-self.max_history_size:]

            return cpu_percent
        except Exception as e:
            logger.error(f"Failed to collect CPU usage: {e}")
            return 0.0

    async def collect_memory_usage(self) -> dict[str, float]:
        """Collect memory usage metrics."""
        try:
            memory = psutil.virtual_memory()
            return {
                "total": memory.total,
                "available": memory.available,
                "used": memory.used,
                "free": memory.free,
                "percent": memory.percent
            }
        except Exception as e:
            logger.error(f"Failed to collect memory usage: {e}")
            return {"percent": 0.0}

    async def collect_disk_usage(self) -> dict[str, float]:
        """Collect disk usage metrics."""
        try:
            disk = psutil.disk_usage('/')
            return {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "percent": (disk.used / disk.total) * 100
            }
        except Exception as e:
            logger.error(f"Failed to collect disk usage: {e}")
            return {"percent": 0.0}

    async def collect_network_stats(self) -> dict[str, float]:
        """Collect network statistics."""
        try:
            net_io = psutil.net_io_counters()
            return {
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv
            }
        except Exception as e:
            logger.error(f"Failed to collect network stats: {e}")
            return {}

    async def collect_process_count(self) -> int:
        """Collect number of running processes."""
        try:
            return len(psutil.pids())
        except Exception as e:
            logger.error(f"Failed to collect process count: {e}")
            return 0


class AgentMetricsCollector:
    """Collects agent-specific metrics."""

    def __init__(self):
        self.agent_metrics: dict[str, dict[str, Any]] = {}
        self.agent_history: dict[str, list[dict[str, Any]]] = {}
        self.max_history_size = 100

    def update_agent_metrics(self, agent_name: str, metrics: dict[str, Any]) -> None:
        """Update metrics for an agent."""
        timestamp = datetime.now()

        # Store current metrics
        self.agent_metrics[agent_name] = {
            **metrics,
            "timestamp": timestamp.isoformat()
        }

        # Store in history
        if agent_name not in self.agent_history:
            self.agent_history[agent_name] = []

        self.agent_history[agent_name].append({
            **metrics,
            "timestamp": timestamp.isoformat()
        })

        # Keep only recent history
        if len(self.agent_history[agent_name]) > self.max_history_size:
            self.agent_history[agent_name] = self.agent_history[agent_name][-self.max_history_size:]

    def get_agent_metrics(self, agent_name: str) -> dict[str, Any] | None:
        """Get current metrics for an agent."""
        return self.agent_metrics.get(agent_name)

    def get_all_agent_metrics(self) -> dict[str, dict[str, Any]]:
        """Get metrics for all agents."""
        return self.agent_metrics.copy()

    def get_agent_history(self, agent_name: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get historical metrics for an agent."""
        history = self.agent_history.get(agent_name, [])
        return history[-limit:] if len(history) > limit else history


class ModelMetricsCollector:
    """Collects model-specific metrics."""

    def __init__(self):
        self.model_metrics: dict[str, dict[str, Any]] = {}
        self.model_history: dict[str, list[dict[str, Any]]] = {}
        self.max_history_size = 100

    def update_model_metrics(self, model_name: str, metrics: dict[str, Any]) -> None:
        """Update metrics for a model."""
        timestamp = datetime.now()

        # Store current metrics
        self.model_metrics[model_name] = {
            **metrics,
            "timestamp": timestamp.isoformat()
        }

        # Store in history
        if model_name not in self.model_history:
            self.model_history[model_name] = []

        self.model_history[model_name].append({
            **metrics,
            "timestamp": timestamp.isoformat()
        })

        # Keep only recent history
        if len(self.model_history[model_name]) > self.max_history_size:
            self.model_history[model_name] = self.model_history[model_name][-self.max_history_size:]

    def get_model_metrics(self, model_name: str) -> dict[str, Any] | None:
        """Get current metrics for a model."""
        return self.model_metrics.get(model_name)

    def get_all_model_metrics(self) -> dict[str, dict[str, Any]]:
        """Get metrics for all models."""
        return self.model_metrics.copy()


class TokenMetricsCollector:
    """Collects token-related metrics."""

    def __init__(self):
        self.token_stats: dict[str, Any] = {
            "total_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_requests": 0,
            "avg_tokens_per_request": 0.0,
            "tokens_per_second": 0.0,
            "cost_per_minute": 0.0,
            "last_request_time": None
        }
        self.request_history: list[dict[str, Any]] = []
        self.max_history_size = 1000
        self.cost_per_token = 0.0001  # $0.0001 per token

    def update_token_usage(self, input_tokens: int, output_tokens: int, model_name: str = "default") -> None:
        """Update token usage statistics."""
        total_tokens = input_tokens + output_tokens
        current_time = datetime.now()

        # Update stats
        self.token_stats["total_tokens"] += total_tokens
        self.token_stats["input_tokens"] += input_tokens
        self.token_stats["output_tokens"] += output_tokens
        self.token_stats["total_requests"] += 1
        self.token_stats["last_request_time"] = current_time.isoformat()

        # Calculate averages
        if self.token_stats["total_requests"] > 0:
            self.token_stats["avg_tokens_per_request"] = (
                self.token_stats["total_tokens"] / self.token_stats["total_requests"]
            )

        # Store in history
        self.request_history.append({
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "model_name": model_name,
            "timestamp": current_time.isoformat()
        })

        # Keep only recent history
        if len(self.request_history) > self.max_history_size:
            self.request_history = self.request_history[-self.max_history_size:]

        # Calculate tokens per second
        self._calculate_tokens_per_second()

        # Calculate cost per minute
        self._calculate_cost_per_minute()

    def _calculate_tokens_per_second(self) -> None:
        """Calculate tokens per second rate."""
        if len(self.request_history) < 2:
            return

        # Get last minute of requests
        one_minute_ago = datetime.now() - timedelta(minutes=1)
        recent_requests = [
            req for req in self.request_history
            if datetime.fromisoformat(req["timestamp"]) > one_minute_ago
        ]

        if recent_requests:
            total_tokens = sum(req["total_tokens"] for req in recent_requests)
            self.token_stats["tokens_per_second"] = total_tokens / 60.0

    def _calculate_cost_per_minute(self) -> None:
        """Calculate cost per minute."""
        if len(self.request_history) < 2:
            return

        # Get last minute of requests
        one_minute_ago = datetime.now() - timedelta(minutes=1)
        recent_requests = [
            req for req in self.request_history
            if datetime.fromisoformat(req["timestamp"]) > one_minute_ago
        ]

        if recent_requests:
            total_tokens = sum(req["total_tokens"] for req in recent_requests)
            self.token_stats["cost_per_minute"] = total_tokens * self.cost_per_token

    def get_token_stats(self) -> dict[str, Any]:
        """Get current token statistics."""
        return self.token_stats.copy()

    def get_token_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get token usage history."""
        return self.request_history[-limit:] if len(self.request_history) > limit else self.request_history


class RealtimeMetricsCollector:
    """Main metrics collector system."""

    def __init__(self, event_bus: EventBus | None = None):
        self.event_bus = event_bus
        self.system_collector = SystemMetricsCollector()
        self.agent_collector = AgentMetricsCollector()
        self.model_collector = ModelMetricsCollector()
        self.token_collector = TokenMetricsCollector()

        # Metric storage
        self.metrics: dict[str, list[MetricPoint]] = {}
        self.aggregations: dict[str, MetricAggregation] = {}

        # Collection state
        self._running = False
        self._collection_task: asyncio.Task | None = None
        self._collection_interval = 5.0  # seconds

        # Metrics configuration
        self.enabled_metrics = {
            "system": True,
            "agents": True,
            "models": True,
            "tokens": True,
            "performance": True
        }

        # Statistics
        self.stats = {
            "metrics_collected": 0,
            "collections_performed": 0,
            "last_collection": None,
            "errors": 0
        }

    async def start(self) -> None:
        """Start metrics collection."""
        if self._running:
            return

        self._running = True
        self._collection_task = asyncio.create_task(self._collection_loop())
        logger.info("RealtimeMetricsCollector started")

    async def stop(self) -> None:
        """Stop metrics collection."""
        self._running = False

        if self._collection_task:
            self._collection_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._collection_task
            self._collection_task = None

        logger.info("RealtimeMetricsCollector stopped")

    async def _collection_loop(self) -> None:
        """Main collection loop."""
        while self._running:
            try:
                await self._collect_all_metrics()
                await asyncio.sleep(self._collection_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in metrics collection: {e}")
                self.stats["errors"] += 1
                await asyncio.sleep(5)

    async def _collect_all_metrics(self) -> None:
        """Collect all enabled metrics."""
        collection_time = datetime.now()

        # System metrics
        if self.enabled_metrics["system"]:
            await self._collect_system_metrics()

        # Agent metrics (updated by agents)
        if self.enabled_metrics["agents"]:
            await self._process_agent_metrics()

        # Model metrics (updated by model system)
        if self.enabled_metrics["models"]:
            await self._process_model_metrics()

        # Token metrics (updated by chat system)
        if self.enabled_metrics["tokens"]:
            await self._process_token_metrics()

        # Update statistics
        self.stats["collections_performed"] += 1
        self.stats["last_collection"] = collection_time.isoformat()

        # Emit metrics update event
        if self.event_bus:
            await self.event_bus.publish(Event(
                event_type=EventType.METRIC_UPDATE,
                source="metrics_collector",
                payload={
                    "collection_time": collection_time.isoformat(),
                    "metrics_count": self.stats["metrics_collected"],
                    "collections_performed": self.stats["collections_performed"]
                }
            ))

    async def _collect_system_metrics(self) -> None:
        """Collect system-level metrics."""
        try:
            # CPU usage
            cpu_usage = await self.system_collector.collect_cpu_usage()
            await self._record_metric("system_cpu_usage", cpu_usage, MetricCategory.SYSTEM, MetricType.GAUGE, "%")

            # Memory usage
            memory_usage = await self.system_collector.collect_memory_usage()
            await self._record_metric("system_memory_usage", memory_usage["percent"], MetricCategory.SYSTEM, MetricType.GAUGE, "%")
            await self._record_metric("system_memory_used", memory_usage["used"], MetricCategory.SYSTEM, MetricType.GAUGE, "bytes")
            await self._record_metric("system_memory_available", memory_usage["available"], MetricCategory.SYSTEM, MetricType.GAUGE, "bytes")

            # Disk usage
            disk_usage = await self.system_collector.collect_disk_usage()
            await self._record_metric("system_disk_usage", disk_usage["percent"], MetricCategory.SYSTEM, MetricType.GAUGE, "%")
            await self._record_metric("system_disk_used", disk_usage["used"], MetricCategory.SYSTEM, MetricType.GAUGE, "bytes")

            # Process count
            process_count = await self.system_collector.collect_process_count()
            await self._record_metric("system_process_count", process_count, MetricCategory.SYSTEM, MetricType.GAUGE, "count")

            # Network stats
            network_stats = await self.system_collector.collect_network_stats()
            for key, value in network_stats.items():
                await self._record_metric(f"system_network_{key}", value, MetricCategory.NETWORK, MetricType.COUNTER, "bytes")

        except Exception as e:
            logger.error(f"Failed to collect system metrics: {e}")

    async def _process_agent_metrics(self) -> None:
        """Process agent metrics."""
        try:
            all_agent_metrics = self.agent_collector.get_all_agent_metrics()

            for agent_name, metrics in all_agent_metrics.items():
                # Agent state
                state = 1 if metrics.get("is_busy", False) else 0
                await self._record_metric(f"agent_{agent_name}_busy", state, MetricCategory.AGENT, MetricType.GAUGE, "boolean")

                # Task metrics
                await self._record_metric(f"agent_{agent_name}_tasks_completed", metrics.get("tasks_completed", 0), MetricCategory.AGENT, MetricType.COUNTER, "count")
                await self._record_metric(f"agent_{agent_name}_tasks_failed", metrics.get("tasks_failed", 0), MetricCategory.AGENT, MetricType.COUNTER, "count")

                # Performance metrics
                await self._record_metric(f"agent_{agent_name}_response_time", metrics.get("average_response_time", 0), MetricCategory.PERFORMANCE, MetricType.GAUGE, "seconds")
                await self._record_metric(f"agent_{agent_name}_error_rate", metrics.get("error_rate", 0), MetricCategory.PERFORMANCE, MetricType.GAUGE, "rate")

                # Resource metrics
                await self._record_metric(f"agent_{agent_name}_cpu_usage", metrics.get("cpu_usage", 0), MetricCategory.PERFORMANCE, MetricType.GAUGE, "percent")
                await self._record_metric(f"agent_{agent_name}_memory_usage", metrics.get("memory_usage", 0), MetricCategory.PERFORMANCE, MetricType.GAUGE, "percent")

        except Exception as e:
            logger.error(f"Failed to process agent metrics: {e}")

    async def _process_model_metrics(self) -> None:
        """Process model metrics."""
        try:
            all_model_metrics = self.model_collector.get_all_model_metrics()

            for model_name, metrics in all_model_metrics.items():
                # Model performance
                await self._record_metric(f"model_{model_name}_accuracy", metrics.get("accuracy", 0), MetricCategory.MODEL, MetricType.GAUGE, "percent")
                await self._record_metric(f"model_{model_name}_latency", metrics.get("latency", 0), MetricCategory.PERFORMANCE, MetricType.GAUGE, "seconds")
                await self._record_metric(f"model_{model_name}_throughput", metrics.get("throughput", 0), MetricCategory.PERFORMANCE, MetricType.GAUGE, "requests_per_second")

                # Model usage
                await self._record_metric(f"model_{model_name}_requests", metrics.get("requests", 0), MetricCategory.MODEL, MetricType.COUNTER, "count")
                await self._record_metric(f"model_{model_name}_tokens", metrics.get("tokens", 0), MetricCategory.MODEL, MetricType.COUNTER, "tokens")

        except Exception as e:
            logger.error(f"Failed to process model metrics: {e}")

    async def _process_token_metrics(self) -> None:
        """Process token metrics."""
        try:
            token_stats = self.token_collector.get_token_stats()

            await self._record_metric("tokens_total", token_stats["total_tokens"], MetricCategory.TOKEN, MetricType.COUNTER, "tokens")
            await self._record_metric("tokens_input", token_stats["input_tokens"], MetricCategory.TOKEN, MetricType.COUNTER, "tokens")
            await self._record_metric("tokens_output", token_stats["output_tokens"], MetricCategory.TOKEN, MetricType.COUNTER, "tokens")
            await self._record_metric("tokens_per_request", token_stats["avg_tokens_per_request"], MetricCategory.TOKEN, MetricType.GAUGE, "tokens")
            await self._record_metric("tokens_per_second", token_stats["tokens_per_second"], MetricCategory.TOKEN, MetricType.RATE, "tokens_per_second")
            await self._record_metric("cost_per_minute", token_stats["cost_per_minute"], MetricCategory.TOKEN, MetricType.GAUGE, "dollars")

        except Exception as e:
            logger.error(f"Failed to process token metrics: {e}")

    async def _record_metric(self, name: str, value: float, category: MetricCategory,
                           metric_type: MetricType, unit: str = "", labels: dict[str, str] | None = None) -> None:
        """Record a metric point."""
        metric = MetricPoint(
            name=name,
            category=category,
            metric_type=metric_type,
            value=value,
            unit=unit,
            labels=labels or {}
        )

        # Store metric
        if name not in self.metrics:
            self.metrics[name] = []

        self.metrics[name].append(metric)
        self.stats["metrics_collected"] += 1

        # Keep only recent metrics
        if len(self.metrics[name]) > 1000:
            self.metrics[name] = self.metrics[name][-1000:]

        # Update aggregation
        if name not in self.aggregations:
            self.aggregations[name] = MetricAggregation(
                name=name,
                category=category,
                metric_type=metric_type
            )

        self.aggregations[name].update(value)

    async def get_metrics(self, category: MetricCategory | None = None,
                          limit: int = 100) -> dict[str, list[dict[str, Any]]]:
        """Get metrics with optional filtering."""
        result = {}

        for name, metric_points in self.metrics.items():
            if category and metric_points[0].category != category:
                continue

            # Get recent metrics
            recent_points = metric_points[-limit:] if len(metric_points) > limit else metric_points
            result[name] = [point.to_dict() for point in recent_points]

        return result

    async def get_aggregations(self, category: MetricCategory | None = None) -> dict[str, dict[str, Any]]:
        """Get metric aggregations with optional filtering."""
        result = {}

        for name, aggregation in self.aggregations.items():
            if category and aggregation.category != category:
                continue

            result[name] = aggregation.to_dict()

        return result

    async def get_stats(self) -> dict[str, Any]:
        """Get collector statistics."""
        return {
            "running": self._running,
            "collection_interval": self._collection_interval,
            "enabled_metrics": self.enabled_metrics,
            "total_metrics": len(self.metrics),
            "total_aggregations": len(self.aggregations),
            **self.stats
        }


# Global metrics collector instance
_metrics_collector: RealtimeMetricsCollector | None = None


async def get_metrics_collector(event_bus: EventBus | None = None) -> RealtimeMetricsCollector:
    """Get the global metrics collector instance."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = RealtimeMetricsCollector(event_bus)
        await _metrics_collector.start()
    return _metrics_collector


async def shutdown_metrics_collector() -> None:
    """Shutdown the metrics collector."""
    global _metrics_collector
    if _metrics_collector:
        await _metrics_collector.stop()
        _metrics_collector = None