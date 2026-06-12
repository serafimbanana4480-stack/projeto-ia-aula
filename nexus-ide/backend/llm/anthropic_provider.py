"""Anthropic Claude provider for NEXUS IDE.

Uses the Anthropic Messages API directly via httpx.  The provider is
OpenAI-compatible in the sense that it exposes the same ``chat_stream``,
``chat_complete`` and ``embed`` interface used by the rest of the system.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from backend.config.settings import get_settings

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """Provider for Anthropic's Claude API."""

    DEFAULT_BASE_URL = "https://api.anthropic.com"

    # Small set of aliases to help users that configure legacy model names.
    MODEL_ALIASES: dict[str, str] = {
        "claude-opus": "claude-3-opus-20240229",
        "claude-sonnet": "claude-3-5-sonnet-20241022",
        "claude-haiku": "claude-3-haiku-20240307",
        "claude-3-5-sonnet": "claude-3-5-sonnet-20241022",
    }

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        if api_key is None:
            api_key = get_settings().anthropic_api_key
        self._api_key = api_key
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        headers: dict[str, str] = {
            "x-api-key": api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def resolve_model(self, model: str) -> str:
        """Resolve a model alias to the official Anthropic model name."""
        return self.MODEL_ALIASES.get(model, model)

    @staticmethod
    def _openai_to_anthropic_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """Normalize messages for the Anthropic Messages API.

        Anthropic only supports ``user`` and ``assistant`` roles and does not
        accept a leading ``system`` message in the ``messages`` array.  We move
        any system message to the dedicated ``system`` field.
        """
        system_texts: list[str] = []
        normalized: list[dict[str, str]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_texts.append(content)
                continue
            if role not in ("user", "assistant"):
                role = "user"
            normalized.append({"role": role, "content": content})
        system = "\n".join(system_texts) if system_texts else None
        return normalized, system

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a chat completion from the Anthropic Messages API."""
        normalized_messages, system = self._openai_to_anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": self.resolve_model(model),
            "messages": normalized_messages,
            "max_tokens": 4096,
            "stream": True,
        }
        if system:
            payload["system"] = system

        if options:
            if "temperature" in options:
                payload["temperature"] = options["temperature"]
            if "max_tokens" in options:
                payload["max_tokens"] = options["max_tokens"]
            if "top_p" in options:
                payload["top_p"] = options["top_p"]

        async with self._client.stream("POST", "/v1/messages", json=payload) as resp:
            if resp.status_code != 200:
                text = await resp.aread()
                raise RuntimeError(f"Anthropic API error {resp.status_code}: {text.decode()}")

            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or line.startswith("event:"):
                    continue
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    event_type = event.get("type")
                    if event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        text = delta.get("text", "")
                        if text:
                            yield text
                    elif event_type == "message_delta":
                        # End of stream signal; no content.
                        pass

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Non-streaming chat completion from the Anthropic Messages API."""
        normalized_messages, system = self._openai_to_anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": self.resolve_model(model),
            "messages": normalized_messages,
            "max_tokens": 4096,
            "stream": False,
        }
        if system:
            payload["system"] = system

        if options:
            if "temperature" in options:
                payload["temperature"] = options["temperature"]
            if "max_tokens" in options:
                payload["max_tokens"] = options["max_tokens"]
            if "top_p" in options:
                payload["top_p"] = options["top_p"]

        resp = await self._client.post("/v1/messages", json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"Anthropic API error {resp.status_code}: {resp.text}")

        data = resp.json()
        contents = data.get("content", [])
        return "".join(block.get("text", "") for block in contents if block.get("type") == "text")

    async def embed(
        self,
        texts: list[str],
        model: str,
        **kwargs: Any,
    ) -> list[list[float]]:
        """Anthropic does not expose an embedding API.

        Raise a clear error so callers can fall back to another provider or
        to the deterministic mock embedding.
        """
        raise NotImplementedError(
            "Anthropic does not provide an embedding endpoint. "
            "Use Ollama embeddings or another provider for RAG."
        )

    async def health_check(self) -> bool:
        """Check API key validity by issuing a minimal request."""
        if not self._api_key:
            return False
        try:
            resp = await self._client.get("/v1/models", timeout=10.0)
            return resp.status_code == 200
        except Exception as exc:
            logger.debug("Anthropic health check failed: %s", exc)
            return False
