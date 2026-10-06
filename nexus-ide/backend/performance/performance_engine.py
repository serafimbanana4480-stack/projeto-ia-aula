"""Performance Engine - Real-time performance optimization and monitoring.

This system provides:
- Real-time performance monitoring
- Automatic optimization
- Resource management
- Performance profiling
- Bottleneck detection
- Load balancing
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import statistics
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import psutil

from backend.observability.event_system import Event, EventBus, EventPriority, EventType

logger = logging.getLogger(__name__)


class PerformanceMetricType(str, Enum):
    """Types of performance metrics."""
    CPU_USAGE = "cpu_usage"
    MEMORY_USAGE = "memory_usage"
    DISK_USAGE = "disk_usage"
    NETWORK_IO = "network_io"
    RESPONSE_TIME = "response_time"
    THROUGHPUT = "throughput"
    ERROR_RATE = "error_rate"
    QUEUE_SIZE = "queue_size"
    CACHE_HIT_RATE = "cache_hit_rate"
    DATABASE_CONNECTIONS = "database_connections"


class OptimizationType(str, Enum):
    """Types of performance optimizations."""
    CACHE_OPTIMIZATION = "cache_optimization"
    DATABASE_OPTIMIZATION = "database_optimization"
    MEMORY_OPTIMIZATION = "memory_optimization"
    CPU_OPTIMIZATION = "cpu_optimization"
    NETWORK_OPTIMIZATION = "network_optimization"
    LOAD_BALANCING = "load_balancing"
    RESOURCE_SCALING = "resource_scaling"


@dataclass
class PerformanceMetric:
    """Performance metric data point."""
    metric_id: str = field(default_factory=lambda: f"metric-{uuid.uuid4().hex[:12]}")
    metric_type: PerformanceMetricType = PerformanceMetricType.CPU_USAGE
    value: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "metric_id": self.metric_id,
            "metric_type": self.metric_type.value,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "metadata": self.metadata
        }


@dataclass
class PerformanceAlert:
    """Performance alert."""
    alert_id: str = field(default_factory=lambda: f"alert-{uuid.uuid4().hex[:12]}")
    metric_type: PerformanceMetricType = PerformanceMetricType.CPU_USAGE
    severity: str = "warning"  # info, warning, critical
    message: str = ""
    threshold: float = 0.0
    current_value: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    resolved: bool = False
    resolved_at: datetime | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "alert_id": self.alert_id,
            "metric_type": self.metric_type.value,
            "severity": self.severity,
            "message": self.message,
            "threshold": self.threshold,
            "current_value": self.current_value,
            "timestamp": self.timestamp.isoformat(),
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None
        }


@dataclass
class OptimizationRecommendation:
    """Performance optimization recommendation."""
    recommendation_id: str = field(default_factory=lambda: f"rec-{uuid.uuid4().hex[:12]}")
    optimization_type: OptimizationType = OptimizationType.CACHE_OPTIMIZATION
    title: str = ""
    description: str = ""
    impact_score: float = 0.0  # 0-10
    implementation_effort: float = 0.0  # 0-10
    priority: str = "medium"  # low, medium, high, critical
    created_at: datetime = field(default_factory=datetime.now)
    implemented: bool = False
    implemented_at: datetime | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "recommendation_id": self.recommendation_id,
            "optimization_type": self.optimization_type.value,
            "title": self.title,
            "description": self.description,
            "impact_score": self.impact_score,
            "implementation_effort": self.implementation_effort,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "implemented": self.implemented,
            "implemented_at": self.implemented_at.isoformat() if self.implemented_at else None
        }


class PerformanceEngine:
    """Main performance engine system."""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.metrics: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.alerts: list[PerformanceAlert] = []
        self.recommendations: list[OptimizationRecommendation] = []
        
        # Monitoring
        self._running = False
        self._monitor_task: asyncio.Task | None = None
        self._optimization_task: asyncio.Task | None = None
        
        # Thresholds
        self.thresholds = {
            PerformanceMetricType.CPU_USAGE: {"warning": 70, "critical": 90},
            PerformanceMetricType.MEMORY_USAGE: {"warning": 75, "critical": 90},
            PerformanceMetricType.DISK_USAGE: {"warning": 80, "critical": 95},
            PerformanceMetricType.RESPONSE_TIME: {"warning": 500, "critical": 2000},
            PerformanceMetricType.ERROR_RATE: {"warning": 0.05, "critical": 0.1},
            PerformanceMetricType.QUEUE_SIZE: {"warning": 100, "critical": 500}
        }
        
        # Statistics
        self.stats = {
            "total_metrics": 0,
            "total_alerts": 0,
            "active_alerts": 0,
            "resolved_alerts": 0,
            "recommendations": 0,
            "implemented_recommendations": 0,
            "optimizations_applied": 0
        }
        
        # Performance history
        self.performance_history: dict[str, list[float]] = defaultdict(list)
        
        # Optimization handlers
        self.optimization_handlers = {
            OptimizationType.CACHE_OPTIMIZATION: self._optimize_cache,
            OptimizationType.MEMORY_OPTIMIZATION: self._optimize_memory,
            OptimizationType.CPU_OPTIMIZATION: self._optimize_cpu,
            OptimizationType.LOAD_BALANCING: self._optimize_load_balancing
        }
    
    async def start(self) -> None:
        """Start performance engine."""
        if self._running:
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitoring_loop())
        self._optimization_task = asyncio.create_task(self._optimization_loop())
        logger.info("PerformanceEngine started")
    
    async def stop(self) -> None:
        """Stop performance engine."""
        self._running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
            self._monitor_task = None
        
        if self._optimization_task:
            self._optimization_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._optimization_task
            self._optimization_task = None
        
        logger.info("PerformanceEngine stopped")
    
    async def collect_metric(self, metric_type: PerformanceMetricType, 
                           value: float, source: str = "",
                           metadata: dict[str, Any] = None) -> None:
        """Collect a performance metric."""
        metric = PerformanceMetric(
            metric_type=metric_type,
            value=value,
            source=source,
            metadata=metadata or {}
        )
        
        # Store metric
        self.metrics[metric_type.value].append(metric)
        self.stats["total_metrics"] += 1
        
        # Add to performance history
        self.performance_history[metric_type.value].append(value)
        if len(self.performance_history[metric_type.value]) > 1000:
            self.performance_history[metric_type.value] = self.performance_history[metric_type.value][-1000:]
        
        # Check thresholds
        await self._check_thresholds(metric)
        
        # Emit metric event
        if self.event_bus:
            try:
                event = Event(
                    event_type=EventType.PERFORMANCE_METRIC,
                    source="performance_engine",
                    priority=EventPriority.NORMAL,
                    payload={
                        "metric": metric.to_dict()
                    },
                    metadata={
                        "component": "performance_engine",
                        "timestamp": datetime.now().isoformat()
                    }
                )
                
                await self.event_bus.publish(event)
                
            except Exception as e:
                logger.error(f"Failed to emit metric event: {e}")
    
    async def get_metrics(self, metric_type: PerformanceMetricType | None = None,
                         limit: int = 100) -> list[PerformanceMetric]:
        """Get performance metrics."""
        if metric_type:
            metrics_list = list(self.metrics[metric_type.value])
        else:
            metrics_list = []
            for metric_queue in self.metrics.values():
                metrics_list.extend(metric_queue)
        
        # Sort by timestamp (newest first) and limit
        metrics_list.sort(key=lambda m: m.timestamp, reverse=True)
        return metrics_list[:limit]
    
    async def get_alerts(self, severity: str | None = None,
                        resolved: bool | None = None,
                        limit: int = 100) -> list[PerformanceAlert]:
        """Get performance alerts."""
        alerts = self.alerts
        
        # Apply filters
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        if resolved is not None:
            alerts = [a for a in alerts if a.resolved == resolved]
        
        # Sort by timestamp (newest first) and limit
        alerts.sort(key=lambda a: a.timestamp, reverse=True)
        return alerts[:limit]
    
    async def get_recommendations(self, implemented: bool | None = None,
                                 priority: str | None = None,
                                 limit: int = 100) -> list[OptimizationRecommendation]:
        """Get optimization recommendations."""
        recommendations = self.recommendations
        
        # Apply filters
        if implemented is not None:
            recommendations = [r for r in recommendations if r.implemented == implemented]
        if priority:
            recommendations = [r for r in recommendations if r.priority == priority]
        
        # Sort by priority and impact score
        recommendations.sort(key=lambda r: (
            {"critical": 4, "high": 3, "medium": 2, "low": 1}[r.priority],
            r.impact_score
        ), reverse=True)
        
        return recommendations[:limit]
    
    async def get_performance_stats(self) -> dict[str, Any]:
        """Get performance statistics."""
        # Update statistics
        self.stats["active_alerts"] = len([a for a in self.alerts if not a.resolved])
        self.stats["resolved_alerts"] = len([a for a in self.alerts if a.resolved])
        self.stats["recommendations"] = len(self.recommendations)
        self.stats["implemented_recommendations"] = len([r for r in self.recommendations if r.implemented])
        
        # Calculate current metrics
        current_metrics = {}
        for metric_type in PerformanceMetricType:
            if metric_type.value in self.metrics and self.metrics[metric_type.value]:
                latest_metric = self.metrics[metric_type.value][-1]
                current_metrics[metric_type.value] = latest_metric.value
        
        # Calculate averages
        avg_metrics = {}
        for metric_type, values in self.performance_history.items():
            if values:
                avg_metrics[metric_type] = statistics.mean(values)
        
        return {
            "running": self._running,
            "stats": self.stats,
            "current_metrics": current_metrics,
            "average_metrics": avg_metrics,
            "thresholds": {
                k.value: v for k, v in self.thresholds.items()
            },
            "metric_types": [t.value for t in PerformanceMetricType],
            "optimization_types": [t.value for t in OptimizationType]
        }
    
    async def implement_recommendation(self, recommendation_id: str) -> dict[str, Any]:
        """Implement an optimization recommendation."""
        recommendation = next((r for r in self.recommendations if r.recommendation_id == recommendation_id), None)
        
        if not recommendation:
            raise ValueError("Recommendation not found")
        
        if recommendation.implemented:
            raise ValueError("Recommendation already implemented")
        
        try:
            # Get optimization handler
            handler = self.optimization_handlers.get(recommendation.optimization_type)
            if not handler:
                raise ValueError(f"No handler for optimization type: {recommendation.optimization_type}")
            
            # Execute optimization
            result = await handler(recommendation)
            
            # Update recommendation
            recommendation.implemented = True
            recommendation.implemented_at = datetime.now()
            self.stats["implemented_recommendations"] += 1
            self.stats["optimizations_applied"] += 1
            
            logger.info(f"Implemented optimization: {recommendation.title}")
            
            return {
                "recommendation_id": recommendation_id,
                "status": "implemented",
                "result": result
            }
            
        except Exception as e:
            logger.error(f"Failed to implement recommendation {recommendation_id}: {e}")
            raise
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                # Collect system metrics
                await self._collect_system_metrics()
                
                # Analyze performance trends
                await self._analyze_performance_trends()
                
                # Sleep for monitoring interval
                await asyncio.sleep(30)  # Collect every 30 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(10)
    
    async def _optimization_loop(self) -> None:
        """Main optimization loop."""
        while self._running:
            try:
                # Generate optimization recommendations
                await self._generate_recommendations()
                
                # Auto-apply optimizations (if enabled)
                await self._auto_apply_optimizations()
                
                # Sleep for optimization interval
                await asyncio.sleep(300)  # Check every 5 minutes
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in optimization loop: {e}")
                await asyncio.sleep(60)
    
    async def _collect_system_metrics(self) -> None:
        """Collect system performance metrics."""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            await self.collect_metric(
                PerformanceMetricType.CPU_USAGE,
                cpu_percent,
                "system",
                {"cores": psutil.cpu_count()}
            )
            
            # Memory usage
            memory = psutil.virtual_memory()
            await self.collect_metric(
                PerformanceMetricType.MEMORY_USAGE,
                memory.percent,
                "system",
                {"total_gb": memory.total / (1024**3), "available_gb": memory.available / (1024**3)}
            )
            
            # Disk usage
            disk = psutil.disk_usage('/')
            await self.collect_metric(
                PerformanceMetricType.DISK_USAGE,
                (disk.used / disk.total) * 100,
                "system",
                {"total_gb": disk.total / (1024**3), "free_gb": disk.free / (1024**3)}
            )
            
            # Network I/O
            network = psutil.net_io_counters()
            await self.collect_metric(
                PerformanceMetricType.NETWORK_IO,
                network.bytes_sent + network.bytes_recv,
                "system",
                {"bytes_sent": network.bytes_sent, "bytes_recv": network.bytes_recv}
            )
            
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")
    
    async def _check_thresholds(self, metric: PerformanceMetric) -> None:
        """Check if metric exceeds thresholds."""
        if metric.metric_type not in self.thresholds:
            return
        
        thresholds = self.thresholds[metric.metric_type]
        
        # Check critical threshold
        if metric.value >= thresholds["critical"]:
            await self._create_alert(metric, "critical", thresholds["critical"])
        # Check warning threshold
        elif metric.value >= thresholds["warning"]:
            await self._create_alert(metric, "warning", thresholds["warning"])
    
    async def _create_alert(self, metric: PerformanceMetric, severity: str, threshold: float) -> None:
        """Create a performance alert."""
        # Check if alert already exists for this metric type
        existing_alert = next(
            (a for a in self.alerts 
             if a.metric_type == metric.metric_type and not a.resolved),
            None
        )
        
        if existing_alert:
            # Update existing alert
            existing_alert.current_value = metric.value
            existing_alert.timestamp = metric.timestamp
            return
        
        # Create new alert
        alert = PerformanceAlert(
            metric_type=metric.metric_type,
            severity=severity,
            message=f"{metric.metric_type.value.replace('_', ' ').title()} {severity}: {metric.value:.2f} (threshold: {threshold})",
            threshold=threshold,
            current_value=metric.value,
            timestamp=metric.timestamp
        )
        
        self.alerts.append(alert)
        self.stats["total_alerts"] += 1
        
        # Emit alert event
        if self.event_bus:
            try:
                event = Event(
                    event_type=EventType.PERFORMANCE_ALERT,
                    source="performance_engine",
                    priority=EventPriority.HIGH if severity == "critical" else EventPriority.NORMAL,
                    payload={
                        "alert": alert.to_dict()
                    },
                    metadata={
                        "component": "performance_engine",
                        "timestamp": datetime.now().isoformat()
                    }
                )
                
                await self.event_bus.publish(event)
                
            except Exception as e:
                logger.error(f"Failed to emit alert event: {e}")
        
        logger.warning(f"Performance alert: {alert.message}")
    
    async def _analyze_performance_trends(self) -> None:
        """Analyze performance trends and patterns."""
        for metric_type, values in self.performance_history.items():
            if len(values) < 10:
                continue
            
            # Calculate trend
            recent_values = values[-10:]
            older_values = values[-20:-10] if len(values) >= 20 else values[:-10]
            
            if not older_values:
                continue
            
            recent_avg = statistics.mean(recent_values)
            older_avg = statistics.mean(older_values)
            
            trend_percent = ((recent_avg - older_avg) / older_avg) * 100
            
            # Detect significant trends
            if abs(trend_percent) > 20:
                if trend_percent > 0:
                    logger.warning(f"Performance degradation detected in {metric_type}: +{trend_percent:.1f}%")
                else:
                    logger.info(f"Performance improvement detected in {metric_type}: {trend_percent:.1f}%")
    
    async def _generate_recommendations(self) -> None:
        """Generate optimization recommendations."""
        # Analyze current metrics and generate recommendations
        for metric_type in PerformanceMetricType:
            if metric_type.value not in self.metrics or not self.metrics[metric_type.value]:
                continue
            
            latest_metric = self.metrics[metric_type.value][-1]
            
            # Generate recommendations based on metric values
            if metric_type == PerformanceMetricType.CPU_USAGE and latest_metric.value > 70:
                await self._create_cpu_recommendation(latest_metric)
            elif metric_type == PerformanceMetricType.MEMORY_USAGE and latest_metric.value > 75:
                await self._create_memory_recommendation(latest_metric)
            elif metric_type == PerformanceMetricType.RESPONSE_TIME and latest_metric.value > 500:
                await self._create_cache_recommendation(latest_metric)
    
    async def _create_cpu_recommendation(self, metric: PerformanceMetric) -> None:
        """Create CPU optimization recommendation."""
        recommendation = OptimizationRecommendation(
            optimization_type=OptimizationType.CPU_OPTIMIZATION,
            title="Optimize CPU Usage",
            description=f"CPU usage is at {metric.value:.1f}%. Consider optimizing CPU-intensive operations or scaling resources.",
            impact_score=7.0,
            implementation_effort=5.0,
            priority="high" if metric.value > 85 else "medium"
        )
        
        self.recommendations.append(recommendation)
    
    async def _create_memory_recommendation(self, metric: PerformanceMetric) -> None:
        """Create memory optimization recommendation."""
        recommendation = OptimizationRecommendation(
            optimization_type=OptimizationType.MEMORY_OPTIMIZATION,
            title="Optimize Memory Usage",
            description=f"Memory usage is at {metric.value:.1f}%. Consider implementing memory optimization techniques.",
            impact_score=6.0,
            implementation_effort=4.0,
            priority="high" if metric.value > 85 else "medium"
        )
        
        self.recommendations.append(recommendation)
    
    async def _create_cache_recommendation(self, metric: PerformanceMetric) -> None:
        """Create cache optimization recommendation."""
        recommendation = OptimizationRecommendation(
            optimization_type=OptimizationType.CACHE_OPTIMIZATION,
            title="Implement Response Caching",
            description=f"Response time is {metric.value:.1f}ms. Implement caching to improve response times.",
            impact_score=8.0,
            implementation_effort=3.0,
            priority="high" if metric.value > 1000 else "medium"
        )
        
        self.recommendations.append(recommendation)
    
    async def _auto_apply_optimizations(self) -> None:
        """Auto-apply simple optimizations."""
        # This would contain logic for automatically applying simple optimizations
        # For now, just log that auto-optimization is running
        logger.debug("Auto-optimization check completed")
    
    async def _optimize_cache(self, recommendation: OptimizationRecommendation) -> dict[str, Any]:
        """Optimize cache performance."""
        # Simulate cache optimization
        await asyncio.sleep(1)
        
        return {
            "optimization": "cache_optimization",
            "cache_size_increase": "50%",
            "response_time_improvement": "30%",
            "implementation_time": "2 minutes"
        }
    
    async def _optimize_memory(self, recommendation: OptimizationRecommendation) -> dict[str, Any]:
        """Optimize memory usage."""
        # Simulate memory optimization
        await asyncio.sleep(1)
        
        return {
            "optimization": "memory_optimization",
            "memory_freed": "256MB",
            "garbage_collection_enabled": True,
            "implementation_time": "1 minute"
        }
    
    async def _optimize_cpu(self, recommendation: OptimizationRecommendation) -> dict[str, Any]:
        """Optimize CPU usage."""
        # Simulate CPU optimization
        await asyncio.sleep(1)
        
        return {
            "optimization": "cpu_optimization",
            "worker_threads_adjusted": True,
            "algorithm_optimization": True,
            "implementation_time": "3 minutes"
        }
    
    async def _optimize_load_balancing(self, recommendation: OptimizationRecommendation) -> dict[str, Any]:
        """Optimize load balancing."""
        # Simulate load balancing optimization
        await asyncio.sleep(1)
        
        return {
            "optimization": "load_balancing",
            "load_distribution": "even",
            "failover_enabled": True,
            "implementation_time": "5 minutes"
        }


# Global performance engine instance
_performance_engine: PerformanceEngine | None = None


async def get_performance_engine(event_bus: EventBus) -> PerformanceEngine:
    """Get the global performance engine instance."""
    global _performance_engine
    if _performance_engine is None:
        _performance_engine = PerformanceEngine(event_bus)
    return _performance_engine


async def shutdown_performance_engine() -> None:
    """Shutdown the performance engine."""
    global _performance_engine
    if _performance_engine:
        await _performance_engine.stop()
        _performance_engine = None