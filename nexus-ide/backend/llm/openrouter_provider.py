"""OpenRouter provider for the NEXUS IDE.

OpenRouter exposes a fully OpenAI-compatible chat completions API at
https://openrouter.ai/api/v1.  We reuse :class:`OpenAIProvider` under the
hood but expose it as a first-party provider so that ``models.yaml`` and the
Settings page can list it alongside the other backends.
"""

from __future__ import annotations

import logging

from backend.llm.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


class OpenRouterProvider:
    """Provider wrapping OpenRouter's OpenAI-compatible API.

    Model aliases resolve to OpenRouter ``provider/{provider_name}/{model_name}``
    strings used in the ``model`` field of the chat completions request.
    """

    DEFAULT_BASE_URL = "https://openrouter.ai/api"

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
        "deepseek/deepseek-v4-flash": "deepseek/deepseek-v4-flash",
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
        # OpenRouter does not support /v1/embeddings — use local Ollama instead.
        from backend.tools.ollama_client import OllamaClient

        try:
            ollama = OllamaClient(base_url="http://localhost:11434")
            # ``OllamaClient.embed`` expects a list of texts and returns
            # ``list[list[float]]`` (one embedding per input). Calling it
            # with a single string in a loop would have appended a 1-D
            # vector per item, which the FAISS indexer misinterprets as a
            # 3-D array of shape (1, n, dim). Use the batch API instead.
            return await ollama.embed(texts, model="nomic-embed-text")
        except Exception as exc:
            # Fall back to hash-based embedding if Ollama is unavailable
            logger.warning("Ollama embed unavailable, using fallback: %s", exc)
            import hashlib
            import math

            def _hash_embed(text: str, dim: int = 384) -> list[float]:
                seed = hashlib.sha256(text.encode("utf-8")).digest()
                vec = []
                r = 0
                while len(vec) < dim:
                    block = hashlib.sha256(seed + r.to_bytes(4, "big")).digest()
                    vec.extend(((b / 255.0) - 0.5) * 2.0 for b in block)
                    r += 1
                vec = vec[:dim]
                norm = math.sqrt(sum(v * v for v in vec))
                return vec if norm == 0 else [v / norm for v in vec]

            return [_hash_embed(t) for t in texts]
