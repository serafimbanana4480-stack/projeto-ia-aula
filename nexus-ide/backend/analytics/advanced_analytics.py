"""Advanced Analytics — Deep insights and predictive analytics for AI systems.

This module provides:
- Behavioral analytics and pattern recognition
- Predictive modeling and forecasting
- Performance optimization analytics
- Anomaly detection and alerting
- Business intelligence and reporting
- Real-time analytics dashboard
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import statistics
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from backend.observability.event_bus import EventBus
from backend.observability.events import Event
from backend.observability.optional_deps import optional_module

# numpy is an optional extra (``uv sync --extra analytics``), not a hard
# dependency: nothing reachable from backend/orchestrator/main.py needs it, and
# making it mandatory would add ~20 MB to every install for a feature nothing
# calls. The stand-in keeps this module importable without numpy and raises a
# message that names the extra only when a statistic is actually computed.
np = optional_module("numpy", extra="analytics", owner=__name__)

logger = logging.getLogger(__name__)


class AnalyticsType(Enum):
    """Types of analytics available."""
    BEHAVIORAL = "behavioral"           # User and agent behavior analysis
    PERFORMANCE = "performance"         # System performance analytics
    PREDICTIVE = "predictive"           # Predictive modeling and forecasting
    ANOMALY = "anomaly"                # Anomaly detection
    BUSINESS = "business"               # Business intelligence
    OPERATIONAL = "operational"         # Operational efficiency analytics
    SECURITY = "security"               # Security analytics
    RESOURCE = "resource"               # Resource utilization analytics


class InsightLevel(Enum):
    """Levels of analytical insights."""
    DESCRIPTIVE = "descriptive"         # What happened
    DIAGNOSTIC = "diagnostic"           # Why it happened
    PREDICTIVE = "predictive"           # What will happen
    PRESCRIPTIVE = "prescriptive"       # What should be done


class AlertSeverity(Enum):
    """Severity levels for analytics alerts."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AnalyticsMetric:
    """Represents an analytics metric."""
    metric_id: str
    name: str
    description: str
    analytics_type: AnalyticsType
    value: float | int | str
    unit: str
    timestamp: datetime
    context: dict[str, Any]
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalyticalInsight:
    """Represents an analytical insight."""
    insight_id: str
    title: str
    description: str
    insight_level: InsightLevel
    confidence: float
    impact_score: float
    analytics_type: AnalyticsType
    data_source: str
    findings: list[str]
    recommendations: list[str]
    supporting_metrics: list[str]
    created_at: datetime
    expires_at: datetime | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PredictionResult:
    """Represents a prediction result."""
    prediction_id: str
    model_name: str
    prediction_type: str
    predicted_value: float | str
    confidence_interval: tuple[float, float]
    confidence_score: float
    features_used: list[str]
    prediction_horizon: timedelta
    created_at: datetime
    actual_value: float | None = None
    accuracy_score: float | None = None


@dataclass
class AnomalyDetection:
    """Represents an anomaly detection result."""
    anomaly_id: str
    detection_type: str
    severity: AlertSeverity
    description: str
    anomaly_score: float
    threshold: float
    context: dict[str, Any]
    detected_at: datetime
    resolved: bool = False
    resolution_action: str | None = None


