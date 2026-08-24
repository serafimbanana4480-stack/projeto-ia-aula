"""Testes do cost governor (audit 2026-08-24, B1/B2) e do buraco Kilo (B3)."""

from __future__ import annotations

import sqlite3

import pytest

from backend.llm.cost_governor import (
    BudgetExceededError,
    CostGovernor,
    reset_cost_governor,
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Ambiente limpo + singleton novo por teste."""
    monkeypatch.delenv("NEXUS_DAILY_BUDGET_USD", raising=False)
    monkeypatch.delenv("NEXUS_PER_RUN_BUDGET_USD", raising=False)
    monkeypatch.setenv("NEXUS_FREE_ONLY", "true")
    reset_cost_governor()
    yield
    reset_cost_governor()


class TestCostGovernor:
    def test_record_persists_across_instances(self, tmp_path) -> None:
        db = tmp_path / "nexus.db"
        gov = CostGovernor(db)
        gov.record(
            cost_usd=0.25,
            provider="openai",
            model="gpt-test",
            input_tokens=100,
            output_tokens=50,
            session_id="s1",
            run_id="r1",
        )
        # Instância nova = simula restart; o saldo tem de sobreviver.
        gov2 = CostGovernor(db)
        assert gov2.today_spend() == pytest.approx(0.25)
        assert gov2.run_spend("r1") == pytest.approx(0.25)

    def test_zero_cost_is_not_recorded(self, tmp_path) -> None:
        db = tmp_path / "nexus.db"
        gov = CostGovernor(db)
        gov.record(cost_usd=0.0, provider="openrouter")
        with sqlite3.connect(db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM usage_ledger").fetchone()[0]
        assert count == 0
        assert gov.today_spend() == 0.0

    def test_daily_budget_blocks_when_exhausted(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_DAILY_BUDGET_USD", "1.00")
        gov = CostGovernor(tmp_path / "nexus.db")
        gov.check()  # dentro do orçamento
        gov.record(cost_usd=0.60, provider="openai", model="m")
        gov.check()
        gov.record(cost_usd=0.40, provider="openai", model="m")
        with pytest.raises(BudgetExceededError) as excinfo:
            gov.check()
        assert excinfo.value.category == "budget_exceeded"
        assert excinfo.value.scope == "daily"

    def test_per_run_budget_only_affects_that_run(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_PER_RUN_BUDGET_USD", "0.50")
        gov = CostGovernor(tmp_path / "nexus.db")
        gov.record(cost_usd=0.60, provider="openai", model="m", run_id="r-explodiu")
        with pytest.raises(BudgetExceededError) as excinfo:
            gov.check(run_id="r-explodiu")
        assert excinfo.value.scope == "run"
        gov.check(run_id="r-outro")  # não afetado
        gov.check()  # sem run_id: só o cap diário (ilimitado aqui)

    def test_unlimited_budget_warns_but_allows(self, tmp_path) -> None:
        gov = CostGovernor(tmp_path / "nexus.db")
        assert gov.daily_budget_usd == 0.0
        gov.check()  # não levanta


class TestDispatchGateIntegration:
    def test_manager_blocks_dispatch_over_budget(self, monkeypatch, tmp_path) -> None:
        from backend.llm.cost_governor import get_cost_governor
        from backend.llm.factory import MultiLLMManager

        monkeypatch.setenv("NEXUS_DAILY_BUDGET_USD", "0.10")
        reset_cost_governor()
        governor = get_cost_governor(tmp_path / "nexus.db")
        governor.record(cost_usd=0.99, provider="openai", model="m")

        manager = MultiLLMManager(free_only=False)
        from types import SimpleNamespace

        manager.providers["fake"] = SimpleNamespace(simulation=False)
        manager._priority["fake"] = 3
        with pytest.raises(BudgetExceededError):
            manager._ensure_dispatch_allowed("fake", "qualquer-modelo")

    def test_free_only_never_hits_budget_gate_for_zero_spend(
        self, monkeypatch, tmp_path
    ) -> None:
        from backend.llm.cost_governor import get_cost_governor
        from backend.llm.factory import MultiLLMManager

        monkeypatch.setenv("NEXUS_DAILY_BUDGET_USD", "0.01")
        reset_cost_governor()
        get_cost_governor(tmp_path / "nexus.db")

        manager = MultiLLMManager(free_only=True)
        from types import SimpleNamespace

        manager.providers["freeprov"] = SimpleNamespace(
            simulation=False,
            validate_model=lambda model: None,
        )
        manager._priority["freeprov"] = 3
        manager._ensure_dispatch_allowed("freeprov", "modelo-gratis")


class TestKiloFreeOnlyHole:
    def test_kilo_not_registered_under_free_only(self, monkeypatch) -> None:
        """B3: gateway pago não pode registar-se com NEXUS_FREE_ONLY=true."""
        from backend.llm import factory

        captured: dict = {}

        class _FakeManager:
            def __init__(self, **kwargs):
                self.providers: dict = {}

            def register_provider(self, name, provider, priority=0):
                self.providers[name] = provider

        original_manager_cls = factory.MultiLLMManager
        factory.MultiLLMManager = _FakeManager
        try:
            monkeypatch.setenv("KILO_API_KEY", "sk-kilo-fake-pago")
            manager = factory.create_multi_llm_manager()
            captured["providers"] = list(manager.providers)
            assert "kilo" not in captured["providers"], (
                "kilo (pago) não pode ser registado em modo free-only"
            )
        finally:
            factory.MultiLLMManager = original_manager_cls

    def test_kilo_whitelist_removed_from_free_direct_providers(self) -> None:
        source = open(
            "backend/llm/factory.py", encoding="utf-8"
        ).read()
        whitelist_line = [
            line
            for line in source.splitlines()
            if 'provider not in {"local", "ollama"' in line
        ]
        assert whitelist_line, "whitelist free-only desapareceu?"
        assert '"kilo"' not in whitelist_line[0], (
            "kilo continua na whitelist direta do free_only"
        )


class TestTerminalAuthBreaker:
    async def test_force_open_outlasts_default_cooldown(self) -> None:
        from backend.llm.circuit_breaker import CircuitState, CircuitBreaker

        breaker = CircuitBreaker(name="t", cooldown_seconds=30.0)
        breaker.force_open(900.0)
        assert breaker.state is CircuitState.OPEN
        assert await breaker.is_call_permitted() is False
        retry = breaker.retry_after
        assert retry is not None and retry > 60  # muito além do clamp de 60s

    async def test_force_open_recovers_after_expiry(self) -> None:
        from backend.llm.circuit_breaker import CircuitState, CircuitBreaker

        breaker = CircuitBreaker(name="t2", cooldown_seconds=30.0)
        breaker.force_open(1.0)
        import asyncio

        await asyncio.sleep(1.05)
        assert await breaker.is_call_permitted() is True
        assert breaker.state is CircuitState.HALF_OPEN

    def test_provider_http_status_error_carries_code(self) -> None:
        from backend.llm.openai_provider import ProviderHTTPStatusError

        exc = ProviderHTTPStatusError(402, '{"error":"insufficient_credits"}')
        assert exc.status_code == 402
        assert "402" in str(exc)
