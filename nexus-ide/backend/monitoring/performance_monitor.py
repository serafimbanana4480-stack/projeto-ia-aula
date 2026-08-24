"""Advanced Performance Monitoring System.

Implements performance profiling, bottleneck detection, resource monitoring,
latency tracking, and optimization recommendations.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
import psutil
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union, Callable
from datetime import datetime, timedelta
from collections import defaultdict, deque

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class PerformanceMetricType(str, Enum):
    """Types of performance metrics."""
    LATENCY = "latency"
    THROUGHPUT = "throughput"
    ERROR_RATE = "error_rate"
    CPU_USAGE = "cpu_usage"
    MEMORY_USAGE = "memory_usage"
    DISK_IO = "disk_io"
    NETWORK_IO = "network_io"
    QUEUE_DEPTH = "queue_depth"
    RESPONSE_TIME = "response_time"
    CONCURRENCY = "concurrency"


class SeverityLevel(str, Enum):
    """Severity levels for performance issues."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OptimizationType(str, Enum):
    """Types of optimization recommendations."""
    CODE = "code"
    CONFIGURATION = "configuration"
    ARCHITECTURE = "architecture"
    RESOURCE = "resource"
    ALGORITHM = "algorithm"


@dataclass
class PerformanceMetric:
    """Individual performance metric."""
    metric_id: str = field(default_factory=lambda: f"metric-{uuid.uuid4().hex[:12]}")
    metric_type: PerformanceMetricType = PerformanceMetricType.LATENCY
    component: str = ""
    value: float = 0.0
    unit: str = ""
    
    # Context
    labels: Dict[str, str] = field(default_factory=dict)
    tags: Set[str] = field(default_factory=set)
    
    # Timestamps
    timestamp: float = field(default_factory=time.time)
    
    # Quality indicators
    quality_score: float = 0.0  # 0.0-1.0
    confidence: float = 0.0  # 0.0-1.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "metric_type": self.metric_type.value,
            "component": self.component,
            "value": self.value,
            "unit": self.unit,
            "labels": self.labels,
            "tags": list(self.tags),
            "timestamp": self.timestamp,
            "quality_score": self.quality_score,
            "confidence": self.confidence,
        }


@dataclass
class PerformanceProfile:
    """Performance profile for a component or operation."""
    profile_id: str = field(default_factory=lambda: f"profile-{uuid.uuid4().hex[:12]}")
    component: str = ""
    operation: str = ""
    
    # Timing data
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration: Optional[float] = None
    
    # Resource usage
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    disk_io_read: int = 0
    disk_io_write: int = 0
    network_io_sent: int = 0
    network_io_recv: int = 0
    
    # Performance metrics
    metrics: List[PerformanceMetric] = field(default_factory=list)
    
    # Context
    context: Dict[str, Any] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    # Quality assessment
    performance_score: float = 0.0  # 0.0-1.0
    efficiency_score: float = 0.0  # 0.0-1.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "component": self.component,
            "operation": self.operation,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "cpu_usage": self.cpu_usage,
            "memory_usage": self.memory_usage,
            "disk_io_read": self.disk_io_read,
            "disk_io_write": self.disk_io_write,
            "network_io_sent": self.network_io_sent,
            "network_io_recv": self.network_io_recv,
            "metrics": [m.to_dict() for m in self.metrics],
            "context": self.context,
            "parameters": self.parameters,
            "performance_score": self.performance_score,
            "efficiency_score": self.efficiency_score,
        }


@dataclass
class PerformanceIssue:
    """Performance issue detection."""
    issue_id: str = field(default_factory=lambda: f"issue-{uuid.uuid4().hex[:12]}")
    title: str = ""
    description: str = ""
    
    # Issue classification
    severity: SeverityLevel = SeverityLevel.MEDIUM
    category: str = ""
    component: str = ""
    
    # Detection data
    detected_at: float = field(default_factory=time.time)
    metrics: List[PerformanceMetric] = field(default_factory=list)
    
    # Impact assessment
    impact_score: float = 0.0  # 0.0-1.0
    affected_components: List[str] = field(default_factory=list)
    
    # Status
    status: str = "open"  # open, investigating, resolved
    resolved_at: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity.value,
            "category": self.category,
            "component": self.component,
            "detected_at": self.detected_at,
            "metrics": [m.to_dict() for m in self.metrics],
            "impact_score": self.impact_score,
            "affected_components": self.affected_components,
            "status": self.status,
            "resolved_at": self.resolved_at,
        }


