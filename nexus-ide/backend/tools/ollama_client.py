"""Async Ollama HTTP client used by agents, routes, and embeddings."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_LIMITS = httpx.Limits(
    max_keepalive_connections=50,
    max_connections=100,
    keepalive_expiry=30.0,
)
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=5.0, pool=5.0)

_RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
_RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.TimeoutException,
)
_BACKOFF_DELAYS = (1, 2, 4, 8)
_MODEL_ALIASES = {
    # Preserve historical aliases that existed in the AirLLM-only phase.
    "q3b-4bit": "qwen2.5:3b",
    "coder3b-4bit": "qwen2.5-coder:3b",
    # Map legacy cloud model IDs to local Ollama fallbacks
    "deepseek/deepseek-v4-flash": "qwen2.5:1.5b",
    "deepseek/deepseek-chat": "qwen2.5:1.5b",
    "deepseek-chat": "qwen2.5:1.5b",
}


@dataclass(frozen=True)
class ChatMessage:
    """A single turn in a chat exchange."""

    role: str
    content: str
    timestamp: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content, "timestamp": self.timestamp}


class OllamaError(RuntimeError):
    """Raised when the Ollama server returns an error."""


class OllamaConnectionError(OllamaError):
    """Raised when the Ollama server cannot be reached."""


class OllamaModelError(OllamaError):
    """Raised when a requested model is not available."""


class OllamaClient:
    """Small async wrapper around the Ollama HTTP API."""

    def __init__(
        self,
        base_url: str = "",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: httpx.Timeout | float | None = None,
        limits: httpx.Limits | None = None,
    ) -> None:
        if not base_url:
            from backend.config.settings import get_settings

            base_url = get_settings().ollama_host

        self.base_url = (base_url or "http://localhost:11434").rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout or DEFAULT_TIMEOUT,
            limits=limits or DEFAULT_LIMITS,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _resolve_model(self, model: str) -> str:
        return _MODEL_ALIASES.get(model, model)

    @staticmethod
    def _normalize_messages(
        messages: list[dict[str, str]] | list[ChatMessage],
    ) -> list[dict[str, str]]:
        return [m.to_dict() if isinstance(m, ChatMessage) else dict(m) for m in messages]

    @staticmethod
    def _format_attempt_failure(
        method: str,
        path: str,
        attempt_count: int,
        failures: list[str],
    ) -> str:
        history = " | ".join(failures)
        return f"{method} {path} failed after {attempt_count} attempts: {history}"

    async def _request_with_retries(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        timeout: httpx.Timeout | float | None = None,
    ) -> httpx.Response:
        failures: list[str] = []
        max_attempts = len(_BACKOFF_DELAYS) + 1

        for attempt in range(1, max_attempts + 1):
            try:
                response = await self._client.request(
                    method,
                    path,
                    json=json_payload,
                    timeout=timeout,
                )
            except _RETRYABLE_EXCEPTIONS as exc:
                error_message = f"{type(exc).__name__}: {exc}"
                failures.append(error_message)
                if attempt == max_attempts:
                    raise OllamaConnectionError(
                        self._format_attempt_failure(method, path, max_attempts, failures)
                    ) from exc
                await asyncio.sleep(_BACKOFF_DELAYS[attempt - 1])
                continue

            if response.status_code < 400:
                return response

            body = response.text.strip()
            error_message = f"HTTP {response.status_code}: {body or response.reason_phrase}"

            if response.status_code == 404:
                raise OllamaModelError(error_message)

            if response.status_code not in _RETRYABLE_STATUS_CODES:
                raise OllamaError(error_message)

            failures.append(error_message)
            if attempt == max_attempts:
                raise OllamaError(
                    self._format_attempt_failure(method, path, max_attempts, failures)
                )

            await asyncio.sleep(_BACKOFF_DELAYS[attempt - 1])

        raise OllamaError(f"{method} {path} failed without a response")

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]] | list[ChatMessage],
        *,
        options: dict[str, Any] | None = None,
        **_: Any,
    ) -> AsyncIterator[str]:
        payload = {
            "model": self._resolve_model(model),
            "messages": self._normalize_messages(messages),
            "stream": True,
            "options": options or {},
        }
        response = await self._request_with_retries("POST", "/api/chat", json_payload=payload)

        async for line in response.aiter_lines():
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Skipping malformed Ollama stream line: %s", line)
                continue

            if data.get("done") is True:
                break

            chunk = data.get("message", {}).get("content")
            if chunk:
                yield chunk

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]] | list[ChatMessage],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        parts: list[str] = []
        async for token in self.chat_stream(model, messages, options=options, **kwargs):
            parts.append(token)
        return "".join(parts)

    async def embed(
        self,
        texts: list[str],
        model: str,
        **_: Any,
    ) -> list[list[float]]:
        payload = {"model": self._resolve_model(model), "input": texts}
        response = await self._request_with_retries("POST", "/api/embed", json_payload=payload)
        data = response.json()
        if "embeddings" in data and isinstance(data["embeddings"], list):
            return data["embeddings"]
        if "embedding" in data and isinstance(data["embedding"], list):
            return [data["embedding"]]
        raise OllamaError("Unexpected Ollama embedding response payload")

    async def health_check(self, timeout: float = 5.0) -> bool:
        try:
            response = await self._client.get("/api/tags", timeout=timeout)
            return response.status_code == 200
        except Exception:
            return False


__all__ = [
    "ChatMessage",
    "OllamaError",
    "OllamaConnectionError",
    "OllamaModelError",
    "OllamaClient",
    "DEFAULT_LIMITS",
    "DEFAULT_TIMEOUT",
]
