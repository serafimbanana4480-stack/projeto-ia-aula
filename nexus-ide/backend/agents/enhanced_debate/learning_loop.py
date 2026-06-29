"""Learning Loop for Enhanced Agent Parliament.

Analyzes decision outcomes and adjusts agent weights dynamically
to improve decision quality over time through continuous learning.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import statistics

from .voting_system import Vote, DecisionType, WeightedVotingSystem
from .evaluator import DecisionScore, TaskResult
from .cache import Cache
from .metrics import MetricsCollector, get_global_metrics_collector

logger = logging.getLogger(__name__)


class LearningStrategy(str, Enum):
    """Strategies for learning from outcomes."""
    REINFORCEMENT = "reinforcement"  # Reinforce good decisions
    DECAY = "decay"  # Decay weights for bad decisions
    BANDIT = "bandit"  # Multi-armed bandit approach
    HYBRID = "hybrid"  # Combination of strategies


@dataclass
class DecisionPattern:
    """Pattern identified from decision outcomes."""
    agent_id: str
    decision_type: DecisionType
    success_rate: float
    avg_score: float
    total_decisions: int
    successful_decisions: int
    last_updated: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "decision_type": self.decision_type.value,
            "success_rate": self.success_rate,
            "avg_score": self.avg_score,
            "total_decisions": self.total_decisions,
            "successful_decisions": self.successful_decisions,
            "last_updated": self.last_updated,
        }


@dataclass
class AgentSpecialization:
    """Detected specialization of an agent."""
    agent_id: str
    best_decision_type: DecisionType
    best_success_rate: float
    best_avg_score: float
    confidence: float  # 0.0-1.0
    sample_size: int
    last_updated: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "best_decision_type": self.best_decision_type.value,
            "best_success_rate": self.best_success_rate,
            "best_avg_score": self.best_avg_score,
            "confidence": self.confidence,
            "sample_size": self.sample_size,
            "last_updated": self.last_updated,
        }


@dataclass
class LearningResult:
    """Result of a learning cycle."""
    patterns_updated: int
    weights_adjusted: int
    specializations_detected: int
    total_decisions_analyzed: int
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "patterns_updated": self.patterns_updated,
            "weights_adjusted": self.weights_adjusted,
            "specializations_detected": self.specializations_detected,
            "total_decisions_analyzed": self.total_decisions_analyzed,
            "timestamp": self.timestamp,
        }


class LearningLoop:
    """Learning loop for continuous improvement of agent weights.
    
    Analyzes decision outcomes to:
    - Identify patterns of success
    - Adjust agent weights based on performance
    - Detect agent specializations
    - Apply learning strategies
    - Prevent weight oscillation
    """
    
    def __init__(
        self,
        voting_system: WeightedVotingSystem,
        strategy: LearningStrategy = LearningStrategy.HYBRID,
        min_sample_size: int = 5,
        confidence_threshold: float = 0.7,
        learning_rate: float = 0.1,
        decay_rate: float = 0.05,
        stabilization_threshold: float = 0.01
    ):
        """Initialize learning loop.
        
        Args:
            voting_system: Weighted voting system to adjust
            strategy: Learning strategy to use
            min_sample_size: Minimum decisions before adjusting weights
            confidence_threshold: Minimum confidence for adjustments
            learning_rate: How aggressively to adjust weights (0.0-1.0)
            decay_rate: Rate to decay weights for poor performance (0.0-1.0)
            stabilization_threshold: Minimum change to apply adjustment
        """
        self.voting_system = voting_system
        self.strategy = strategy
        
        # Learning parameters
        self.min_sample_size = min_sample_size
        self.confidence_threshold = confidence_threshold
        self.learning_rate = learning_rate
        self.decay_rate = decay_rate
        self.stabilization_threshold = stabilization_threshold
        
        # Pattern tracking
        self.decision_patterns: Dict[Tuple[str, DecisionType], DecisionPattern] = {}
        self.agent_specializations: Dict[str, AgentSpecialization] = {}
        
        # Cache for pattern analysis results
        self.cache = Cache(default_ttl=300.0, max_size=50)  # 5 minutes, 50 entries
        
        # Metrics collector
        self.metrics_collector = get_global_metrics_collector()
        self.metrics_collector.register_component("learning_loop")
        
        # History for trend analysis
        self.weight_history: Dict[Tuple[str, DecisionType], List[float]] = defaultdict(list)
        self.max_history_length = 10
        
        logger.info(
            f"LearningLoop initialized with strategy={self.strategy}, "
            f"min_sample_size={self.min_sample_size}"
        )
    
    async def learn_from_outcomes(
        self,
        outcomes: List[Tuple[str, DecisionScore, TaskResult]]
    ) -> LearningResult:
        """Learn from a batch of decision outcomes.
        
        Args:
            outcomes: List of (agent_id, decision_score, task_result) tuples
            
        Returns:
            LearningResult with statistics
        """
        logger.info(f"Learning from {len(outcomes)} decision outcomes")
        
        patterns_updated = 0
        weights_adjusted = 0
        specializations_detected = 0
        
        # Update patterns for each outcome
        for agent_id, decision_score, task_result in outcomes:
            # Determine decision type from task result or use default
            decision_type = self._extract_decision_type(task_result)
            
            # Update pattern
            pattern = self._update_pattern(
                agent_id,
                decision_type,
                decision_score,
                task_result
            )
            patterns_updated += 1
        
        # Detect specializations
        specializations_detected = self._detect_specializations()
        
        # Apply learning strategy
        weights_adjusted = await self._apply_learning_strategy()
        
        result = LearningResult(
            patterns_updated=patterns_updated,
            weights_adjusted=weights_adjusted,
            specializations_detected=specializations_detected,
            total_decisions_analyzed=len(outcomes)
        )
        
        logger.info(
            f"Learning complete: {result.patterns_updated} patterns, "
            f"{result.weights_adjusted} weights adjusted, "
            f"{result.specializations_detected} specializations detected"
        )
        
        return result
    
    def _extract_decision_type(self, task_result: TaskResult) -> DecisionType:
        """Extract decision type from task result."""
        # If task result has decision_type metadata, use it
        if hasattr(task_result, 'decision_type'):
            try:
                return DecisionType(task_result.decision_type.lower())
            except (ValueError, AttributeError):
                pass
        
        # Otherwise use default
        return DecisionType.DEFAULT
    
    def _update_pattern(
        self,
        agent_id: str,
        decision_type: DecisionType,
        decision_score: DecisionScore,
        task_result: TaskResult
    ) -> DecisionPattern:
        """Update pattern tracking for an agent/decision type combination."""
        key = (agent_id, decision_type)
        
        if key not in self.decision_patterns:
            pattern = DecisionPattern(
                agent_id=agent_id,
                decision_type=decision_type,
                success_rate=0.0,
                avg_score=0.0,
                total_decisions=0,
                successful_decisions=0
            )
            self.decision_patterns[key] = pattern
        else:
            pattern = self.decision_patterns[key]
        
        # Update statistics
        pattern.total_decisions += 1
        if task_result.success:
            pattern.successful_decisions += 1
        
        # Calculate running average
        pattern.success_rate = pattern.successful_decisions / pattern.total_decisions
        pattern.avg_score = (
            (pattern.avg_score * (pattern.total_decisions - 1) + decision_score.overall_score)
            / pattern.total_decisions
        )
        pattern.last_updated = time.time()
        
        logger.debug(
            f"Updated pattern for {agent_id}/{decision_type}: "
            f"success_rate={pattern.success_rate:.2f}, avg_score={pattern.avg_score:.2f}"
        )
        
        return pattern
    
    def _detect_specializations(self) -> int:
        """Detect agent specializations based on patterns with caching."""
        # Generate cache key based on current patterns
        pattern_keys = sorted(self.decision_patterns.keys())
        cache_key = self.cache._generate_key("specializations", pattern_keys, self.min_sample_size, self.confidence_threshold)
        
        # Check cache
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug("Specializations retrieved from cache")
            # Restore cached specializations
            for agent_id, spec_data in cached_result.items():
                self.agent_specializations[agent_id] = AgentSpecialization(**spec_data)
            return len(cached_result)
        
        detected = 0
        
        # Group patterns by agent
        agent_patterns: Dict[str, List[DecisionPattern]] = defaultdict(list)
        for key, pattern in self.decision_patterns.items():
            agent_id, _ = key
            if pattern.total_decisions >= self.min_sample_size:
                agent_patterns[agent_id].append(pattern)
        
        # Find best decision type for each agent
        for agent_id, patterns in agent_patterns.items():
            if len(patterns) < 2:  # Need at least 2 decision types to detect specialization
                continue
            
            # Find pattern with highest success rate
            best_pattern = max(patterns, key=lambda p: p.success_rate)
            
            # Calculate confidence based on sample size
            confidence = min(1.0, best_pattern.total_decisions / (self.min_sample_size * 2))
            
            if confidence >= self.confidence_threshold:
                specialization = AgentSpecialization(
                    agent_id=agent_id,
                    best_decision_type=best_pattern.decision_type,
                    best_success_rate=best_pattern.success_rate,
                    best_avg_score=best_pattern.avg_score,
                    confidence=confidence,
                    sample_size=best_pattern.total_decisions
                )
                
                self.agent_specializations[agent_id] = specialization
                detected += 1
                
                logger.info(
                    f"Detected specialization: {agent_id} best at "
                    f"{best_pattern.decision_type} (success_rate={best_pattern.success_rate:.2f})"
                )
        
        # Cache result
        cache_data = {
            agent_id: spec.to_dict()
            for agent_id, spec in self.agent_specializations.items()
        }
        self.cache.set(cache_key, cache_data, ttl=300.0)  # 5 minutes
        
        return detected
    
    async def _apply_learning_strategy(self) -> int:
        """Apply learning strategy to adjust weights."""
        weights_adjusted = 0
        
        if self.strategy == LearningStrategy.REINFORCEMENT:
            weights_adjusted = await self._apply_reinforcement()
        elif self.strategy == LearningStrategy.DECAY:
            weights_adjusted = await self._apply_decay()
        elif self.strategy == LearningStrategy.BANDIT:
            weights_adjusted = await self._apply_bandit()
        elif self.strategy == LearningStrategy.HYBRID:
            weights_adjusted = await self._apply_hybrid()
        
        return weights_adjusted
    
    async def _apply_reinforcement(self) -> int:
        """Apply reinforcement learning strategy."""
        adjusted = 0
        
        for key, pattern in self.decision_patterns.items():
            agent_id, decision_type = key
            
            # Skip if not enough data
            if pattern.total_decisions < self.min_sample_size:
                continue
            
            current_weight = self.voting_system.get_agent_weight(agent_id, decision_type)
            
            # Calculate adjustment based on success rate
            if pattern.success_rate > 0.7:
                # Reinforce good performance
                adjustment = self.learning_rate * (pattern.success_rate - 0.5)
                new_weight = current_weight * (1.0 + adjustment)
            elif pattern.success_rate < 0.3:
                # No reinforcement for poor performance
                continue
            else:
                # Neutral performance, small adjustment toward baseline
                adjustment = self.learning_rate * 0.1 * (0.5 - pattern.success_rate)
                new_weight = current_weight * (1.0 - adjustment)
            
            # Apply adjustment if significant
            if abs(new_weight - current_weight) >= self.stabilization_threshold:
                self.voting_system.agent_weights[agent_id][decision_type] = new_weight
                self._record_weight_history(agent_id, decision_type, new_weight)
                adjusted += 1
                
                logger.debug(
                    f"Reinforcement: {agent_id}/{decision_type} "
                    f"{current_weight:.2f} -> {new_weight:.2f}"
                )
        
        return adjusted
    
    async def _apply_decay(self) -> int:
        """Apply decay strategy for poor performance."""
        adjusted = 0
        
        for key, pattern in self.decision_patterns.items():
            agent_id, decision_type = key
            
            # Skip if not enough data
            if pattern.total_decisions < self.min_sample_size:
                continue
            
            current_weight = self.voting_system.get_agent_weight(agent_id, decision_type)
            
            # Decay weight for poor performance
            if pattern.success_rate < 0.3:
                decay = self.decay_rate * (0.3 - pattern.success_rate)
                new_weight = current_weight * (1.0 - decay)
                
                # Apply adjustment if significant
                if abs(new_weight - current_weight) >= self.stabilization_threshold:
                    self.voting_system.agent_weights[agent_id][decision_type] = new_weight
                    self._record_weight_history(agent_id, decision_type, new_weight)
                    adjusted += 1
                    
                    logger.debug(
                        f"Decay: {agent_id}/{decision_type} "
                        f"{current_weight:.2f} -> {new_weight:.2f}"
                    )
        
        return adjusted
    
    async def _apply_bandit(self) -> int:
        """Apply multi-armed bandit strategy."""
        adjusted = 0
        
        # Group patterns by decision type
        decision_type_patterns: Dict[DecisionType, List[Tuple[str, DecisionPattern]]] = defaultdict(list)
        for key, pattern in self.decision_patterns.items():
            agent_id, decision_type = key
            if pattern.total_decisions >= self.min_sample_size:
                decision_type_patterns[decision_type].append((agent_id, pattern))
        
        # For each decision type, adjust weights based on relative performance
        for decision_type, patterns in decision_type_patterns.items():
            if len(patterns) < 2:
                continue
            
            # Calculate average success rate for this decision type
            avg_success_rate = statistics.mean([p.success_rate for _, p in patterns])
            
            # Adjust weights based on performance relative to average
            for agent_id, pattern in patterns:
                current_weight = self.voting_system.get_agent_weight(agent_id, decision_type)
                
                # Calculate adjustment
                relative_performance = pattern.success_rate - avg_success_rate
                adjustment = self.learning_rate * relative_performance
                new_weight = current_weight * (1.0 + adjustment)
                
                # Apply adjustment if significant
                if abs(new_weight - current_weight) >= self.stabilization_threshold:
                    self.voting_system.agent_weights[agent_id][decision_type] = new_weight
                    self._record_weight_history(agent_id, decision_type, new_weight)
                    adjusted += 1
                    
                    logger.debug(
                        f"Bandit: {agent_id}/{decision_type} "
                        f"{current_weight:.2f} -> {new_weight:.2f} "
                        f"(relative_performance={relative_performance:.2f})"
                    )
        
        return adjusted
    
    async def _apply_hybrid(self) -> int:
        """Apply hybrid strategy (combination of reinforcement and decay)."""
        adjusted = 0
        
        # Apply reinforcement first
        adjusted += await self._apply_reinforcement()
        
        # Then apply decay
        adjusted += await self._apply_decay()
        
        return adjusted
    
    def _record_weight_history(
        self,
        agent_id: str,
        decision_type: DecisionType,
        weight: float
    ) -> None:
        """Record weight change for trend analysis."""
        key = (agent_id, decision_type)
        
        self.weight_history[key].append(weight)
        
        # Limit history length
        if len(self.weight_history[key]) > self.max_history_length:
            self.weight_history[key].pop(0)
    
    def get_weight_trend(
        self,
        agent_id: str,
        decision_type: DecisionType
    ) -> Optional[str]:
        """Get trend for an agent's weight on a decision type.
        
        Returns:
            "increasing", "decreasing", "stable", or None if not enough data
        """
        key = (agent_id, decision_type)
        
        if key not in self.weight_history or len(self.weight_history[key]) < 3:
            return None
        
        history = self.weight_history[key]
        
        # Calculate trend using linear regression
        n = len(history)
        x = list(range(n))
        
        # Simple linear regression
        sum_x = sum(x)
        sum_y = sum(history)
        sum_xy = sum(xi * yi for xi, yi in zip(x, history))
        sum_x2 = sum(xi * xi for xi in x)
        
        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
        
        if slope > 0.01:
            return "increasing"
        elif slope < -0.01:
            return "decreasing"
        else:
            return "stable"
    
    def get_patterns(self) -> List[DecisionPattern]:
        """Get all current decision patterns."""
        return list(self.decision_patterns.values())
    
    def get_specializations(self) -> List[AgentSpecialization]:
        """Get all detected agent specializations."""
        return list(self.agent_specializations.values())
    
    def get_agent_specialization(self, agent_id: str) -> Optional[AgentSpecialization]:
        """Get specialization for a specific agent."""
        return self.agent_specializations.get(agent_id)
    
    async def reset_agent_weight(
        self,
        agent_id: str,
        decision_type: DecisionType
    ) -> None:
        """Reset an agent's weight to default.
        
        Args:
            agent_id: ID of the agent
            decision_type: Decision type to reset
        """
        default_weight = 1.0
        self.voting_system.agent_weights[agent_id][decision_type] = default_weight
        
        # Clear pattern for this agent/decision type
        key = (agent_id, decision_type)
        if key in self.decision_patterns:
            del self.decision_patterns[key]
        
        # Clear weight history
        if key in self.weight_history:
            del self.weight_history[key]
        
        logger.info(f"Reset weight for {agent_id}/{decision_type} to {default_weight}")
    
    def get_learning_statistics(self) -> Dict[str, Any]:
        """Get statistics about learning progress.
        
        Returns:
            Dictionary with learning statistics
        """
        total_patterns = len(self.decision_patterns)
        total_specializations = len(self.agent_specializations)
        
        # Calculate average success rate
        if total_patterns > 0:
            avg_success_rate = statistics.mean(
                [p.success_rate for p in self.decision_patterns.values()]
            )
        else:
            avg_success_rate = 0.0
        
        # Calculate average sample size
        if total_patterns > 0:
            avg_sample_size = statistics.mean(
                [p.total_decisions for p in self.decision_patterns.values()]
            )
        else:
            avg_sample_size = 0.0
        
        return {
            "total_patterns": total_patterns,
            "total_specializations": total_specializations,
            "average_success_rate": avg_success_rate,
            "average_sample_size": avg_sample_size,
            "strategy": self.strategy.value,
            "min_sample_size": self.min_sample_size,
            "learning_rate": self.learning_rate,
        }
    
    def collect_metrics(self) -> None:
        """Collect metrics from learning loop."""
        # Collect learning loop specific metrics
        self.metrics_collector.collect_learning_loop_metrics("learning_loop", self)
        
        # Collect cache metrics
        self.metrics_collector.collect_cache_metrics("learning_loop", self.cache)
        
        # Collect voting system metrics
        self.metrics_collector.collect_voting_system_metrics(
            "learning_loop", self.voting_system
        )
