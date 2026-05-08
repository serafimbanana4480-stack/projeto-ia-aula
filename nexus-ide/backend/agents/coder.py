"""CODER — production code generation agent.

Model: qwen3-coder:30b (EXPERT, MoE). Context 256K, FIM support.
Prompt: config/prompts/coder.md
See ARCHITECTURE.md §3.4.
"""
from __future__ import annotations

from typing import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class CoderAgent(AgentBase):
    """Single-shot streaming code generator (Tier 1).

    ReAct loop with tool-use (read_file, write_file, execute_code) is deferred
    to a later phase. The current implementation simply relays the system
    prompt + user request to the model and streams tokens.
    """

    name = "CODER"
    # Tier 1 defaults to the 7B coder to keep memory reasonable on workstations.
    # Upgrade to "expert" (32B) once hardware is validated; the prompt is identical.
    model_key = "medium"
    prompt_file = "coder"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.WRITE_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.CONSULT_AGENT,
        AgentAction.EXECUTE_CODE,
    }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        async for token in self.stream_llm(request):
            yield token
