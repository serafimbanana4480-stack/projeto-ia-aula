"""Regression tests for Kimi endpoint and TLS setup."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from backend.llm.kimi_provider import KimiProvider


class _LineIterator:
    def __init__(self, events: list[str | Exception]) -> None:
        self._events = iter(events)

    def __aiter__(self) -> _LineIterator:
        return self

    async def __anext__(self) -> str:
        try:
            event = next(self._events)
        except StopIteration:
            raise StopAsyncIteration from None
        if isinstance(event, Exception):
            raise event
        return event


class _StreamResponse:
    status_code = 200

    def __init__(self, events: list[str | Exception]) -> None:
        self._events = events

    async def __aenter__(self) -> _StreamResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def aread(self) -> bytes:
        return b"error"

    def aiter_lines(self) -> _LineIterator:
        return _LineIterator(self._events)


class _StreamClient:
    def __init__(self, events: list[str | Exception]) -> None:
        self._events = events
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def stream(self, *args: Any, **kwargs: Any) -> _StreamResponse:
        self.calls.append((args, kwargs))
        return _StreamResponse(self._events)


def _text_frame(text: str) -> str:
    return "data: " + json.dumps(
        {"choices": [{"delta": {"content": text}}]}
    )


def test_default_base_url_does_not_duplicate_v1_in_chat_path() -> None:
    provider = KimiProvider(api_key="test-key")
    try:
        request = provider._client.build_request("POST", "/chat/completions")
        assert str(request.url) == "https://api.moonshot.cn/v1/chat/completions"
    finally:
        asyncio.run(provider.aclose())


def test_host_only_base_url_is_normalized_to_kimi_v1_root() -> None:
    provider = KimiProvider(base_url="https://mock.kimi.test", api_key="test-key")
    try:
        request = provider._client.build_request("POST", "/embeddings")
        assert str(request.url) == "https://mock.kimi.test/v1/embeddings"
    finally:
        asyncio.run(provider.aclose())


class TestKimiStreaming:
    async def test_parses_sse_text_until_done_frame(self) -> None:
        provider = KimiProvider(api_key="test-key")
        await provider.aclose()
        stream_client = _StreamClient(
            [_text_frame("Hello"), _text_frame(" world"), "data: [DONE]"]
        )
        provider._client = stream_client  # type: ignore[assignment]

        tokens = [
            token
            async for token in provider.chat_stream(
                "kimi-k2", [{"role": "user", "content": "Hello"}]
            )
        ]

        assert tokens == ["Hello", " world"]
        assert stream_client.calls[0][0][:2] == ("POST", "/chat/completions")

    async def test_empty_stream_raises_instead_of_returning_blank_response(self) -> None:
        provider = KimiProvider(api_key="test-key")
        await provider.aclose()
        provider._client = _StreamClient(["data: [DONE]"])  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="without text content"):
            async for _ in provider.chat_stream(
                "kimi-k2", [{"role": "user", "content": "Hello"}]
            ):
                pass

    async def test_network_failure_after_output_is_not_retried(self) -> None:
        provider = KimiProvider(api_key="test-key")
        await provider.aclose()
        stream_client = _StreamClient(
            [_text_frame("partial"), httpx.ReadError("connection lost")]
        )
        provider._client = stream_client  # type: ignore[assignment]

        stream = provider.chat_stream(
            "kimi-k2", [{"role": "user", "content": "Hello"}]
        )
        assert await anext(stream) == "partial"
        with pytest.raises(httpx.ReadError, match="connection lost"):
            await anext(stream)
        assert len(stream_client.calls) == 1
