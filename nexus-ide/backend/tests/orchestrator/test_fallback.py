"""Tests for backend.orchestrator.fallback."""
from __future__ import annotations

from typing import AsyncIterator

import pytest

from backend.orchestrator.fallback import FallbackOutcome, _load_chain, invoke_with_fallback
from backend.tools.ollama_client import OllamaError


class TestFallbackOutcome:
    def test_frozen_dataclass(self) -> None:
        outcome = FallbackOutcome(
            used_agent="CODER",
            attempts=1,
            notified_dashboard=False,
            reason="",
        )
        assert outcome.used_agent == "CODER"
        assert outcome.attempts == 1

        with pytest.raises(AttributeError):
            outcome.used_agent = "MICRO"  # frozen

    def test_fallback_records_reason(self) -> None:
        outcome = FallbackOutcome(
            used_agent="MICRO",
            attempts=2,
            notified_dashboard=True,
            reason="fell-back-from-CODER",
        )
        assert "CODER" in outcome.reason
        assert outcome.notified_dashboard is True


class TestLoadChain:
    def test_known_agent_returns_configured_chain(self) -> None:
        chain = _load_chain("CODER")
        assert chain, "CODER must have at least one fallback configured"
        assert all(isinstance(x, str) for x in chain)

    def test_unknown_agent_falls_back_to_micro(self) -> None:
        chain = _load_chain("DOES_NOT_EXIST")
        assert chain == ["MICRO"]


class TestInvokeWithFallback:
    async def test_primary_succeeds_no_fallback(self) -> None:
        async def make_stream() -> AsyncIterator[str]:
            async def gen() -> AsyncIterator[str]:
                yield "ok"
            return gen()

        calls: list[str] = []

        async def invoke(name: str) -> AsyncIterator[str]:
            calls.append(name)
            return await make_stream()

        outcome, stream = await invoke_with_fallback("CODER", invoke)
        assert outcome.used_agent == "CODER"
        assert outcome.attempts == 1
        assert outcome.notified_dashboard is False
        assert outcome.reason == ""
        tokens = [t async for t in stream]
        assert tokens == ["ok"]
        assert calls == ["CODER"]

    async def test_primary_fails_falls_through_chain(self) -> None:
        async def good_stream() -> AsyncIterator[str]:
            async def gen() -> AsyncIterator[str]:
                yield "recovered"
            return gen()

        async def invoke(name: str) -> AsyncIterator[str]:
            if name == "CODER":
                raise OllamaError("primary down")
            return await good_stream()

        outcome, stream = await invoke_with_fallback("CODER", invoke)
        assert outcome.used_agent != "CODER"
        assert outcome.attempts >= 2
        assert outcome.notified_dashboard is True
        assert "fell-back-from-CODER" in outcome.reason
        tokens = [t async for t in stream]
        assert tokens == ["recovered"]

    async def test_entire_chain_exhausted_raises(self) -> None:
        async def invoke(name: str) -> AsyncIterator[str]:
            raise OllamaError(f"{name} is down")

        with pytest.raises(OllamaError):
            await invoke_with_fallback("CODER", invoke)
