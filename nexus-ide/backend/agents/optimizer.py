"""OPTIMIZER — performance tuning agent.

Model: qwen3.5:9b (SMALL) with optional thinking mode.
Prompt: config/prompts/optimizer.md
See ARCHITECTURE.md §3.8.
"""
from __future__ import annotations

from typing import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class OptimizerAgent(AgentBase):
    name = "OPTIMIZER"
    model_key = "small"
    prompt_file = "optimizer"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.EXECUTE_CODE,
        AgentAction.SEARCH_CODEBASE,
    }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        async for token in self.stream_llm(request):
            yield token
