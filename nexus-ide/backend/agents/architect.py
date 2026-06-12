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
        AgentAction.CONSULT_AGENT,  # may consult RESEARCHER, ANALYZER, CODER
        AgentAction.READ_FILE,
        AgentAction.READ_FILE_ABSOLUTE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.SEARCH_SYMBOLS,
        AgentAction.INDEX_SYMBOLS,
        AgentAction.RECALL_CONTEXT,
        AgentAction.STORE_MEMORY,
        AgentAction.WRITE_FILE,
        AgentAction.WRITE_FILE_ABSOLUTE,
        AgentAction.LIST_DIR,
        AgentAction.LIST_DIR_ABSOLUTE,
    }

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run with ReAct loop so tools are always available."""
        async for token in self._run_react_loop(request):
            yield token
