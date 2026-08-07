"""Endpoint construction regressions for OpenAI-compatible providers."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.llm.openai_provider import OpenAIProvider


def test_v1_base_url_does_not_duplicate_the_api_version() -> None:
    provider = OpenAIProvider("https://api.example.test/v1", api_key="test-key")
    try:
        request = provider._client.build_request("POST", "/v1/chat/completions")
        assert str(request.url) == "https://api.example.test/v1/chat/completions"
    finally:
        asyncio.run(provider.aclose())


def test_nested_v1_base_url_keeps_its_prefix_once() -> None:
    provider = OpenAIProvider("https://api.example.test/openai/v1", api_key="test-key")
    try:
        request = provider._client.build_request("POST", "/v1/embeddings")
        assert str(request.url) == "https://api.example.test/openai/v1/embeddings"
    finally:
        asyncio.run(provider.aclose())


@pytest.mark.asyncio
async def test_empty_stream_is_reported_as_a_provider_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    provider = OpenAIProvider("https://api.example.test/v1", api_key="test-key")
    await provider.aclose()
    provider._client = httpx.AsyncClient(
        base_url="https://api.example.test",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(RuntimeError, match="without text content"):
            async for _ in provider.chat_stream("model", [{"role": "user", "content": "hello"}]):
                pass
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_stream_error_payload_is_not_silently_discarded() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'data: {"error":"rate limited"}\n\n')

    provider = OpenAIProvider("https://api.example.test", api_key="test-key")
    await provider.aclose()
    provider._client = httpx.AsyncClient(
        base_url="https://api.example.test",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(RuntimeError, match="rate limited"):
            async for _ in provider.chat_stream("model", [{"role": "user", "content": "hello"}]):
                pass
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_closed_transport_is_recreated_before_request() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    provider = OpenAIProvider("https://api.example.test/v1", api_key="test-key")
    await provider.aclose()
    replacement = httpx.AsyncClient(
        base_url="https://api.example.test",
        transport=httpx.MockTransport(handler),
    )
    provider._new_client = lambda: replacement  # type: ignore[method-assign]
    try:
        # The provider must recover instead of leaking httpx's closed-client
        # error to the model fallback chain.
        assert await provider.chat_complete(
            "model", [{"role": "user", "content": "hello"}]
        ) == "ok"
    finally:
        await provider.aclose()
