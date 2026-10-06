"""Async OpenCode Go API client with streaming support and retry logic.

Implements a Chat Completions client for the OpenCode Go API
(https://opencode.ai/zen/go/v1/chat/completions) that is interface-compatible
with the existing :class:`OllamaClient`.

Supports:
- Chat streaming (SSE/JSON streaming)
- List models
- Check model availability
- Retry logic with exponential backoff
- Timeout handling

Usage:
    client = OpenCodeClient(api_key="...", api_url="https://opencode.ai/zen/go/v1")
    async for token in client.chat_stream("deepseek-v4-flash", messages):
        print(token)
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)

# Retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_MAX = 30.0

# HTTP status codes that indicate transient errors
TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class ChatMessage:
    """A single turn in a chat exchange, matching the OpenCode API schema."""

    role: str  # "system" | "user" | "assistant"
    content: str
    timestamp: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class OpenCodeError(RuntimeError):
    """Raised when the OpenCode API returns a non-2xx response or invalid JSON."""

    def __init__(self, message: str, status_code: int | None = None, is_transient: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.is_transient = is_transient


class OpenCodeConnectionError(OpenCodeError):
    """Raised when connection to the OpenCode API fails."""

    def __init__(self, message: str):
        super().__init__(message, status_code=None, is_transient=True)


class OpenCodeTransientError(OpenCodeError):
    """Raised for transient errors (timeout, 5xx) that can be retried."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message, status_code=status_code, is_transient=True)


