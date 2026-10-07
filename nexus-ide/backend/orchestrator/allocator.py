"""AgentAllocator — resource-aware agent allocation for tasks.

Scores agents by capability match, respects concurrency limits,
and provides fallback chains for resilient execution.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from backend.agents.base import AgentBase

logger = logging.getLogger(__name__)


@dataclass
class Capability:
    """A capability that an agent can perform."""

    name: str
    description: str = ""
    stack_preferences: list[str] = field(default_factory=list)
    confidence: float = 1.0  # 0.0-1.0


@dataclass
class AgentScore:
    """Score result for agent-task matching."""

    agent_name: str
    score: float  # 0.0-1.0
    capabilities_matched: list[str] = field(default_factory=list)
    reason: str = ""


class AgentAllocator:
    """Allocates agents to tasks based on capability matching and resource availability."""

    CAPABILITY_MAP: dict[str, list[str]] = {
        "design": ["ARCHITECT"],
        "api_design": ["ARCHITECT"],
        "database_schema": ["ARCHITECT"],
        "research": ["RESEARCHER"],
        "tech_eval": ["RESEARCHER"],
        "code_generation": ["CODER"],
        "refactoring": ["CODER", "OPTIMIZER"],
        "multi_file_impl": ["CODER"],
        "code_review": ["ANALYZER"],
        "security_audit": ["ANALYZER"],
        "performance_analysis": ["ANALYZER", "OPTIMIZER"],
        "debugging": ["DEBUGGER"],
        "test_repair": ["DEBUGGER"],
        "patch_generation": ["DEBUGGER"],
        "documentation": ["DOCUMENTER"],
        "docstrings": ["DOCUMENTER"],
        "readme": ["DOCUMENTER"],
        "optimization": ["OPTIMIZER"],
        "caching": ["OPTIMIZER"],
        "resource_tuning": ["OPTIMIZER"],
        "quick_fix": ["MICRO"],
        "one_liner": ["MICRO"],
    }

    # Reputation score multipliers per tier
    REPUTATION_MULTIPLIERS: dict[str, float] = {
        "expert": 1.2,
        "reliable": 1.0,
        "novice": 0.8,
        "deprecated": 0.3,
    }

    def __init__(self, registry: dict[str, AgentBase], pool: Any | None = None,
                 reputation_system: Any | None = None) -> None:
        self._registry = registry
        self._pool = pool
        self._reputation = reputation_system

    def score_agents(self, task_type: str, stack: str = "") -> list[AgentScore]:
        """Score all agents for a given task type.

        Args:
            task_type: Capability required (e.g., "code_generation").
            stack: Preferred technology stack.

        Returns:
            List of AgentScore sorted by score descending.
        """
        candidates = self.CAPABILITY_MAP.get(task_type, [])
        scores: list[AgentScore] = []

        for agent_name in candidates:
            if agent_name not in self._registry:
                continue

            score = 1.0
            reason = f"Primary capability match for {task_type}"

            # Boost for stack preference
            agent = self._registry[agent_name]
            if stack and hasattr(agent, "supported_stacks"):
                if stack in agent.supported_stacks:
                    score += 0.2
                    reason += f", stack match: {stack}"

            # Apply reputation multiplier if available
            if self._reputation is not None:
                profile = self._reputation.get(agent_name)
                if profile is not None:
                    tier = profile.reputation_tier.value if hasattr(profile.reputation_tier, 'value') else str(profile.reputation_tier)
                    multiplier = self.REPUTATION_MULTIPLIERS.get(tier, 1.0)
                    score *= multiplier
                    reason += f", reputation: {tier} ({multiplier}x)"

            scores.append(AgentScore(
                agent_name=agent_name,
                score=min(score, 1.0),
                capabilities_matched=[task_type],
                reason=reason,
            ))

        # Fallback: CODER can attempt anything
        if not scores and "CODER" in self._registry:
            scores.append(AgentScore(
                agent_name="CODER",
                score=0.3,
                capabilities_matched=[],
                reason="Fallback agent",
            ))

        scores.sort(key=lambda s: s.score, reverse=True)
        return scores

    async def allocate(self, task_type: str, stack: str = "", timeout: float = 30.0) -> AgentBase | None:
        """Allocate the best available agent for a task.

        Args:
            task_type: Required capability.
            stack: Preferred stack.
            timeout: Max time to wait for agent availability.

        Returns:
            Agent instance or None if no agent available.
        """
        scores = self.score_agents(task_type, stack)

        for score in scores:
            agent = self._registry.get(score.agent_name)
            if not agent:
                continue

            # Check concurrency if pool exists
            if self._pool and hasattr(self._pool, "acquire"):
                try:
                    await asyncio.wait_for(
                        self._pool.acquire(score.agent_name),
                        timeout=timeout / len(scores),
                    )
                except TimeoutError:
                    logger.warning("Agent %s busy, trying next", score.agent_name)
                    continue

            logger.info("Allocated %s for %s (score %.2f)", score.agent_name, task_type, score.score)
            return agent

        logger.error("No agent available for task type: %s", task_type)
        return None

    def get_fallback_chain(self, task_type: str) -> list[str]:
        """Get ordered list of agents to try as fallbacks."""
        scores = self.score_agents(task_type)
        return [s.agent_name for s in scores]
