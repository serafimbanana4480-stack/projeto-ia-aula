"""Testes: run_id no cost governor (2026-08-25).

Prova que, com run_id propagado do dispatch até ``CostGovernor.check()`` e
``CostGovernor.record()``, o cap ``NEXUS_PER_RUN_BUDGET_USD`` bloqueia a
segunda chamada do mesmo run — e que sem run_id o comportamento antigo
(só cap diário) se mantém.
"""

from __future__ import annotations

import pytest

from backend.llm.cost_governor import (
    BudgetExceededError,
    CostGovernor,
    get_cost_governor,
    reset_cost_governor,
)
from backend.llm.free_policy import ProviderUnavailableError
from backend.llm.multi_llm_manager import MultiLLMManager


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Ambiente limpo + singleton novo por teste (convenção de test_cost_governor)."""
    monkeypatch.delenv("NEXUS_DAILY_BUDGET_USD", raising=False)
    monkeypatch.delenv("NEXUS_PER_RUN_BUDGET_USD", raising=False)
    monkeypatch.setenv("NEXUS_FREE_ONLY", "true")
    reset_cost_governor()
    yield
    reset_cost_governor()


class TestGovernorRunIdUnit:
    def test_per_run_budget_blocks_second_call_same_run(self, tmp_path) -> None:
        monkey_env = pytest.MonkeyPatch()
        try:
            monkey_env.setenv("NEXUS_PER_RUN_BUDGET_USD", "0.25")
            gov = CostGovernor(tmp_path / "nexus.db")
            gov.check(run_id="run-a")  # 1.ª chamada autorizada
            gov.record(
                cost_usd=0.30,
                provider="openai",
                model="m",
                input_tokens=100,
                output_tokens=50,
                run_id="run-a",
            )
            with pytest.raises(BudgetExceededError) as excinfo:
                gov.check(run_id="run-a")  # 2.ª chamada bloqueada
            assert excinfo.value.category == "budget_exceeded"
            assert excinfo.value.scope == "run"
        finally:
            monkey_env.undo()

    def test_other_runs_and_no_run_are_not_blocked(self, tmp_path) -> None:
        monkey_env = pytest.MonkeyPatch()
        try:
            monkey_env.setenv("NEXUS_PER_RUN_BUDGET_USD", "0.25")
            gov = CostGovernor(tmp_path / "nexus.db")
            gov.record(cost_usd=1.00, provider="openai", model="m", run_id="run-a")
            with pytest.raises(BudgetExceededError):
                gov.check(run_id="run-a")
            gov.check(run_id="run-b")  # outro run: não afetado
            gov.check()  # sem run_id: só o cap diário (ilimitado aqui)
        finally:
            monkey_env.undo()


class _PricedProvider:
    """Provider não-simulação cuja chamada custa $0.30 (via _compute_cost patch)."""

    simulation = False

    def __init__(self) -> None:
        self.calls = 0

    async def chat_complete(self, model, messages, **kwargs) -> str:
        self.calls += 1
        return "ok"


def _manager_with_provider(name: str = "govrun-fake") -> tuple[MultiLLMManager, _PricedProvider]:
    manager = MultiLLMManager(free_only=False)
    provider = _PricedProvider()
    manager.register_provider(name, provider)
    return manager, provider


class TestManagerEnforcesPerRunBudget:
    async def test_second_dispatch_same_run_is_blocked(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEXUS_PER_RUN_BUDGET_USD", "0.25")
        from backend.llm import multi_llm_manager as mlm_module

        original_compute = mlm_module._compute_cost
        try:
            get_cost_governor(tmp_path / "nexus.db")
            monkeypatch.setattr(mlm_module, "_compute_cost", lambda *a, **k: 0.30)

            manager, provider = _manager_with_provider()
            messages = [{"role": "user", "content": "oi"}]

            first = await manager.chat_complete("m", messages, run_id="run-77")
            assert first == "ok"
            assert provider.calls == 1

            # O registo pós-chamada levou o run_id → o saldo do run existe e
            # já excede o cap de $0.25.
            governor = get_cost_governor(tmp_path / "nexus.db")
            assert governor.run_spend("run-77") == pytest.approx(0.30)

            with pytest.raises(ProviderUnavailableError) as excinfo:
                await manager.chat_complete("m", messages, run_id="run-77")

            assert excinfo.value.category == "budget_exceeded"
            assert provider.calls == 1  # a 2.ª chamada nunca chegou ao provider
        finally:
            monkeypatch.setattr(mlm_module, "_compute_cost", original_compute)

    async def test_without_run_id_behaviour_is_unchanged(self, monkeypatch, tmp_path):
        """Sem run_id o cap per-run não se aplica (só cap diário) — compat."""
        monkeypatch.setenv("NEXUS_PER_RUN_BUDGET_USD", "0.25")
        from backend.llm import multi_llm_manager as mlm_module

        original_compute = mlm_module._compute_cost
        try:
            get_cost_governor(tmp_path / "nexus.db")
            monkeypatch.setattr(mlm_module, "_compute_cost", lambda *a, **k: 0.20)

            manager, provider = _manager_with_provider()
            messages = [{"role": "user", "content": "oi"}]

            await manager.chat_complete("m", messages)
            second = await manager.chat_complete("m", messages)

            assert second == "ok"
            assert provider.calls == 2
        finally:
            monkeypatch.setattr(mlm_module, "_compute_cost", original_compute)

    async def test_streaming_also_enforces_per_run_budget(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("NEXUS_PER_RUN_BUDGET_USD", "0.25")
        from backend.llm import multi_llm_manager as mlm_module

        original_compute = mlm_module._compute_cost
        try:
            get_cost_governor(tmp_path / "nexus.db")
            monkeypatch.setattr(mlm_module, "_compute_cost", lambda *a, **k: 0.30)

            class _StreamProvider(_PricedProvider):
                async def chat_stream(self, model, messages, **kwargs):
                    self.calls += 1
                    yield "ok"

            manager = MultiLLMManager(free_only=False)
            provider = _StreamProvider()
            manager.register_provider("govrun-stream-fake", provider)

            messages = [{"role": "user", "content": "oi"}]
            chunks = [
                token
                async for token in manager.chat_stream("m", messages, run_id="run-s1")
            ]
            assert chunks == ["ok"]

            with pytest.raises(ProviderUnavailableError) as excinfo:
                async for _ in manager.chat_stream("m", messages, run_id="run-s1"):
                    pass  # pragma: no cover - não deve chegar aqui

            assert excinfo.value.category == "budget_exceeded"
            assert provider.calls == 1
        finally:
            monkeypatch.setattr(mlm_module, "_compute_cost", original_compute)