class OpenCodePermanentError(OpenCodeError):
    """Raised for permanent errors (4xx) that should not be retried."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message, status_code=status_code, is_transient=False)


class OpenCodeClient:
    """Async client for the OpenCode Go Chat Completions API.

    Interface-compatible with :class:`OllamaClient` for the core methods
    (chat_stream, ping, list_models, check_model_available).

    Uses ``httpx`` for HTTP transport. One instance per process, shared via
    FastAPI lifespan.

    Features:
    - SSE streaming for chat completions
    - Automatic retry with exponential backoff for transient errors
    - Health check via ping()/list_models()
    - Model availability checking
    - Compatible with existing OllamaClient interface
    """

    def __init__(
        self,
        api_key: str = "",
        api_url: str = "https://opencode.ai/zen/go/v1",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_max: float = DEFAULT_BACKOFF_MAX,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport

        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        self._client = httpx.AsyncClient(
            base_url=self._api_url,
            headers=headers,
            transport=transport,
            timeout=timeout,
        )
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Chat streaming (main interface)
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        model: str,
        messages: list[ChatMessage],
        *,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens from the OpenCode Go API.

        Yields **content deltas** (not full messages). The API returns
        server-sent events (SSE) with ``data: {...}`` lines. The final
        event has ``"finish_reason": "stop"`` which terminates the stream.

        Args:
            model: Model identifier (e.g. 'deepseek-v4-flash').
            messages: Chat conversation history.
            options: Additional parameters (temperature, max_tokens, etc.).

        Yields:
            Content delta strings as they arrive.

        Raises:
            OpenCodeError: On HTTP failure or malformed chunks.
            OpenCodeConnectionError: If the API server is unreachable.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "stream": True,
        }
        if options:
            # Map Ollama-style options to OpenCode API params
            if "temperature" in options:
                payload["temperature"] = options["temperature"]
            if "max_tokens" in options:
                payload["max_tokens"] = options["max_tokens"]
            if "top_p" in options:
                payload["top_p"] = options["top_p"]
            if "stop" in options:
                payload["stop"] = options["stop"]

        try:
            async with self._client.stream(
                "POST", "/chat/completions", json=payload
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    body_text = body.decode("utf-8", errors="replace")[:500]
                    if resp.status_code in TRANSIENT_STATUS_CODES:
                        raise OpenCodeTransientError(
                            f"OpenCode /chat/completions {resp.status_code}: {body_text}",
                            status_code=resp.status_code,
                        )
                    else:
                        raise OpenCodePermanentError(
                            f"OpenCode /chat/completions {resp.status_code}: {body_text}",
                            status_code=resp.status_code,
                        )

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    # Handle SSE format: "data: {...}"
                    data_str = line[6:] if line.startswith("data: ") else line

                    if data_str.strip() == "[DONE]":
                        return

                    chunk = _parse_chunk(data_str)
                    if chunk is None:
                        continue

                    # OpenAI-compatible delta format
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})
                    finish_reason = choices[0].get("finish_reason")
                    if finish_reason == "stop":
                        return

                    content = delta.get("content", "")
                    if content:
                        yield content

        except httpx.ConnectError as e:
            raise OpenCodeConnectionError(
                f"Cannot connect to OpenCode API at {self._api_url}: {e}"
            ) from e
        except httpx.TimeoutException as e:
            raise OpenCodeTransientError(
                f"Timeout in OpenCode request: {e}"
            ) from e

    async def chat_complete(
        self,
        model: str,
        messages: list[ChatMessage],
        *,
        options: dict[str, Any] | None = None,
    ) -> str:
        """Non-streaming variant. Returns the full concatenated content string."""
        parts: list[str] = []
        async for token in self.chat_stream(model, messages, options=options):
            parts.append(token)
        return "".join(parts)

    # ------------------------------------------------------------------
    # Health / Discovery
    # ------------------------------------------------------------------

    async def ping(self) -> bool:
        """Health check: verify the OpenCode API is reachable.

        Returns True if the /models endpoint responds, False otherwise.
        """
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=10.0)
            ) as client:
                headers = {}
                if self._api_key:
                    headers["Authorization"] = f"Bearer {self._api_key}"
                resp = await client.get(
                    f"{self._api_url}/models",
                    headers=headers,
                )
                return resp.status_code == 200
        except Exception as e:
            logger.debug("OpenCode ping failed: %s", e)
            return False

    async def list_models(self) -> list[dict[str, Any]]:
        """List available models from the OpenCode API.

        Returns a list of model dicts (each with 'id', 'name', etc.).

        Raises:
            OpenCodeConnectionError: If the API is unreachable.
            OpenCodePermanentError: On non-2xx response.
        """
        try:
            headers = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            resp = await self._client.get("/models", headers=headers)
            if resp.status_code != 200:
                raise OpenCodePermanentError(
                    f"Failed to list models: status {resp.status_code}",
                    status_code=resp.status_code,
                )
            data = resp.json()
            return data if isinstance(data, list) else data.get("data", [])
        except httpx.ConnectError as e:
            raise OpenCodeConnectionError(
                f"Cannot connect to OpenCode API at {self._api_url}: {e}"
            ) from e
        except httpx.TimeoutException as e:
            raise OpenCodeTransientError(f"Timeout connecting to OpenCode API: {e}") from e

    async def check_model_available(self, model_id: str) -> bool:
        """Check if a specific model is available on the OpenCode API.

        Args:
            model_id: Model identifier (e.g. 'deepseek-v4-flash').

        Returns:
            True if the model is available, False otherwise.
        """
        try:
            models = await self.list_models()
            # Models list could be list of strings or list of dicts
            for m in models:
                if isinstance(m, dict):
                    if m.get("id") == model_id:
                        return True
                elif isinstance(m, str) and m == model_id:
                    return True
            return False
        except OpenCodeError:
            return False

    # ------------------------------------------------------------------
    # Retry wrapper
    # ------------------------------------------------------------------

    async def chat_stream_with_retry(
        self,
        model: str,
        messages: list[ChatMessage],
        *,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Stream chat completion with automatic retry on transient errors.

        Same as chat_stream but with exponential backoff retry logic for
        transient failures (timeouts, 5xx, rate limits).
        """
        last_error: OpenCodeError | None = None

        for attempt in range(self._max_retries + 1):
            try:
                async for token in self.chat_stream(model, messages, options=options):
                    yield token
                return
            except OpenCodeError as e:
                if not e.is_transient:
                    raise
                last_error = e
                if attempt < self._max_retries:
                    backoff = min(
                        self._backoff_base * (2**attempt),
                        self._backoff_max,
                    )
                    logger.warning(
                        "OpenCode request failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1,
                        self._max_retries + 1,
                        backoff,
                        e,
                    )
                    await asyncio.sleep(backoff)
                else:
                    raise

        if last_error:
            raise last_error

    # ------------------------------------------------------------------
    # Embeddings support
    # ------------------------------------------------------------------

    async def embed(self, text: str, model: str = "deepseek-v4-flash") -> list[float]:
        """Generate an embedding vector via the OpenCode API (if supported).

        Args:
            text: Text to embed.
            model: Model to use for embedding.

        Returns:
            List of float values representing the embedding.

        Raises:
            OpenCodeError: On HTTP failure or empty response.
        """
        payload: dict[str, Any] = {"model": model, "input": text}
        try:
            resp = await self._client.post("/embeddings", json=payload)
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", errors="replace")[:500]
                if resp.status_code in TRANSIENT_STATUS_CODES:
                    raise OpenCodeTransientError(
                        f"OpenCode /embeddings {resp.status_code}: {body}",
                        status_code=resp.status_code,
                    )
                else:
                    raise OpenCodePermanentError(
                        f"OpenCode /embeddings {resp.status_code}: {body}",
                        status_code=resp.status_code,
                    )
            data = resp.json()
            embedding_data = data.get("data", [])
            if embedding_data and isinstance(embedding_data, list):
                embedding = embedding_data[0].get("embedding", [])
                if embedding:
                    return embedding
            raise OpenCodeError("Empty embedding returned by OpenCode API")
        except httpx.ConnectError as e:
            raise OpenCodeConnectionError(
                f"Cannot connect to OpenCode API at {self._api_url}: {e}"
            ) from e
        except httpx.TimeoutException as e:
            raise OpenCodeTransientError(
                f"Timeout in OpenCode embedding request: {e}"
            ) from e


def _parse_chunk(line: str) -> dict[str, Any] | None:
    """Parse a JSON chunk from an SSE stream.

    Returns None on malformed input (logged by caller).
    """
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
