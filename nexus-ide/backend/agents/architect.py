"""ARCHITECT — system design agent.

Model: deepseek-r1:8b (REASONING tier) with thinking mode always on.
Prompt: config/prompts/architect.md
See ARCHITECTURE.md §3.2.

Supports autonomous execution via ReAct loop:
- Reads files to understand existing architecture
- Searches codebase for patterns and dependencies
- Consults other agents (RESEARCHER, ANALYZER) for specialized input
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class ArchitectAgent(AgentBase):
    name = "ARCHITECT"
    model_key = "reasoning"  # deepseek-r1:8b for deep design reasoning
    prompt_file = "architect"
    supported_actions = {
        AgentAction.CONSULT_AGENT,  # may consult RESEARCHER, ANALYZER
        AgentAction.READ_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.RECALL_CONTEXT,
    }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run architect with ReAct loop for complex design tasks.

        Uses ReAct loop when the task involves analysis, design, or planning
        that benefits from reading files and searching the codebase.
        Falls back to single-shot for simple questions.
        """
        is_complex = self._is_complex_task(request.query)

        if is_complex and request.max_iterations > 1:
            async for token in self._run_react_loop(request):
                yield token
        else:
            async for token in self.stream_llm(request):
                yield token

    def _is_complex_task(self, query: str) -> bool:
        """Heuristic to detect tasks needing the ReAct loop."""
        complex_markers = [
            "design", "architect", "plan", "structure", "refactor",
            "analyze", "review", "evaluate", "assess", "compare",
            "how should", "what should", "recommend", "propose",
            "create a", "build a", "implement", "set up",
            "projetar", "arquitetar", "planejar", "estruturar",
            "analisar", "revisar", "avaliar", "recomendar",
        ]
        lowered = query.lower()
        return any(marker in lowered for marker in complex_markers)
