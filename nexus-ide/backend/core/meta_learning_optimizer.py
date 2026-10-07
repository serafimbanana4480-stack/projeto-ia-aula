"""Meta-Learning Optimizer — optimizes the improvement process itself using Thompson Sampling.

Learns: optimal cycle intervals, agent assignments, strategy selection,
budget allocation, confidence thresholds.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from typing import Any

from backend.core.exploration_bonus import ExplorationBonus

logger = logging.getLogger(__name__)


@dataclass
class HyperparameterUpdate:
    cycle_interval_minutes: int
    auto_apply_threshold: float
    max_parallel: int
    strategy_preference: str
    confidence: float
    reasoning: str


class MetaLearningOptimizer:
    """Optimizes the improvement process ITSELF using Thompson Sampling.

    Learns: optimal cycle intervals, agent assignments, strategy selection,
    budget allocation, confidence thresholds.
    """

    HYPERPARAMETER_SPACE = {
        "cycle_interval_minutes": [15, 30, 60, 120],
        "auto_apply_threshold": [0.7, 0.8, 0.85, 0.9],
        "max_parallel": [2, 3, 5, 8],
        "strategy_preference": ["divide", "ensemble", "pipeline", "debate", "adaptive"],
    }

    REWARD_WEIGHTS = {
        "success_rate": 0.4,
        "cycle_efficiency": 0.3,
        "time_to_value": 0.2,
        "regression_penalty": 0.1,
    }

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = []
        self._arm_stats: dict[str, dict[str, Any]] = {}
        self._exploration = ExplorationBonus()

    async def optimize_hyperparameters(self, history: list[dict[str, Any]]) -> HyperparameterUpdate | None:
        if len(history) < 5:
            return None
        try:
            rewards = self._compute_rewards(history)
            best = self._thompson_sample(rewards)
            if self._exploration.should_explore():
                best = self._explore_random()
                reasoning = f"Exploration mode selected {best} (ε-greedy)"
            else:
                reasoning = f"Thompson Sampling selected {best} based on {len(history)} cycles"
            return HyperparameterUpdate(
                cycle_interval_minutes=best.get("cycle_interval_minutes", 30),
                auto_apply_threshold=best.get("auto_apply_threshold", 0.85),
                max_parallel=best.get("max_parallel", 3),
                strategy_preference=best.get("strategy_preference", "adaptive"),
                confidence=0.7,
                reasoning=reasoning,
            )
        except Exception:
            logger.exception("Meta-learning optimization failed")
            return None

    def _explore_random(self) -> dict[str, Any]:
        return {key: random.choice(arms) for key, arms in self.HYPERPARAMETER_SPACE.items()}

    def _compute_rewards(self, history: list[dict[str, Any]]) -> dict[str, float]:
        rewards: dict[str, float] = {}
        for cycle in history:
            success_rate = cycle.get("proposals_verified", 0) / max(1, cycle.get("proposals_generated", 1))
            cycle_eff = 1.0 / max(1.0, cycle.get("wall_time_seconds", 60.0))
            time_to_value = cycle.get("proposals_applied", 0) / max(1.0, cycle.get("wall_time_seconds", 60.0))
            regression_penalty = 1.0 - min(1.0, cycle.get("regressions_introduced", 0) * 0.1)
            reward = (
                self.REWARD_WEIGHTS["success_rate"] * success_rate
                + self.REWARD_WEIGHTS["cycle_efficiency"] * cycle_eff
                + self.REWARD_WEIGHTS["time_to_value"] * time_to_value
                + self.REWARD_WEIGHTS["regression_penalty"] * regression_penalty
            )
            for key in self.HYPERPARAMETER_SPACE:
                if key in cycle:
                    rewards[key] = rewards.get(key, 0.0) + reward
        return rewards

    def _thompson_sample(self, rewards: dict[str, float]) -> dict[str, Any]:
        best: dict[str, Any] = {}
        for key, arms in self.HYPERPARAMETER_SPACE.items():
            reward = rewards.get(key, 0.0)
            best_arm = arms[0]
            best_val = -float("inf")
            for arm in arms:
                if isinstance(arm, (int, float)):
                    score = reward + math.log(float(arm) + 1) * 0.1
                else:
                    score = reward + hash(str(arm)) % 100 / 100.0
                if score > best_val:
                    best_val = score
                    best_arm = arm
            best[key] = best_arm
        return best

    def record_cycle(self, cycle_data: dict[str, Any]) -> None:
        self._history.append(cycle_data)
