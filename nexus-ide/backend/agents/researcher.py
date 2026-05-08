"""RESEARCHER — online research agent.

Model: qwen3.5:9b (SMALL) with Brave Search + URL fetching.
Prompt: config/prompts/researcher.md
See ARCHITECTURE.md §3.3 and §5.3 (web search pipeline).
"""
from __future__ import annotations

from typing import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class ResearcherAgent(AgentBase):
    name = "RESEARCHER"
    model_key = "small"
    prompt_file = "researcher"
    supported_actions = {
        AgentAction.SEARCH_WEB,
        AgentAction.FETCH_URL,
        AgentAction.READ_DOCS,
        AgentAction.RECALL_CONTEXT,
    }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        # Tier 1: no web search yet. The agent answers from training data and
        # must explicitly caveat anything time-sensitive (its prompt enforces this).
        async for token in self.stream_llm(request):
            yield token
