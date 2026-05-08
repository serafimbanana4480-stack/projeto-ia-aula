"""ARCHITECT — system design agent.

Model: qwen3.5:27b (LARGE) with thinking mode always on.
Prompt: config/prompts/architect.md
See ARCHITECTURE.md §3.2.
"""
from __future__ import annotations

from typing import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class ArchitectAgent(AgentBase):
    name = "ARCHITECT"
    model_key = "large"
    prompt_file = "architect"
    supported_actions = {
        AgentAction.CONSULT_AGENT,   # may consult RESEARCHER, ANALYZER
        AgentAction.READ_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.RECALL_CONTEXT,
    }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        async for token in self.stream_llm(request):
            yield token
