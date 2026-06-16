"""OpenRouter provider for the NEXUS IDE.

OpenRouter exposes a fully OpenAI-compatible chat completions API at
https://openrouter.ai/api/v1.  We reuse :class:`OpenAIProvider` under the
hood but expose it as a first-party provider so that ``models.yaml`` and the
Settings page can list it alongside the other backends.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.llm.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


class OpenRouterProvider:
    """Provider wrapping OpenRouter's OpenAI-compatible API.

    Model aliases resolve to OpenRouter ``provider/{provider_name}/{model_name}``
    strings used in the ``model`` field of the chat completions request.
    """

    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

    MODEL_ALIASES: dict[str, str] = {
        "auto": "auto",
        # Popular models available through OpenRouter
        "openai/gpt-4o": "openai/gpt-4o",
        "openai/gpt-4o-mini": "openai/gpt-4o-mini",
        "anthropic/claude-3.5-sonnet": "anthropic/claude-3.5-sonnet",
        "anthropic/claude-3-opus": "anthropic/claude-3-opus",
        "google/gemini-2.0-flash": "google/gemini-2.0-flash-exp:free",
        "google/gemini-1.5-pro": "google/gemini-1.5-pro",
        "deepseek/deepseek-chat": "deepseek/deepseek-chat",
        "meta-llama/llama-4-maverick": "meta-llama/llama-4-maverick",
        "mistral/mistral-large": "mistral/mistral-large",
    }

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = OpenAIProvider(base_url=self._base_url, api_key=api_key)

    async def aclose(self) -> None:
        await self._client.aclose()

    def resolve_model(self, model: str) -> str:
        """Resolve a model alias to the OpenRouter model identifier."""
        return self.MODEL_ALIASES.get(model, model)

    async def chat_stream(self, model, messages, **kwargs):
        resolved = self.resolve_model(model)
        async for token in self._client.chat_stream(resolved, messages, **kwargs):
            yield token

    async def chat_complete(self, model, messages, **kwargs):
        resolved = self.resolve_model(model)
        return await self._client.chat_complete(resolved, messages, **kwargs)

    async def embed(self, texts, model, **kwargs):
        resolved = self.resolve_model(model)
        return await self._client.embed(texts, resolved)