class AdvancedAnalyticsEngine:
    """Advanced analytics engine for AI systems."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

        # Data storage
        self.metrics: dict[str, list[AnalyticsMetric]] = defaultdict(list)
        self.insights: dict[str, AnalyticalInsight] = {}
        self.predictions: dict[str, PredictionResult] = {}
        self.anomalies: dict[str, AnomalyDetection] = {}

        # Analytics configurations
        self.analytics_configs: dict[AnalyticsType, dict[str, Any]] = {}
        self.prediction_models: dict[str, dict[str, Any]] = {}
        self.anomaly_detectors: dict[str, dict[str, Any]] = {}

        # Time series data
        self.time_series_data: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))

        # Performance tracking
        self.analytics_performance: dict[str, dict[str, Any]] = {}

        # Initialize configurations
        self._initialize_analytics_configs()

        # Start background tasks
        self._analytics_task = asyncio.create_task(self._continuous_analytics())
        self._prediction_task = asyncio.create_task(self._periodic_predictions())
        self._anomaly_task = asyncio.create_task(self._continuous_anomaly_detection())

    def _initialize_analytics_configs(self) -> None:
        """Initialize analytics configurations."""

        self.analytics_configs = {
            AnalyticsType.BEHAVIORAL: {
                "window_size": 100,
                "sampling_rate": 1.0,
                "pattern_threshold": 0.7,
                "trend_analysis": True,
                "seasonality_detection": True
            },
            AnalyticsType.PERFORMANCE: {
                "window_size": 200,
                "sampling_rate": 1.0,
                "baseline_calculation": "moving_average",
                "performance_thresholds": {
                    "response_time": 2.0,  # seconds
                    "error_rate": 0.05,    # 5%
                    "throughput": 1000     # requests/minute
                }
            },
            AnalyticsType.PREDICTIVE: {
                "prediction_horizon": timedelta(hours=24),
                "model_types": ["linear_regression", "time_series", "ensemble"],
                "confidence_threshold": 0.8,
                "feature_selection": True
            },
            AnalyticsType.ANOMALY: {
                "detection_methods": ["statistical", "ml_based", "rule_based"],
                "sensitivity": 0.95,
                "min_anomaly_score": 0.7,
                "alert_threshold": 0.8
            },
            AnalyticsType.BUSINESS: {
                "kpi_tracking": True,
                "roi_calculation": True,
                "cost_analysis": True,
                "trend_forecasting": True
            },
            AnalyticsType.OPERATIONAL: {
                "efficiency_metrics": True,
                "resource_optimization": True,
                "process_mining": True,
                "bottleneck_detection": True
            },
            AnalyticsType.SECURITY: {
                "threat_detection": True,
                "vulnerability_analysis": True,
                "compliance_monitoring": True,
                "risk_assessment": True
            },
            AnalyticsType.RESOURCE: {
                "utilization_tracking": True,
                "capacity_planning": True,
                "cost_optimization": True,
                "resource_forecasting": True
            }
        }

    async def collect_metric(self, metric_type: AnalyticsType, name: str,
                            value: float | int | str, unit: str,
                            context: dict[str, Any] = None) -> str:
        """Collect an analytics metric."""

        metric_id = str(uuid.uuid4())

        metric = AnalyticsMetric(
            metric_id=metric_id,
            name=name,
            description=f"Analytics metric for {name}",
            analytics_type=metric_type,
            value=value,
            unit=unit,
            timestamp=datetime.now(),
            context=context or {},
            tags=self._extract_metric_tags(name, context)
        )

        # Store metric
        self.metrics[metric_type.value].append(metric)

        # Add to time series data
        self.time_series_data[name].append({
            "timestamp": metric.timestamp,
            "value": metric.value,
            "context": metric.context
        })

        # Emit metric collection event
        await self.event_bus.emit(Event(
            type="analytics_metric_collected",
            data={
                "metric_id": metric_id,
                "metric_type": metric_type.value,
                "name": name,
                "value": value,
                "unit": unit
            }
        ))

        return metric_id

    async def analyze_behavioral_patterns(self, agent_id: str = None,
                                        time_window: timedelta = None) -> list[AnalyticalInsight]:
        """Analyze behavioral patterns."""

        insights = []

        # Get behavioral metrics
        behavioral_metrics = self.metrics.get(AnalyticsType.BEHAVIORAL.value, [])

        if time_window:
            cutoff_time = datetime.now() - time_window
            behavioral_metrics = [m for m in behavioral_metrics if m.timestamp >= cutoff_time]

        if agent_id:
            behavioral_metrics = [m for m in behavioral_metrics
                               if m.context.get("agent_id") == agent_id]

        if not behavioral_metrics:
            return insights

        # Pattern analysis
        patterns = self._detect_patterns(behavioral_metrics)

        # Trend analysis
        self._analyze_trends(behavioral_metrics)

        # Create insights
        for pattern in patterns:
            insight = AnalyticalInsight(
                insight_id=str(uuid.uuid4()),
                title=f"Behavioral Pattern: {pattern['name']}",
                description=pattern['description'],
                insight_level=InsightLevel.DIAGNOSTIC,
                confidence=pattern['confidence'],
                impact_score=pattern['impact_score'],
                analytics_type=AnalyticsType.BEHAVIORAL,
                data_source="behavioral_metrics",
                findings=pattern['findings'],
                recommendations=pattern['recommendations'],
                supporting_metrics=pattern['supporting_metrics'],
                created_at=datetime.now(),
                expires_at=datetime.now() + timedelta(hours=24)
            )

            insights.append(insight)
            self.insights[insight.insight_id] = insight

        return insights

    async def analyze_performance_metrics(self, component_id: str = None,
                                        time_window: timedelta = None) -> list[AnalyticalInsight]:
        """Analyze performance metrics."""

        insights = []

        # Get performance metrics
        performance_metrics = self.metrics.get(AnalyticsType.PERFORMANCE.value, [])

        if time_window:
            cutoff_time = datetime.now() - time_window
            performance_metrics = [m for m in performance_metrics if m.timestamp >= cutoff_time]

        if component_id:
            performance_metrics = [m for m in performance_metrics
                                 if m.context.get("component_id") == component_id]

        if not performance_metrics:
            return insights

        # Performance analysis
        performance_analysis = self._analyze_performance(performance_metrics)

        # Create insights
        for analysis in performance_analysis:
            insight = AnalyticalInsight(
                insight_id=str(uuid.uuid4()),
                title=f"Performance Analysis: {analysis['metric']}",
                description=analysis['description'],
                insight_level=InsightLevel.DESCRIPTIVE,
                confidence=analysis['confidence'],
                impact_score=analysis['impact_score'],
                analytics_type=AnalyticsType.PERFORMANCE,
                data_source="performance_metrics",
                findings=analysis['findings'],
                recommendations=analysis['recommendations'],
                supporting_metrics=analysis['supporting_metrics'],
                created_at=datetime.now(),
                expires_at=datetime.now() + timedelta(hours=12)
            )

            insights.append(insight)
            self.insights[insight.insight_id] = insight

        return insights

    async def generate_predictions(self, prediction_type: str,
                                 target_metric: str,
                                 horizon: timedelta = None) -> list[PredictionResult]:
        """Generate predictions using various models."""

        predictions = []

        # Get time series data for target metric
        time_series = list(self.time_series_data[target_metric])

        if len(time_series) < 10:  # Need minimum data points
            return predictions

        # Use different prediction models
        models = self.analytics_configs[AnalyticsType.PREDICTIVE]["model_types"]

        for model_name in models:
            try:
                prediction = await self._generate_prediction(
                    model_name, target_metric, time_series, horizon
                )

                if prediction:
                    predictions.append(prediction)
                    self.predictions[prediction.prediction_id] = prediction

            except Exception as e:
                logger.error(f"Error generating prediction with {model_name}: {e}")

        return predictions

    async def detect_anomalies(self, metric_name: str = None,
                             detection_method: str = None) -> list[AnomalyDetection]:
        """Detect anomalies in metrics."""

        anomalies = []

        # Get metrics to analyze
        if metric_name:
            metrics_to_check = [list(self.time_series_data[metric_name])]
        else:
            metrics_to_check = [list(data) for data in self.time_series_data.values()]

        for time_series in metrics_to_check:
            if len(time_series) < 5:  # Need minimum data points
                continue

            # Detect anomalies using different methods
            methods = detection_method or self.analytics_configs[AnalyticsType.ANOMALY]["detection_methods"]

            for method in methods:
                try:
                    detected_anomalies = await self._detect_anomalies_method(
                        method, time_series
                    )

                    anomalies.extend(detected_anomalies)

                except Exception as e:
                    logger.error(f"Error in anomaly detection with {method}: {e}")

        # Store anomalies
        for anomaly in anomalies:
            self.anomalies[anomaly.anomaly_id] = anomaly

        return anomalies

    async def generate_business_intelligence(self, time_period: timedelta = None) -> dict[str, Any]:
        """Generate business intelligence report."""

        # Get business metrics
        business_metrics = self.metrics.get(AnalyticsType.BUSINESS.value, [])

        if time_period:
            cutoff_time = datetime.now() - time_period
            business_metrics = [m for m in business_metrics if m.timestamp >= cutoff_time]

        # Calculate KPIs
        kpis = self._calculate_kpis(business_metrics)

        # ROI analysis
        roi_analysis = self._calculate_roi(business_metrics)

        # Cost analysis
        cost_analysis = self._analyze_costs(business_metrics)

        # Trend forecasting
        trend_forecast = self._forecast_trends(business_metrics)

        bi_report = {
            "report_id": str(uuid.uuid4()),
            "generated_at": datetime.now().isoformat(),
            "time_period": time_period.days if time_period else "all_time",
            "kpis": kpis,
            "roi_analysis": roi_analysis,
            "cost_analysis": cost_analysis,
            "trend_forecast": trend_forecast,
            "summary": self._generate_bi_summary(kpis, roi_analysis, cost_analysis)
        }

        return bi_report

    def _extract_metric_tags(self, name: str, context: dict[str, Any]) -> list[str]:
        """Extract tags from metric name and context."""

        tags = []

        # Extract from name
        name_parts = name.lower().split('_')
        tags.extend(name_parts)

        # Extract from context
        for key, value in context.items():
            if isinstance(value, str):
                tags.append(value.lower())
            elif isinstance(value, (int, float)):
                tags.append(f"{key}_{value}")

        # Remove duplicates and limit
        unique_tags = list(set(tags))
        return unique_tags[:10]

    def _detect_patterns(self, metrics: list[AnalyticsMetric]) -> list[dict[str, Any]]:
        """Detect patterns in behavioral metrics."""

        patterns = []

        # Group metrics by name
        metric_groups = defaultdict(list)
        for metric in metrics:
            metric_groups[metric.name].append(metric)

        # Analyze each metric group
        for name, group_metrics in metric_groups.items():
            if len(group_metrics) < 5:
                continue

            # Extract values
            values = [float(m.value) if isinstance(m.value, (int, float)) else 0 for m in group_metrics]

            # Detect patterns
            if self._is_cyclical_pattern(values):
                patterns.append({
                    "name": f"Cyclical Pattern in {name}",
                    "description": f"Detected cyclical behavior in {name}",
                    "confidence": 0.8,
                    "impact_score": 0.6,
                    "findings": [f"Pattern repeats every {self._detect_cycle_length(values)} periods"],
                    "recommendations": [f"Optimize scheduling based on {name} patterns"],
                    "supporting_metrics": [m.metric_id for m in group_metrics[-5:]]
                })

            if self._is_trending_pattern(values):
                trend_direction = "increasing" if values[-1] > values[0] else "decreasing"
                patterns.append({
                    "name": f"Trend Pattern in {name}",
                    "description": f"Detected {trend_direction} trend in {name}",
                    "confidence": 0.7,
                    "impact_score": 0.5,
                    "findings": [f"{name.capitalize()} is {trend_direction} over time"],
                    "recommendations": [f"Monitor {name} trend and adjust accordingly"],
                    "supporting_metrics": [m.metric_id for m in group_metrics[-5:]]
                })

        return patterns

    def _analyze_trends(self, metrics: list[AnalyticsMetric]) -> list[dict[str, Any]]:
        """Analyze trends in metrics."""

        trends = []

        # Group metrics by name
        metric_groups = defaultdict(list)
        for metric in metrics:
            metric_groups[metric.name].append(metric)

        # Analyze trends for each metric
        for name, group_metrics in metric_groups.items():
            if len(group_metrics) < 3:
                continue

            # Sort by timestamp
            group_metrics.sort(key=lambda m: m.timestamp)

            # Extract values
            values = [float(m.value) if isinstance(m.value, (int, float)) else 0 for m in group_metrics]

            # Calculate trend
            if len(values) >= 2:
                trend_slope = self._calculate_trend_slope(values)

                trends.append({
                    "metric": name,
                    "trend_slope": trend_slope,
                    "trend_direction": "increasing" if trend_slope > 0 else "decreasing",
                    "strength": abs(trend_slope)
                })

        return trends

    def _analyze_performance(self, metrics: list[AnalyticsMetric]) -> list[dict[str, Any]]:
        """Analyze performance metrics."""

        analyses = []

        # Group metrics by name
        metric_groups = defaultdict(list)
        for metric in metrics:
            metric_groups[metric.name].append(metric)

        # Analyze each metric group
        for name, group_metrics in metric_groups.items():
            if len(group_metrics) < 3:
                continue

            # Extract values
            values = [float(m.value) if isinstance(m.value, (int, float)) else 0 for m in group_metrics]

            # Calculate statistics
            avg_value = statistics.mean(values)
            min(values)
            max(values)
            statistics.stdev(values) if len(values) > 1 else 0

            # Check against thresholds
            config = self.analytics_configs[AnalyticsType.PERFORMANCE]
            thresholds = config.get("performance_thresholds", {})

            threshold = thresholds.get(name)
            if threshold and avg_value > threshold:
                analyses.append({
                    "metric": name,
                    "description": f"{name} average ({avg_value:.2f}) exceeds threshold ({threshold})",
                    "confidence": 0.9,
                    "impact_score": min(1.0, avg_value / threshold),
                    "findings": [
                        f"Average {name}: {avg_value:.2f}",
                        f"Threshold: {threshold}",
                        f"Exceeded by: {((avg_value/threshold - 1) * 100):.1f}%"
                    ],
                    "recommendations": [
                        f"Investigate {name} performance issues",
                        f"Consider optimizing {name} processing"
                    ],
                    "supporting_metrics": [m.metric_id for m in group_metrics[-5:]]
                })

        return analyses

    async def _generate_prediction(self, model_name: str, target_metric: str,
                                  time_series: list[dict[str, Any]],
                                  horizon: timedelta) -> PredictionResult | None:
        """Generate prediction using specified model."""

        if model_name == "linear_regression":
            return self._linear_regression_prediction(target_metric, time_series, horizon)
        elif model_name == "time_series":
            return self._time_series_prediction(target_metric, time_series, horizon)
        elif model_name == "ensemble":
            return self._ensemble_prediction(target_metric, time_series, horizon)

        return None

    def _linear_regression_prediction(self, target_metric: str,
                                   time_series: list[dict[str, Any]],
                                   horizon: timedelta) -> PredictionResult:
        """Generate prediction using linear regression."""

        # Extract values and timestamps
        values = [float(item["value"]) for item in time_series]
        [item["timestamp"] for item in time_series]

        # Simple linear regression (time as x, value as y)
        n = len(values)
        if n < 2:
            raise ValueError("Insufficient data for linear regression")

        # Calculate coefficients
        x = np.arange(n)
        y = np.array(values)

        # Linear regression calculation
        x_mean = np.mean(x)
        y_mean = np.mean(y)

        numerator = np.sum((x - x_mean) * (y - y_mean))
        denominator = np.sum((x - x_mean) ** 2)

        slope = 0 if denominator == 0 else numerator / denominator

        intercept = y_mean - slope * x_mean

        # Predict future value
        future_x = n + (horizon.total_seconds() / 3600)  # Convert to hours
        predicted_value = slope * future_x + intercept

        # Calculate confidence interval (simplified)
        residuals = y - (slope * x + intercept)
        mse = np.mean(residuals ** 2)
        std_error = np.sqrt(mse)

        confidence_interval = (
            predicted_value - 1.96 * std_error,
            predicted_value + 1.96 * std_error
        )

        # Calculate confidence score
        confidence_score = max(0.0, min(1.0, 1.0 - (std_error / abs(predicted_value))))

        return PredictionResult(
            prediction_id=str(uuid.uuid4()),
            model_name="linear_regression",
            prediction_type="value_prediction",
            predicted_value=predicted_value,
            confidence_interval=confidence_interval,
            confidence_score=confidence_score,
            features_used=["time"],
            prediction_horizon=horizon,
            created_at=datetime.now()
        )

    def _time_series_prediction(self, target_metric: str,
                              time_series: list[dict[str, Any]],
                              horizon: timedelta) -> PredictionResult:
        """Generate prediction using time series analysis."""

        # Extract values
        values = [float(item["value"]) for item in time_series]

        if len(values) < 3:
            raise ValueError("Insufficient data for time series prediction")

        # Simple moving average prediction
        window_size = min(5, len(values))
        recent_values = values[-window_size:]

        predicted_value = statistics.mean(recent_values)

        # Calculate confidence interval based on recent volatility
        std_dev = statistics.stdev(recent_values) if len(recent_values) > 1 else 0
        confidence_interval = (
            predicted_value - 1.96 * std_dev,
            predicted_value + 1.96 * std_dev
        )

        # Calculate confidence score
        confidence_score = max(0.0, min(1.0, 1.0 - (std_dev / abs(predicted_value))))

        return PredictionResult(
            prediction_id=str(uuid.uuid4()),
            model_name="time_series",
            prediction_type="value_prediction",
            predicted_value=predicted_value,
            confidence_interval=confidence_interval,
            confidence_score=confidence_score,
            features_used=["moving_average"],
            prediction_horizon=horizon,
            created_at=datetime.now()
        )

    def _ensemble_prediction(self, target_metric: str,
                            time_series: list[dict[str, Any]],
                            horizon: timedelta) -> PredictionResult:
        """Generate prediction using ensemble method."""

        # Get predictions from multiple models
        lr_prediction = self._linear_regression_prediction(target_metric, time_series, horizon)
        ts_prediction = self._time_series_prediction(target_metric, time_series, horizon)

        # Ensemble by averaging
        predicted_value = (lr_prediction.predicted_value + ts_prediction.predicted_value) / 2

        # Combine confidence intervals
        ci_low = (lr_prediction.confidence_interval[0] + ts_prediction.confidence_interval[0]) / 2
        ci_high = (lr_prediction.confidence_interval[1] + ts_prediction.confidence_interval[1]) / 2
        confidence_interval = (ci_low, ci_high)

        # Average confidence score
        confidence_score = (lr_prediction.confidence_score + ts_prediction.confidence_score) / 2

        return PredictionResult(
            prediction_id=str(uuid.uuid4()),
            model_name="ensemble",
            prediction_type="value_prediction",
            predicted_value=predicted_value,
            confidence_interval=confidence_interval,
            confidence_score=confidence_score,
            features_used=["time", "moving_average"],
            prediction_horizon=horizon,
            created_at=datetime.now()
        )

    async def _detect_anomalies_method(self, method: str,
                                      time_series: list[dict[str, Any]]) -> list[AnomalyDetection]:
        """Detect anomalies using specified method."""

        anomalies = []

        if method == "statistical":
            anomalies.extend(self._statistical_anomaly_detection(time_series))
        elif method == "ml_based":
            anomalies.extend(self._ml_anomaly_detection(time_series))
        elif method == "rule_based":
            anomalies.extend(self._rule_based_anomaly_detection(time_series))

        return anomalies

    def _statistical_anomaly_detection(self, time_series: list[dict[str, Any]]) -> list[AnomalyDetection]:
        """Statistical anomaly detection using z-score."""

        anomalies = []

        # Extract values
        values = [float(item["value"]) for item in time_series]

        if len(values) < 3:
            return anomalies

        # Calculate statistics
        mean = statistics.mean(values)
        std_dev = statistics.stdev(values) if len(values) > 1 else 0

        if std_dev == 0:
            return anomalies

        # Detect anomalies (z-score > 3)
        threshold = 3.0
        self.analytics_configs[AnalyticsType.ANOMALY]["sensitivity"]

        # `values` is built by a comprehension over `time_series`, so the two are
        # equal by construction: strict=True turns a future refactor that breaks
        # that invariant into a loud error instead of a silently short z-score scan.
        for _i, (item, value) in enumerate(zip(time_series, values, strict=True)):
            z_score = abs((value - mean) / std_dev)

            if z_score > threshold:
                severity = AlertSeverity.CRITICAL if z_score > 4 else AlertSeverity.HIGH

                anomaly = AnomalyDetection(
                    anomaly_id=str(uuid.uuid4()),
                    detection_type="statistical_zscore",
                    severity=severity,
                    description=f"Statistical anomaly detected: z-score = {z_score:.2f}",
                    anomaly_score=z_score / 5.0,  # Normalize to 0-1
                    threshold=threshold,
                    context={"timestamp": item["timestamp"], "value": value, "z_score": z_score},
                    detected_at=datetime.now()
                )

                anomalies.append(anomaly)

        return anomalies

    def _ml_anomaly_detection(self, time_series: list[dict[str, Any]]) -> list[AnomalyDetection]:
        """Machine learning based anomaly detection."""

        # Simplified ML-based detection using isolation forest concept
        anomalies = []

        # Extract values
        values = [float(item["value"]) for item in time_series]

        if len(values) < 10:
            return anomalies

        # Simple isolation: detect points far from median
        median = statistics.median(values)
        mad = statistics.median([abs(v - median) for v in values])  # Median absolute deviation

        if mad == 0:
            return anomalies

        # Detect anomalies
        threshold = 3.0  # MAD threshold

        # Same invariant as _statistical_anomaly_detection: `values` is derived
        # from `time_series` one-for-one.
        for _i, (item, value) in enumerate(zip(time_series, values, strict=True)):
            mad_score = abs(value - median) / mad

            if mad_score > threshold:
                severity = AlertSeverity.HIGH if mad_score > 4 else AlertSeverity.MEDIUM

                anomaly = AnomalyDetection(
                    anomaly_id=str(uuid.uuid4()),
                    detection_type="ml_isolation",
                    severity=severity,
                    description=f"ML-based anomaly detected: MAD score = {mad_score:.2f}",
                    anomaly_score=mad_score / 5.0,  # Normalize to 0-1
                    threshold=threshold,
                    context={"timestamp": item["timestamp"], "value": value, "mad_score": mad_score},
                    detected_at=datetime.now()
                )

                anomalies.append(anomaly)

        return anomalies

    def _rule_based_anomaly_detection(self, time_series: list[dict[str, Any]]) -> list[AnomalyDetection]:
        """Rule-based anomaly detection."""

        anomalies = []

        # Extract values
        values = [float(item["value"]) for item in time_series]

        if len(values) < 2:
            return anomalies

        # Rule 1: Sudden spike (increase > 50% from previous value)
        for i in range(1, len(values)):
            prev_value = values[i-1]
            curr_value = values[i]

            if prev_value != 0:
                change_rate = abs((curr_value - prev_value) / prev_value)

                if change_rate > 0.5:  # 50% change
                    severity = AlertSeverity.CRITICAL if change_rate > 1.0 else AlertSeverity.HIGH

                    anomaly = AnomalyDetection(
                        anomaly_id=str(uuid.uuid4()),
                        detection_type="rule_based_spike",
                        severity=severity,
                        description=f"Sudden spike detected: {change_rate:.2f} change",
                        anomaly_score=min(1.0, change_rate),
                        threshold=0.5,
                        context={
                            "timestamp": time_series[i]["timestamp"],
                            "value": curr_value,
                            "previous_value": prev_value,
                            "change_rate": change_rate
                        },
                        detected_at=datetime.now()
                    )

                    anomalies.append(anomaly)

        return anomalies

    def _calculate_kpis(self, business_metrics: list[AnalyticsMetric]) -> dict[str, Any]:
        """Calculate key performance indicators."""

        kpis = {}

        # Group metrics by name
        metric_groups = defaultdict(list)
        for metric in business_metrics:
            metric_groups[metric.name].append(metric)

        # Calculate KPIs for each metric group
        for name, group_metrics in metric_groups.items():
            values = [float(m.value) if isinstance(m.value, (int, float)) else 0 for m in group_metrics]

            if values:
                kpis[name] = {
                    "current": values[-1] if values else 0,
                    "average": statistics.mean(values),
                    "min": min(values),
                    "max": max(values),
                    "trend": "increasing" if len(values) > 1 and values[-1] > values[0] else "decreasing",
                    "volatility": statistics.stdev(values) if len(values) > 1 else 0
                }

        return kpis

    def _calculate_roi(self, business_metrics: list[AnalyticsMetric]) -> dict[str, Any]:
        """Calculate return on investment."""

        roi_analysis = {}

        # Extract cost and benefit metrics
        costs = []
        benefits = []

        for metric in business_metrics:
            if "cost" in metric.name.lower():
                costs.append(float(metric.value) if isinstance(metric.value, (int, float)) else 0)
            elif "revenue" in metric.name.lower() or "benefit" in metric.name.lower():
                benefits.append(float(metric.value) if isinstance(metric.value, (int, float)) else 0)

        if costs and benefits:
            total_cost = sum(costs)
            total_benefit = sum(benefits)

            roi = ((total_benefit - total_cost) / total_cost) * 100 if total_cost > 0 else 0

            roi_analysis = {
                "total_cost": total_cost,
                "total_benefit": total_benefit,
                "roi_percentage": roi,
                "payback_period": "N/A",  # Would need more detailed analysis
                "roi_trend": "positive" if roi > 0 else "negative"
            }

        return roi_analysis

    def _analyze_costs(self, business_metrics: list[AnalyticsMetric]) -> dict[str, Any]:
        """Analyze cost structure."""

        cost_analysis = {}

        # Extract cost metrics
        cost_metrics = [m for m in business_metrics if "cost" in m.name.lower()]

        if cost_metrics:
            costs = [float(m.value) if isinstance(m.value, (int, float)) else 0 for m in cost_metrics]

            cost_analysis = {
                "total_cost": sum(costs),
                "average_cost": statistics.mean(costs),
                "cost_trend": "increasing" if len(costs) > 1 and costs[-1] > costs[0] else "decreasing",
                "cost_breakdown": {
                    m.name: float(m.value) if isinstance(m.value, (int, float)) else 0
                    for m in cost_metrics
                }
            }

        return cost_analysis

    def _forecast_trends(self, business_metrics: list[AnalyticsMetric]) -> dict[str, Any]:
        """Forecast future trends."""

        trends = {}

        # Group metrics by name
        metric_groups = defaultdict(list)
        for metric in business_metrics:
            metric_groups[metric.name].append(metric)

        # Forecast for each metric group
        for name, group_metrics in metric_groups.items():
            if len(group_metrics) >= 3:
                values = [float(m.value) if isinstance(m.value, (int, float)) else 0 for m in group_metrics]

                # Simple trend forecast
                if len(values) >= 2:
                    trend_slope = self._calculate_trend_slope(values)

                    # Forecast next value
                    next_value = values[-1] + trend_slope

                    trends[name] = {
                        "current_trend": "increasing" if trend_slope > 0 else "decreasing",
                        "trend_strength": abs(trend_slope),
                        "next_period_forecast": next_value,
                        "confidence": max(0.0, min(1.0, 1.0 - abs(trend_slope) / max(abs(values), 1)))
                    }

        return trends

    def _generate_bi_summary(self, kpis: dict[str, Any], roi_analysis: dict[str, Any],
                           cost_analysis: dict[str, Any]) -> str:
        """Generate business intelligence summary."""

        summary_parts = []

        # KPI summary
        if kpis:
            top_kpis = sorted(kpis.items(), key=lambda x: x[1].get("average", 0), reverse=True)[:3]
            kpi_summary = ", ".join(
                f"{k}({v.get('average', 0):.2f})" for k, v in top_kpis
            )
            summary_parts.append(f"Top KPIs: {kpi_summary}")

        # ROI summary
        if roi_analysis:
            roi = roi_analysis.get("roi_percentage", 0)
            summary_parts.append(f"ROI: {roi:.1f}% ({'positive' if roi > 0 else 'negative'})")

        # Cost summary
        if cost_analysis:
            total_cost = cost_analysis.get("total_cost", 0)
            cost_trend = cost_analysis.get("cost_trend", "stable")
            summary_parts.append(f"Total Cost: {total_cost:.2f} ({cost_trend})")

        return " | ".join(summary_parts) if summary_parts else "No data available"

    def _is_cyclical_pattern(self, values: list[float]) -> bool:
        """Check if values follow a cyclical pattern."""

        if len(values) < 6:
            return False

        # Simple autocorrelation check
        def autocorrelation(values, lag):
            if len(values) <= lag:
                return 0

            n = len(values) - lag
            mean = statistics.mean(values)

            numerator = sum((values[i] - mean) * (values[i + lag] - mean) for i in range(n))
            denominator = sum((values[i] - mean) ** 2 for i in range(len(values)))

            return numerator / denominator if denominator > 0 else 0

        # Check for significant autocorrelation at different lags
        for lag in range(1, min(len(values) // 2, 5)):
            if abs(autocorrelation(values, lag)) > 0.7:
                return True

        return False

    def _detect_cycle_length(self, values: list[float]) -> int:
        """Detect cycle length in cyclical pattern."""

        if len(values) < 6:
            return 0

        # Find the lag with maximum autocorrelation
        max_correlation = 0
        best_lag = 0

        for lag in range(1, min(len(values) // 2, 10)):
            correlation = abs(self._autocorrelation(values, lag))
            if correlation > max_correlation:
                max_correlation = correlation
                best_lag = lag

        return best_lag

    def _autocorrelation(self, values: list[float], lag: int) -> float:
        """Calculate autocorrelation at given lag."""

        if len(values) <= lag:
            return 0

        n = len(values) - lag
        mean = statistics.mean(values)

        numerator = sum((values[i] - mean) * (values[i + lag] - mean) for i in range(n))
        denominator = sum((values[i] - mean) ** 2 for i in range(len(values)))

        return numerator / denominator if denominator > 0 else 0

    def _is_trending_pattern(self, values: list[float]) -> bool:
        """Check if values show a clear trend."""

        if len(values) < 3:
            return False

        # Calculate trend slope
        slope = self._calculate_trend_slope(values)

        # Check if trend is significant
        return abs(slope) > 0.1

    def _calculate_trend_slope(self, values: list[float]) -> float:
        """Calculate trend slope using linear regression."""

        if len(values) < 2:
            return 0

        x = np.arange(len(values))
        y = np.array(values)

        x_mean = np.mean(x)
        y_mean = np.mean(y)

        numerator = np.sum((x - x_mean) * (y - y_mean))
        denominator = np.sum((x - x_mean) ** 2)

        return numerator / denominator if denominator > 0 else 0

    async def _continuous_analytics(self) -> None:
        """Background task for continuous analytics processing."""

        while True:
            try:
                # Process behavioral analytics
                await self.analyze_behavioral_patterns()

                # Process performance analytics
                await self.analyze_performance_metrics()

                # Sleep for 5 minutes
                await asyncio.sleep(300)

            except Exception as e:
                logger.error(f"Error in continuous analytics: {e}")
                await asyncio.sleep(60)

    async def _periodic_predictions(self) -> None:
        """Background task for periodic predictions."""

        while True:
            try:
                # Generate predictions for key metrics
                key_metrics = ["response_time", "error_rate", "throughput", "cost"]

                for metric in key_metrics:
                    if metric in self.time_series_data and len(self.time_series_data[metric]) >= 10:
                        await self.generate_predictions("value_prediction", metric)

                # Sleep for 1 hour
                await asyncio.sleep(3600)

            except Exception as e:
                logger.error(f"Error in periodic predictions: {e}")
                await asyncio.sleep(300)

    async def _continuous_anomaly_detection(self) -> None:
        """Background task for continuous anomaly detection."""

        while True:
            try:
                # Detect anomalies in all metrics
                await self.detect_anomalies()

                # Sleep for 10 minutes
                await asyncio.sleep(600)

            except Exception as e:
                logger.error(f"Error in continuous anomaly detection: {e}")
                await asyncio.sleep(120)

    async def get_analytics_dashboard(self) -> dict[str, Any]:
        """Get comprehensive analytics dashboard data."""

        # Get recent insights
        recent_insights = [insight for insight in self.insights.values()
                         if insight.created_at > datetime.now() - timedelta(hours=24)]

        # Get active predictions
        active_predictions = [pred for pred in self.predictions.values()
                           if pred.created_at > datetime.now() - timedelta(hours=24)]

        # Get unresolved anomalies
        active_anomalies = [anomaly for anomaly in self.anomalies.values()
                           if not anomaly.resolved]

        # Get metrics summary
        metrics_summary = {}
        for metric_type, metrics_list in self.metrics.items():
            if metrics_list:
                recent_metrics = [m for m in metrics_list
                                if m.timestamp > datetime.now() - timedelta(hours=24)]
                metrics_summary[metric_type] = {
                    "total": len(recent_metrics),
                    "latest": recent_metrics[-1].value if recent_metrics else None
                }

        return {
            "dashboard_id": str(uuid.uuid4()),
            "generated_at": datetime.now().isoformat(),
            "insights": {
                "total": len(recent_insights),
                "high_impact": len([i for i in recent_insights if i.impact_score > 0.7]),
                "recent": recent_insights[:10]
            },
            "predictions": {
                "total": len(active_predictions),
                "high_confidence": len([p for p in active_predictions if p.confidence_score > 0.8]),
                "recent": active_predictions[:10]
            },
            "anomalies": {
                "total": len(active_anomalies),
                "critical": len([a for a in active_anomalies if a.severity == AlertSeverity.CRITICAL]),
                "recent": active_anomalies[:10]
            },
            "metrics": metrics_summary,
            "summary": {
                "total_insights": len(self.insights),
                "total_predictions": len(self.predictions),
                "total_anomalies": len(self.anomalies),
                "active_analyses": len(self.analytics_configs)
            }
        }

    async def shutdown(self) -> None:
        """Shutdown the advanced analytics engine."""

        # Cancel background tasks
        if self._analytics_task:
            self._analytics_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._analytics_task

        if self._prediction_task:
            self._prediction_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._prediction_task

        if self._anomaly_task:
            self._anomaly_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._anomaly_task

        logger.info("Advanced analytics engine shutdown completed")