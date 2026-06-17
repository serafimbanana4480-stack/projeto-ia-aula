"""Backwards-compatible Ollama provider export."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.tools.ollama_client import OllamaClient


class OllamaProvider(OllamaClient):
    """Ollama provider with a batch-friendly override.

    The base :class:`~backend.tools.ollama_client.OllamaClient` exposes a
    streaming ``chat_complete`` that we fan out concurrently here.  The
    Ollama HTTP API does not natively support a true batch ``/api/chat``
    request, so we simply call ``chat_complete`` once per message set
    using :func:`asyncio.gather`.
    """

    async def batch_complete(
        self,
        messages_list: list[list[dict[str, str]]],
        *,
        model: str | None = None,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """Run multiple chat completions concurrently for the given model."""
        if model is None:
            raise ValueError("OllamaProvider.batch_complete requires an explicit 'model'")
        return list(
            await asyncio.gather(
                *(
                    self.chat_complete(model, msgs, options=options, **kwargs)
                    for msgs in messages_list
                )
            )
        )


__all__ = ["OllamaProvider"]
