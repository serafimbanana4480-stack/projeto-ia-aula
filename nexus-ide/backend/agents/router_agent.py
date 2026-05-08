"""ROUTER — intent classifier (NANO / qwen3.5:2b).

Prompt: config/prompts/router.md
See ARCHITECTURE.md §3.1. Implementation detail: emits strict JSON only.
"""
from __future__ import annotations

from typing import AsyncIterator

from .base import AgentBase, AgentRequest


class RouterAgent(AgentBase):
    """Pure JSON classifier. Used indirectly via :func:`router.route_with_model`.

    This class exists so the router conforms to the generic AgentBase contract
    (useful for observability and consistent metrics labels). It is *not*
    invoked by the orchestrator; the router module calls ``chat_complete``
    directly to enforce a non-streaming JSON response.
    """

    name = "ROUTER"
    model_key = "nano"
    prompt_file = "router"
    supported_actions = set()

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        # Even though routing is normally invoked non-streamed, expose a
        # streaming variant for debugging & uniformity.
        async for token in self.stream_llm(request, temperature=0.1):
            yield token
