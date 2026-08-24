"""Cost visibility endpoints backed by the durable ``usage_ledger`` table.

Foundation for user-facing metering/billing: until plans and payments exist,
operators still need truthful answers to "quanto já gastámos hoje / este mês /
em que modelo". All reads are SQL aggregations over the ledger written by the
CostGovernor on every paid LLM call.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.llm.cost_governor import get_cost_governor
from backend.persistence.db import DB_PATH

router = APIRouter(prefix="/metrics", tags=["costs"])


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH), timeout=5.0)


@router.get("/costs")
async def cost_summary(days: int = Query(default=30, ge=1, le=366)) -> dict[str, Any]:
    """Budget state + spend aggregated by day/provider/model."""
    governor = get_cost_governor()
    try:
        with _connect() as conn:
            by_day = conn.execute(
                """
                SELECT day, ROUND(SUM(cost_usd), 4) AS usd, COUNT(*) AS calls
                FROM usage_ledger
                GROUP BY day
                ORDER BY day DESC
                LIMIT ?
                """,
                (days,),
            ).fetchall()
            by_provider = conn.execute(
                """
                SELECT provider, ROUND(SUM(cost_usd), 4) AS usd, COUNT(*) AS calls
                FROM usage_ledger
                GROUP BY provider
                ORDER BY usd DESC
                LIMIT 25
                """
            ).fetchall()
            by_model = conn.execute(
                """
                SELECT model, ROUND(SUM(cost_usd), 4) AS usd, COUNT(*) AS calls
                FROM usage_ledger
                GROUP BY model
                ORDER BY usd DESC
                LIMIT 25
                """
            ).fetchall()
            month_row = conn.execute(
                """
                SELECT COALESCE(SUM(cost_usd), 0.0)
                FROM usage_ledger
                WHERE substr(day, 1, 7) = substr(date('now'), 1, 7)
                """
            ).fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"usage_ledger read failed: {exc}") from exc

    return {
        **governor.snapshot(),
        "month_to_date_usd": round(float(month_row[0]), 4) if month_row else 0.0,
        "by_day": [
            {"day": d, "usd": float(u), "calls": int(c)} for d, u, c in by_day
        ],
        "by_provider": [
            {"provider": p or "?", "usd": float(u), "calls": int(c)}
            for p, u, c in by_provider
        ],
        "by_model": [
            {"model": m or "?", "usd": float(u), "calls": int(c)} for m, u, c in by_model
        ],
    }


@router.get("/costs/ledger")
async def cost_ledger(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    """Most recent billed LLM calls (one row per call)."""
    try:
        with _connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, ts, day, provider, model,
                       input_tokens, output_tokens, cost_usd,
                       session_id, run_id
                FROM usage_ledger
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"usage_ledger read failed: {exc}") from exc

    return {
        "entries": [dict(r) for r in rows],
        "count": len(rows),
    }
