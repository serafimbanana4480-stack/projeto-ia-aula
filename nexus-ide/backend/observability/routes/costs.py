"""Cost visibility endpoints backed by the durable ``usage_ledger`` table.

Foundation for user-facing metering/billing: until plans and payments exist,
operators still need truthful answers to "quanto já gastámos hoje / este mês /
em que modelo". All reads are SQL aggregations over the ledger written by the
CostGovernor on every paid LLM call.

Tenant scope
------------
The ledger has no owner column, but every row carries the ``session_id`` it
was billed to, and a session belongs to exactly one user.  Both endpoints
below therefore join ``sessions`` and restrict the rows to the caller's own
sessions: an unscoped read answered "what did every other tenant of this
instance spend, and in which model", on a route every registered user can
call.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.llm.cost_governor import get_cost_governor
from backend.middleware.auth import require_auth
from backend.persistence.db import DB_PATH

router = APIRouter(prefix="/metrics", tags=["costs"], dependencies=[Depends(require_auth)])


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH), timeout=5.0)


def _caller_id(user: dict[str, Any] | None) -> str:
    """The caller's user id, or a 401 when the guard produced nothing."""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def _owned_session_ids(conn: sqlite3.Connection, user_id: str) -> set[str]:
    """The sessions the caller owns.

    A ledger whose database has no ``sessions`` table cannot attribute a
    single row to a tenant, so it has no rows for anybody.
    """
    try:
        rows = conn.execute(
            "SELECT id FROM sessions WHERE user_id = ?", (user_id,)
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return set()
        raise
    return {str(row[0]) for row in rows}


@router.get("/costs")
async def cost_summary(
    days: int = Query(default=30, ge=1, le=366),
    user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Budget state + spend aggregated by day/provider/model.

    The spend figures are the caller's own (the ledger rows are joined to the
    sessions the caller owns).  The budget *limits* come from the cost
    governor and stay instance-wide — they are configuration, not another
    tenant's data — but ``today_spent_usd`` is the caller's own spend, not
    the instance's.
    """
    user_id = _caller_id(user)
    governor = get_cost_governor()
    try:
        with _connect() as conn:
            owned = _owned_session_ids(conn, user_id)
            if not owned:
                by_day: list[Any] = []
                by_provider: list[Any] = []
                by_model: list[Any] = []
                month_total = 0.0
                today_total = 0.0
            else:
                by_day = conn.execute(
                    """
                    SELECT ul.day AS day, ROUND(SUM(ul.cost_usd), 4) AS usd, COUNT(*) AS calls
                    FROM usage_ledger ul
                    JOIN sessions s ON s.id = ul.session_id
                    WHERE s.user_id = ?
                    GROUP BY ul.day
                    ORDER BY ul.day DESC
                    LIMIT ?
                    """,
                    (user_id, days),
                ).fetchall()
                by_provider = conn.execute(
                    """
                    SELECT ul.provider AS provider, ROUND(SUM(ul.cost_usd), 4) AS usd,
                           COUNT(*) AS calls
                    FROM usage_ledger ul
                    JOIN sessions s ON s.id = ul.session_id
                    WHERE s.user_id = ?
                    GROUP BY ul.provider
                    ORDER BY usd DESC
                    LIMIT 25
                    """,
                    (user_id,),
                ).fetchall()
                by_model = conn.execute(
                    """
                    SELECT ul.model AS model, ROUND(SUM(ul.cost_usd), 4) AS usd,
                           COUNT(*) AS calls
                    FROM usage_ledger ul
                    JOIN sessions s ON s.id = ul.session_id
                    WHERE s.user_id = ?
                    GROUP BY ul.model
                    ORDER BY usd DESC
                    LIMIT 25
                    """,
                    (user_id,),
                ).fetchall()
                month_row = conn.execute(
                    """
                    SELECT COALESCE(SUM(ul.cost_usd), 0.0)
                    FROM usage_ledger ul
                    JOIN sessions s ON s.id = ul.session_id
                    WHERE s.user_id = ?
                      AND substr(ul.day, 1, 7) = substr(date('now'), 1, 7)
                    """,
                    (user_id,),
                ).fetchone()
                today_row = conn.execute(
                    """
                    SELECT COALESCE(SUM(ul.cost_usd), 0.0)
                    FROM usage_ledger ul
                    JOIN sessions s ON s.id = ul.session_id
                    WHERE s.user_id = ? AND ul.day = date('now')
                    """,
                    (user_id,),
                ).fetchone()
                month_total = float(month_row[0]) if month_row else 0.0
                today_total = float(today_row[0]) if today_row else 0.0
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"usage_ledger read failed: {exc}") from exc

    snapshot = dict(governor.snapshot())
    # The governor's "spent today" is the whole instance's; the caller's own
    # figure is the one that belongs in a per-tenant answer.
    snapshot["today_spent_usd"] = round(today_total, 4)

    return {
        **snapshot,
        "month_to_date_usd": round(month_total, 4),
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
async def cost_ledger(
    limit: int = Query(default=100, ge=1, le=500),
    user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Most recent billed LLM calls (one row per call) — the caller's own.

    The ledger is shared by every session of the instance, so the rows are
    joined to the sessions the caller owns before they are returned.  A
    ``session_id`` from another tenant is therefore never in the answer, and
    a row that belongs to no session at all is nobody's to see.
    """
    user_id = _caller_id(user)
    try:
        with _connect() as conn:
            conn.row_factory = sqlite3.Row
            owned = _owned_session_ids(conn, user_id)
            rows: list[Any] = []
            if owned:
                rows = conn.execute(
                    """
                    SELECT ul.id AS id, ul.ts AS ts, ul.day AS day, ul.provider AS provider,
                           ul.model AS model, ul.input_tokens AS input_tokens,
                           ul.output_tokens AS output_tokens, ul.cost_usd AS cost_usd,
                           ul.session_id AS session_id, ul.run_id AS run_id
                    FROM usage_ledger ul
                    JOIN sessions s ON s.id = ul.session_id
                    WHERE s.user_id = ?
                    ORDER BY ul.id DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"usage_ledger read failed: {exc}") from exc

    return {
        "entries": [dict(r) for r in rows],
        "count": len(rows),
    }
