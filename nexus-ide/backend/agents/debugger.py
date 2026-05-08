"""DEBUGGER — root cause analysis.

Model: qwen3-coder:7b (MEDIUM). Can execute code in Docker sandbox.
Prompt: config/prompts/debugger.md
See ARCHITECTURE.md §3.6.
"""
from __future__ import annotations

from typing import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class DebuggerAgent(AgentBase):
    name = "DEBUGGER"
    model_key = "medium"
    prompt_file = "debugger"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.EXECUTE_CODE,
        AgentAction.SEARCH_CODEBASE,
    }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        async for token in self.stream_llm(request):
            yield token
