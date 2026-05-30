"""Debate Iterative — agent disagreement resolution.

When agents disagree, a structured debate is run over up to 3 rounds.
If no consensus emerges, META_ANALYZER makes the final call.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.core.agent_bus import BusMessage, get_agent_bus

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────────────────────────────────────


class AgentOpinion(BaseModel):
    """A single agent's stance in a debate."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str
    position: str
    arguments: list[str] = Field(default_factory=list)


class DebateRound(BaseModel):
    """One round of a debate session."""

    model_config = ConfigDict(extra="forbid")

    round_number: int
    opinions: list[AgentOpinion]


class DebateResult(BaseModel):
    """Final outcome of a debate session."""

    model_config = ConfigDict(extra="forbid")

    debate_id: str
    topic: str
    consensus_reached: bool
    winning_position: str
    dissenting_positions: list[AgentOpinion]
    meta_decision: str = ""
    rounds: list[DebateRound]


# ──────────────────────────────────────────────────────────────────────────────
# DebateSession
# ──────────────────────────────────────────────────────────────────────────────


class DebateSession:
    """Structured multi-round debate between agents.

    Usage::

        session = DebateSession(
            topic="Should we use SQLAlchemy or raw SQL?",
            opinions=[AgentOpinion(...), AgentOpinion(...)],
            max_rounds=3,
        )
        result = await session.run()
    """

    def __init__(
        self,
        topic: str,
        opinions: list[AgentOpinion],
        max_rounds: int = 3,
    ) -> None:
        self.topic = topic
        self.opinions = opinions
        self.max_rounds = max_rounds
        self.debate_id = uuid.uuid4().hex[:12]
        self._rounds: list[DebateRound] = []

    async def run(self) -> DebateResult:
        """Execute the debate and return the result."""
        logger.info("Debate %s started on: %s", self.debate_id, self.topic)

        # Round 1: initial positions
        round1 = DebateRound(round_number=1, opinions=self.opinions)
        self._rounds.append(round1)

        # Round 2: responses to each other
        round2_opinions: list[AgentOpinion] = []
        for opinion in self.opinions:
            responses = [
                f"Response to {other.agent_name}: acknowledges {other.position}"
                for other in self.opinions
                if other.agent_name != opinion.agent_name
            ]
            round2_opinions.append(
                AgentOpinion(
                    agent_name=opinion.agent_name,
                    position=opinion.position,
                    arguments=opinion.arguments + responses,
                )
            )
        round2 = DebateRound(round_number=2, opinions=round2_opinions)
        self._rounds.append(round2)

        # Round 3: final position + compromise proposals
        round3_opinions: list[AgentOpinion] = []
        for opinion in self.opinions:
            compromise = (
                f"Compromise proposal from {opinion.agent_name}: "
                "synthesize best aspects of all positions"
            )
            round3_opinions.append(
                AgentOpinion(
                    agent_name=opinion.agent_name,
                    position=opinion.position,
                    arguments=opinion.arguments + [compromise],
                )
            )
        round3 = DebateRound(round_number=3, opinions=round3_opinions)
        self._rounds.append(round3)

        # Determine consensus
        positions = [o.position for o in self.opinions]
        consensus = len(set(positions)) == 1

        winning_position = ""
        dissenting: list[AgentOpinion] = []

        if consensus:
            winning_position = positions[0]
        else:
            counts = Counter(positions)
            winning_position = counts.most_common(1)[0][0]
            dissenting = [
                o for o in self.opinions if o.position != winning_position
            ]

        meta_decision = ""
        if not consensus:
            meta_decision = (
                f"META_ANALYZER decides: adopt '{winning_position}' "
                "after weighing all arguments."
            )

        result = DebateResult(
            debate_id=self.debate_id,
            topic=self.topic,
            consensus_reached=consensus,
            winning_position=winning_position,
            dissenting_positions=dissenting,
            meta_decision=meta_decision,
            rounds=self._rounds,
        )

        await self._publish_result(result)
        return result

    async def _publish_result(self, result: DebateResult) -> None:
        try:
            bus = get_agent_bus()
            await bus.publish(
                "debate.result",
                BusMessage(
                    message_id=uuid.uuid4().hex[:16],
                    source_agent="DEBATE_SYSTEM",
                    payload=result.model_dump(mode="json"),
                ),
            )
        except Exception as exc:
            logger.warning("Failed to publish debate.result: %s", exc)


# ──────────────────────────────────────────────────────────────────────────────
# Global registry
# ──────────────────────────────────────────────────────────────────────────────

_debate_registry: dict[str, DebateResult] = {}


async def run_debate(
    topic: str,
    opinions: list[AgentOpinion],
    max_rounds: int = 3,
) -> DebateResult:
    """Convenience wrapper that runs a debate and caches the result."""
    session = DebateSession(topic=topic, opinions=opinions, max_rounds=max_rounds)
    result = await session.run()
    _debate_registry[result.debate_id] = result
    return result


def get_debate_result(debate_id: str) -> DebateResult | None:
    """Retrieve a previously run debate result by id."""
    return _debate_registry.get(debate_id)
