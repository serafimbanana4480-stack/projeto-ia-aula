"""B6: orçamento partilhado entre workers via SQLite autoritativo."""

from __future__ import annotations

import pytest

from backend.llm.cost_governor import (
    BudgetExceededError,
    CostGovernor,
    reset_cost_governor,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NEXUS_DAILY_BUDGET_USD", raising=False)
    monkeypatch.delenv("NEXUS_PER_RUN_BUDGET_USD", raising=False)
    reset_cost_governor()
    yield
    reset_cost_governor()


class TestMultiWorkerBudget:
    def test_second_worker_sees_first_worker_spend(self, tmp_path) -> None:
        """Dois 'processos' (instâncias) sobre o mesmo ficheiro SQLite."""
        shared_db = tmp_path / "nexus.db"

        worker_a = CostGovernor(shared_db, )
        worker_b = CostGovernor(shared_db)

        # Worker A gasta; o cache do B continua a zero — mas o B lê o ledger.
        worker_a.record(cost_usd=0.75, provider="openai", model="m")
        assert worker_a.today_spend() == pytest.approx(0.75)
        assert worker_b.today_spend() == pytest.approx(0.75), (
            "worker B tem de ver o gasto de A sem restart (B6)"
        )

    def test_budget_enforced_across_instances(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_DAILY_BUDGET_USD", "1.00")
        shared_db = tmp_path / "nexus.db"
        worker_a = CostGovernor(shared_db)
        worker_b = CostGovernor(shared_db)

        worker_a.record(cost_usd=0.90, provider="openai", model="m")
        worker_b.check()  # ainda dentro

        worker_b.record(cost_usd=0.20, provider="openai", model="m")
        for gov in (worker_a, worker_b):
            with pytest.raises(BudgetExceededError):
                gov.check()

    def test_run_spend_shared_across_instances(self, tmp_path) -> None:
        shared_db = tmp_path / "nexus.db"
        worker_a = CostGovernor(shared_db)
        worker_b = CostGovernor(shared_db)
        worker_a.record(cost_usd=0.30, provider="openai", model="m", run_id="r9")
        assert worker_b.run_spend("r9") == pytest.approx(0.30)

    def test_falls_back_to_cache_when_db_unreadable(self, tmp_path) -> None:
        gov = CostGovernor(tmp_path / "ok.db")
        gov.record(cost_usd=0.10, provider="openai", model="m")
        # Aponta para uma DB inexistente/ilegível após o facto.
        gov._db_path = str(tmp_path / "desaparecida" / "x.db")
        # _sum_cost falha → fallback para o cache em memória.
        assert gov.today_spend() == pytest.approx(0.10)
