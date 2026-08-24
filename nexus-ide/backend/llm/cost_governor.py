"""Cost governor — hard caps for real-money LLM spending.

Why this exists (audit 2026-08-24, blockers B1+B2):
  * Nothing limited how much a session could spend: an agent loop plus
    multi-provider failover could burn unlimited budget on N accounts.
  * Cost was tracked only in memory (TokenTracker); a restart erased the
    entire financial history, making billing/auditing impossible.

This module adds:
  * ``NEXUS_DAILY_BUDGET_USD``  — hard cap per UTC day (0/unset = unlimited,
    logged once as a warning because unlimited spend is rarely intended).
  * ``NEXUS_PER_RUN_BUDGET_USD`` — optional cap per run id (enforced only
    when callers pass a run id to :meth:`CostGovernor.check`).
  * A durable ``usage_ledger`` table (one row per billed LLM call) written
    immediately, so budgets survive restarts and finance can be audited.

The governor must NEVER break a chat on accounting errors: every hook used
by the manager wraps failures in logging only — except budget checks, which
are *supposed* to stop dispatch.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_DAILY_BUDGET_ENV = "NEXUS_DAILY_BUDGET_USD"
_PER_RUN_BUDGET_ENV = "NEXUS_PER_RUN_BUDGET_USD"


class BudgetExceededError(RuntimeError):
    """Raised before dispatch when spending would exceed a configured cap."""

    def __init__(
        self,
        message: str,
        *,
        scope: str = "daily",
        spent_usd: float = 0.0,
        limit_usd: float = 0.0,
    ) -> None:
        super().__init__(message)
        self.category = "budget_exceeded"
        self.scope = scope
        self.spent_usd = spent_usd
        self.limit_usd = limit_usd


class CostGovernor:
    """Thread-safe spend limiter backed by the ``usage_ledger`` table."""

    def __init__(self, db_path: str | os.PathLike[str]) -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self.daily_budget_usd = _env_float(_DAILY_BUDGET_ENV, 0.0)
        self.per_run_budget_usd = _env_float(_PER_RUN_BUDGET_ENV, 0.0)
        self._day = self._utc_day()
        self._day_spend = 0.0
        self._run_spend: dict[str, float] = {}
        self._warned_unlimited = False
        self._ensure_table()
        self._load_today()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def check(self, run_id: str | None = None) -> None:
        """Raise :class:`BudgetExceededError` if a new paid call is not allowed."""
        self._roll_day_if_needed()
        if self.daily_budget_usd > 0:
            spent = self.today_spend()
            if spent >= self.daily_budget_usd:
                raise BudgetExceededError(
                    f"Daily LLM budget exhausted: ${spent:.4f} spent of "
                    f"${self.daily_budget_usd:.2f}. No further paid dispatches today.",
                    scope="daily",
                    spent_usd=spent,
                    limit_usd=self.daily_budget_usd,
                )
        elif not self._warned_unlimited:
            self._warned_unlimited = True
            logger.warning(
                "%s unset/0 — LLM spending is UNLIMITED. Set a hard cap "
                "before operating with paid API keys.",
                _DAILY_BUDGET_ENV,
            )
        if run_id and self.per_run_budget_usd > 0:
            run_spent = self.run_spend(run_id)
            if run_spent >= self.per_run_budget_usd:
                raise BudgetExceededError(
                    f"Per-run LLM budget exhausted: ${run_spent:.4f} of "
                    f"${self.per_run_budget_usd:.2f} for run {run_id}.",
                    scope="run",
                    spent_usd=run_spent,
                    limit_usd=self.per_run_budget_usd,
                )

    def record(
        self,
        *,
        cost_usd: float,
        provider: str = "",
        model: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        session_id: str = "",
        run_id: str = "",
    ) -> None:
        """Persist one billed call and update the cached counters."""
        if cost_usd <= 0:
            return
        day = self._utc_day()
        ts = datetime.now(timezone.utc).isoformat()
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO usage_ledger (
                        ts, day, provider, model, input_tokens,
                        output_tokens, cost_usd, session_id, run_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ts,
                        day,
                        provider,
                        model,
                        int(input_tokens),
                        int(output_tokens),
                        float(cost_usd),
                        session_id,
                        run_id,
                    ),
                )
        except sqlite3.Error as exc:  # pragma: no cover - disk/db failure
            logger.error("usage_ledger insert failed: %s", exc)
            return
        with self._lock:
            if day == self._day:
                self._day_spend += cost_usd
            if run_id:
                self._run_spend[run_id] = self._run_spend.get(run_id, 0.0) + cost_usd

    def today_spend(self) -> float:
        self._roll_day_if_needed()
        with self._lock:
            return round(self._day_spend, 6)

    def run_spend(self, run_id: str) -> float:
        with self._lock:
            return round(self._run_spend.get(run_id, 0.0), 6)

    def snapshot(self) -> dict[str, Any]:
        """Small dict for /api/metrics endpoints and logs."""
        self._roll_day_if_needed()
        with self._lock:
            return {
                "daily_budget_usd": self.daily_budget_usd,
                "per_run_budget_usd": self.per_run_budget_usd,
                "today_spent_usd": round(self._day_spend, 4),
                "day": self._day,
            }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _utc_day() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _roll_day_if_needed(self) -> None:
        today = self._utc_day()
        with self._lock:
            if today != self._day:
                self._day = today
                self._day_spend = 0.0

    def _ensure_table(self) -> None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS usage_ledger (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts TEXT NOT NULL,
                        day TEXT NOT NULL,
                        provider TEXT DEFAULT '',
                        model TEXT DEFAULT '',
                        input_tokens INTEGER DEFAULT 0,
                        output_tokens INTEGER DEFAULT 0,
                        cost_usd REAL DEFAULT 0.0,
                        session_id TEXT DEFAULT '',
                        run_id TEXT DEFAULT ''
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_usage_ledger_day "
                    "ON usage_ledger(day)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_usage_ledger_run "
                    "ON usage_ledger(run_id)"
                )
        except sqlite3.Error as exc:  # pragma: no cover - disk/db failure
            logger.error("usage_ledger table creation failed: %s", exc)

    def _load_today(self) -> None:
        """Seed today's counters from the ledger (survives restarts)."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                day_row = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0.0) FROM usage_ledger WHERE day = ?",
                    (self._day,),
                ).fetchone()
                run_rows = conn.execute(
                    """
                    SELECT run_id, COALESCE(SUM(cost_usd), 0.0)
                    FROM usage_ledger
                    WHERE day = ? AND run_id != ''
                    GROUP BY run_id
                    """,
                    (self._day,),
                ).fetchall()
        except sqlite3.Error as exc:  # pragma: no cover - disk/db failure
            logger.error("usage_ledger read failed: %s", exc)
            return
        with self._lock:
            self._day_spend = float(day_row[0]) if day_row else 0.0
            self._run_spend = {str(r[0]): float(r[1]) for r in run_rows}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("Invalid %s=%r — ignoring", name, raw)
        return default


_governor: CostGovernor | None = None
_governor_lock = threading.Lock()


def get_cost_governor(db_path: str | os.PathLike[str] | None = None) -> CostGovernor:
    """Return the process-wide governor singleton."""
    global _governor
    if _governor is None:
        with _governor_lock:
            if _governor is None:
                if db_path is None:
                    from backend.persistence.db import DB_PATH

                    db_path = DB_PATH
                _governor = CostGovernor(db_path)
    return _governor


def reset_cost_governor() -> None:
    """Test helper: drop the singleton."""
    global _governor
    with _governor_lock:
        _governor = None
