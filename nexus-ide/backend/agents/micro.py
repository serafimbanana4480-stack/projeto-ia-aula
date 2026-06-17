"""MICRO — fast factoid agent.

Not listed among the 9 specialised roles in §3 of the architecture, but the
Router prompt can legitimately route here for trivial questions (e.g. "what is
HTTP?"). Using the SMALL model with a concise-answer instruction keeps latency
well under one second on common hardware.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentBase, AgentRequest

_SYSTEM = (
    "You are NEXUS-MICRO. Answer the user's question in at most three sentences. "
    "Be factual. If you are not sure, say so. Never speculate."
)


class MicroAgent(AgentBase):
    name = "MICRO"
    model_key = "micro"
    prompt_file = "router"  # unused — kept for compatibility

    def system_prompt(self) -> str:
        return _SYSTEM

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        async for token in self.stream_llm(request, temperature=0.3):
            yield token
