"""Consensus engine for multi-agent voting.

Agents propose solutions; the ConsensusEngine evaluates them and picks
a winner using the ANALYZER agent or heuristic similarity metrics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from backend.agents.base import AgentRequest
from backend.orchestrator.registry import resolve

logger = logging.getLogger(__name__)


@dataclass
class ConsensusResult:
    """Result of a consensus vote."""

    winner: str
    winning_proposal: str
    votes: dict[str, int] = field(default_factory=dict)
    confidence: float = 0.0
    justification: str = ""


class ConsensusEngine:
    """Multiple agents vote on the best solution."""

    def __init__(self, llm_client: Any, registry: dict[str, Any]) -> None:
        self.llm_client = llm_client
        self.registry = registry

    async def vote(
        self,
        proposals: list[str],
        criteria: list[str] | None = None,
        session_id: str = "",
    ) -> ConsensusResult:
        """Have ANALYZER evaluate all proposals against criteria and pick winner."""
        if not proposals:
            return ConsensusResult(
                winner="",
                winning_proposal="",
                confidence=0.0,
                justification="No proposals to evaluate.",
            )

        criteria = criteria or ["correctness", "completeness", "clarity"]

        eval_prompt = (
            "Evaluate the following proposals and pick the best one.\n\n"
            f"Criteria: {', '.join(criteria)}\n\n"
        )
        for i, proposal in enumerate(proposals, 1):
            eval_prompt += f"## Proposal {i}:\n{proposal[:2000]}\n\n"

        eval_prompt += (
            "\nRespond in this format:\n"
            "Winner: <proposal number>\n"
            "Justification: <why this is the best>\n"
            "Confidence: <0.0-1.0>"
        )

        try:
            agent = resolve(self.registry, "ANALYZER")
            req = AgentRequest(
                session_id=session_id,
                query=eval_prompt,
                client=self.llm_client,
            )

            parts: list[str] = []
            async for token in agent.run(req):
                parts.append(token)

            response = "".join(parts)

            # Parse winner index
            winner_idx = 0
            for i in range(len(proposals)):
                if f"proposal {i + 1}" in response.lower() or f"#{i + 1}" in response:
                    winner_idx = i
                    break

            # Parse confidence
            confidence = 0.7
            if "confidence:" in response.lower():
                try:
                    conf_str = response.lower().split("confidence:")[1].split()[0]
                    confidence = float(conf_str)
                except (ValueError, IndexError):
                    logger.debug(
                        "Failed to parse confidence from consensus response", exc_info=True
                    )

            return ConsensusResult(
                winner=f"proposal_{winner_idx + 1}",
                winning_proposal=proposals[winner_idx],
                votes={f"proposal_{winner_idx + 1}": 1},
                confidence=min(max(confidence, 0.0), 1.0),
                justification=response[:1000],
            )

        except Exception as exc:
            logger.exception("Consensus vote failed: %s", exc)
            return ConsensusResult(
                winner="proposal_1",
                winning_proposal=proposals[0] if proposals else "",
                confidence=0.5,
                justification=f"Fallback due to error: {exc}",
            )

    def similarity_score(self, a: str, b: str) -> float:
        """Calculate semantic similarity between two proposals.

        Uses Python's difflib.SequenceMatcher for a quick lexical similarity
        score between 0.0 (completely different) and 1.0 (identical).
        """
        return SequenceMatcher(None, a, b).ratio()
