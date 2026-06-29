"""SwarmOrchestrator — multiple agents working in parallel on the same objective.

Strategies:
- divide: Split objective into subtasks, assign to the best agents in parallel
- ensemble: All agents work on same task, LLM synthesises a merged answer
- pipeline: Agents work in sequence, passing output to next with verification
- debate: Agents propose solutions, moderator picks best and integrates feedback

Each strategy supports sub-agent consultation (CONSULT_AGENT) because every
agent runs through the standard ReAct loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
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


# Default agent capabilities used for intelligent task-to-agent assignment.
_AGENT_CAPABILITIES: dict[str, list[str]] = {
    "ARCHITECT": ["design", "architecture", "planning", "review", "specification"],
    "CODER": ["implementation", "refactoring", "scaffolding", "writing", "code"],
    "ANALYZER": ["analysis", "review", "security", "quality", "audit"],
    "DEBUGGER": ["debugging", "testing", "fixing", "verification", "troubleshooting"],
    "DOCUMENTER": ["documentation", "readme", "comments", "examples"],
    "RESEARCHER": ["research", "web", "docs", "information"],
    "OPTIMIZER": ["performance", "optimization", "profiling", "benchmark"],
}


class SwarmOrchestrator:
    """Orchestrates multiple agents in parallel strategies with LLM synthesis."""

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
        history: list[ChatMessage] | None = None,
        max_iterations: int = 5,
        enable_thinking: bool = False,
    ) -> SwarmResult:
        """Execute a swarm of agents on an objective."""
        start = time.time()
        available_agents = agents or ["CODER", "ANALYZER", "DEBUGGER", "DOCUMENTER"]
        available_agents = [a for a in available_agents if a in self.registry][: self.max_agents]

        if not available_agents:
            return SwarmResult(
                final_answer="No valid agents available for the swarm.",
                strategy_used=strategy,
                confidence=0.0,
            )

        # Adaptive strategy selection: pick the most appropriate strategy when
        # the caller leaves it up to us.
        selected_strategy = self._select_strategy(objective, available_agents, strategy)

        self._slog.info(
            f"Swarm started | strategy={selected_strategy} | agents={available_agents}",
            agent="SWARM",
            session_id=session_id,
            source="swarm",
            extra={"strategy": selected_strategy, "objective": objective[:200]},
        )

        # Common kwargs passed to every strategy so they all use the same
        # iteration budget, thinking mode, and conversational history.
        strategy_kwargs = {
            "history": history,
            "max_iterations": max_iterations,
            "enable_thinking": enable_thinking,
        }

        if selected_strategy == "divide":
            result = await self._divide_and_conquer(
                objective, session_id, available_agents, project_path, **strategy_kwargs
            )
        elif selected_strategy == "ensemble":
            result = await self._ensemble(
                objective, session_id, available_agents, project_path, **strategy_kwargs
            )
        elif selected_strategy == "pipeline":
            result = await self._pipeline(
                objective, session_id, available_agents, project_path, **strategy_kwargs
            )
        elif selected_strategy == "debate":
            result = await self._debate(
                objective, session_id, available_agents, project_path, **strategy_kwargs
            )
        else:
            result = await self._divide_and_conquer(
                objective, session_id, available_agents, project_path, **strategy_kwargs
            )

        result.duration_ms = int((time.time() - start) * 1000)
        result.strategy_used = selected_strategy

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
        history: list[ChatMessage] | None = None,
        max_iterations: int = 5,
        enable_thinking: bool = False,
    ) -> SwarmResult:
        """Split objective into subtasks, assign each to the best agent in parallel."""
        subtasks = await self._create_subtasks(
            objective,
            agents,
            session_id,
            project_path,
            history=history,
            max_iterations=max_iterations,
            enable_thinking=enable_thinking,
        )

        # Map each subtask to the most capable available agent
        tasks: list[tuple[str, str, str]] = []  # (agent, subtask, original_index)
        for i, subtask in enumerate(subtasks):
            agent = self._pick_agent_for_task(subtask, agents)
            tasks.append((agent, subtask, f"subtask-{i + 1}"))

        results = await asyncio.gather(
            *[
                self._run_agent(
                    agent,
                    subtask,
                    session_id,
                    project_path,
                    subtask_id=subtask_id,
                    history=history,
                    max_iterations=max_iterations,
                    enable_thinking=enable_thinking,
                )
                for agent, subtask, subtask_id in tasks
            ],
            return_exceptions=True,
        )

        agent_results: list[AgentResult] = []
        for (agent, _subtask, _subtask_id), res in zip(tasks, results, strict=True):
            if isinstance(res, AgentResult):
                agent_results.append(res)
            else:
                agent_results.append(AgentResult(agent=agent, error=str(res), success=False))

        # LLM synthesis instead of simple concatenation
        merged = await self._merge_with_llm(
            objective,
            agent_results,
            session_id,
            project_path,
            style="divide",
        )

        return SwarmResult(
            final_answer=merged,
            agent_results=agent_results,
            tokens_used=sum(r.tokens for r in agent_results),
            confidence=sum(1 for r in agent_results if r.success) / max(1, len(agent_results)),
            metadata={"subtasks": [s for _, s, _ in tasks]},
        )

    async def _ensemble(
        self,
        objective: str,
        session_id: str,
        agents: list[str],
        project_path: str,
        history: list[ChatMessage] | None = None,
        max_iterations: int = 5,
        enable_thinking: bool = False,
    ) -> SwarmResult:
        """All agents work on the same objective, merge results intelligently."""
        results = await asyncio.gather(
            *[
                self._run_agent(
                    agent,
                    objective,
                    session_id,
                    project_path,
                    subtask_id="ensemble",
                    history=history,
                    max_iterations=max_iterations,
                    enable_thinking=enable_thinking,
                )
                for agent in agents
            ],
            return_exceptions=True,
        )

        agent_results: list[AgentResult] = []
        for agent, res in zip(agents, results, strict=True):
            if isinstance(res, AgentResult):
                agent_results.append(res)
            else:
                agent_results.append(AgentResult(agent=agent, error=str(res), success=False))

        # LLM synthesis: pick best, integrate unique insights, resolve conflicts
        merged = await self._merge_with_llm(
            objective,
            agent_results,
            session_id,
            project_path,
            style="ensemble",
        )

        return SwarmResult(
            final_answer=merged,
            agent_results=agent_results,
            tokens_used=sum(r.tokens for r in agent_results),
            confidence=sum(1 for r in agent_results if r.success) / max(1, len(agents)),
        )

    async def _pipeline(
        self,
        objective: str,
        session_id: str,
        agents: list[str],
        project_path: str,
        history: list[ChatMessage] | None = None,
        max_iterations: int = 5,
        enable_thinking: bool = False,
    ) -> SwarmResult:
        """Chain agents: output of agent N becomes input of agent N+1.

        Each stage is verified; if a stage fails, the pipeline stops and the
        previous valid output is returned with an explanation.
        """
        agent_results: list[AgentResult] = []
        current_input = objective
        last_good_output = ""

        for idx, agent in enumerate(agents):
            stage_prompt = (
                f"Stage {idx + 1}/{len(agents)} | Agent: {agent}\n\n"
                f"Original objective: {objective}\n\n"
                f"Previous stage output:\n{current_input}\n\n"
                f"Continue working toward the original objective. "
                f"Build on the previous output and produce the next deliverable."
            )
            result = await self._run_agent(
                agent,
                stage_prompt,
                session_id,
                project_path,
                subtask_id=f"stage-{idx + 1}",
                history=history,
                max_iterations=max_iterations,
                enable_thinking=enable_thinking,
            )
            agent_results.append(result)
            if result.success:
                last_good_output = result.output
                current_input = result.output
            else:
                # Pipeline failed; synthesise what we have so far
                fallback = (
                    f"Pipeline stopped at stage {idx + 1} ({agent}): {result.error}\n\n"
                    f"Output from previous stages:\n{last_good_output}"
                )
                return SwarmResult(
                    final_answer=fallback,
                    agent_results=agent_results,
                    tokens_used=sum(r.tokens for r in agent_results),
                    confidence=(idx) / max(1, len(agents)),
                    metadata={"failed_stage": agent, "error": result.error},
                )

        # Final synthesis across all pipeline stages
        merged = await self._merge_with_llm(
            objective,
            agent_results,
            session_id,
            project_path,
            style="pipeline",
        )

        return SwarmResult(
            final_answer=merged,
            agent_results=agent_results,
            tokens_used=sum(r.tokens for r in agent_results),
            confidence=sum(1 for r in agent_results if r.success) / max(1, len(agents)),
        )

    async def _debate(
        self,
        objective: str,
        session_id: str,
        agents: list[str],
        project_path: str,
        history: list[ChatMessage] | None = None,
        max_iterations: int = 5,
        enable_thinking: bool = False,
    ) -> SwarmResult:
        """Agents propose solutions, then a moderator picks and integrates the best."""
        # Phase 1: Each agent proposes a solution
        proposals = await asyncio.gather(
            *[
                self._run_agent(
                    agent,
                    f"Propose a concrete solution or answer for: {objective}\n\n"
                    "Be specific. Include rationale, trade-offs, and implementation steps if applicable.",
                    session_id,
                    project_path,
                    subtask_id=f"proposal-{agent}",
                    history=history,
                    max_iterations=max_iterations,
                    enable_thinking=enable_thinking,
                )
                for agent in agents
            ],
            return_exceptions=True,
        )

        agent_results: list[AgentResult] = []
        valid_proposals: list[tuple[str, str]] = []
        for agent, res in zip(agents, proposals, strict=True):
            if isinstance(res, AgentResult):
                agent_results.append(res)
                if res.success:
                    valid_proposals.append((agent, res.output))
            else:
                agent_results.append(AgentResult(agent=agent, error=str(res), success=False))

        if not valid_proposals:
            return SwarmResult(
                final_answer=f"Debate failed: no valid proposals. Errors: {[r.error for r in agent_results]}",
                agent_results=agent_results,
                tokens_used=sum(r.tokens for r in agent_results),
                confidence=0.0,
            )

        if len(valid_proposals) == 1:
            return SwarmResult(
                final_answer=valid_proposals[0][1],
                agent_results=agent_results,
                tokens_used=sum(r.tokens for r in agent_results),
                confidence=0.6,
                metadata={"debate_proposals": 1},
            )

        # Phase 2: Moderator evaluates and integrates
        moderator = next((a for a in agents if a == "ANALYZER"), agents[-1])
        debate_prompt = (
            f"You are moderating a debate on: {objective}\n\n"
            "Evaluate the following proposals. Select the BEST proposal and explain why. "
            "Then produce a FINAL, INTEGRATED answer that:"
        )

        for agent, proposal in valid_proposals:
            debate_prompt += f"\n\n## {agent}\n{proposal[:800]}"

        debate_prompt += "\n\nYour final answer should:"

        final = await self._run_agent(
            moderator,
            debate_prompt,
            session_id,
            project_path,
            subtask_id="debate-moderator",
            history=history,
            max_iterations=max_iterations,
            enable_thinking=True,
        )
        agent_results.append(final)

        final_answer = final.output if final.success else valid_proposals[0][1]

        return SwarmResult(
            final_answer=final_answer,
            agent_results=agent_results,
            tokens_used=sum(r.tokens for r in agent_results),
            confidence=0.85 if final.success else 0.55,
            metadata={
                "debate_proposals": len(valid_proposals),
                "moderator": moderator,
                "integration_method": "moderator_llm",
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _pick_agent_for_task(self, task: str, available: list[str]) -> str:
        """Heuristic assignment: match task keywords to agent capabilities."""
        lowered = task.lower()
        scores: dict[str, int] = {agent: 0 for agent in available}
        for agent in available:
            caps = _AGENT_CAPABILITIES.get(agent, [])
            for cap in caps:
                if cap in lowered:
                    scores[agent] += 1
        # Prefer ANALYZER for review tasks, CODER for implementation tasks
        if (
            any(k in lowered for k in ("review", "audit", "analyze", "security"))
            and "ANALYZER" in available
        ):
            scores["ANALYZER"] += 2
        if (
            any(k in lowered for k in ("implement", "write", "create", "build", "code"))
            and "CODER" in available
        ):
            scores["CODER"] += 2
        if (
            any(k in lowered for k in ("debug", "fix", "test", "verify"))
            and "DEBUGGER" in available
        ):
            scores["DEBUGGER"] += 2
        if (
            any(k in lowered for k in ("design", "architecture", "plan"))
            and "ARCHITECT" in available
        ):
            scores["ARCHITECT"] += 2

        best = max(scores, key=lambda a: scores[a])
        return best

    def _select_strategy(self, objective: str, agents: list[str], strategy: str) -> str:
        """Return the requested strategy or pick one adaptively.

        Adaptive heuristics:
        - debate → comparison / evaluation / trade-off questions
        - pipeline → implementation tasks with multiple phases
        - ensemble → review / audit / quality tasks (multiple perspectives)
        - divide → default; parallel subtasks
        """
        if strategy != "adaptive":
            return strategy

        lowered = objective.lower()

        debate_markers = (
            "compare",
            "debate",
            "best approach",
            "trade-off",
            "tradeoff",
            "pros and cons",
            "advantages",
            "vs",
            "versus",
            "choose between",
        )
        if any(m in lowered for m in debate_markers) and len(agents) >= 2:
            return "debate"

        pipeline_markers = (
            "implement",
            "build",
            "create",
            "develop",
            "write",
            "refactor",
            "design and implement",
            "step by step",
        )
        if any(m in lowered for m in pipeline_markers) and len(agents) >= 2:
            return "pipeline"

        ensemble_markers = (
            "review",
            "audit",
            "analyze",
            "assess",
            "evaluate",
            "security",
            "quality",
            "check",
            "verify",
            "examine",
        )
        if any(m in lowered for m in ensemble_markers):
            return "ensemble"

        return "divide"

    async def _create_subtasks(
        self,
        objective: str,
        agents: list[str],
        session_id: str,
        project_path: str,
        history: list[ChatMessage] | None = None,
        max_iterations: int = 5,
        enable_thinking: bool = False,
    ) -> list[str]:
        """Use an agent to break the objective into specific, parallel subtasks."""
        # Prefer ARCHITECT or ANALYZER for planning, then CODER
        planner_agent = next(
            (a for a in agents if a in ("ARCHITECT", "ANALYZER")),
            next((a for a in agents if a == "CODER"), agents[0]),
        )

        prompt = (
            f"Break this objective into 2-{self.max_agents} specific, parallel subtasks.\n\n"
            f"Objective: {objective}\n\n"
            f"Available agents: {', '.join(agents)}\n\n"
            "Capabilities:\n"
            "- ARCHITECT: design, architecture, planning, trade-offs\n"
            "- CODER: implementation, refactoring, file creation\n"
            "- ANALYZER: review, audit, security, quality\n"
            "- DEBUGGER: bug fixing, testing, verification\n"
            "- DOCUMENTER: documentation, README, examples\n"
            "- RESEARCHER: external information, APIs, libraries\n"
            "- OPTIMIZER: performance, benchmarking, profiling\n\n"
            "Return ONLY a numbered list of subtasks, one per line. "
            "Each subtask must be actionable, self-contained, and include a hint about which agent type is best suited. "
            "If the objective is simple, return a single subtask."
        )

        result = await self._run_agent(
            planner_agent,
            prompt,
            session_id,
            project_path,
            subtask_id="planner",
            history=history,
            max_iterations=max_iterations,
            enable_thinking=enable_thinking,
        )
        if not result.success:
            return [objective]

        lines = result.output.split("\n")
        subtasks = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Remove numbering like "1. " or "- "
            for prefix in ("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "0.", "-"):
                if line.startswith(prefix):
                    line = line[len(prefix) :].strip()
                    break
            if line:
                subtasks.append(line)

        return subtasks[: self.max_agents] or [objective]

    async def _merge_with_llm(
        self,
        objective: str,
        agent_results: list[AgentResult],
        session_id: str,
        project_path: str,
        style: str = "divide",
    ) -> str:
        """Use a lightweight LLM call to synthesise agent outputs.

        Weights successful outputs by the agent's reported confidence and
        explicitly asks the editor to resolve contradictions, cite sources,
        and produce actionable next steps.
        """
        successful = [r for r in agent_results if r.success and r.output.strip()]
        if not successful:
            errors = [r.error for r in agent_results if r.error]
            return f"All swarm agents failed. Errors: {errors}"
        if len(successful) == 1:
            return successful[0].output

        # Build synthesis prompt with per-agent confidence metadata.
        total_tokens = max(1, sum(r.tokens for r in successful))
        parts = [
            f"Objective: {objective}",
            f"Swarm strategy: {style}",
            "",
            "You are a senior editor integrating multiple expert contributions into one coherent, professional answer.",
            "Instructions:",
            "1. Resolve any contradictions between contributors (state which view you adopt and why).",
            "2. Integrate unique insights from each contributor.",
            "3. Cite the contributing agent(s) for each key point.",
            "4. End with a short 'Next actions' list when applicable.",
            "5. Do not simply concatenate the outputs.",
            "",
            "Contributor outputs:",
        ]
        for r in successful:
            weight = r.tokens / total_tokens
            parts.append(
                f"\n--- {r.agent} (success, ~{weight:.0%} of tokens) ---\n{r.output[:1200]}"
            )

        synthesis_prompt = "\n".join(parts)

        try:
            messages = [
                ChatMessage(
                    role="system",
                    content=(
                        "You are a senior technical editor. Synthesise multiple expert opinions "
                        "into one coherent, professional answer. Be concise but complete."
                    ),
                ),
                ChatMessage(role="user", content=synthesis_prompt),
            ]
            response = await self.llm_client.chat_complete(
                model=self._fast_model_id(),
                messages=messages,
                options={"temperature": 0.3, "num_predict": 2048},
            )
            merged = response.strip()
            if merged:
                return merged
        except Exception as exc:
            logger.warning("LLM swarm synthesis failed: %s", exc)

        # Fallback to structured concatenation
        fallback_parts = [
            f"# Swarm Results ({style.title()} strategy)\n\n**Objective:** {objective}\n"
        ]
        for r in successful:
            fallback_parts.append(f"\n## {r.agent}\n{r.output[:800]}")
        return "\n".join(fallback_parts)

    def _fast_model_id(self) -> str:
        """Return a fast model id for lightweight synthesis."""
        from backend.config.settings import get_model_config

        try:
            return get_model_config("fast")["id"]
        except Exception:
            try:
                return get_model_config("micro")["id"]
            except Exception:
                return "qwen2.5:1.5b"

    async def _run_agent(
        self,
        agent_name: str,
        query: str,
        session_id: str,
        project_path: str,
        subtask_id: str = "",
        history: list[ChatMessage] | None = None,
        max_iterations: int = 5,
        enable_thinking: bool = False,
    ) -> AgentResult:
        """Run a single agent and capture metrics."""
        agent = self.registry.get(agent_name)
        if not agent:
            return AgentResult(
                agent=agent_name, error=f"Agent {agent_name} not found", success=False
            )

        start = time.time()
        tokens = 0
        parts: list[str] = []

        try:
            req = AgentRequest(
                session_id=f"{session_id}:{subtask_id}" if subtask_id else session_id,
                query=query,
                client=self.llm_client,
                history=history or [],
                project_path=project_path,
                max_iterations=max_iterations,
                enable_thinking=enable_thinking,
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
