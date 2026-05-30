"""ARCHITECT_DESIGN — architecture & design specialist agent.

Model: reasoning tier (deep thinking) with ReAct loop.
Prompt: config/prompts/architect_design.md

Supports autonomous execution via ReAct loop:
- Reads files to understand existing architecture
- Searches codebase for patterns and dependencies
- Consults other agents (RESEARCHER, ANALYZER) for specialized input
- Writes design documents and ADRs to docs/architecture/
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class ArchitectDesignAgent(AgentBase):
    name = "ARCHITECT_DESIGN"
    model_key = "reasoning"
    prompt_file = "architect_design"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.CONSULT_AGENT,
        AgentAction.RECALL_CONTEXT,
        AgentAction.WRITE_FILE,
    }

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run with ReAct loop so tools are always available."""
        async for token in self._run_react_loop(request):
            yield token