@dataclass
class OptimizationRecommendation:
    """Performance optimization recommendation."""
    recommendation_id: str = field(default_factory=lambda: f"rec-{uuid.uuid4().hex[:12]}")
    title: str = ""
    description: str = ""
    
    # Recommendation classification
    optimization_type: OptimizationType = OptimizationType.CODE
    priority: str = "medium"  # low, medium, high, critical
    component: str = ""
    
    # Expected impact
    expected_improvement: float = 0.0  # 0.0-1.0
    implementation_effort: str = "medium"  # low, medium, high
    risk_level: str = "low"  # low, medium, high
    
    # Implementation details
    steps: List[str] = field(default_factory=list)
    code_examples: List[str] = field(default_factory=list)
    configuration_changes: Dict[str, Any] = field(default_factory=dict)
    
    # Context
    related_issues: List[str] = field(default_factory=list)
    supporting_metrics: List[PerformanceMetric] = field(default_factory=list)
    
    # Status
    status: str = "pending"  # pending, implemented, verified
    created_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "title": self.title,
            "description": self.description,
            "optimization_type": self.optimization_type.value,
            "priority": self.priority,
            "component": self.component,
            "expected_improvement": self.expected_improvement,
            "implementation_effort": self.implementation_effort,
            "risk_level": self.risk_level,
            "steps": self.steps,
            "code_examples": self.code_examples,
            "configuration_changes": self.configuration_changes,
            "related_issues": self.related_issues,
            "supporting_metrics": [m.to_dict() for m in self.supporting_metrics],
            "status": self.status,
            "created_at": self.created_at,
        }


