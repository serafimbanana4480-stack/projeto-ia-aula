"""RESEARCHER — online research agent.

Model: qwen2.5-coder:7b (CODER tier) with DuckDuckGo Search + URL fetching.
Prompt: config/prompts/researcher.md
See ARCHITECTURE.md §3.3 and §5.3 (web search pipeline).

Supports autonomous execution via ReAct loop:
- Searches the web for information
- Fetches and reads URLs for detailed content
- Reads documentation for reference
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class ResearcherAgent(AgentBase):
    name = "RESEARCHER"
    model_key = "coder"  # qwen2.5-coder:7b for thorough research with tool use
    prompt_file = "researcher"
    supported_actions = {
        AgentAction.SEARCH_WEB,
        AgentAction.FETCH_URL,
        AgentAction.READ_DOCS,
        AgentAction.RECALL_CONTEXT,
        AgentAction.ANALYZE_DATA,
    }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run with ReAct loop so tools are always available."""
        async for token in self._run_react_loop(request):
            yield token
