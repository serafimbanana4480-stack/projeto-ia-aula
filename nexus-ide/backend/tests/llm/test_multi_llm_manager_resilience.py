"""Regression tests for multi-provider stream and embedding resilience."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from backend.llm.multi_llm_manager import MultiLLMManager


class _Provider:
    def __init__(self) -> None:
        self.stream_calls = 0
        self.embed_calls = 0


class _FailsBeforeOutput(_Provider):
    async def chat_stream(self, *args, **kwargs) -> AsyncIterator[str]:
        self.stream_calls += 1
        raise RuntimeError("provider unavailable")
        yield ""  # pragma: no cover - makes this an async generator


class _FailsAfterOutput(_Provider):
    async def chat_stream(self, *args, **kwargs) -> AsyncIterator[str]:
        self.stream_calls += 1
        yield "partial"
        raise RuntimeError("connection dropped")


class _Healthy(_Provider):
    async def chat_stream(self, *args, **kwargs) -> AsyncIterator[str]:
        self.stream_calls += 1
        yield "recovered"

    async def chat_complete(self, model, messages, **kwargs) -> str:
        return f"answer:{messages[0]['content']}"

    async def embed(self, texts: list[str], model: str, **kwargs) -> list[list[float]]:
        self.embed_calls += 1
        return [[float(index)] for index, _ in enumerate(texts)]


class _BrokenEmbed(_Provider):
    async def embed(self, texts: list[str], model: str, **kwargs) -> list[list[float]]:
        self.embed_calls += 1
        raise RuntimeError("embedding service unavailable")


@pytest.mark.asyncio
async def test_stream_fails_over_before_any_visible_token() -> None:
    manager = MultiLLMManager()
    broken = _FailsBeforeOutput()
    healthy = _Healthy()
    manager.register_provider("stream-pre-output-broken", broken, priority=0)
    manager.register_provider("stream-pre-output-healthy", healthy, priority=1)

    tokens = [
        token
        async for token in manager.chat_stream(
            "model", [{"role": "user", "content": "hello"}]
        )
    ]

    assert tokens == ["recovered"]
    assert broken.stream_calls == 1
    assert healthy.stream_calls == 1


@pytest.mark.asyncio
async def test_stream_never_fails_over_after_visible_token() -> None:
    manager = MultiLLMManager()
    partial = _FailsAfterOutput()
    healthy = _Healthy()
    manager.register_provider("stream-partial", partial, priority=0)
    manager.register_provider("stream-partial-healthy", healthy, priority=1)

    stream = manager.chat_stream("model", [{"role": "user", "content": "hello"}])
    assert await anext(stream) == "partial"
    with pytest.raises(RuntimeError, match="connection dropped"):
        await anext(stream)

    assert partial.stream_calls == 1
    assert healthy.stream_calls == 0


@pytest.mark.asyncio
async def test_embed_fails_over_to_a_provider_that_supports_it() -> None:
    manager = MultiLLMManager()
    broken = _BrokenEmbed()
    healthy = _Healthy()
    manager.register_provider("embedding-broken", broken, priority=0)
    manager.register_provider("embedding-healthy", healthy, priority=1)

    vectors = await manager.embed(["one", "two"], model="embed-model")

    assert vectors == [[0.0], [1.0]]
    assert broken.embed_calls == 1
    assert healthy.embed_calls == 1


@pytest.mark.asyncio
async def test_batch_complete_works_without_provider_specific_batch_api() -> None:
    manager = MultiLLMManager()
    healthy = _Healthy()
    manager.register_provider("batch-healthy", healthy, priority=0)

    results = await manager.batch_complete(
        [
            [{"role": "user", "content": "one"}],
            [{"role": "user", "content": "two"}],
        ],
        model="model",
    )

    assert results == ["answer:one", "answer:two"]