class PerformanceProfiler:
    """Performance profiling and measurement."""
    
    def __init__(self, component_name: str):
        self.component_name = component_name
        self.active_profiles: Dict[str, PerformanceProfile] = {}
        self.profile_history: List[PerformanceProfile] = []
        
    def start_profile(
        self,
        operation: str,
        context: Optional[Dict[str, Any]] = None,
        parameters: Optional[Dict[str, Any]] = None
    ) -> str:
        """Start a new performance profile."""
        profile = PerformanceProfile(
            component=self.component_name,
            operation=operation,
            context=context or {},
            parameters=parameters or {},
        )
        
        # Get baseline resource usage
        profile.cpu_usage = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        profile.memory_usage = memory.percent
        
        # Get baseline I/O
        disk_io = psutil.disk_io_counters()
        if disk_io:
            profile.disk_io_read = disk_io.read_bytes
            profile.disk_io_write = disk_io.write_bytes
            
        network_io = psutil.net_io_counters()
        if network_io:
            profile.network_io_sent = network_io.bytes_sent
            profile.network_io_recv = network_io.bytes_recv
            
        self.active_profiles[profile.profile_id] = profile
        
        return profile.profile_id
        
    def end_profile(self, profile_id: str) -> Optional[PerformanceProfile]:
        """End a performance profile and calculate metrics."""
        if profile_id not in self.active_profiles:
            return None
            
        profile = self.active_profiles[profile_id]
        profile.end_time = time.time()
        profile.duration = profile.end_time - profile.start_time
        
        # Calculate resource usage delta
        profile.cpu_usage = psutil.cpu_percent() - profile.cpu_usage
        memory = psutil.virtual_memory()
        profile.memory_usage = memory.percent - profile.memory_usage
        
        # Calculate I/O delta
        disk_io = psutil.disk_io_counters()
        if disk_io:
            profile.disk_io_read = disk_io.read_bytes - profile.disk_io_read
            profile.disk_io_write = disk_io.write_bytes - profile.disk_io_write
            
        network_io = psutil.net_io_counters()
        if network_io:
            profile.network_io_sent = network_io.bytes_sent - profile.network_io_sent
            profile.network_io_recv = network_io.bytes_recv - profile.network_io_recv
            
        # Add basic metrics
        profile.metrics.append(PerformanceMetric(
            metric_type=PerformanceMetricType.RESPONSE_TIME,
            component=self.component_name,
            value=profile.duration,
            unit="seconds",
            labels={"operation": profile.operation}
        ))
        
        profile.metrics.append(PerformanceMetric(
            metric_type=PerformanceMetricType.CPU_USAGE,
            component=self.component_name,
            value=profile.cpu_usage,
            unit="percent",
            labels={"operation": profile.operation}
        ))
        
        profile.metrics.append(PerformanceMetric(
            metric_type=PerformanceMetricType.MEMORY_USAGE,
            component=self.component_name,
            value=profile.memory_usage,
            unit="percent",
            labels={"operation": profile.operation}
        ))
        
        # Calculate scores
        profile.performance_score = self._calculate_performance_score(profile)
        profile.efficiency_score = self._calculate_efficiency_score(profile)
        
        # Move to history
        self.profile_history.append(profile)
        del self.active_profiles[profile_id]
        
        # Keep only last 1000 profiles
        if len(self.profile_history) > 1000:
            self.profile_history = self.profile_history[-1000:]
            
        return profile
        
    def _calculate_performance_score(self, profile: PerformanceProfile) -> float:
        """Calculate performance score."""
        if not profile.duration:
            return 0.0
            
        score = 1.0
        
        # Duration penalty (longer is worse)
        if profile.duration > 1.0:
            score -= min(0.5, (profile.duration - 1.0) / 10.0)
        elif profile.duration > 5.0:
            score -= 0.5
            
        # Resource usage penalty
        if profile.cpu_usage > 80:
            score -= 0.2
        if profile.memory_usage > 80:
            score -= 0.2
            
        return max(0.0, score)
        
    def _calculate_efficiency_score(self, profile: PerformanceProfile) -> float:
        """Calculate efficiency score."""
        if not profile.duration:
            return 0.0
            
        # Efficiency = work done / resources used
        work_factor = 1.0  # Could be based on actual work metrics
        
        resource_factor = 1.0
        if profile.cpu_usage > 0:
            resource_factor *= (100 - profile.cpu_usage) / 100
        if profile.memory_usage > 0:
            resource_factor *= (100 - profile.memory_usage) / 100
            
        return work_factor * resource_factor
        
    def get_profile_statistics(self, operation: Optional[str] = None) -> Dict[str, Any]:
        """Get profile statistics."""
        profiles = self.profile_history
        
        if operation:
            profiles = [p for p in profiles if p.operation == operation]
            
        if not profiles:
            return {}
            
        durations = [p.duration for p in profiles if p.duration]
        performance_scores = [p.performance_score for p in profiles]
        efficiency_scores = [p.efficiency_score for p in profiles]
        
        return {
            "total_profiles": len(profiles),
            "avg_duration": sum(durations) / len(durations) if durations else 0.0,
            "min_duration": min(durations) if durations else 0.0,
            "max_duration": max(durations) if durations else 0.0,
            "avg_performance_score": sum(performance_scores) / len(performance_scores) if performance_scores else 0.0,
            "avg_efficiency_score": sum(efficiency_scores) / len(efficiency_scores) if efficiency_scores else 0.0,
        }


