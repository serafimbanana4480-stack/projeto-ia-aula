"""Regression tests for Gemini REST streaming integration."""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.llm.gemini_provider import GeminiProvider


class _LineIterator:
    def __init__(self, lines: list[str]) -> None:
        self._lines = iter(lines)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        try:
            return next(self._lines)
        except StopIteration:
            raise StopAsyncIteration from None


class _StreamResponse:
    status_code = 200

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def aread(self) -> bytes:
        return b"error"

    def aiter_lines(self) -> _LineIterator:
        return _LineIterator(self._lines)


class _StreamClient:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def aclose(self) -> None:
        return None

    def stream(self, *args: Any, **kwargs: Any) -> _StreamResponse:
        self.calls.append((args, kwargs))
        return _StreamResponse(self._lines)


def _frame(text: str, *, usage: dict[str, int] | None = None) -> str:
    payload: dict[str, Any] = {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
    }
    if usage:
        payload["usageMetadata"] = usage
    return f"data: {json.dumps(payload)}"


class TestGeminiStreaming:
    async def test_sends_key_and_alt_sse_and_parses_multiple_sse_frames(self) -> None:
        provider = GeminiProvider(api_key="gemini-test-key")
        await provider.aclose()
        stream_client = _StreamClient(
            [
                "event: message",
                _frame("Hello"),
                _frame(
                    " world",
                    usage={"promptTokenCount": 3, "candidatesTokenCount": 2, "totalTokenCount": 5},
                ),
                "data: [DONE]",
            ]
        )
        provider._client = stream_client  # type: ignore[assignment]

        tokens = [
            token
            async for token in provider.chat_stream(
                "gemini-2.5-flash",
                [{"role": "user", "content": "Say hello"}],
                options={"num_predict": 42, "top_p": 0.8},
            )
        ]

        assert tokens == ["Hello", " world"]
        assert len(stream_client.calls) == 1
        _, kwargs = stream_client.calls[0]
        assert kwargs["params"] == {"key": "gemini-test-key", "alt": "sse"}
        assert kwargs["json"]["generationConfig"] == {"topP": 0.8, "maxOutputTokens": 42}
        assert provider.last_usage == {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}

    async def test_parses_legacy_json_array_without_terminating_after_first_chunk(self) -> None:
        provider = GeminiProvider(api_key="gemini-test-key")
        await provider.aclose()
        stream_client = _StreamClient(
            [
                json.dumps(
                    [
                        {"candidates": [{"content": {"parts": [{"text": "one"}]}}]},
                        {"candidates": [{"content": {"parts": [{"text": " two"}]}}]},
                    ]
                )
            ]
        )
        provider._client = stream_client  # type: ignore[assignment]

        tokens = [
            token
            async for token in provider.chat_stream(
                "gemini-2.5-flash", [{"role": "user", "content": "Count"}]
            )
        ]

        assert tokens == ["one", " two"]

    async def test_empty_stream_is_an_error_not_a_blank_answer(self) -> None:
        provider = GeminiProvider(api_key="gemini-test-key")
        await provider.aclose()
        provider._client = _StreamClient(["data: [DONE]"])  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="without text content"):
            async for _ in provider.chat_stream(
                "gemini-2.5-flash", [{"role": "user", "content": "Hello"}]
            ):
                pass


def test_generation_config_uses_documented_gemini_field_names() -> None:
    assert GeminiProvider._generation_config(
        {"temperature": 0.2, "max_tokens": 128, "top_p": 0.9, "top_k": 32}
    ) == {"temperature": 0.2, "topP": 0.9, "topK": 32, "maxOutputTokens": 128}
