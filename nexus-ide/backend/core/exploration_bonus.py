"""Exploration Bonus — ε-greedy extension for Thompson Sampling.

Prevents premature convergence by adding an exploration bonus to arm scores.
Ensures the meta-learning optimizer occasionally tries suboptimal arms
to discover better strategies.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExplorationConfig:
    epsilon: float = 0.1
    decay_rate: float = 0.995
    min_epsilon: float = 0.01
    exploration_bonus_factor: float = 0.2


class ExplorationBonus:
    """Adds ε-greedy exploration to Thompson Sampling."""

    def __init__(self, config: ExplorationConfig | None = None) -> None:
        self.config = config or ExplorationConfig()
        self._arm_counts: dict[str, int] = {}
        self._total_pulls: int = 0

    def should_explore(self) -> bool:
        epsilon = max(
            self.config.min_epsilon,
            self.config.epsilon * (self.config.decay_rate**self._total_pulls),
        )
        return random.random() < epsilon

    def score_arm(self, arm: Any, reward: float, key: str) -> float:
        self._total_pulls += 1
        self._arm_counts[key] = self._arm_counts.get(key, 0) + 1
        count = self._arm_counts[key]
        if isinstance(arm, (int, float)):
            bonus = self.config.exploration_bonus_factor * math.sqrt(math.log(self._total_pulls + 1) / max(1, count))
        else:
            bonus = self.config.exploration_bonus_factor * hash(str(arm)) % 100 / 100.0
        return reward + bonus

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_pulls": self._total_pulls,
            "arm_counts": dict(self._arm_counts),
            "current_epsilon": max(
                self.config.min_epsilon,
                self.config.epsilon * (self.config.decay_rate**self._total_pulls),
            ),
        }
