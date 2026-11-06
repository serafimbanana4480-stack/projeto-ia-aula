"""ROUTER — intent classifier (NANO / qwen3.5:2b).

Prompt: config/prompts/router.md
See ARCHITECTURE.md §3.1. Implementation detail: emits strict JSON only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentBase, AgentRequest


class RouterAgent(AgentBase):
    """Pure JSON classifier. Used indirectly via :func:`router.route_with_model`.

    Deprecated for orchestration: production routing uses ``chat_primary`` /
    ``orchestrator/router``. This class exists for the AgentBase contract and
    metrics labels only; the orchestrator calls ``chat_complete`` directly.
    """

    name = "ROUTER"
    model_key = "nano"
    prompt_file = "router"
    supported_actions = set()

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        # Even though routing is normally invoked non-streamed, expose a
        # streaming variant for debugging & uniformity.
        async for token in self.stream_llm(request, temperature=0.1):
            yield token
        # The stream completed without raising, so the run succeeded.  The
        # verdict is instance state and ``AgentBase.run`` resets it to False
        # before every run: an agent that never sets it (this one overrides
        # ``_execute`` and never calls the ReAct loop) would never be
        # remembered, and — worse — a run that RAISED would be remembered as
        # "Agent ROUTER completed a task".
        self._record_run_success(request, True)
