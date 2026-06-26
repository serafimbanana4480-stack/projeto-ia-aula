"""Metrics collector for Enhanced Agent Parliament.

Collects and aggregates metrics from all components for monitoring.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """Types of metrics."""
    COUNTER = "counter"  # Incrementing value
    GAUGE = "gauge"  # Current value
    HISTOGRAM = "histogram"  # Distribution of values


@dataclass
class Metric:
    """A single metric."""
    name: str
    value: float
    metric_type: MetricType
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metric to dictionary."""
        return {
            "name": self.name,
            "value": self.value,
            "type": self.metric_type.value,
            "labels": self.labels,
            "timestamp": self.timestamp,
        }


@dataclass
class ComponentMetrics:
    """Metrics for a specific component."""
    component_name: str
    metrics: List[Metric] = field(default_factory=list)
    
    def add_metric(
        self,
        name: str,
        value: float,
        metric_type: MetricType,
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """Add a metric to this component."""
        metric = Metric(
            name=name,
            value=value,
            metric_type=metric_type,
            labels=labels or {},
        )
        self.metrics.append(metric)
    
    def get_metric_value(self, name: str, labels: Optional[Dict[str, str]] = None) -> Optional[float]:
        """Get the latest value for a metric."""
        for metric in reversed(self.metrics):
            if metric.name == name:
                if labels is None or metric.labels == labels:
                    return metric.value
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert component metrics to dictionary."""
        return {
            "component_name": self.component_name,
            "metrics": [m.to_dict() for m in self.metrics],
        }


class MetricsCollector:
    """Collects metrics from all Enhanced Agent Parliament components.
    
    Aggregates metrics from:
    - Circuit Breaker
    - Cache
    - Voting System
    - Decision Evaluator
    - Learning Loop
    - Debate Transcriber
    """
    
    def __init__(self):
        """Initialize metrics collector."""
        self.components: Dict[str, ComponentMetrics] = {}
        self.start_time = time.time()
        
        logger.info("MetricsCollector initialized")
    
    def register_component(self, component_name: str) -> ComponentMetrics:
        """Register a component for metrics collection.
        
        Args:
            component_name: Name of the component
            
        Returns:
            ComponentMetrics instance for this component
        """
        if component_name not in self.components:
            self.components[component_name] = ComponentMetrics(
                component_name=component_name
            )
            logger.debug(f"Registered component for metrics: {component_name}")
        
        return self.components[component_name]
    
    def record_metric(
        self,
        component_name: str,
        metric_name: str,
        value: float,
        metric_type: MetricType,
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """Record a metric for a component.
        
        Args:
            component_name: Name of the component
            metric_name: Name of the metric
            value: Metric value
            metric_type: Type of metric
            labels: Optional labels for the metric
        """
        component = self.register_component(component_name)
        component.add_metric(metric_name, value, metric_type, labels)
    
    def increment_counter(
        self,
        component_name: str,
        metric_name: str,
        value: float = 1.0,
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """Increment a counter metric.
        
        Args:
            component_name: Name of the component
            metric_name: Name of the metric
            value: Value to increment by (default 1.0)
            labels: Optional labels for the metric
        """
        current = self.get_metric_value(component_name, metric_name, labels) or 0.0
        self.record_metric(
            component_name,
            metric_name,
            current + value,
            MetricType.COUNTER,
            labels,
        )
    
    def set_gauge(
        self,
        component_name: str,
        metric_name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """Set a gauge metric.
        
        Args:
            component_name: Name of the component
            metric_name: Name of the metric
            value: Value to set
            labels: Optional labels for the metric
        """
        self.record_metric(
            component_name,
            metric_name,
            value,
            MetricType.GAUGE,
            labels,
        )
    
    def get_metric_value(
        self,
        component_name: str,
        metric_name: str,
        labels: Optional[Dict[str, str]] = None
    ) -> Optional[float]:
        """Get the latest value for a metric.
        
        Args:
            component_name: Name of the component
            metric_name: Name of the metric
            labels: Optional labels for the metric
            
        Returns:
            Metric value or None if not found
        """
        component = self.components.get(component_name)
        if component:
            return component.get_metric_value(metric_name, labels)
        return None
    
    def get_component_metrics(self, component_name: str) -> Optional[ComponentMetrics]:
        """Get all metrics for a component.
        
        Args:
            component_name: Name of the component
            
        Returns:
            ComponentMetrics or None if not found
        """
        return self.components.get(component_name)
    
    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get all metrics from all components.
        
        Returns:
            Dictionary mapping component names to their metrics
        """
        return {
            name: component.to_dict()
            for name, component in self.components.items()
        }
    
    def collect_circuit_breaker_metrics(
        self,
        component_name: str,
        circuit_breaker: Any
    ) -> None:
        """Collect metrics from a circuit breaker.
        
        Args:
            component_name: Name of the component
            circuit_breaker: CircuitBreaker instance
        """
        stats = circuit_breaker.get_stats()
        
        # Record state
        state_value = 1.0 if stats.state.value == "closed" else 0.0
        self.set_gauge(component_name, "circuit_breaker_closed", state_value)
        
        # Record counts
        self.set_gauge(component_name, "circuit_breaker_failure_count", stats.failure_count)
        self.set_gauge(component_name, "circuit_breaker_success_count", stats.success_count)
        
        # Record totals
        self.set_gauge(component_name, "circuit_breaker_total_calls", stats.total_calls)
        self.set_gauge(component_name, "circuit_breaker_total_failures", stats.total_failures)
        self.set_gauge(component_name, "circuit_breaker_total_successes", stats.total_successes)
        
        # Calculate and record failure rate
        failure_rate = (
            stats.total_failures / stats.total_calls
            if stats.total_calls > 0
            else 0.0
        )
        self.set_gauge(component_name, "circuit_breaker_failure_rate", failure_rate)
    
    def collect_cache_metrics(
        self,
        component_name: str,
        cache: Any
    ) -> None:
        """Collect metrics from a cache.
        
        Args:
            component_name: Name of the component
            cache: Cache instance
        """
        stats = cache.get_stats()
        
        # Record size
        self.set_gauge(component_name, "cache_size", stats["size"])
        self.set_gauge(component_name, "cache_max_size", stats["max_size"])
        
        # Record counts
        self.set_gauge(component_name, "cache_hits", stats["hits"])
        self.set_gauge(component_name, "cache_misses", stats["misses"])
        self.set_gauge(component_name, "cache_evictions", stats["evictions"])
        
        # Record hit rate
        self.set_gauge(component_name, "cache_hit_rate", stats["hit_rate"])
    
    def collect_voting_system_metrics(
        self,
        component_name: str,
        voting_system: Any
    ) -> None:
        """Collect metrics from a voting system.
        
        Args:
            component_name: Name of the component
            voting_system: WeightedVotingSystem instance
        """
        # Record threshold
        self.set_gauge(
            component_name,
            "voting_consensus_threshold",
            voting_system.consensus_threshold,
        )
        
        self.set_gauge(
            component_name,
            "voting_std_dev_threshold",
            voting_system.consensus_std_dev_threshold,
        )
    
    def collect_learning_loop_metrics(
        self,
        component_name: str,
        learning_loop: Any
    ) -> None:
        """Collect metrics from a learning loop.
        
        Args:
            component_name: Name of the component
            learning_loop: LearningLoop instance
        """
        # Record pattern count
        pattern_count = len(learning_loop.decision_patterns)
        self.set_gauge(component_name, "learning_pattern_count", pattern_count)
        
        # Record specialization count
        specialization_count = len(learning_loop.agent_specializations)
        self.set_gauge(component_name, "learning_specialization_count", specialization_count)
        
        # Record parameters
        self.set_gauge(
            component_name,
            "learning_min_sample_size",
            learning_loop.min_sample_size,
        )
        self.set_gauge(
            component_name,
            "learning_confidence_threshold",
            learning_loop.confidence_threshold,
        )
    
    def collect_transcriber_metrics(
        self,
        component_name: str,
        transcriber: Any
    ) -> None:
        """Collect metrics from a debate transcriber.
        
        Args:
            component_name: Name of the component
            transcriber: DebateTranscriber instance
        """
        # Record transcript count
        transcript_count = len(transcriber._local_transcripts)
        self.set_gauge(component_name, "transcriber_transcript_count", transcript_count)
        
        # Record if KG is available
        kg_available = 1.0 if transcriber.kg else 0.0
        self.set_gauge(component_name, "transcriber_kg_available", kg_available)
        
        # Record if SQLite is available
        sqlite_available = 1.0 if transcriber._conn else 0.0
        self.set_gauge(component_name, "transcriber_sqlite_available", sqlite_available)
    
    def collect_evaluator_metrics(
        self,
        component_name: str,
        evaluator: Any
    ) -> None:
        """Collect metrics from a decision evaluator.
        
        Args:
            component_name: Name of the component
            evaluator: DecisionEvaluator instance
        """
        # Record threshold
        self.set_gauge(
            component_name,
            "evaluator_resource_efficiency_threshold",
            evaluator.resource_efficiency_threshold,
        )
        
        # Record metric weights
        for metric_name, weight in evaluator.metric_weights.items():
            self.set_gauge(
                component_name,
                f"evaluator_weight_{metric_name}",
                weight,
                labels={"metric": metric_name},
            )
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all metrics.
        
        Returns:
            Dictionary with summary metrics
        """
        total_metrics = sum(len(c.metrics) for c in self.components.values())
        uptime = time.time() - self.start_time
        
        return {
            "uptime_seconds": uptime,
            "total_components": len(self.components),
            "total_metrics": total_metrics,
            "components": list(self.components.keys()),
        }


# Global metrics collector instance
_global_metrics_collector: Optional[MetricsCollector] = None


def get_global_metrics_collector() -> MetricsCollector:
    """Get or create global metrics collector instance.
    
    Returns:
        Global metrics collector instance
    """
    global _global_metrics_collector
    if _global_metrics_collector is None:
        _global_metrics_collector = MetricsCollector()
    return _global_metrics_collector
