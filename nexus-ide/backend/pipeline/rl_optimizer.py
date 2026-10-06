"""RLOptimizer — reinforcement learning for meta-optimization.

Tunes orchestrator parameters (agent count, model selection, retry limits)
using reward signals from deployment success rates.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AgentReputationTier(Enum):
    """Agent reputation tiers."""

    NOVICE = "novice"       # < 10 tasks, untrusted
    RELIABLE = "reliable"   # >= 80% success rate
    EXPERT = "expert"       # >= 95% success rate
    DEPRECATED = "deprecated"  # < 50% success rate


@dataclass
class AgentProfile:
    """Profile and reputation data for an agent."""

    agent_id: str
    role: str  # backend, frontend, security, qa, etc.
    tasks_completed: int = 0
    tasks_failed: int = 0
    avg_duration_seconds: float = 0.0
    reputation_tier: AgentReputationTier = AgentReputationTier.NOVICE
    last_active: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def success_rate(self) -> float:
        total = self.tasks_completed + self.tasks_failed
        if total == 0:
            return 0.0
        return (self.tasks_completed / total) * 100

    def record_success(self, duration_seconds: float = 0.0) -> None:
        self.tasks_completed += 1
        if self.tasks_completed > 0:
            self.avg_duration_seconds = (
                (self.avg_duration_seconds * (self.tasks_completed - 1) + duration_seconds)
                / self.tasks_completed
            )
        self.last_active = datetime.now(UTC).isoformat()
        self._recalc_tier()

    def record_failure(self) -> None:
        self.tasks_failed += 1
        self.last_active = datetime.now(UTC).isoformat()
        self._recalc_tier()

    def _recalc_tier(self) -> None:
        rate = self.success_rate
        total = self.tasks_completed + self.tasks_failed

        if total < 5:
            self.reputation_tier = AgentReputationTier.NOVICE
        elif rate < 50:
            self.reputation_tier = AgentReputationTier.DEPRECATED
        elif rate >= 95:
            self.reputation_tier = AgentReputationTier.EXPERT
        elif rate >= 80:
            self.reputation_tier = AgentReputationTier.RELIABLE
        else:
            self.reputation_tier = AgentReputationTier.NOVICE


@dataclass
class OptimizationAction:
    """An action the RL optimizer can take."""

    parameter: str  # num_agents, model_tier, max_retries
    current_value: float
    new_value: float
    confidence: float = 0.5  # 0.0-1.0


class AgentReputationSystem:
    """Tracks and manages agent reputation."""

    def __init__(self) -> None:
        self._profiles: dict[str, AgentProfile] = {}

    def register(self, agent_id: str, role: str) -> AgentProfile:
        profile = AgentProfile(agent_id=agent_id, role=role)
        self._profiles[agent_id] = profile
        return profile

    def get(self, agent_id: str) -> AgentProfile | None:
        return self._profiles.get(agent_id)

    def get_best_for_role(self, role: str, min_tier: AgentReputationTier | None = None) -> AgentProfile | None:
        """Select the best agent for a given role.

        Args:
            role: Desired agent role.
            min_tier: Minimum reputation tier required.

        Returns:
            Best matching AgentProfile or None.
        """
        candidates = [
            p for p in self._profiles.values()
            if p.role == role and (min_tier is None or p.reputation_tier.value >= min_tier.value)
        ]
        if not candidates:
            return None

        # Sort by tier then success rate
        tier_order = {
            AgentReputationTier.EXPERT: 0,
            AgentReputationTier.RELIABLE: 1,
            AgentReputationTier.NOVICE: 2,
            AgentReputationTier.DEPRECATED: 3,
        }
        return sorted(candidates, key=lambda p: (
            tier_order.get(p.reputation_tier, 99),
            -p.success_rate,
        ))[0]

    def get_all_profiles(self) -> list[AgentProfile]:
        return list(self._profiles.values())


class RLOptimizer:
    """Reinforcement learning optimizer for meta-parameter tuning.

    Uses epsilon-greedy exploration with reward based on task success rate.
    """

    def __init__(self, exploration_rate: float = 0.1) -> None:
        self._epsilon = exploration_rate
        self._q_values: dict[str, dict[str, float]] = {}  # state -> action -> value
        self._history: list[dict[str, Any]] = []

    def select_action(self, state: str, actions: list[str]) -> str:
        """Select action using epsilon-greedy policy.

        Args:
            state: Current state description.
            actions: Available action names.

        Returns:
            Selected action name.
        """
        if random.random() < self._epsilon:
            return random.choice(actions)

        q = self._q_values.get(state, {})
        if not q:
            return random.choice(actions)

        return max(actions, key=lambda a: q.get(a, 0.0))

    def update(self, state: str, action: str, reward: float, learning_rate: float = 0.1,
               discount: float = 0.9) -> None:
        """Update Q-values using temporal difference learning.

        Args:
            state: State before action.
            action: Action taken.
            reward: Reward received.
            learning_rate: Alpha parameter.
            discount: Gamma parameter.
        """
        if state not in self._q_values:
            self._q_values[state] = {}

        old_q = self._q_values[state].get(action, 0.0)
        max_future = max(self._q_values[state].values()) if self._q_values[state] else 0.0
        new_q = old_q + learning_rate * (reward + discount * max_future - old_q)
        self._q_values[state][action] = new_q

        self._history.append({
            "state": state,
            "action": action,
            "reward": reward,
            "new_q": new_q,
        })

    def get_best_parameters(self) -> dict[str, str]:
        """Get the best learned action per state."""
        best: dict[str, str] = {}
        for state, actions in self._q_values.items():
            if actions:
                best[state] = max(actions, key=actions.get)
        return best

    def get_q_values(self) -> dict[str, dict[str, float]]:
        return dict(self._q_values)