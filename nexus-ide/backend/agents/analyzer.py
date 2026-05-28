"""ANALYZER — critical code/architecture reviewer.

Model: deepseek-r1:8b (REASONING tier) with thinking mode.
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
    model_key = "reasoning"
    prompt_file = "analyzer"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.READ_DOCS,
        AgentAction.ANALYZE_DATA,
    }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run analyzer with ReAct loop so tools are always available."""
        async for token in self._run_react_loop(request):
            yield token
