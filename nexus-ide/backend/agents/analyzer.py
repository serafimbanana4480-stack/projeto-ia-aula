"""ANALYZER — critical code/architecture reviewer.

Model: qwen3.5:27b (LARGE) with thinking mode.
Prompt: config/prompts/analyzer.md
See ARCHITECTURE.md §3.5.

Supports autonomous execution via ReAct loop:
- Reads files to understand code structure
- Searches codebase for patterns and issues
- Reads documentation for context
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class AnalyzerAgent(AgentBase):
    name = "ANALYZER"
    model_key = "large"
    prompt_file = "analyzer"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.READ_DOCS,
    }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run analyzer with ReAct loop for code review tasks.

        Uses ReAct loop when the task involves reviewing, analyzing,
        or auditing code. Falls back to single-shot for simple questions.
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
            "review", "analyze", "audit", "check", "inspect",
            "find bugs", "security", "vulnerability", "code quality",
            "what's wrong", "why does", "explain the code",
            "is there", "are there", "identify", "detect",
            "revisar", "analisar", "auditar", "verificar",
            "encontrar bugs", "segurança", "qualidade",
        ]
        lowered = query.lower()
        return any(marker in lowered for marker in complex_markers)
