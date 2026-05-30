"""OpenAI-compatible provider for DeepSeek, Groq, OpenAI, etc."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx


class OpenAIProvider:
    """Provider for OpenAI-compatible APIs (DeepSeek, Groq, OpenAI, etc.)."""

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0),
        )

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
        """Stream chat completion from OpenAI-compatible API."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if options:
            for key in ("temperature", "max_tokens", "top_p", "frequency_penalty", "presence_penalty"):
                if key in options:
                    payload[key] = options[key]

        async with self._client.stream("POST", "/v1/chat/completions", json=payload) as resp:
            if resp.status_code != 200:
                text = await resp.aread()
                raise RuntimeError(f"OpenAI API error {resp.status_code}: {text.decode()}")

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
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if options:
            for key in ("temperature", "max_tokens", "top_p"):
                if key in options:
                    payload[key] = options[key]

        resp = await self._client.post("/v1/chat/completions", json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text}")

        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def embed(
        self,
        texts: list[str],
        model: str,
        **kwargs: Any,
    ) -> list[list[float]]:
        """Get embeddings for texts."""
        resp = await self._client.post(
            "/v1/embeddings",
            json={"model": model, "input": texts},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text}")

        data = resp.json()
        return [item["embedding"] for item in data["data"]]
