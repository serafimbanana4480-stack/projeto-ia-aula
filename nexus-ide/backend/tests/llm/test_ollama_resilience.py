"""Resilience tests for OllamaClient, OllamaProvider, and factory fallback chain."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.llm.airllm_provider import (
    AIRLLM_AVAILABLE,
    AirLLMProvider,
    CircuitBreaker,
    CircuitState,
)
from backend.llm.dev_provider import DevProvider
from backend.llm.factory import MockProvider, ResilientLLMProvider, _build_fallback_chain

OllamaProvider = AirLLMProvider  # backwards-compat alias for existing tests
from backend.tests.conftest import make_stream_response  # noqa: E402
from backend.tools.ollama_client import ChatMessage, OllamaClient, OllamaError  # noqa: E402


@pytest.fixture(autouse=True)
def _legacy_fallback_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """These chain-shape tests exercise legacy paid/simulation fallback semantics."""
    monkeypatch.setenv("NEXUS_FREE_ONLY", "false")

# ---------------------------------------------------------------------------
# Retry logic tests
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="OllamaClient is now a shim over AirLLMProvider; HTTP retry logic is no longer applicable"
)
class TestRetryLogic:
    async def test_retry_on_connect_error_then_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Transport errors should be retried up to 3 times with backoff."""
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("backend.tools.ollama_client.asyncio.sleep", fake_sleep)

        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise httpx.ConnectError("connection refused")
            return make_stream_response(["ok"])

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            result = await client.chat_complete("m", [ChatMessage(role="user", content="hi")])
            assert result == "ok"
            assert call_count == 3
            assert sleeps == [1, 2]
        finally:
            await client.aclose()

    async def test_retry_exhausted_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After 4 retries an OllamaError with full history should be raised."""
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("backend.tools.ollama_client.asyncio.sleep", fake_sleep)

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(OllamaError) as excinfo:
                await client.chat_complete("m", [ChatMessage(role="user", content="hi")])
            assert "failed after 5 attempts" in str(excinfo.value)
            assert "ConnectError" in str(excinfo.value)
            assert sleeps == [1, 2, 4, 8]
        finally:
            await client.aclose()

    async def test_no_retry_on_4xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """4xx client errors should not be retried."""
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("backend.tools.ollama_client.asyncio.sleep", fake_sleep)

        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(404, text="not found")

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(OllamaError) as excinfo:
                await client.chat_complete("m", [ChatMessage(role="user", content="hi")])
            assert "404" in str(excinfo.value)
            assert call_count == 1
            assert sleeps == []
        finally:
            await client.aclose()

    async def test_retry_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TimeoutException should be retried."""
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("backend.tools.ollama_client.asyncio.sleep", fake_sleep)

        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.TimeoutException("timed out")
            return make_stream_response(["ok"])

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            result = await client.chat_complete("m", [ChatMessage(role="user", content="hi")])
            assert result == "ok"
            assert call_count == 2
            assert sleeps == [1]
        finally:
            await client.aclose()

    async def test_retry_on_503_then_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTTP 503 should be retried with backoff."""
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("backend.tools.ollama_client.asyncio.sleep", fake_sleep)

        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return httpx.Response(503, text="upstream busy")
            return make_stream_response(["ok"])

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            result = await client.chat_complete("m", [ChatMessage(role="user", content="hi")])
            assert result == "ok"
            assert call_count == 3
            assert sleeps == [1, 2]
        finally:
            await client.aclose()

    async def test_retry_on_500_then_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTTP 500 should be retried with backoff."""
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("backend.tools.ollama_client.asyncio.sleep", fake_sleep)

        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(500, text="internal error")
            return make_stream_response(["ok"])

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            result = await client.chat_complete("m", [ChatMessage(role="user", content="hi")])
            assert result == "ok"
            assert call_count == 2
            assert sleeps == [1]
        finally:
            await client.aclose()

    async def test_retry_503_exhausted_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After 4 retries on HTTP 503 an OllamaError with history should be raised."""
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("backend.tools.ollama_client.asyncio.sleep", fake_sleep)

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="upstream busy")

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(OllamaError) as excinfo:
                await client.chat_complete("m", [ChatMessage(role="user", content="hi")])
            assert "failed after 5 attempts" in str(excinfo.value)
            assert "HTTP 503" in str(excinfo.value)
            assert sleeps == [1, 2, 4, 8]
        finally:
            await client.aclose()


# ---------------------------------------------------------------------------
# Health check tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not AIRLLM_AVAILABLE, reason="AirLLM not installed")
class TestHealthCheckAirLLM:
    async def test_health_check_success(self) -> None:
        """Should return True when AirLLM is available."""
        client = AirLLMProvider()
        try:
            assert await client.health_check() is True
        finally:
            await client.aclose()

    async def test_health_check_failure_when_airllm_not_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return False when AirLLM is not available."""
        monkeypatch.setattr("backend.llm.airllm_provider.AIRLLM_AVAILABLE", False)
        client = AirLLMProvider()
        try:
            assert await client.health_check() is False
        finally:
            await client.aclose()


