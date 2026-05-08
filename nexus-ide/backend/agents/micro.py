"""MICRO — fast factoid agent.

Not listed among the 9 specialised roles in §3 of the architecture, but the
Router prompt can legitimately route here for trivial questions (e.g. "what is
HTTP?"). Using the SMALL model with a concise-answer instruction keeps latency
well under one second on common hardware.
"""
from __future__ import annotations

from typing import AsyncIterator

from backend.tools.ollama_client import ChatMessage

from .base import AgentBase, AgentRequest

_SYSTEM = (
    "You are NEXUS-MICRO. Answer the user's question in at most three sentences. "
    "Be factual. If you are not sure, say so. Never speculate."
)


class MicroAgent(AgentBase):
    name = "MICRO"
    model_key = "micro"
    prompt_file = "router"  # unused — overridden below

    def system_prompt(self) -> str:  # type: ignore[override]
        return _SYSTEM

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        # Override build_messages inline: we don't want the router prompt file.
        messages = [
            ChatMessage(role="system", content=_SYSTEM),
            *request.history,
            ChatMessage(role="user", content=request.query),
        ]
        from backend.config.settings import get_model_config

        cfg = get_model_config(self.model_key)
        async for token in request.client.chat_stream(
            model=cfg["id"],
            messages=messages,
            options={"temperature": 0.3, "num_predict": cfg.get("max_tokens", 1024)},
        ):
            yield token
