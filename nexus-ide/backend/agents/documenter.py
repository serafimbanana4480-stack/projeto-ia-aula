"""DOCUMENTER — technical writing agent.

Model: qwen2.5:3b (FAST tier).
Prompt: config/prompts/documenter.md
See ARCHITECTURE.md §3.7.

Supports autonomous execution via ReAct loop:
- Reads files to understand what needs documenting
- Writes documentation files
- Searches codebase for context
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class DocumenterAgent(AgentBase):
    name = "DOCUMENTER"
    model_key = "fast"
    prompt_file = "documenter"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.WRITE_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.GENERATE_REPORT,
    }

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run with ReAct loop so tools are always available."""
        async for token in self._run_react_loop(request):
            yield token