# ---------------------------------------------------------------------------
# Embed tests
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="OllamaClient embed via HTTP is obsolete; AirLLMProvider uses local sentence-transformers"
)
class TestEmbed:
    async def test_embed_success(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            assert req.url.path == "/api/embed"
            return httpx.Response(
                200,
                json={"embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]},
            )

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            result = await client.embed(["hello", "world"], model="nomic")
            assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        finally:
            await client.aclose()

    async def test_embed_old_api_format(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            result = await client.embed(["hello"], model="nomic")
            assert result == [[0.1, 0.2, 0.3]]
        finally:
            await client.aclose()

    async def test_embed_4xx_no_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_sleep(delay: float) -> None:
            pass

        monkeypatch.setattr("backend.tools.ollama_client.asyncio.sleep", fake_sleep)
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(400, text="bad request")

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(OllamaError) as excinfo:
                await client.embed(["hello"], model="nomic")
            assert "400" in str(excinfo.value)
            assert call_count == 1
        finally:
            await client.aclose()


# ---------------------------------------------------------------------------
# Circuit breaker tests
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.can_execute() is True

    def test_opens_after_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.can_execute() is True
        cb.record_failure()
        assert cb.can_execute() is False
        assert cb.state == CircuitState.OPEN

    def test_half_open_after_timeout(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        with patch("backend.llm.airllm_provider.time.time", return_value=time.time() + 15):
            assert cb.can_execute() is True
            assert cb.state == CircuitState.HALF_OPEN

    def test_closes_on_success_in_half_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=10.0)
        cb.record_failure()
        cb.record_failure()

        with patch("backend.llm.airllm_provider.time.time", return_value=time.time() + 15):
            cb.record_success()
            assert cb.state == CircuitState.CLOSED
            assert cb.failure_count == 0

    def test_reopens_on_failure_in_half_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=10.0)
        cb.record_failure()
        cb.record_failure()

        with patch("backend.llm.airllm_provider.time.time", return_value=time.time() + 15):
            cb.record_failure()
            assert cb.state == CircuitState.OPEN


class TestAirLLMProviderCircuitBreaker:
    def test_circuit_opens_after_threshold(self) -> None:
        """Circuit breaker should open after threshold failures."""
        provider = AirLLMProvider()
        provider._circuit.failure_threshold = 3
        provider._circuit.record_failure()
        provider._circuit.record_failure()
        assert provider._circuit.can_execute() is True
        provider._circuit.record_failure()
        assert provider._circuit.can_execute() is False
        assert provider._circuit.state == CircuitState.OPEN

    def test_circuit_half_open_after_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = AirLLMProvider()
        provider._circuit.failure_threshold = 2
        provider._circuit.reset_timeout = 10.0
        provider._circuit.record_failure()
        provider._circuit.record_failure()
        assert provider._circuit.state == CircuitState.OPEN
        with patch("backend.llm.airllm_provider.time.time", return_value=time.time() + 15):
            assert provider._circuit.can_execute() is True
            assert provider._circuit.state == CircuitState.HALF_OPEN

    def test_circuit_closes_on_success_in_half_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = AirLLMProvider()
        provider._circuit.failure_threshold = 2
        provider._circuit.record_failure()
        provider._circuit.record_failure()
        with patch("backend.llm.airllm_provider.time.time", return_value=time.time() + 15):
            provider._circuit.record_success()
            assert provider._circuit.state == CircuitState.CLOSED
            assert provider._circuit.failure_count == 0

    async def test_chat_complete_checks_circuit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = AirLLMProvider()
        provider._circuit.state = CircuitState.OPEN
        provider._circuit.last_failure_time = time.time()
        with pytest.raises(RuntimeError, match="temporarily unavailable"):
            await provider.chat_complete("m", [{"role": "user", "content": "hi"}])

    async def test_chat_stream_checks_circuit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = AirLLMProvider()
        provider._circuit.state = CircuitState.OPEN
        provider._circuit.last_failure_time = time.time()
        with pytest.raises(RuntimeError, match="temporarily unavailable"):
            async for _ in provider.chat_stream("m", [{"role": "user", "content": "hi"}]):
                pass

    async def test_embed_checks_circuit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = AirLLMProvider()
        provider._circuit.state = CircuitState.OPEN
        provider._circuit.last_failure_time = time.time()
        with pytest.raises(RuntimeError, match="temporarily unavailable"):
            await provider.embed(["hello"], model="nomic")


# ---------------------------------------------------------------------------
# MockProvider tests
# ---------------------------------------------------------------------------


class TestMockProvider:
    async def test_chat_complete_returns_helpful_message(self) -> None:
        mp = MockProvider()
        result = await mp.chat_complete("m", [{"role": "user", "content": "hi"}])
        assert "currently unavailable" in result
        assert "currently unavailable" in result

    async def test_chat_stream_returns_helpful_message(self) -> None:
        mp = MockProvider()
        tokens = [t async for t in mp.chat_stream("m", [{"role": "user", "content": "hi"}])]
        full = "".join(tokens)
        assert "currently unavailable" in full

    async def test_embed_returns_deterministic_vectors(self) -> None:
        mp = MockProvider()
        result = await mp.embed(["a", "b"], model="m")
        assert len(result) == 2
        assert len(result[0]) == 384
        assert any(v != 0.0 for v in result[0])
        assert result[0] != result[1]

    async def test_health_check_returns_true(self) -> None:
        mp = MockProvider()
        assert await mp.health_check() is True


# ---------------------------------------------------------------------------
# ResilientLLMProvider tests
# ---------------------------------------------------------------------------


class TestResilientLLMProvider:
    async def test_uses_primary_when_healthy(self) -> None:
        primary = AsyncMock()
        primary.chat_complete = AsyncMock(return_value="primary")
        fb = AsyncMock()
        fb.chat_complete = AsyncMock(return_value="fallback")

        rlp = ResilientLLMProvider(primary, [fb])
        result = await rlp.chat_complete("m", [{"role": "user", "content": "hi"}])
        assert result == "primary"
        primary.chat_complete.assert_awaited_once()
        fb.chat_complete.assert_not_awaited()

    async def test_falls_back_when_primary_fails(self) -> None:
        primary = AsyncMock()
        primary.chat_complete = AsyncMock(side_effect=RuntimeError("primary down"))
        fb = AsyncMock()
        fb.chat_complete = AsyncMock(return_value="fallback")

        rlp = ResilientLLMProvider(primary, [fb])
        result = await rlp.chat_complete("m", [{"role": "user", "content": "hi"}])
        assert result == "fallback"
        primary.chat_complete.assert_awaited_once()
        fb.chat_complete.assert_awaited_once()

    async def test_chat_stream_fallback(self) -> None:
        async def failing_stream(*a: Any, **kw: Any) -> AsyncIterator[str]:
            raise RuntimeError("stream down")
            yield ""  # pragma: no cover

        async def ok_stream(*a: Any, **kw: Any) -> AsyncIterator[str]:
            yield "fallback"

        primary = AsyncMock()
        primary.chat_stream = failing_stream
        fb = AsyncMock()
        fb.chat_stream = ok_stream

        rlp = ResilientLLMProvider(primary, [fb])
        tokens = [t async for t in rlp.chat_stream("m", [{"role": "user", "content": "hi"}])]
        assert tokens == ["fallback"]

    async def test_chat_stream_does_not_retry_after_visible_output(self) -> None:
        """Avoid appending a fallback response after a partial reply."""
        fallback_calls = 0

        async def partial_stream(*a: Any, **kw: Any) -> AsyncIterator[str]:
            yield "partial"
            raise RuntimeError("connection lost")

        async def fallback_stream(*a: Any, **kw: Any) -> AsyncIterator[str]:
            nonlocal fallback_calls
            fallback_calls += 1
            yield "must not be appended"

        primary = AsyncMock()
        primary.chat_stream = partial_stream
        fb = AsyncMock()
        fb.chat_stream = fallback_stream

        rlp = ResilientLLMProvider(primary, [fb])
        stream = rlp.chat_stream("m", [{"role": "user", "content": "hi"}])
        assert await anext(stream) == "partial"
        with pytest.raises(RuntimeError, match="connection lost"):
            await anext(stream)
        assert fallback_calls == 0

    async def test_all_failed_raises(self) -> None:
        primary = AsyncMock()
        primary.chat_complete = AsyncMock(side_effect=RuntimeError("primary down"))
        fb = AsyncMock()
        fb.chat_complete = AsyncMock(side_effect=RuntimeError("fallback down"))

        rlp = ResilientLLMProvider(primary, [fb])
        with pytest.raises(RuntimeError, match="All providers failed"):
            await rlp.chat_complete("m", [{"role": "user", "content": "hi"}])

    async def test_fallback_to_mock_provider(self) -> None:
        primary = AsyncMock()
        primary.chat_complete = AsyncMock(side_effect=RuntimeError("primary down"))

        rlp = ResilientLLMProvider(primary, [MockProvider()])
        result = await rlp.chat_complete("m", [{"role": "user", "content": "hi"}])
        assert "currently unavailable" in result


# ---------------------------------------------------------------------------
# Factory fallback chain tests
# ---------------------------------------------------------------------------


class TestBuildFallbackChain:
    def test_adds_local_fallback_when_primary_is_local(self) -> None:
        settings = MagicMock()
        settings.ollama_host = "http://primary:11434"
        settings.ollama_dashboard_host = "http://fallback:11435"
        settings.openai_api_key = ""
        settings.kimi_api_key = ""
        settings.deepseek_api_key = ""
        settings.groq_api_key = ""

        fallbacks = _build_fallback_chain(settings, {}, primary_provider="ollama")
        # Ollama fallback host + DevProvider + MockProvider
        assert len(fallbacks) == 3
        assert isinstance(fallbacks[0], OllamaClient)
        assert isinstance(fallbacks[1], DevProvider)
        assert isinstance(fallbacks[2], MockProvider)

    def test_skips_duplicate_local_fallback_host(self) -> None:
        settings = MagicMock()
        settings.ollama_host = "http://same-host:11434"
        settings.ollama_dashboard_host = "http://same-host:11434"
        settings.openai_api_key = ""
        settings.kimi_api_key = ""
        settings.deepseek_api_key = ""
        settings.groq_api_key = ""

        fallbacks = _build_fallback_chain(settings, {}, primary_provider="ollama")
        # DevProvider + MockProvider only when fallback host matches the primary host.
        assert len(fallbacks) == 2
        assert isinstance(fallbacks[0], DevProvider)
        assert isinstance(fallbacks[-1], MockProvider)

    def test_uses_override_local_fallback_host(self) -> None:
        settings = MagicMock()
        settings.ollama_host = "http://primary:11434"
        settings.ollama_dashboard_host = "http://default-fallback:11435"
        settings.openai_api_key = ""
        settings.kimi_api_key = ""
        settings.deepseek_api_key = ""
        settings.groq_api_key = ""

        fallbacks = _build_fallback_chain(
            settings,
            {"ollama_dashboard_host": "http://override-fallback:11436"},
            primary_provider="ollama",
        )
        assert len(fallbacks) == 3
        assert isinstance(fallbacks[0], OllamaClient)

    def test_cloud_providers_added_before_mock(self) -> None:
        settings = MagicMock()
        settings.openai_api_key = ""
        settings.kimi_api_key = ""
        settings.deepseek_api_key = ""
        settings.groq_api_key = ""

        fallbacks = _build_fallback_chain(settings, {}, primary_provider=None)
        # DevProvider + MockProvider when no cloud keys set
        assert len(fallbacks) == 2

    def test_no_local_fallback_when_not_local_primary(self) -> None:
        settings = MagicMock()
        settings.ollama_host = "http://primary:11434"
        settings.ollama_dashboard_host = "http://fallback:11435"
        settings.openai_api_key = ""
        settings.kimi_api_key = ""
        settings.deepseek_api_key = ""
        settings.groq_api_key = ""

        fallbacks = _build_fallback_chain(settings, {}, primary_provider="openai")
        # No local fallback when primary is not local
        assert all(not isinstance(fb, OllamaClient) for fb in fallbacks)
