"""Async Ollama HTTP client with streaming support.

Uses ``httpx`` directly against the Ollama ``/api/chat`` endpoint instead of the
``ollama`` SDK so that:

1. There is a single, explicit transport to mock in tests.
2. We have fine-grained control over timeouts and cancellation.
3. We do not pull a heavy dependency graph just for two endpoints.

Ollama server reference: https://github.com/ollama/ollama/blob/main/docs/api.md
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=5.0, pool=5.0)


@dataclass(frozen=True)
class ChatMessage:
    """A single turn in a chat exchange, matching Ollama's schema."""

    role: str  # "system" | "user" | "assistant"
    content: str
    timestamp: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content, "timestamp": self.timestamp}


class OllamaError(RuntimeError):
    """Raised when the Ollama server returns a non-2xx response or invalid JSON."""


class OllamaClient:
    """Thin async client. One instance per process, shared via FastAPI lifespan.

    Not thread-safe in the free-threading sense, but safe under a single asyncio
    event loop which is how FastAPI uses it.
    """

    def __init__(
        self,
        host: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=host.rstrip("/"),
            transport=transport,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat_stream(
        self,
        model: str,
        messages: list[ChatMessage],
        *,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens from Ollama.

        Yields **content deltas** (not full messages). Each line from Ollama is
        NDJSON containing a ``message.content`` increment. The final line has
        ``"done": true`` which terminates the stream.

        Raises :class:`OllamaError` on HTTP failure or malformed chunks.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "stream": True,
        }
        if options:
            payload["options"] = options

        async with self._client.stream("POST", "/api/chat", json=payload) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", errors="replace")
                raise OllamaError(f"ollama /api/chat {resp.status_code}: {body[:500]}")

            async for line in resp.aiter_lines():
                if not line:
                    continue
                chunk = _parse_chunk(line)
                if chunk is None:
                    continue
                if chunk.get("done"):
                    return
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content

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


def _parse_chunk(line: str) -> dict[str, Any] | None:
    """Parse one NDJSON line. Returns None on malformed input (logged by caller)."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
