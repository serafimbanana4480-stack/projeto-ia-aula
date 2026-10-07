"""P1-3 — the cost governor was bypassed in the shipped configuration.

``.env`` sets ``MULTI_LLM_ENABLED=false``, so ``create_llm_client()`` returns
:class:`~backend.llm.factory.ResilientLLMProvider`, whose 300-line body had no
``CostGovernor.check()`` and no ``record()``.  The daily cap, the per-run cap
and the whole ``usage_ledger`` were therefore bypassed on every real request.

These tests pin the gate on both the streaming and the non-streaming path, the
fail-closed behaviour, the "accounting must never break chat" rule, and the
402 mapping at the HTTP layer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core import disk_guard
from backend.llm import cost_governor as cg
from backend.llm.cost_governor import BudgetExceededError, CostGovernor, reset_cost_governor
from backend.llm.factory import ResilientLLMProvider


@pytest.fixture(autouse=True)
def _no_disk_guard(monkeypatch):
    monkeypatch.setattr(disk_guard, "require_disk_headroom", lambda *_a, **_k: None)
    yield


@pytest.fixture
def governor(tmp_path, monkeypatch):
    """A governor with a tiny budget wired into the module singleton."""
    reset_cost_governor()
    instance = CostGovernor(tmp_path / "ledger.db")
    instance.daily_budget_usd = 0.0
    instance.per_run_budget_usd = 0.0
    monkeypatch.setattr(cg, "get_cost_governor", lambda *a, **k: instance)
    yield instance
    reset_cost_governor()


class _PaidProvider:
    """A provider that reports real token usage, like a cloud client would."""

    provider_name = "openai"
    fallback_model = ""

    def __init__(self, text: str = "a fairly long completion to price") -> None:
        self.text = text
        self.calls = 0
        self._last_usage = {
            "input_tokens": 1000,
            "output_tokens": 1000,
            "total_tokens": 2000,
        }

    @property
    def last_usage(self) -> dict[str, int]:
        return dict(self._last_usage)

    async def chat_complete(self, model: str, messages: list[dict[str, str]], **kw: Any) -> str:
        self.calls += 1
        return self.text

    async def chat_stream(
        self, model: str, messages: list[dict[str, str]], **kw: Any
    ) -> AsyncIterator[str]:
        self.calls += 1
        for word in self.text.split():
            yield word + " "

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------------------
# 1. The gate
# ---------------------------------------------------------------------------
class TestGateBeforeDispatch:
    async def test_chat_complete_raises_when_budget_exhausted(self, governor) -> None:
        governor.daily_budget_usd = 0.0001
        governor.record(cost_usd=1.0, provider="openai", model="gpt-4o")
        provider = _PaidProvider()
        client = ResilientLLMProvider(provider, [])

        with pytest.raises(BudgetExceededError) as excinfo:
            await client.chat_complete("gpt-4o", [{"role": "user", "content": "hi"}])
        assert excinfo.value.category == "budget_exceeded"
        assert provider.calls == 0, "a dispatch happened after the budget was spent"

    async def test_chat_stream_raises_before_the_first_token(self, governor) -> None:
        governor.daily_budget_usd = 0.0001
        governor.record(cost_usd=1.0, provider="openai", model="gpt-4o")
        provider = _PaidProvider()
        client = ResilientLLMProvider(provider, [])

        stream = client.chat_stream("gpt-4o", [{"role": "user", "content": "hi"}])
        with pytest.raises(BudgetExceededError):
            async for _ in stream:
                pass
        assert provider.calls == 0

    async def test_budget_error_is_not_swallowed_by_the_fallback_chain(
        self, governor
    ) -> None:
        """Failing over to a cheaper model after "stop spending" is the bug.

        A ``BudgetExceededError`` must not be converted into
        ``ProviderUnavailableError`` (which reads as "try again later") nor
        into a silent MockProvider answer.
        """
        governor.daily_budget_usd = 0.0001
        governor.record(cost_usd=1.0, provider="openai", model="gpt-4o")
        primary = _PaidProvider()
        fallback = _PaidProvider("cheaper")
        client = ResilientLLMProvider(primary, [fallback])

        with pytest.raises(BudgetExceededError):
            await client.chat_complete("gpt-4o", [{"role": "user", "content": "hi"}])
        assert primary.calls == 0 and fallback.calls == 0

    async def test_per_run_cap_is_enforced_with_a_run_id(self, governor) -> None:
        governor.per_run_budget_usd = 0.0001
        governor.record(cost_usd=1.0, provider="openai", model="gpt-4o", run_id="run-7")
        client = ResilientLLMProvider(_PaidProvider(), [])
        with pytest.raises(BudgetExceededError) as excinfo:
            await client.chat_complete(
                "gpt-4o", [{"role": "user", "content": "hi"}], run_id="run-7"
            )
        assert excinfo.value.scope == "run"

    async def test_run_id_is_read_from_several_shapes(self, governor) -> None:
        """Whatever kwarg the caller uses must reach the governor."""
        seen: list[str] = []
        monkey_calls: list[str | None] = []

        class _Spy:
            def check(self, run_id: str | None = None) -> None:
                monkey_calls.append(run_id)

            def record(self, **kwargs: Any) -> None:  # noqa: ANN003
                seen.append(kwargs.get("run_id", ""))

            daily_budget_usd = 0.0
            today_spend = staticmethod(lambda: 0.0)

        import backend.llm.cost_governor as module

        original = module.get_cost_governor
        module.get_cost_governor = lambda *a, **k: _Spy()  # type: ignore[assignment]
        try:
            client = ResilientLLMProvider(_PaidProvider(), [])
            await client.chat_complete("gpt-4o", [{"role": "user", "content": "x"}], run_id="r1")
            await client.chat_complete(
                "gpt-4o", [{"role": "user", "content": "x"}], session_id="s1"
            )
            await client.chat_complete(
                "gpt-4o",
                [{"role": "user", "content": "x"}],
                context={"mission_id": "m1"},
            )
        finally:
            module.get_cost_governor = original  # type: ignore[assignment]

        assert monkey_calls == ["r1", "s1", "m1"]
        assert seen == ["r1", "s1", "m1"]


# ---------------------------------------------------------------------------
# 2. The ledger
# ---------------------------------------------------------------------------
class TestRecordAfterResponse:
    async def test_chat_complete_records_the_call(self, governor, tmp_path) -> None:
        client = ResilientLLMProvider(_PaidProvider(), [])
        await client.chat_complete("gpt-4o", [{"role": "user", "content": "hello"}])
        assert governor.today_spend() > 0

    async def test_chat_stream_records_the_call(self, governor) -> None:
        client = ResilientLLMProvider(_PaidProvider(), [])
        async for _ in client.chat_stream("gpt-4o", [{"role": "user", "content": "hello"}]):
            pass
        assert governor.today_spend() > 0

    async def test_run_id_reaches_the_ledger(self, governor) -> None:
        client = ResilientLLMProvider(_PaidProvider(), [])
        await client.chat_complete(
            "gpt-4o", [{"role": "user", "content": "hi"}], run_id="run-42"
        )
        assert governor.run_spend("run-42") > 0

    async def test_recorded_call_counts_towards_the_daily_cap(self, governor) -> None:
        """A dispatch must not be free: the spend has to land in the ledger."""
        client = ResilientLLMProvider(_PaidProvider(), [])
        await client.chat_complete("gpt-4o", [{"role": "user", "content": "hi"}])
        spent = governor.today_spend()
        assert spent > 0
        governor.daily_budget_usd = spent
        with pytest.raises(BudgetExceededError):
            await client.chat_complete("gpt-4o", [{"role": "user", "content": "hi"}])

    async def test_streaming_records_only_once(self, governor) -> None:
        client = ResilientLLMProvider(_PaidProvider(), [])
        async for _ in client.chat_stream("gpt-4o", [{"role": "user", "content": "hi"}]):
            pass
        assert governor.today_spend() > 0
        first = governor.today_spend()
        async for _ in client.chat_stream("gpt-4o", [{"role": "user", "content": "hi"}]):
            pass
        assert governor.today_spend() > first

    async def test_failed_dispatch_records_nothing(self, governor) -> None:
        class _Failing(_PaidProvider):
            async def chat_complete(self, model, messages, **kw):  # noqa: ANN001
                self.calls += 1
                raise RuntimeError("upstream 500")

        from backend.llm.free_policy import ProviderUnavailableError

        client = ResilientLLMProvider(_Failing(), [])
        with pytest.raises(ProviderUnavailableError):
            await client.chat_complete("gpt-4o", [{"role": "user", "content": "hi"}])
        assert governor.today_spend() == 0


# ---------------------------------------------------------------------------
# 3. Accounting must never break chat
# ---------------------------------------------------------------------------
class TestAccountingNeverBreaksChat:
    async def test_record_failure_is_swallowed(self, governor, monkeypatch) -> None:
        def boom(**kwargs: Any) -> None:  # noqa: ANN003
            raise RuntimeError("ledger is on fire")

        monkeypatch.setattr(governor, "record", boom)
        client = ResilientLLMProvider(_PaidProvider(), [])
        answer = await client.chat_complete("gpt-4o", [{"role": "user", "content": "hi"}])
        assert answer  # the answer still came back

    async def test_usage_extraction_failure_is_swallowed(self, governor) -> None:
        class _Exploding(_PaidProvider):
            @property
            def last_usage(self) -> dict[str, int]:
                raise RuntimeError("provider blew up reading usage")

        client = ResilientLLMProvider(_Exploding(), [])
        answer = await client.chat_complete("gpt-4o", [{"role": "user", "content": "hi"}])
        assert answer


# ---------------------------------------------------------------------------
# 4. Shipped configuration actually goes through ResilientLLMProvider
# ---------------------------------------------------------------------------
class TestShippedConfiguration:
    def test_multi_llm_is_disabled_in_the_shipped_env(self) -> None:
        """The path that matters is the one the deployment uses."""
        from backend.config.settings import get_settings

        assert get_settings().multi_llm_enabled is False

    def test_resilient_provider_is_the_returned_client(self) -> None:
        from backend.llm.factory import create_llm_client

        client = create_llm_client()
        assert isinstance(client, ResilientLLMProvider), type(client)

    def test_resilient_provider_has_the_governor_hooks(self) -> None:
        assert hasattr(ResilientLLMProvider, "_cost_check")
        assert hasattr(ResilientLLMProvider, "_cost_record")

    def test_cost_check_is_called_on_both_paths(self) -> None:
        """Structural guard against a future refactor dropping one of them."""
        import inspect

        stream_src = inspect.getsource(ResilientLLMProvider.chat_stream)
        complete_src = inspect.getsource(ResilientLLMProvider._try_providers)
        assert "self._cost_check(kwargs)" in stream_src
        assert "self._cost_check(kwargs)" in complete_src
        assert "self._cost_record(" in stream_src
        assert "self._cost_record(" in complete_src


# ---------------------------------------------------------------------------
# 5. The route layer can turn this into a 402
# ---------------------------------------------------------------------------
class TestBudgetHTTPResponse:
    def test_budget_exceeded_maps_to_402(self) -> None:
        from backend.llm.cost_governor import BudgetExceededError
        from backend.orchestrator.main import _budget_exceeded_handler

        exc = BudgetExceededError(
            "Daily LLM budget exhausted", scope="daily", spent_usd=10.0, limit_usd=25.0
        )
        import asyncio

        import anyio
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/chat",
            "headers": [],
            "query_string": b"",
        }
        response = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            _budget_exceeded_handler(Request(scope), exc)
        )
        assert response.status_code == 402
        import json

        body = json.loads(response.body)
        assert body["error"] == "budget_exceeded"
        assert body["scope"] == "daily"
        assert body["limit_usd"] == 25.0
        assert anyio is not None

    def test_app_registers_the_handler(self) -> None:
        from backend.orchestrator.main import app

        assert BudgetExceededError in app.exception_handlers

    def test_budget_error_survives_the_full_asgi_stack(self) -> None:
        """A 402 body, end to end, not just a handler unit test."""
        import json

        from backend.llm.cost_governor import BudgetExceededError
        from backend.orchestrator.main import app

        async def explode() -> None:
            raise BudgetExceededError(
                "Daily LLM budget exhausted: $25.00 spent of $25.00.",
                scope="daily",
                spent_usd=25.0,
                limit_usd=25.0,
            )

        probe = FastAPI()
        probe.add_exception_handler(
            BudgetExceededError, app.exception_handlers[BudgetExceededError]
        )

        @probe.get("/boom")
        async def boom() -> None:
            await explode()

        client = TestClient(probe, raise_server_exceptions=False)
        response = client.get("/boom")
        assert response.status_code == 402
        assert json.loads(response.text)["error"] == "budget_exceeded"


# ---------------------------------------------------------------------------
# 6. Non-zero defaults
# ---------------------------------------------------------------------------
class TestDefaults:
    def test_env_example_has_a_non_zero_daily_budget(self) -> None:
        from pathlib import Path

        env_example = Path(__file__).resolve().parents[2] / ".env.example"
        text = env_example.read_text(encoding="utf-8")
        line = next(
            line for line in text.splitlines() if line.startswith("NEXUS_DAILY_BUDGET_USD=")
        )
        assert float(line.split("=", 1)[1]) > 0, "unlimited-by-default is the defect"

    def test_env_example_has_a_non_zero_per_run_budget(self) -> None:
        from pathlib import Path

        env_example = Path(__file__).resolve().parents[2] / ".env.example"
        text = env_example.read_text(encoding="utf-8")
        line = next(
            line for line in text.splitlines() if line.startswith("NEXUS_PER_RUN_BUDGET_USD=")
        )
        assert float(line.split("=", 1)[1]) > 0

    def test_unlimited_logs_a_warning(self, tmp_path, monkeypatch, caplog) -> None:
        monkeypatch.setenv("NEXUS_DAILY_BUDGET_USD", "0")
        with caplog.at_level("WARNING"):
            instance = CostGovernor(tmp_path / "g.db")
            instance.check()
        assert any("UNLIMITED" in record.message for record in caplog.records)
