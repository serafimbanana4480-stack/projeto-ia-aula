"""Gemini (Google AI) provider for NEXUS IDE.

Uses the Google Generative AI API via the Google AI Python SDK. The provider
exposes the same chat_stream, chat_complete and embed interface used by the
rest of the system.

Endpoint:
    POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}
    POST https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?key={api_key}
    POST https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent?key={api_key}

Python SDK alternative (used here):
    pip install google-generativeai
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

# Defaults for the Google Generative AI API (as an OpenAI-compatible proxy also exists via Google)
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    """Provider for Google Gemini API (via REST v1beta)."""

    DEFAULT_BASE_URL = DEFAULT_BASE_URL

    # Model aliases → canonical API model names
    MODEL_ALIASES: dict[str, str] = {
        "gemini-2.0-flash": "gemini-2.0-flash",
        "gemini-2.0-flash-lite": "gemini-2.0-flash-lite",
        "gemini-2.5-flash": "gemini-2.5-flash",
        "gemini-2.5-pro": "gemini-2.5-pro",
        "gemini-1.5-pro": "gemini-1.5-pro",
        "gemini-1.5-flash": "gemini-1.5-flash",
        "gemini-1.5-flash-8b": "gemini-1.5-flash-8b",
        "gemini-embedding": "text-embedding-004",
        "gemini-embedding-001": "gemini-embedding-001",
    }

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
    ) -> None:
        if api_key is None:
            api_key = get_settings().gemini_api_key
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0),
        )
        # Internal — set after each successful chat call
        self._last_usage: dict[str, int] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def last_usage(self) -> dict[str, int]:
        """Return usage from the most recent call."""
        return dict(self._last_usage)

    def resolve_model(self, model: str) -> str:
        """Resolve a model alias to the canonical Gemini model name."""
        return self.MODEL_ALIASES.get(model, model)

    def _key_param(self) -> dict[str, str]:
        return {"key": self._api_key} if self._api_key else {}

    def _convert_messages(self, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Convert OpenAI-format messages to Gemini ``contents`` format.

        Maps: system → model instruction/bias, user → role=user, assistant → role=model.
        Gemini does not have a system role in contents; we fold the system message
        into the first user turn as a ``system_instruction`` field.
        """
        contents: list[dict[str, Any]] = []
        system_instruction: str | None = None
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_instruction = content
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})
            else:
                contents.append({"role": "user", "parts": [{"text": content}]})

        result: dict[str, Any] = {"contents": contents}
        if system_instruction:
            result["system_instruction"] = {"parts": [{"text": system_instruction}]}
        return result

    def _get_model_url(self, model: str, action: str) -> str:
        return f"/models/{model}:{action}"

    async def _post_with_retry(
        self,
        url: str,
        json_payload: dict[str, Any],
        max_retries: int = 3,
    ) -> httpx.Response:
        """POST with exponential backoff retry for transient errors."""
        params = self._key_param()
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = await self._client.post(url, json=json_payload, params=params)
                if resp.status_code < 500:
                    return resp
                last_exc = RuntimeError(f"Gemini API error {resp.status_code}: {resp.text}")
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                last_exc = exc
            if attempt < max_retries:
                wait = 2 ** (attempt - 1)
                logger.warning(
                    "Gemini request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt,
                    max_retries,
                    wait,
                    last_exc,
                )
                await asyncio.sleep(wait)
        raise last_exc or RuntimeError("Gemini request failed after retries")

    def _extract_usage_from_gemini(self, data: dict[str, Any]) -> dict[str, int]:
        """Extract token counts from a Gemini generateContent response."""
        usage_meta = data.get("usageMetadata", {})
        return {
            "input_tokens": usage_meta.get("promptTokenCount", 0) or 0,
            "output_tokens": usage_meta.get("candidatesTokenCount", 0) or 0,
            "total_tokens": usage_meta.get("totalTokenCount", 0) or 0,
        }

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream chat completion from Gemini API."""
        self._last_usage = {}
        resolved = self.resolve_model(model)
        payload: dict[str, Any] = self._convert_messages(messages)
        # Gemini uses generationConfig
        gen_config: dict[str, Any] = {}
        if options:
            for key in ("temperature", "max_output_tokens", "top_p", "top_k"):
                if key in options:
                    # Map common option names to Gemini equivalents
                    if key == "max_output_tokens" or key == "top_k":
                        gen_config[key] = options[key]
                    else:
                        gen_config[key] = options[key]
        if gen_config:
            payload["generationConfig"] = gen_config

        url = self._get_model_url(resolved, "streamGenerateContent")

        max_retries = 3
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                async with self._client.stream("POST", url, json=payload) as resp:
                    if resp.status_code != 200:
                        text = await resp.aread()
                        if resp.status_code >= 500 and attempt < max_retries:
                            wait = 2 ** (attempt - 1)
                            logger.warning(
                                "Gemini stream error %d (attempt %d/%d), retrying in %.1fs",
                                resp.status_code,
                                attempt,
                                max_retries,
                                wait,
                            )
                            await asyncio.sleep(wait)
                            continue
                        raise RuntimeError(f"Gemini API error {resp.status_code}: {text.decode()}")
                    last_chunk: dict[str, Any] = {}
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or line == "data: []":
                            continue
                        if line.startswith("["):
                            # Gemini streaming returns raw JSON array (one entry per chunk)
                            try:
                                chunks = json.loads(line)
                                for chunk in chunks:
                                    last_chunk = chunk
                                    candidates = chunk.get("candidates", [])
                                    if candidates:
                                        parts = candidates[0].get("content", {}).get("parts", [])
                                        for part in parts:
                                            text_piece = part.get("text", "")
                                            if text_piece:
                                                yield text_piece
                            except json.JSONDecodeError:
                                continue
                            # Extract usage from the last chunk if available
                            if last_chunk:
                                usage_gemini = last_chunk.get("usageMetadata", {})
                                if usage_gemini:
                                    self._last_usage = {
                                        "input_tokens": usage_gemini.get("promptTokenCount", 0) or 0,
                                        "output_tokens": usage_gemini.get("candidatesTokenCount", 0) or 0,
                                    }
                            return
                        if line.startswith("{"):
                            try:
                                chunk = json.loads(line)
                                last_chunk = chunk
                                candidates = chunk.get("candidates", [])
                                if candidates:
                                    parts = candidates[0].get("content", {}).get("parts", [])
                                    for part in parts:
                                        text_piece = part.get("text", "")
                                        if text_piece:
                                            yield text_piece
                            except json.JSONDecodeError:
                                continue
                    return
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < max_retries:
                    wait = 2 ** (attempt - 1)
                    logger.warning(
                        "Gemini stream network error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt,
                        max_retries,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)
        if last_exc:
            raise last_exc
        raise RuntimeError("Gemini stream failed after retries")

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Non-streaming chat completion."""
        resolved = self.resolve_model(model)
        payload: dict[str, Any] = self._convert_messages(messages)
        gen_config: dict[str, Any] = {}
        if options:
            for key in ("temperature", "max_output_tokens", "top_p", "top_k"):
                if key in options:
                    if key in ("max_output_tokens", "top_k"):
                        gen_config[key] = options[key]
                    else:
                        gen_config[key] = options[key]
        if gen_config:
            payload["generationConfig"] = gen_config

        url = self._get_model_url(resolved, "generateContent")
        resp = await self._post_with_retry(url, payload)
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text}")
        data = resp.json()
        self._last_usage = self._extract_usage_from_gemini(data)
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"Gemini returned no candidates. Response: {data}")
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    async def embed(
        self,
        texts: list[str],
        model: str,
        **kwargs: Any,
    ) -> list[list[float]]:
        """Get embeddings for texts via Gemini embedContent API."""
        resolved = self.resolve_model(model)
        results: list[list[float]] = []
        for text in texts:
            payload = {
                "model": f"models/{resolved}",
                "content": {"parts": [{"text": text}]},
            }
            resp = await self._post_with_retry(f"/models/{resolved}:embedContent", payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text}")
            data = resp.json()
            embedding = data.get("embedding", {}).get("values", [])
            results.append(list(map(float, embedding)))
        return results
