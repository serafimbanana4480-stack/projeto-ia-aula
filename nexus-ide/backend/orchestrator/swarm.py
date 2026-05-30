"""SwarmOrchestrator — multiple agents working in parallel on the same objective.

Strategies:
- divide: Split objective into subtasks, assign to different agents
- ensemble: All agents work on same task, merge results
- pipeline: Agents work in sequence, passing output to next
- debate: Agents debate solutions, moderator picks best
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from backend.agents.base import AgentBase, AgentRequest
from backend.observability.advanced_logging import get_structured_logger
from backend.tools.ollama_client import ChatMessage

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    agent: str
    output: str = ""
    tokens: int = 0
    duration_ms: int = 0
    success: bool = False
    error: str = ""


@dataclass
class SwarmResult:
    final_answer: str = ""
    agent_results: list[AgentResult] = field(default_factory=list)
    strategy_used: str = ""
    duration_ms: int = 0
    tokens_used: int = 0
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class SwarmOrchestrator:
    """Orchestrates multiple agents in parallel strategies."""

    def __init__(
        self,
        llm_client: Any,
        registry: dict[str, AgentBase],
        event_bus: Any,
        max_agents: int = 5,
    ) -> None:
        self.llm_client = llm_client
        self.registry = registry
        self.events = event_bus
        self.max_agents = max_agents
        self._slog = get_structured_logger()

    async def execute_swarm(
        self,
        objective: str,
        session_id: str,
        agents: list[str] | None = None,
        strategy: str = "divide",
        project_path: str = ".",
    ) -> SwarmResult:
        """Execute a swarm of agents on an objective."""
        start = time.time()
        available_agents = agents or ["CODER", "ANALYZER", "DEBUGGER", "DOCUMENTER"]
        available_agents = [a for a in available_agents if a in self.registry][: self.max_agents]

        self._slog.info(
            f"Swarm started | strategy={strategy} | agents={available_agents}",
            agent="SWARM",
            session_id=session_id,
            source="swarm",
            extra={"strategy": strategy, "objective": objective[:200]},
        )

        if strategy == "divide":
            result = await self._divide_and_conquer(objective, session_id, available_agents, project_path)
        elif strategy == "ensemble":
            result = await self._ensemble(objective, session_id, available_agents, project_path)
        elif strategy == "pipeline":
            result = await self._pipeline(objective, session_id, available_agents, project_path)
        elif strategy == "debate":
            result = await self._debate(objective, session_id, available_agents, project_path)
        else:
            result = await self._divide_and_conquer(objective, session_id, available_agents, project_path)

        result.duration_ms = int((time.time() - start) * 1000)
        result.strategy_used = strategy

        self._slog.info(
            f"Swarm complete | strategy={strategy} | agents={len(result.agent_results)} | duration={result.duration_ms}ms",
            agent="SWARM",
            session_id=session_id,
            source="swarm",
            extra={"result_tokens": result.tokens_used},
        )

        return result

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    async def _divide_and_conquer(
        self,
        objective: str,
        session_id: str,
        agents: list[str],
        project_path: str,
    ) -> SwarmResult:
        """Split objective into subtasks, assign to different agents in parallel."""
        # Use first available agent to create subtasks (prefer ARCHITECT or CODER)
        planner_agent = next(
            (a for a in agents if a in ("ARCHITECT", "CODER")),
            agents[0],
        )

        subtasks = await self._create_subtasks(objective, planner_agent, session_id, project_path)

        # Assign subtasks to agents round-robin
        tasks: list[tuple[str, str]] = []  # (agent, subtask)
        for i, subtask in enumerate(subtasks):
            agent = agents[i % len(agents)]
            tasks.append((agent, subtask))

        # Execute in parallel
        results = await asyncio.gather(
            *[self._run_agent(agent, subtask, session_id, project_path) for agent, subtask in tasks],
            return_exceptions=True,
        )

        agent_results = []
        final_parts = [f"# Swarm Results (Divide & Conquer)\n\n**Objective:** {objective}\n"]

        for (agent, subtask), res in zip(tasks, results):
            if isinstance(res, AgentResult):
                agent_results.append(res)
                final_parts.append(f"\n## {agent}\n{res.output[:500]}")
            else:
                agent_results.append(
                    AgentResult(agent=agent, error=str(res), success=False)
                )

        return SwarmResult(
            final_answer="\n".join(final_parts),
            agent_results=agent_results,
            tokens_used=sum(r.tokens for r in agent_results),
            confidence=sum(1 for r in agent_results if r.success) / max(1, len(agent_results)),
        )

    async def _ensemble(
        self,
        objective: str,
        session_id: str,
        agents: list[str],
        project_path: str,
    ) -> SwarmResult:
        """All agents work on the same objective, merge results intelligently."""
        results = await asyncio.gather(
            *[self._run_agent(agent, objective, session_id, project_path) for agent in agents],
            return_exceptions=True,
        )

        agent_results = []
        successful = []
        for agent, res in zip(agents, results):
            if isinstance(res, AgentResult):
                agent_results.append(res)
                if res.success:
                    successful.append(res)
            else:
                agent_results.append(AgentResult(agent=agent, error=str(res), success=False))

        # Merge: pick the longest/most detailed successful response as base
        if successful:
            best = max(successful, key=lambda r: len(r.output))
            # Add insights from other agents as comments
            merged = best.output + "\n\n# Additional insights from swarm:\n"
            for r in successful:
                if r.agent != best.agent:
                    merged += f"\n## {r.agent} added:\n{r.output[:300]}\n"
        else:
            merged = f"All agents failed. Errors: {[r.error for r in agent_results]}"

        return SwarmResult(
            final_answer=merged,
            agent_results=agent_results,
            tokens_used=sum(r.tokens for r in agent_results),
            confidence=len(successful) / max(1, len(agents)),
        )

    async def _pipeline(
        self,
        objective: str,
        session_id: str,
        agents: list[str],
        project_path: str,
    ) -> SwarmResult:
        """Chain agents: output of agent N becomes input of agent N+1."""
        agent_results = []
        current_input = objective

        for agent in agents:
            result = await self._run_agent(agent, current_input, session_id, project_path)
            agent_results.append(result)
            if result.success:
                current_input = f"Previous agent ({agent}) produced:\n{result.output}\n\nContinue with the original objective: {objective}"
            else:
                break

        return SwarmResult(
            final_answer=agent_results[-1].output if agent_results else "Pipeline failed",
            agent_results=agent_results,
            tokens_used=sum(r.tokens for r in agent_results),
            confidence=sum(1 for r in agent_results if r.success) / max(1, len(agent_results)),
        )

    async def _debate(
        self,
        objective: str,
        session_id: str,
        agents: list[str],
        project_path: str,
    ) -> SwarmResult:
        """Agents propose solutions, then debate. Pick best."""
        # Phase 1: Each agent proposes a solution
        proposals = await asyncio.gather(
            *[self._run_agent(agent, f"Propose a solution for: {objective}", session_id, project_path)
              for agent in agents],
            return_exceptions=True,
        )

        agent_results = []
        valid_proposals = []
        for agent, res in zip(agents, proposals):
            if isinstance(res, AgentResult):
                agent_results.append(res)
                if res.success:
                    valid_proposals.append((agent, res.output))
            else:
                agent_results.append(AgentResult(agent=agent, error=str(res), success=False))

        if len(valid_proposals) < 2:
            return SwarmResult(
                final_answer=valid_proposals[0][1] if valid_proposals else "Debate failed",
                agent_results=agent_results,
                tokens_used=sum(r.tokens for r in agent_results),
                confidence=0.5,
            )

        # Phase 2: Have ANALYZER or last agent pick the best
        moderator = next((a for a in agents if a == "ANALYZER"), agents[-1])
        debate_prompt = (
            f"Evaluate these proposals for: {objective}\n\n"
            + "\n\n".join(f"## {agent}\n{proposal[:500]}" for agent, proposal in valid_proposals)
            + "\n\nSelect the BEST proposal and explain why. Return the full best proposal."
        )

        final = await self._run_agent(moderator, debate_prompt, session_id, project_path)
        agent_results.append(final)

        return SwarmResult(
            final_answer=final.output if final.success else valid_proposals[0][1],
            agent_results=agent_results,
            tokens_used=sum(r.tokens for r in agent_results),
            confidence=0.8 if final.success else 0.5,
            metadata={"debate_proposals": len(valid_proposals), "moderator": moderator},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _create_subtasks(
        self,
        objective: str,
        planner_agent: str,
        session_id: str,
        project_path: str,
    ) -> list[str]:
        """Use an agent to break the objective into subtasks."""
        prompt = (
            f"Break this objective into 2-5 specific subtasks that can be worked on in parallel.\n\n"
            f"Objective: {objective}\n\n"
            f"Return ONLY a numbered list of subtasks, one per line. Be specific and actionable."
        )

        result = await self._run_agent(planner_agent, prompt, session_id, project_path)
        if not result.success:
            return [objective]

        # Parse numbered list
        lines = result.output.split("\n")
        subtasks = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Remove numbering like "1. " or "- "
            for prefix in ("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "0.", "-"):
                if line.startswith(prefix):
                    line = line[len(prefix):].strip()
                    break
            if line:
                subtasks.append(line)

        return subtasks[: self.max_agents] or [objective]

    async def _run_agent(
        self,
        agent_name: str,
        query: str,
        session_id: str,
        project_path: str,
    ) -> AgentResult:
        """Run a single agent and capture metrics."""
        agent = self.registry.get(agent_name)
        if not agent:
            return AgentResult(agent=agent_name, error=f"Agent {agent_name} not found", success=False)

        start = time.time()
        tokens = 0
        parts: list[str] = []

        try:
            req = AgentRequest(
                session_id=session_id,
                query=query,
                client=self.llm_client,
                project_path=project_path,
                max_iterations=3,
            )

            async for token in agent.run(req):
                parts.append(token)
                tokens += 1

            output = "".join(parts)
            duration = int((time.time() - start) * 1000)

            self._slog.agent_end(agent_name, session_id, tokens, duration, True)

            return AgentResult(
                agent=agent_name,
                output=output,
                tokens=tokens,
                duration_ms=duration,
                success=True,
            )

        except Exception as exc:
            duration = int((time.time() - start) * 1000)
            self._slog.agent_end(agent_name, session_id, tokens, duration, False)
            return AgentResult(
                agent=agent_name,
                error=str(exc),
                tokens=tokens,
                duration_ms=duration,
                success=False,
            )
