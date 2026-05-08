"""DOCUMENTER — technical writing agent.

Model: qwen3.5:9b (SMALL).
Prompt: config/prompts/documenter.md
See ARCHITECTURE.md §3.7.
"""
from __future__ import annotations

from typing import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class DocumenterAgent(AgentBase):
    name = "DOCUMENTER"
    model_key = "small"
    prompt_file = "documenter"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.WRITE_FILE,
        AgentAction.SEARCH_CODEBASE,
    }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        async for token in self.stream_llm(request):
            yield token
