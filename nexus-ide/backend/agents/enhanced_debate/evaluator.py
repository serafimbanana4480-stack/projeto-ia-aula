"""Decision Quality Evaluator for Enhanced Agent Parliament.

Evaluates the quality of decisions made by the agent parliament
to enable learning and improvement over time.
"""
from __future__ import annotations

import logging
import time
import yaml
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .voting_system import Vote, DecisionType
from .logical_judge import JudgeReasoning

logger = logging.getLogger(__name__)


class EvaluationMetric(str, Enum):
    """Types of evaluation metrics."""
    SUCCESS_RATE = "success_rate"
    TIME_EFFICIENCY = "time_efficiency"
    QUALITY_SCORE = "quality_score"
    RESOURCE_EFFICIENCY = "resource_efficiency"
    STAKEHOLDER_SATISFACTION = "stakeholder_satisfaction"


@dataclass
class TaskResult:
    """Result of a task that followed a decision."""
    task_id: str
    decision_id: str
    success: bool
    completion_time: float
    expected_time: float
    quality_metrics: Dict[str, float]
    resource_usage: Dict[str, float]
    stakeholder_feedback: Optional[float] = None
    error_message: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "decision_id": self.decision_id,
            "success": self.success,
            "completion_time": self.completion_time,
            "expected_time": self.expected_time,
            "quality_metrics": self.quality_metrics,
            "resource_usage": self.resource_usage,
            "stakeholder_feedback": self.stakeholder_feedback,
            "error_message": self.error_message,
            "timestamp": self.timestamp,
        }


@dataclass
class DecisionScore:
    """Score for a decision's quality."""
    decision_id: str
    overall_score: float  # 0.0-1.0
    success_rate: float
    time_efficiency: float
    quality_score: float
    resource_efficiency: float
    stakeholder_satisfaction: float
    metric_weights: Dict[str, float]
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "overall_score": self.overall_score,
            "success_rate": self.success_rate,
            "time_efficiency": self.time_efficiency,
            "quality_score": self.quality_score,
            "resource_efficiency": self.resource_efficiency,
            "stakeholder_satisfaction": self.stakeholder_satisfaction,
            "metric_weights": self.metric_weights,
            "timestamp": self.timestamp,
        }


