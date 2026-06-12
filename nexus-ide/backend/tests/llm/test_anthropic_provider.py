"""Tests for backend.llm.anthropic_provider.

Covers:
- Model alias resolution
- Message normalization (OpenAI → Anthropic)
- chat_complete / chat_stream parsing
- embed() raises NotImplementedError
- health_check with/without API key and mocked httpx
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.llm.anthropic_provider import AnthropicProvider


def _anthropic_sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Build one SSE event line as returned by Anthropic streaming API.

    Anthropic places the event type both in the ``event:`` field and inside
    the JSON payload as ``type``.
    """
    payload = {"type": event_type, **data}
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> Iterator[AnthropicProvider]:
    """Provider wired to a fake API key and default base URL."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-key")
    from backend.config.settings import get_settings

    get_settings.cache_clear()
    p = AnthropicProvider(api_key="fake-anthropic-key")
    try:
        yield p
    finally:
        # close the async client synchronously for test cleanup
        try:
            import asyncio

            asyncio.get_running_loop().run_until_complete(p.aclose())
        except RuntimeError:
            pass


class TestModelResolution:
    def test_resolve_model_alias(self) -> None:
        p = AnthropicProvider(api_key="x")
        assert p.resolve_model("claude-opus") == "claude-3-opus-20240229"
        assert p.resolve_model("claude-sonnet") == "claude-3-5-sonnet-20241022"
        assert p.resolve_model("claude-haiku") == "claude-3-haiku-20240307"
        assert p.resolve_model("claude-3-5-sonnet") == "claude-3-5-sonnet-20241022"

    def test_resolve_unknown_model_passthrough(self) -> None:
        p = AnthropicProvider(api_key="x")
        assert p.resolve_model("custom-model") == "custom-model"


class TestMessageNormalization:
    def test_system_message_extracted(self) -> None:
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        normalized, system = AnthropicProvider._openai_to_anthropic_messages(messages)
        assert system == "You are a helpful assistant."
        assert normalized == [{"role": "user", "content": "Hello"}]

    def test_multiple_system_messages_joined(self) -> None:
        messages = [
            {"role": "system", "content": "Line 1."},
            {"role": "system", "content": "Line 2."},
            {"role": "user", "content": "Hello"},
        ]
        normalized, system = AnthropicProvider._openai_to_anthropic_messages(messages)
        assert system == "Line 1.\nLine 2."
        assert len(normalized) == 1

    def test_unsupported_roles_become_user(self) -> None:
        messages = [
            {"role": "developer", "content": "dev"},
            {"role": "user", "content": "Hello"},
        ]
        normalized, system = AnthropicProvider._openai_to_anthropic_messages(messages)
        assert system is None
        assert all(msg["role"] in ("user", "assistant") for msg in normalized)


class TestChatComplete:
    async def test_chat_complete_success(self, provider: AnthropicProvider) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/messages"
            body = json.loads(request.content)
            assert body["model"] == "claude-3-haiku-20240307"
            assert body["messages"] == [{"role": "user", "content": "Hello"}]
            assert body["system"] == "You are helpful."
            return httpx.Response(
                200,
                json={
                    "content": [
                        {"type": "text", "text": "Hi there!"},
                        {"type": "thinking", "thinking": "ignored"},
                    ]
                },
            )

        provider._client = httpx.AsyncClient(
            base_url=provider._base_url,
            headers={"x-api-key": provider._api_key or "", "anthropic-version": "2023-06-01"},
            transport=httpx.MockTransport(handler),
        )

        result = await provider.chat_complete(
            model="claude-haiku",
            messages=[
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello"},
            ],
        )
        assert result == "Hi there!"

    async def test_chat_complete_error(self, provider: AnthropicProvider) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="unauthorized")

        provider._client = httpx.AsyncClient(
            base_url=provider._base_url,
            headers={"x-api-key": provider._api_key or "", "anthropic-version": "2023-06-01"},
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(RuntimeError, match="Anthropic API error 401"):
            await provider.chat_complete(
                model="claude-haiku",
                messages=[{"role": "user", "content": "Hello"}],
            )


class _MockStreamResponse:
    """Minimal async-context-manager stand-in for httpx streaming response."""

    def __init__(self, status_code: int, lines: list[str]) -> None:
        self.status_code = status_code
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def aread(self) -> bytes:
        return b"error"

    def aiter_lines(self) -> "_MockLineIterator":
        return _MockLineIterator(self._lines)


class _MockLineIterator:
    def __init__(self, lines: list[str]) -> None:
        self._lines = iter(lines)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        try:
            return next(self._lines)
        except StopIteration:
            raise StopAsyncIteration


class _MockAsyncClient:
    """Client that returns a canned streaming response."""

    def __init__(self, status_code: int, lines: list[str]) -> None:
        self._status_code = status_code
        self._lines = lines

    async def aclose(self) -> None:
        pass

    def stream(self, *args: object, **kwargs: object) -> _MockStreamResponse:
        return _MockStreamResponse(self._status_code, self._lines)


class TestChatStream:
    async def test_chat_stream_yields_text_deltas(self) -> None:
        raw_sse = (
            _anthropic_sse_event(
                "content_block_delta",
                {"delta": {"type": "text_delta", "text": "Hello"}},
            )
            + _anthropic_sse_event(
                "content_block_delta",
                {"delta": {"type": "text_delta", "text": " world"}},
            )
            + _anthropic_sse_event("message_delta", {"stop_reason": "end_turn"})
        )
        lines = [line for line in raw_sse.splitlines()]
        provider = AnthropicProvider(api_key="fake-key")
        provider._client = _MockAsyncClient(200, lines)  # type: ignore[assignment]

        tokens = [
            token
            async for token in provider.chat_stream(
                model="claude-haiku",
                messages=[{"role": "user", "content": "Hello"}],
            )
        ]
        assert tokens == ["Hello", " world"]

    async def test_chat_stream_http_error(self) -> None:
        provider = AnthropicProvider(api_key="fake-key")
        provider._client = _MockAsyncClient(500, [])  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="Anthropic API error 500"):
            async for _ in provider.chat_stream(
                model="claude-haiku",
                messages=[{"role": "user", "content": "Hello"}],
            ):
                pass


class TestEmbedAndHealth:
    async def test_embed_raises_not_implemented(self, provider: AnthropicProvider) -> None:
        with pytest.raises(NotImplementedError):
            await provider.embed(["hello"], model="claude-haiku")

    async def test_health_check_without_key_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        from backend.config.settings import get_settings

        get_settings.cache_clear()
        p = AnthropicProvider(api_key="")
        assert await p.health_check() is False

    async def test_health_check_success(self, provider: AnthropicProvider) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/models"
            return httpx.Response(200, json={"data": []})

        provider._client = httpx.AsyncClient(
            base_url=provider._base_url,
            headers={"x-api-key": provider._api_key or "", "anthropic-version": "2023-06-01"},
            transport=httpx.MockTransport(handler),
        )

        assert await provider.health_check() is True


class TestProviderRegistration:
    def test_factory_creates_anthropic_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        from backend.config.settings import get_settings

        get_settings.cache_clear()

        from backend.llm.factory import create_llm_client

        client = create_llm_client()
        assert client.__class__.__name__ == "AnthropicProvider"
