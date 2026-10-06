"""Weighted Voting System for Enhanced Agent Parliament.

Implements weighted voting where agents have different weights based on
their specialization and the type of decision being made.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class DecisionType(str, Enum):
    """Types of decisions that can be voted on."""
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    RESEARCH = "research"
    ANALYSIS = "analysis"
    OPTIMIZATION = "optimization"
    DEFAULT = "default"


@dataclass
class Vote:
    """Individual vote from an agent."""
    agent_id: str
    value: int  # 0-10 scale
    reasoning: str = ""
    timestamp: float = field(default_factory=time.time)
    
    def __post_init__(self):
        """Validate vote value after initialization."""
        if not isinstance(self.value, int):
            raise TypeError(f"Vote value must be int, got {type(self.value)}")
        if not 0 <= self.value <= 10:
            raise ValueError(f"Vote value must be 0-10, got {self.value}")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "value": self.value,
            "reasoning": self.reasoning,
            "timestamp": self.timestamp,
        }


@dataclass
class VoteResult:
    """Result of weighted voting."""
    weighted_sum: float
    total_weight: float
    weighted_average: float
    consensus_reached: bool
    winning_option: str
    vote_breakdown: dict[str, float]  # agent_id -> weighted_vote
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "weighted_sum": self.weighted_sum,
            "total_weight": self.total_weight,
            "weighted_average": self.weighted_average,
            "consensus_reached": self.consensus_reached,
            "winning_option": self.winning_option,
            "vote_breakdown": self.vote_breakdown,
            "timestamp": self.timestamp,
        }


class WeightedVotingSystem:
    """Implements weighted voting for agent decisions.
    
    Each agent has different weights based on their specialization.
    For example, ARCHITECT has weight 2.0 for architecture decisions
    but weight 0.8 for research decisions.
    """
    
    def __init__(
        self,
        weights_config_path: str | None = None,
        consensus_threshold: float = 0.7,
        consensus_std_dev_threshold: float = 0.3
    ):
        """Initialize weighted voting system.
        
        Args:
            weights_config_path: Path to YAML config with agent weights
            consensus_threshold: Threshold for consensus (0.0-1.0)
            consensus_std_dev_threshold: Standard deviation threshold for consensus (0.0-1.0)
        
        Raises:
            ValueError: If consensus_threshold or consensus_std_dev_threshold is not between 0.0 and 1.0
        """
        # Validate consensus_threshold
        if not 0.0 <= consensus_threshold <= 1.0:
            raise ValueError(
                f"consensus_threshold must be between 0.0 and 1.0, got {consensus_threshold}"
            )
        
        # Validate consensus_std_dev_threshold
        if not 0.0 <= consensus_std_dev_threshold <= 1.0:
            raise ValueError(
                f"consensus_std_dev_threshold must be between 0.0 and 1.0, got {consensus_std_dev_threshold}"
            )
        
        self.consensus_threshold = consensus_threshold
        self.consensus_std_dev_threshold = consensus_std_dev_threshold
        
        # Default weights
        self.agent_weights = {
            "ARCHITECT": {
                DecisionType.ARCHITECTURE: 2.0,
                DecisionType.IMPLEMENTATION: 1.2,
                DecisionType.RESEARCH: 0.8,
                DecisionType.ANALYSIS: 1.0,
                DecisionType.OPTIMIZATION: 1.0,
                DecisionType.DEFAULT: 1.0,
            },
            "RESEARCHER": {
                DecisionType.RESEARCH: 2.0,
                DecisionType.ARCHITECTURE: 1.2,
                DecisionType.IMPLEMENTATION: 0.8,
                DecisionType.ANALYSIS: 1.0,
                DecisionType.OPTIMIZATION: 0.8,
                DecisionType.DEFAULT: 1.0,
            },
            "CODER": {
                DecisionType.IMPLEMENTATION: 2.0,
                DecisionType.ARCHITECTURE: 1.0,
                DecisionType.RESEARCH: 0.8,
                DecisionType.ANALYSIS: 0.8,
                DecisionType.OPTIMIZATION: 1.2,
                DecisionType.DEFAULT: 1.0,
            },
            "ANALYZER": {
                DecisionType.ANALYSIS: 2.0,
                DecisionType.ARCHITECTURE: 1.0,
                DecisionType.IMPLEMENTATION: 0.8,
                DecisionType.RESEARCH: 1.0,
                DecisionType.OPTIMIZATION: 1.2,
                DecisionType.DEFAULT: 1.0,
            },
            "OPTIMIZER": {
                DecisionType.OPTIMIZATION: 2.0,
                DecisionType.IMPLEMENTATION: 1.2,
                DecisionType.ARCHITECTURE: 1.0,
                DecisionType.RESEARCH: 0.8,
                DecisionType.ANALYSIS: 1.0,
                DecisionType.DEFAULT: 1.0,
            },
        }
        
        # Load custom weights if provided
        if weights_config_path:
            self._load_weights_from_config(weights_config_path)
        
        # Weight adjustment parameters
        self.min_weight = 0.5
        self.max_weight = 3.0
        self.weight_adjustment_rate = 0.05
        
        logger.info(
            "WeightedVotingSystem initialized with threshold=%s",
            self.consensus_threshold
        )
    
    def _load_weights_from_config(self, config_path: str) -> None:
        """Load agent weights from YAML config file."""
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
            
            if 'agent_weights' in config:
                for agent_id, weights in config['agent_weights'].items():
                    if agent_id not in self.agent_weights:
                        self.agent_weights[agent_id] = {}
                    
                    for decision_type, weight in weights.items():
                        # Validate weight value
                        if not isinstance(weight, (int, float)) or weight <= 0:
                            logger.warning(
                                f"Invalid weight {weight} for {agent_id}/{decision_type}, "
                                f"must be positive number, skipping"
                            )
                            continue
                        
                        # Clamp weight to max_weight
                        clamped_weight = min(weight, self.max_weight)
                        if clamped_weight != weight:
                            logger.warning(
                                f"Weight {weight} for {agent_id}/{decision_type} "
                                f"exceeds max_weight {self.max_weight}, clamping"
                            )
                        
                        try:
                            dt = DecisionType(decision_type.upper())
                            self.agent_weights[agent_id][dt] = clamped_weight
                        except ValueError:
                            logger.warning(
                                f"Invalid decision type '{decision_type}' for agent {agent_id}, "
                                f"skipping (valid types: {[dt.value for dt in DecisionType]})"
                            )
            
            if 'consensus_threshold' in config:
                threshold = config['consensus_threshold']
                if not 0.0 <= threshold <= 1.0:
                    logger.warning(
                        f"Invalid consensus_threshold {threshold}, must be 0.0-1.0, using default"
                    )
                else:
                    self.consensus_threshold = threshold
            
            if 'consensus_std_dev_threshold' in config:
                std_dev_threshold = config['consensus_std_dev_threshold']
                if not 0.0 <= std_dev_threshold <= 1.0:
                    logger.warning(
                        f"Invalid consensus_std_dev_threshold {std_dev_threshold}, must be 0.0-1.0, using default"
                    )
                else:
                    self.consensus_std_dev_threshold = std_dev_threshold
            
            if 'min_weight' in config:
                min_w = config['min_weight']
                if not isinstance(min_w, (int, float)) or min_w <= 0:
                    logger.warning(f"Invalid min_weight {min_w}, must be positive, using default")
                else:
                    self.min_weight = min_w
            
            if 'max_weight' in config:
                max_w = config['max_weight']
                if not isinstance(max_w, (int, float)) or max_w <= 0:
                    logger.warning(f"Invalid max_weight {max_w}, must be positive, using default")
                else:
                    self.max_weight = max_w
            
            if 'weight_adjustment_rate' in config:
                rate = config['weight_adjustment_rate']
                if not isinstance(rate, (int, float)) or not 0.0 <= rate <= 1.0:
                    logger.warning(
                        f"Invalid weight_adjustment_rate {rate}, must be 0.0-1.0, using default"
                    )
                else:
                    self.weight_adjustment_rate = rate
            
            # Validate min/max relationship
            if self.min_weight >= self.max_weight:
                logger.warning(
                    f"min_weight ({self.min_weight}) >= max_weight ({self.max_weight}), "
                    f"resetting to defaults"
                )
                self.min_weight = 0.5
                self.max_weight = 3.0
            
            logger.info(f"Loaded weights from {config_path}")
        except Exception as e:
            logger.warning(f"Failed to load weights from {config_path}: {e}")
    
    def get_agent_weight(
        self,
        agent_id: str,
        decision_type: DecisionType = DecisionType.DEFAULT
    ) -> float:
        """Get the weight of an agent for a specific decision type.
        
        Args:
            agent_id: ID of the agent
            decision_type: Type of decision
            
        Returns:
            Weight of the agent (0.0-3.0)
        """
        if agent_id not in self.agent_weights:
            logger.warning(f"Unknown agent {agent_id}, using default weight 1.0")
            return 1.0
        
        weights = self.agent_weights[agent_id]
        
        # Try specific decision type, then default
        if decision_type in weights:
            return weights[decision_type]
        elif DecisionType.DEFAULT in weights:
            return weights[DecisionType.DEFAULT]
        else:
            return 1.0
    
    async def calculate_weighted_vote(
        self,
        votes: list[Vote],
        decision_type: DecisionType = DecisionType.DEFAULT,
        options: list[str] | None = None
    ) -> VoteResult:
        """Calculate weighted voting result.
        
        Args:
            votes: List of votes from agents
            decision_type: Type of decision
            options: List of options being voted on (if applicable)
            
        Returns:
            VoteResult with weighted average and consensus status
        """
        if not votes:
            raise ValueError("No votes provided")
        
        weighted_sum = 0.0
        total_weight = 0.0
        vote_breakdown = {}
        
        for vote in votes:
            weight = self.get_agent_weight(vote.agent_id, decision_type)
            weighted_vote = vote.value * weight
            
            weighted_sum += weighted_vote
            total_weight += weight
            vote_breakdown[vote.agent_id] = weighted_vote
            
            logger.debug(
                f"Vote from {vote.agent_id}: value={vote.value}, "
                f"weight={weight}, weighted={weighted_vote}"
            )
        
        if total_weight == 0:
            raise ValueError("Total weight is zero")
        
        weighted_average = weighted_sum / total_weight
        
        # Check consensus
        consensus_reached = self._check_consensus(votes, decision_type)
        
        # Determine winning option if options provided
        winning_option = ""
        if options:
            winning_option = self._determine_winning_option(
                votes, options, decision_type
            )
        
        result = VoteResult(
            weighted_sum=weighted_sum,
            total_weight=total_weight,
            weighted_average=weighted_average,
            consensus_reached=consensus_reached,
            winning_option=winning_option,
            vote_breakdown=vote_breakdown,
        )
        
        logger.info(
            f"Weighted vote result: avg={weighted_average:.2f}, "
            f"consensus={consensus_reached}"
        )
        
        return result
    
    def _check_consensus(
        self,
        votes: list[Vote],
        decision_type: DecisionType
    ) -> bool:
        """Check if consensus is reached.
        
        Consensus is reached if:
        1. Standard deviation of votes is below threshold
        2. Or weighted average is above threshold
        
        Args:
            votes: List of votes
            decision_type: Type of decision
            
        Returns:
            True if consensus reached
        """
        if len(votes) < 2:
            return True  # Single vote is consensus
        
        # Calculate standard deviation
        values = [v.value for v in votes]
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std_dev = variance ** 0.5
        
        # Normalize std_dev to 0-1 scale (votes are 0-10, so max std_dev is ~7.07)
        # Divide by 10 to get a reasonable 0-1 scale
        normalized_std_dev = std_dev / 10.0
        
        # Consensus if normalized std dev is low (votes are close together)
        if normalized_std_dev < self.consensus_std_dev_threshold:
            return True
        
        # Or if weighted average is high (strong agreement)
        return mean >= 8.0
    
    def _determine_winning_option(
        self,
        votes: list[Vote],
        options: list[str],
        decision_type: DecisionType
    ) -> str:
        """Determine winning option from multiple choice vote.
        
        Args:
            votes: List of votes (vote.value is index of option)
            options: List of option strings
            decision_type: Type of decision
            
        Returns:
            Winning option string
        """
        option_scores = {opt: 0.0 for opt in options}
        
        for vote in votes:
            if 0 <= vote.value < len(options):
                weight = self.get_agent_weight(vote.agent_id, decision_type)
                option_scores[options[vote.value]] += weight
        
        winning_option = max(option_scores, key=option_scores.get)
        return winning_option
    
    async def update_weights(
        self,
        updates: dict[str, dict[DecisionType, float]]
    ) -> None:
        """Update agent weights.
        
        Args:
            updates: Dictionary of agent_id -> {decision_type -> new_weight}
        """
        for agent_id, weight_updates in updates.items():
            if agent_id not in self.agent_weights:
                self.agent_weights[agent_id] = {}
            
            for decision_type, new_weight in weight_updates.items():
                # Clamp to bounds
                clamped_weight = max(self.min_weight, min(self.max_weight, new_weight))
                self.agent_weights[agent_id][decision_type] = clamped_weight
                
                logger.info(
                    f"Updated weight for {agent_id}/{decision_type}: "
                    f"{new_weight:.2f} -> {clamped_weight:.2f}"
                )
    
    def adjust_weight_for_outcome(
        self,
        agent_id: str,
        decision_type: DecisionType,
        success: bool,
        voted_correctly: bool
    ) -> float:
        """Adjust agent weight based on decision outcome.
        
        Args:
            agent_id: ID of the agent
            decision_type: Type of decision
            success: Whether the decision was successful
            voted_correctly: Whether the agent voted correctly
            
        Returns:
            New weight
        """
        current_weight = self.get_agent_weight(agent_id, decision_type)
        adjustment = self.weight_adjustment_rate
        
        if success and voted_correctly:
            # Increase weight if agent voted correctly in successful decision
            new_weight = current_weight * (1.0 + adjustment)
        elif not success and not voted_correctly:
            # Decrease weight if agent voted incorrectly in failed decision
            new_weight = current_weight * (1.0 - adjustment)
        else:
            # No change
            new_weight = current_weight
        
        # Clamp to bounds
        clamped_weight = max(self.min_weight, min(self.max_weight, new_weight))
        
        # Update weight
        if agent_id not in self.agent_weights:
            self.agent_weights[agent_id] = {}
        
        self.agent_weights[agent_id][decision_type] = clamped_weight
        
        logger.debug(
            f"Adjusted weight for {agent_id}/{decision_type}: "
            f"{current_weight:.2f} -> {clamped_weight:.2f} "
            f"(success={success}, voted_correctly={voted_correctly})"
        )
        
        return clamped_weight
    
    def get_all_weights(self) -> dict[str, dict[str, float]]:
        """Get all agent weights.
        
        Returns:
            Dictionary of agent_id -> {decision_type -> weight}
        """
        result = {}
        for agent_id, weights in self.agent_weights.items():
            result[agent_id] = {
                dt.value: w for dt, w in weights.items()
            }
        return result