class DecisionEvaluator:
    """Evaluates the quality of decisions made by the agent parliament.
    
    Evaluates decisions based on:
    - Success rate (task completed successfully)
    - Time efficiency (completed within expected time)
    - Quality score (output quality metrics)
    - Resource efficiency (resource usage)
    - Stakeholder satisfaction (feedback if available)
    
    Uses weighted scoring to produce an overall quality score.
    """
    
    def __init__(
        self,
        metric_weights: Optional[Dict[str, float]] = None,
        resource_efficiency_threshold: float = 0.6,
        config_path: Optional[str] = None
    ):
        """Initialize decision evaluator.
        
        Args:
            metric_weights: Weights for each metric (default: balanced)
            resource_efficiency_threshold: Minimum acceptable resource efficiency (0.0-1.0)
            config_path: Path to YAML config with evaluation settings
        
        Raises:
            ValueError: If resource_efficiency_threshold is not between 0.0 and 1.0
        """
        # Validate resource_efficiency_threshold
        if not 0.0 <= resource_efficiency_threshold <= 1.0:
            raise ValueError(
                f"resource_efficiency_threshold must be between 0.0 and 1.0, got {resource_efficiency_threshold}"
            )
        
        self.resource_efficiency_threshold = resource_efficiency_threshold
        
        # Load config if provided
        if config_path:
            self._load_config(config_path)
        
        # Default metric weights
        self.metric_weights = metric_weights or {
            EvaluationMetric.SUCCESS_RATE.value: 0.4,
            EvaluationMetric.TIME_EFFICIENCY.value: 0.2,
            EvaluationMetric.QUALITY_SCORE.value: 0.3,
            EvaluationMetric.RESOURCE_EFFICIENCY.value: 0.1,
            EvaluationMetric.STAKEHOLDER_SATISFACTION.value: 0.0,
        }
        
        # Normalize weights
        total_weight = sum(self.metric_weights.values())
        if total_weight > 0:
            self.metric_weights = {
                k: v / total_weight
                for k, v in self.metric_weights.items()
            }
        
        logger.info(
            f"DecisionEvaluator initialized with weights: {self.metric_weights}, "
            f"resource_efficiency_threshold: {self.resource_efficiency_threshold}"
        )
    
    def _load_config(self, config_path: str) -> None:
        """Load evaluation settings from YAML config file."""
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            if 'resource_efficiency_threshold' in config:
                threshold = config['resource_efficiency_threshold']
                if not 0.0 <= threshold <= 1.0:
                    logger.warning(
                        f"Invalid resource_efficiency_threshold {threshold}, must be 0.0-1.0, using default"
                    )
                else:
                    self.resource_efficiency_threshold = threshold
            
            if 'metric_weights' in config:
                weights = config['metric_weights']
                if isinstance(weights, dict):
                    # Update metric weights
                    for metric, weight in weights.items():
                        if metric in [m.value for m in EvaluationMetric]:
                            if not isinstance(weight, (int, float)) or weight < 0:
                                logger.warning(
                                    f"Invalid weight {weight} for metric {metric}, skipping"
                                )
                                continue
                            self.metric_weights[metric] = weight
                    
                    # Normalize weights
                    total_weight = sum(self.metric_weights.values())
                    if total_weight > 0:
                        self.metric_weights = {
                            k: v / total_weight
                            for k, v in self.metric_weights.items()
                        }
            
            logger.info(f"Loaded evaluation config from {config_path}")
        except Exception as e:
            logger.warning(f"Failed to load evaluation config from {config_path}: {e}")
    
    async def evaluate_decision(
        self,
        decision_id: str,
        task_result: TaskResult
    ) -> DecisionScore:
        """Evaluate the quality of a decision based on task result.
        
        Args:
            decision_id: ID of the decision being evaluated
            task_result: Result of the task that followed the decision
            
        Returns:
            DecisionScore with quality metrics
        """
        # Calculate individual metric scores
        success_rate = self._calculate_success_rate(task_result)
        time_efficiency = self._calculate_time_efficiency(task_result)
        quality_score = self._calculate_quality_score(task_result)
        resource_efficiency = self._calculate_resource_efficiency(task_result)
        stakeholder_satisfaction = self._calculate_stakeholder_satisfaction(
            task_result
        )
        
        # Calculate overall weighted score
        overall_score = (
            success_rate * self.metric_weights[EvaluationMetric.SUCCESS_RATE.value] +
            time_efficiency * self.metric_weights[EvaluationMetric.TIME_EFFICIENCY.value] +
            quality_score * self.metric_weights[EvaluationMetric.QUALITY_SCORE.value] +
            resource_efficiency * self.metric_weights[EvaluationMetric.RESOURCE_EFFICIENCY.value] +
            stakeholder_satisfaction * self.metric_weights[EvaluationMetric.STAKEHOLDER_SATISFACTION.value]
        )
        
        score = DecisionScore(
            decision_id=decision_id,
            overall_score=overall_score,
            success_rate=success_rate,
            time_efficiency=time_efficiency,
            quality_score=quality_score,
            resource_efficiency=resource_efficiency,
            stakeholder_satisfaction=stakeholder_satisfaction,
            metric_weights=self.metric_weights.copy(),
        )
        
        logger.info(
            f"Evaluated decision {decision_id}: "
            f"overall_score={overall_score:.2f}, "
            f"success={success_rate:.2f}"
        )
        
        return score
    
    def _calculate_success_rate(self, task_result: TaskResult) -> float:
        """Calculate success rate metric.
        
        Returns 1.0 if successful, 0.0 if failed.
        """
        return 1.0 if task_result.success else 0.0
    
    def _calculate_time_efficiency(self, task_result: TaskResult) -> float:
        """Calculate time efficiency metric.
        
        Returns 1.0 if completed in expected time,
        decreases linearly as time exceeds expectation.
        """
        if task_result.expected_time <= 0 or task_result.completion_time <= 0:
            return 1.0  # No valid data, assume efficient
        
        ratio = task_result.expected_time / task_result.completion_time
        
        if ratio >= 1.0:
            # Completed faster or on time
            return min(1.0, ratio)  # Cap at 1.0
        else:
            # Took longer than expected
            # Linear decrease: 2x time = 0.5 score, 3x time = 0.33 score, etc.
            return max(0.0, ratio)
    
    def _calculate_quality_score(self, task_result: TaskResult) -> float:
        """Calculate quality score metric.
        
        Average of all quality metrics (0.0-1.0).
        """
        if not task_result.quality_metrics:
            return 0.5  # Neutral if no metrics
        
        values = list(task_result.quality_metrics.values())
        
        # Ensure all values are in [0, 1] range
        normalized = [max(0.0, min(1.0, v)) for v in values]
        
        return sum(normalized) / len(normalized)
    
    def _calculate_resource_efficiency(self, task_result: TaskResult) -> float:
        """Calculate resource efficiency metric.
        
        Based on resource usage. Lower usage = higher score.
        """
        if not task_result.resource_usage:
            return 1.0  # No resource data, assume efficient
        
        # Simple heuristic: if any resource usage is very high, reduce score
        # This is a placeholder - real implementation would need baselines
        max_usage = max(task_result.resource_usage.values())
        
        if max_usage > 1000:  # Arbitrary threshold
            return 0.5
        elif max_usage > 500:
            return 0.75
        else:
            return 1.0
    
    def _calculate_stakeholder_satisfaction(
        self,
        task_result: TaskResult
    ) -> float:
        """Calculate stakeholder satisfaction metric.
        
        Uses stakeholder feedback if available (0.0-1.0).
        """
        if task_result.stakeholder_feedback is None:
            # If no feedback, use success as proxy
            return self._calculate_success_rate(task_result)
        
        # Feedback should be in [0, 1] range
        return max(0.0, min(1.0, task_result.stakeholder_feedback))
    
    async def calculate_success_metrics(
        self,
        task_result: TaskResult
    ) -> Dict[str, float]:
        """Calculate success metrics for a task result.
        
        Args:
            task_result: Task result to analyze
            
        Returns:
            Dictionary of metric names to values
        """
        return {
            EvaluationMetric.SUCCESS_RATE.value: self._calculate_success_rate(
                task_result
            ),
            EvaluationMetric.TIME_EFFICIENCY.value: self._calculate_time_efficiency(
                task_result
            ),
            EvaluationMetric.QUALITY_SCORE.value: self._calculate_quality_score(
                task_result
            ),
            EvaluationMetric.RESOURCE_EFFICIENCY.value: self._calculate_resource_efficiency(
                task_result
            ),
            EvaluationMetric.STAKEHOLDER_SATISFACTION.value: self._calculate_stakeholder_satisfaction(
                task_result
            ),
        }
    
    def update_metric_weights(
        self,
        new_weights: Dict[str, float]
    ) -> None:
        """Update metric weights.
        
        Args:
            new_weights: New weights for metrics
        """
        # Validate weights
        for metric in new_weights:
            if metric not in [m.value for m in EvaluationMetric]:
                logger.warning(f"Unknown metric: {metric}")
        
        # Update weights
        for metric, weight in new_weights.items():
            self.metric_weights[metric] = weight
        
        # Normalize
        total_weight = sum(self.metric_weights.values())
        if total_weight > 0:
            self.metric_weights = {
                k: v / total_weight
                for k, v in self.metric_weights.items()
            }
        
        logger.info(f"Updated metric weights: {self.metric_weights}")
    
    def get_metric_weights(self) -> Dict[str, float]:
        """Get current metric weights.
        
        Returns:
            Dictionary of metric names to weights
        """
        return self.metric_weights.copy()
    
    def meets_resource_efficiency_threshold(self, decision_score: DecisionScore) -> bool:
        """Check if a decision meets the resource efficiency threshold.
        
        Args:
            decision_score: Decision score to check
            
        Returns:
            True if resource efficiency meets or exceeds threshold
        """
        return decision_score.resource_efficiency >= self.resource_efficiency_threshold
    
    async def batch_evaluate(
        self,
        results: List[tuple[str, TaskResult]]
    ) -> List[DecisionScore]:
        """Evaluate multiple decisions in batch.
        
        Args:
            results: List of (decision_id, task_result) tuples
            
        Returns:
            List of DecisionScore objects
        """
        scores = []
        
        for decision_id, task_result in results:
            score = await self.evaluate_decision(decision_id, task_result)
            scores.append(score)
        
        logger.info(f"Batch evaluated {len(scores)} decisions")
        
        return scores
    
    async def get_evaluation_summary(
        self,
        scores: List[DecisionScore]
    ) -> Dict[str, Any]:
        """Get summary statistics for a set of evaluations.
        
        Args:
            scores: List of DecisionScore objects
            
        Returns:
            Summary statistics
        """
        if not scores:
            return {
                "count": 0,
                "average_overall_score": 0.0,
                "average_success_rate": 0.0,
                "min_overall_score": 0.0,
                "max_overall_score": 0.0,
            }
        
        overall_scores = [s.overall_score for s in scores]
        success_rates = [s.success_rate for s in scores]
        
        return {
            "count": len(scores),
            "average_overall_score": sum(overall_scores) / len(overall_scores),
            "average_success_rate": sum(success_rates) / len(success_rates),
            "min_overall_score": min(overall_scores),
            "max_overall_score": max(overall_scores),
            "metric_weights": scores[0].metric_weights if scores else {},
        }
