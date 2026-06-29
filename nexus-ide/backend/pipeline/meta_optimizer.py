"""MetaOptimizer — connects RLOptimizer to orchestrator lifecycle.

Wraps the existing RLOptimizer with orchestrator-aware state/action
definitions and reward computation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.pipeline.rl_optimizer import RLOptimizer

logger = logging.getLogger(__name__)


@dataclass
class OptimizationResult:
    """Result of a meta-optimization query."""

    num_agents: int = 5
    model_tier: str = "balanced"
    max_retries: int = 3
    confidence: float = 0.5


class MetaOptimizer:
    """Bridges RLOptimizer with SupremeOrchestrator execution lifecycle.

    Maps workflow context (task complexity, phase) to states, and
    orchestrator parameters to actions. Computes reward from
    execution outcomes.
    """

    # Available actions per parameter
    ACTIONS: dict[str, list[str]] = {
        "num_agents": ["num_agents=3", "num_agents=5", "num_agents=8"],
        "model_tier": ["model_tier=mini", "model_tier=balanced", "model_tier=opus"],
        "max_retries": ["max_retries=1", "max_retries=3", "max_retries=5"],
    }

    def __init__(self, exploration_rate: float = 0.1) -> None:
        self._rl = RLOptimizer(exploration_rate=exploration_rate)
        self._workflow_count = 0

    def get_parameters(self, task_complexity: str = "medium",
                       phase: str = "code_gen") -> OptimizationResult:
        """Get optimized parameters for a given context.

        Args:
            task_complexity: simple, medium, or complex.
            phase: code_gen, test, deploy.

        Returns:
            OptimizationResult with selected parameters.
        """
        result = OptimizationResult()

        for param, actions in self.ACTIONS.items():
            state = f"{task_complexity}:{phase}:{param}"
            action = self._rl.select_action(state, actions)

            raw_value = action.split("=")[1]
            if param == "num_agents":
                result.num_agents = int(raw_value)
            elif param == "model_tier":
                result.model_tier = raw_value  # string value
            elif param == "max_retries":
                result.max_retries = int(raw_value)

        result.confidence = self._compute_confidence(task_complexity, phase)
        return result

    def record_outcome(self, task_complexity: str, phase: str,
                       params: OptimizationResult, success: bool,
                       tests_passed: bool = False) -> None:
        """Record execution outcome for learning.

        Args:
            task_complexity: simple, medium, or complex.
            phase: code_gen, test, deploy.
            params: The OptimizationResult used for this execution.
            success: Whether the deployment succeeded.
            tests_passed: Whether all tests passed.
        """
        # Compute reward
        if success and tests_passed:
            reward = 1.0
        elif tests_passed:
            reward = 0.5
        elif success:
            reward = 0.3
        else:
            reward = -1.0

        # Update Q-values for each parameter
        param_values = {
            "num_agents": f"num_agents={params.num_agents}",
            "model_tier": f"model_tier={params.model_tier}",
            "max_retries": f"max_retries={params.max_retries}",
        }

        for param, action in param_values.items():
            state = f"{task_complexity}:{phase}:{param}"
            self._rl.update(state, action, reward)

        self._workflow_count += 1

        # Decay exploration rate
        if self._workflow_count >= 50:
            self._rl._epsilon = max(0.01, self._rl._epsilon * 0.98)

        logger.debug(
            "Recorded outcome: complexity=%s phase=%s success=%s reward=%.2f count=%d",
            task_complexity, phase, success, reward, self._workflow_count,
        )

    def get_best_parameters(self) -> dict[str, dict[str, str]]:
        """Get the best learned parameters per context."""
        return self._rl.get_best_parameters()

    def get_q_values(self) -> dict[str, dict[str, float]]:
        return self._rl.get_q_values()

    def _compute_confidence(self, task_complexity: str, phase: str) -> float:
        """Estimate confidence based on how much data we have for this context."""
        q_values = self._rl.get_q_values()
        context_prefix = f"{task_complexity}:{phase}:"
        relevant = {k: v for k, v in q_values.items() if k.startswith(context_prefix)}
        if not relevant:
            return 0.3
        # Higher max Q-value spread = higher confidence
        all_values = [v for d in relevant.values() for v in d.values()]
        if not all_values:
            return 0.3
        return min(1.0, 0.3 + len(relevant) * 0.1)