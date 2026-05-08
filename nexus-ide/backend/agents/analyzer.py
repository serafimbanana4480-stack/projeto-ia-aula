"""ANALYZER — critical code/architecture reviewer.

Model: qwen3.5:27b (LARGE) with thinking mode.
Prompt: config/prompts/analyzer.md
See ARCHITECTURE.md §3.5.
"""
from __future__ import annotations

from typing import AsyncIterator

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
        async for token in self.stream_llm(request):
            yield token
