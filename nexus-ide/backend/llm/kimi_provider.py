"""Kimi (Moonshot AI) provider.

Kimi's API is OpenAI-compatible (base_url = https://api.moonshot.cn/v1).
This provider uses httpx directly with retry logic and Kimi-specific model
defaults.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from backend.config.settings import get_settings

logger = logging.getLogger(__name__)


class KimiProvider:
    """Provider for Kimi (Moonshot AI) API."""

    # Kimi model aliases → actual API model names
    MODEL_ALIASES: dict[str, str] = {
        "moonshot-v1-8k": "moonshot-v1-8k",
        "moonshot-v1-32k": "moonshot-v1-32k",
        "moonshot-v1-128k": "moonshot-v1-128k",
        "kimi-k1": "kimi-k1",
        "kimi-k1.5": "kimi-k1.5",
        "kimi-k2": "kimi-k2",
        "kimi-k2.5": "kimi-k2.5",
        "kimi-light": "kimi-k2-light",
        "kimi-mini": "kimi-k2-mini",
        "kimi-embedding": "kimi-embedding-v1",
    }

    def __init__(
        self,
        base_url: str = "https://api.moonshot.cn/v1",
        api_key: str | None = None,
    ) -> None:
        if api_key is None:
            api_key = get_settings().kimi_api_key
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=httpx.Timeout(10.0, connect=10.0, read=60.0, write=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def resolve_model(self, model: str) -> str:
        """Resolve a model alias to the actual Kimi model name."""
        return self.MODEL_ALIASES.get(model, model)

    async def _post_with_retry(
        self,
        path: str,
        json_payload: dict[str, Any],
        max_retries: int = 3,
    ) -> httpx.Response:
        """POST with exponential backoff retry for transient errors."""
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = await self._client.post(path, json=json_payload)
                if resp.status_code < 500:
                    return resp
                last_exc = RuntimeError(f"Kimi API error {resp.status_code}: {resp.text}")
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                last_exc = exc
            if attempt < max_retries:
                wait = 2 ** (attempt - 1)
                logger.warning(
                    "Kimi request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt,
                    max_retries,
                    wait,
                    last_exc,
                )
                await asyncio.sleep(wait)
        raise last_exc or RuntimeError("Kimi request failed after retries")

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream chat completion from Kimi API."""
        payload: dict[str, Any] = {
            "model": self.resolve_model(model),
            "messages": messages,
            "stream": True,
        }
        if options:
            for key in (
                "temperature",
                "max_tokens",
                "top_p",
                "frequency_penalty",
                "presence_penalty",
            ):
                if key in options:
                    payload[key] = options[key]

        max_retries = 3
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                async with self._client.stream(
                    "POST", "/v1/chat/completions", json=payload
                ) as resp:
                    if resp.status_code != 200:
                        text = await resp.aread()
                        if resp.status_code >= 500 and attempt < max_retries:
                            wait = 2 ** (attempt - 1)
                            logger.warning(
                                "Kimi stream error %d (attempt %d/%d), retrying in %.1fs",
                                resp.status_code,
                                attempt,
                                max_retries,
                                wait,
                            )
                            await asyncio.sleep(wait)
                            continue
                        raise RuntimeError(f"Kimi API error {resp.status_code}: {text.decode()}")
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or line == "data: [DONE]":
                            continue
                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except (json.JSONDecodeError, IndexError):
                                continue
                    return
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < max_retries:
                    wait = 2 ** (attempt - 1)
                    logger.warning(
                        "Kimi stream network error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt,
                        max_retries,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)
        if last_exc:
            raise last_exc
        raise RuntimeError("Kimi stream failed after retries")

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Non-streaming chat completion."""
        payload: dict[str, Any] = {
            "model": self.resolve_model(model),
            "messages": messages,
            "stream": False,
        }
        if options:
            for key in ("temperature", "max_tokens", "top_p"):
                if key in options:
                    payload[key] = options[key]

        resp = await self._post_with_retry("/v1/chat/completions", payload)
        if resp.status_code != 200:
            raise RuntimeError(f"Kimi API error {resp.status_code}: {resp.text}")

        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def embed(
        self,
        texts: list[str],
        model: str,
        **kwargs: Any,
    ) -> list[list[float]]:
        """Get embeddings for texts."""
        payload = {"model": self.resolve_model(model), "input": texts}
        resp = await self._post_with_retry("/v1/embeddings", payload)
        if resp.status_code != 200:
            raise RuntimeError(f"Kimi API error {resp.status_code}: {resp.text}")

        data = resp.json()
        return [item["embedding"] for item in data["data"]]