class PerformanceMonitor:
    """Advanced performance monitoring system."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        
        # Profilers
        self.profilers: Dict[str, PerformanceProfiler] = {}
        
        # Metrics storage
        self.metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.metric_aggregates: Dict[str, Dict[str, float]] = {}
        
        # Issues and recommendations
        self.issues: List[PerformanceIssue] = []
        self.recommendations: List[OptimizationRecommendation] = []
        
        # Monitoring configuration
        self.monitoring_rules: List[Dict[str, Any]] = []
        self.thresholds: Dict[str, Dict[str, float]] = {}
        
        # Background tasks
        self.monitoring_task: Optional[asyncio.Task] = None
        self.analysis_task: Optional[asyncio.Task] = None
        
    async def initialize(self) -> None:
        """Initialize the performance monitor."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        # Load existing data
        await self._load_metrics()
        await self._load_issues()
        await self._load_recommendations()
        
        # Setup default monitoring rules
        self._setup_default_rules()
        
        # Start background tasks
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        self.analysis_task = asyncio.create_task(self._analysis_loop())
        
        logger.info("PerformanceMonitor initialized")
        
    async def shutdown(self) -> None:
        """Shutdown the performance monitor."""
        if self.monitoring_task:
            self.monitoring_task.cancel()
        if self.analysis_task:
            self.analysis_task.cancel()
            
        if self._redis:
            await self._redis.close()
            
        logger.info("PerformanceMonitor shutdown")
        
    async def _load_metrics(self) -> None:
        """Load existing metrics from Redis."""
        try:
            cursor = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match="perf_metrics:*", count=100)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        metric_data = json.loads(data)
                        metric = PerformanceMetric(**metric_data)
                        
                        metric_key = f"{metric.metric_type}_{metric.component}"
                        self.metrics[metric_key].append(metric)
                        
        except Exception as exc:
            logger.error("Failed to load metrics: %s", exc)
            
    async def _load_issues(self) -> None:
        """Load existing issues from Redis."""
        try:
            cursor = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match="perf_issues:*", count=100)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        issue_data = json.loads(data)
                        issue = PerformanceIssue(**issue_data)
                        self.issues.append(issue)
                        
        except Exception as exc:
            logger.error("Failed to load issues: %s", exc)
            
    async def _load_recommendations(self) -> None:
        """Load existing recommendations from Redis."""
        try:
            cursor = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match="perf_recommendations:*", count=100)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        rec_data = json.loads(data)
                        rec = OptimizationRecommendation(**rec_data)
                        self.recommendations.append(rec)
                        
        except Exception as exc:
            logger.error("Failed to load recommendations: %s", exc)
            
    def _setup_default_rules(self) -> None:
        """Setup default monitoring rules."""
        self.monitoring_rules = [
            {
                "name": "high_latency",
                "metric_type": PerformanceMetricType.LATENCY,
                "threshold": 1.0,
                "operator": "gt",
                "severity": SeverityLevel.HIGH,
                "description": "High latency detected"
            },
            {
                "name": "high_cpu_usage",
                "metric_type": PerformanceMetricType.CPU_USAGE,
                "threshold": 80.0,
                "operator": "gt",
                "severity": SeverityLevel.MEDIUM,
                "description": "High CPU usage detected"
            },
            {
                "name": "high_memory_usage",
                "metric_type": PerformanceMetricType.MEMORY_USAGE,
                "threshold": 80.0,
                "operator": "gt",
                "severity": SeverityLevel.MEDIUM,
                "description": "High memory usage detected"
            },
            {
                "name": "high_error_rate",
                "metric_type": PerformanceMetricType.ERROR_RATE,
                "threshold": 5.0,
                "operator": "gt",
                "severity": SeverityLevel.HIGH,
                "description": "High error rate detected"
            }
        ]
        
    def get_profiler(self, component_name: str) -> PerformanceProfiler:
        """Get or create profiler for component."""
        if component_name not in self.profilers:
            self.profilers[component_name] = PerformanceProfiler(component_name)
        return self.profilers[component_name]
        
    async def record_metric(
        self,
        metric_type: PerformanceMetricType,
        component: str,
        value: float,
        unit: str = "",
        labels: Optional[Dict[str, str]] = None,
        tags: Optional[Set[str]] = None
    ) -> None:
        """Record a performance metric."""
        metric = PerformanceMetric(
            metric_type=metric_type,
            component=component,
            value=value,
            unit=unit,
            labels=labels or {},
            tags=tags or set(),
        )
        
        # Store in memory
        metric_key = f"{metric_type}_{component}"
        self.metrics[metric_key].append(metric)
        
        # Store in Redis
        if self._redis:
            key = f"perf_metrics:{metric.metric_id}"
            await self._redis.setex(key, 86400, json.dumps(metric.to_dict()))  # 24 hours
            
        # Check thresholds
        await self._check_thresholds(metric)
        
    async def _check_thresholds(self, metric: PerformanceMetric) -> None:
        """Check if metric violates any thresholds."""
        for rule in self.monitoring_rules:
            if rule["metric_type"] == metric.metric_type:
                if self._evaluate_rule(rule, metric):
                    await self._create_issue(rule, metric)
                    
    def _evaluate_rule(self, rule: Dict[str, Any], metric: PerformanceMetric) -> bool:
        """Evaluate monitoring rule."""
        operator = rule["operator"]
        threshold = rule["threshold"]
        
        if operator == "gt":
            return metric.value > threshold
        elif operator == "lt":
            return metric.value < threshold
        elif operator == "gte":
            return metric.value >= threshold
        elif operator == "lte":
            return metric.value <= threshold
        else:
            return False
            
    async def _create_issue(self, rule: Dict[str, Any], metric: PerformanceMetric) -> None:
        """Create performance issue."""
        issue = PerformanceIssue(
            title=f"{rule['name']} in {metric.component}",
            description=rule["description"],
            severity=rule["severity"],
            category=rule["metric_type"].value,
            component=metric.component,
            metrics=[metric],
            impact_score=self._calculate_impact_score(rule, metric),
        )
        
        self.issues.append(issue)
        
        # Store in Redis
        if self._redis:
            key = f"perf_issues:{issue.issue_id}"
            await self._redis.setex(key, 86400 * 7, json.dumps(issue.to_dict()))  # 7 days
            
        # Generate recommendation
        await self._generate_recommendation(issue)
        
        logger.warning("Performance issue detected: %s", issue.title)
        
    def _calculate_impact_score(self, rule: Dict[str, Any], metric: PerformanceMetric) -> float:
        """Calculate impact score for issue."""
        base_score = 0.5
        
        # Severity factor
        severity_factor = {
            SeverityLevel.LOW: 0.2,
            SeverityLevel.MEDIUM: 0.5,
            SeverityLevel.HIGH: 0.8,
            SeverityLevel.CRITICAL: 1.0
        }.get(rule["severity"], 0.5)
        
        # Threshold violation factor
        threshold = rule["threshold"]
        violation_factor = min(1.0, abs(metric.value - threshold) / threshold)
        
        return base_score + (severity_factor * 0.3) + (violation_factor * 0.2)
        
    async def _generate_recommendation(self, issue: PerformanceIssue) -> None:
        """Generate optimization recommendation for issue."""
        if issue.category == "latency":
            recommendation = OptimizationRecommendation(
                title="Optimize latency for " + issue.component,
                description=f"High latency detected in {issue.component}. Consider optimizing algorithms, adding caching, or scaling resources.",
                optimization_type=OptimizationType.CODE,
                priority="high" if issue.severity == SeverityLevel.CRITICAL else "medium",
                component=issue.component,
                expected_improvement=0.3,
                implementation_effort="medium",
                risk_level="low",
                steps=[
                    "Profile the operation to identify bottlenecks",
                    "Consider caching frequently accessed data",
                    "Optimize database queries",
                    "Review algorithm complexity"
                ],
                related_issues=[issue.issue_id],
                supporting_metrics=issue.metrics,
            )
        elif issue.category == "cpu_usage":
            recommendation = OptimizationRecommendation(
                title="Reduce CPU usage for " + issue.component,
                description=f"High CPU usage detected in {issue.component}. Consider optimizing code or scaling resources.",
                optimization_type=OptimizationType.CODE,
                priority="medium",
                component=issue.component,
                expected_improvement=0.2,
                implementation_effort="medium",
                risk_level="low",
                steps=[
                    "Profile CPU-intensive operations",
                    "Optimize loops and algorithms",
                    "Consider async/await patterns",
                    "Review for unnecessary computations"
                ],
                related_issues=[issue.issue_id],
                supporting_metrics=issue.metrics,
            )
        elif issue.category == "memory_usage":
            recommendation = OptimizationRecommendation(
                title="Optimize memory usage for " + issue.component,
                description=f"High memory usage detected in {issue.component}. Consider memory optimization techniques.",
                optimization_type=OptimizationType.CODE,
                priority="medium",
                component=issue.component,
                expected_improvement=0.25,
                implementation_effort="medium",
                risk_level="low",
                steps=[
                    "Profile memory allocation patterns",
                    "Optimize data structures",
                    "Implement memory pooling",
                    "Review for memory leaks"
                ],
                related_issues=[issue.issue_id],
                supporting_metrics=issue.metrics,
            )
        else:
            # Generic recommendation
            recommendation = OptimizationRecommendation(
                title="Investigate performance issue in " + issue.component,
                description=f"Performance issue detected in {issue.component}. Further investigation required.",
                optimization_type=OptimizationType.ARCHITECTURE,
                priority="medium",
                component=issue.component,
                expected_improvement=0.2,
                implementation_effort="high",
                risk_level="medium",
                steps=[
                    "Conduct thorough performance analysis",
                    "Review system architecture",
                    "Consider alternative approaches",
                    "Plan optimization roadmap"
                ],
                related_issues=[issue.issue_id],
                supporting_metrics=issue.metrics,
            )
            
        self.recommendations.append(recommendation)
        
        # Store in Redis
        if self._redis:
            key = f"perf_recommendations:{recommendation.recommendation_id}"
            await self._redis.setex(key, 86400 * 30, json.dumps(recommendation.to_dict()))  # 30 days
            
    async def _monitoring_loop(self) -> None:
        """Background monitoring loop."""
        while True:
            try:
                await asyncio.sleep(10)  # Monitor every 10 seconds
                
                # Collect system metrics
                await self._collect_system_metrics()
                
                # Update aggregates
                await self._update_aggregates()
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Monitoring loop error: %s", exc)
                await asyncio.sleep(1.0)
                
    async def _collect_system_metrics(self) -> None:
        """Collect system-level metrics."""
        # CPU metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        await self.record_metric(
            PerformanceMetricType.CPU_USAGE,
            "system",
            cpu_percent,
            "percent",
            tags={"system"}
        )
        
        # Memory metrics
        memory = psutil.virtual_memory()
        await self.record_metric(
            PerformanceMetricType.MEMORY_USAGE,
            "system",
            memory.percent,
            "percent",
            tags={"system"}
        )
        
        # Disk I/O metrics
        disk_io = psutil.disk_io_counters()
        if disk_io:
            await self.record_metric(
                PerformanceMetricType.DISK_IO,
                "system",
                disk_io.read_bytes + disk_io.write_bytes,
                "bytes",
                tags={"system"}
            )
            
        # Network I/O metrics
        network_io = psutil.net_io_counters()
        if network_io:
            await self.record_metric(
                PerformanceMetricType.NETWORK_IO,
                "system",
                network_io.bytes_sent + network_io.bytes_recv,
                "bytes",
                tags={"system"}
            )
            
    async def _update_aggregates(self) -> None:
        """Update metric aggregates."""
        for metric_key, metric_deque in self.metrics.items():
            if not metric_deque:
                continue
                
            values = [m.value for m in metric_deque]
            
            self.metric_aggregates[metric_key] = {
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
                "latest": values[-1],
                "timestamp": metric_deque[-1].timestamp,
            }
            
    async def _analysis_loop(self) -> None:
        """Background analysis loop."""
        while True:
            try:
                await asyncio.sleep(60)  # Analyze every minute
                
                # Analyze trends
                await self._analyze_trends()
                
                # Detect anomalies
                await self._detect_anomalies()
                
                # Generate insights
                await self._generate_insights()
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Analysis loop error: %s", exc)
                await asyncio.sleep(1.0)
                
    async def _analyze_trends(self) -> None:
        """Analyze performance trends."""
        for metric_key, metric_deque in self.metrics.items():
            if len(metric_deque) < 10:
                continue
                
            # Simple trend analysis
            recent_values = [m.value for m in list(metric_deque)[-10:]]
            older_values = [m.value for m in list(metric_deque)[-20:-10]] if len(metric_deque) >= 20 else []
            
            if older_values:
                recent_avg = sum(recent_values) / len(recent_values)
                older_avg = sum(older_values) / len(older_values)
                
                trend = (recent_avg - older_avg) / older_avg if older_avg > 0 else 0
                
                # Detect concerning trends
                if trend > 0.2:  # 20% increase
                    logger.warning("Increasing trend detected in %s: %.2f%%", metric_key, trend * 100)
                elif trend < -0.2:  # 20% decrease
                    logger.info("Decreasing trend detected in %s: %.2f%%", metric_key, trend * 100)
                    
    async def _detect_anomalies(self) -> None:
        """Detect performance anomalies."""
        for metric_key, metric_deque in self.metrics.items():
            if len(metric_deque) < 50:
                continue
                
            # Simple anomaly detection using standard deviation
            values = [m.value for m in metric_deque]
            mean = sum(values) / len(values)
            variance = sum((x - mean) ** 2 for x in values) / len(values)
            std_dev = variance ** 0.5
            
            # Check for outliers
            for metric in list(metric_deque)[-10:]:
                if abs(metric.value - mean) > 2 * std_dev:  # 2 sigma
                    logger.warning("Anomaly detected in %s: %.2f (mean: %.2f, std: %.2f)", 
                                 metric_key, metric.value, mean, std_dev)
                    
    async def _generate_insights(self) -> None:
        """Generate performance insights."""
        # Generate insights based on metrics and issues
        insights = []
        
        # High error rate insight
        error_metrics = [m for m in self.metrics.get("error_rate_system", []) if m.value > 5.0]
        if error_metrics:
            insights.append({
                "type": "high_error_rate",
                "description": f"High error rate detected: {len(error_metrics)} instances",
                "severity": "high"
            })
            
        # Performance degradation insight
        for metric_key, aggregates in self.metric_aggregates.items():
            if aggregates["avg"] > aggregates.get("baseline", aggregates["avg"]) * 1.5:
                insights.append({
                    "type": "performance_degradation",
                    "description": f"Performance degradation in {metric_key}",
                    "severity": "medium"
                })
                
        if insights:
            logger.info("Generated %d performance insights", len(insights))
            
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get comprehensive performance summary."""
        return {
            "metrics_summary": {
                key: aggregates for key, aggregates in self.metric_aggregates.items()
            },
            "active_issues": len([i for i in self.issues if i.status == "open"]),
            "pending_recommendations": len([r for r in self.recommendations if r.status == "pending"]),
            "profiler_count": len(self.profilers),
            "monitoring_rules": len(self.monitoring_rules),
            "system_health": self._calculate_system_health(),
        }
        
    def _calculate_system_health(self) -> float:
        """Calculate overall system health score."""
        if not self.metric_aggregates:
            return 1.0
            
        health_score = 1.0
        
        # CPU health
        cpu_metrics = self.metric_aggregates.get("cpu_usage_system", {})
        if cpu_metrics:
            cpu_avg = cpu_metrics.get("avg", 0)
            if cpu_avg > 80:
                health_score -= 0.3
            elif cpu_avg > 60:
                health_score -= 0.1
                
        # Memory health
        memory_metrics = self.metric_aggregates.get("memory_usage_system", {})
        if memory_metrics:
            memory_avg = memory_metrics.get("avg", 0)
            if memory_avg > 80:
                health_score -= 0.3
            elif memory_avg > 60:
                health_score -= 0.1
                
        # Error rate health
        error_metrics = self.metric_aggregates.get("error_rate_system", {})
        if error_metrics:
            error_avg = error_metrics.get("avg", 0)
            if error_avg > 5:
                health_score -= 0.4
            elif error_avg > 1:
                health_score -= 0.2
                
        return max(0.0, health_score)
        
    def get_component_performance(self, component: str) -> Dict[str, Any]:
        """Get performance data for specific component."""
        profiler = self.profilers.get(component)
        stats = profiler.get_profile_statistics() if profiler else {}
        
        # Get component metrics
        component_metrics = {}
        for metric_key, metric_deque in self.metrics.items():
            if metric_key.endswith(f"_{component}"):
                component_metrics[metric_key] = list(metric_deque)
                
        # Get component issues
        component_issues = [i for i in self.issues if i.component == component]
        
        # Get component recommendations
        component_recommendations = [r for r in self.recommendations if r.component == component]
        
        return {
            "component": component,
            "profile_stats": stats,
            "metrics": component_metrics,
            "issues": [i.to_dict() for i in component_issues],
            "recommendations": [r.to_dict() for r in component_recommendations],
        }


# Global performance monitor instance
performance_monitor: Optional[PerformanceMonitor] = None