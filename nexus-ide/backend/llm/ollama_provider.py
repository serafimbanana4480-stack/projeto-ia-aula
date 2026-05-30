"""Ollama provider — wraps the existing OllamaClient."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from backend.tools.ollama_client import OllamaClient, ChatMessage


class OllamaProvider:
    """Provider for local Ollama instances."""

    def __init__(self, base_url: str, **kwargs: Any) -> None:
        self._client = OllamaClient(host=base_url)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream chat completion from Ollama."""
        chat_messages = [ChatMessage(role=m["role"], content=m["content"]) for m in messages]
        async for token in self._client.chat_stream(
            model=model,
            messages=chat_messages,
            options=options,
        ):
            yield token

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Non-streaming chat completion."""
        chat_messages = [ChatMessage(role=m["role"], content=m["content"]) for m in messages]
        return await self._client.chat_complete(
            model=model,
            messages=chat_messages,
            options=options,
        )

    async def embed(
        self,
        texts: list[str],
        model: str,
        **kwargs: Any,
    ) -> list[list[float]]:
        """Get embeddings from Ollama."""
        return await self._client.embed(texts=texts, model=model)
