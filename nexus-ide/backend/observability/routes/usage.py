"""Usage tracking endpoints.

Provides token usage and cost metrics via the ``/api/metrics/usage``
endpoints.  These query the in-memory :class:`TokenTracker` (from
:mod:`backend.llm.multi_llm_manager`) and the database for historical
aggregation.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Query

from backend.persistence.db import get_message_statistics

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_current_tracker():
    """Get the global TokenTracker from the LLM manager (lazy)."""
    from backend.llm.multi_llm_manager import get_token_tracker

    return get_token_tracker()


def _parse_range_hint(range_hint: str) -> float:
    """Convert a range hint like ``24h``, ``7d``, ``30d`` to a Unix timestamp.

    Returns 0.0 if the hint cannot be parsed (i.e. all-time).
    """
    now = time.time()
    hint = range_hint.lower().strip()
    if hint.endswith("h"):
        try:
            hours = int(hint[:-1])
            return now - hours * 3600
        except ValueError:
            pass
    elif hint.endswith("d"):
        try:
            days = int(hint[:-1])
            return now - days * 86400
        except ValueError:
            pass
    elif hint.endswith("m"):
        try:
            minutes = int(hint[:-1])
            return now - minutes * 60
        except ValueError:
            pass
    return 0.0


@router.get("/metrics/usage")
async def get_usage(
    range: str = Query("24h", description='Time window: "24h", "7d", "30d" or "all"'),
) -> dict[str, Any]:
    """Return token usage and cost for the requested time window.

    Combines the in-memory token tracker (for real-time data) with
    database aggregates (for historical data).
    """
    since = _parse_range_hint(range)
    tracker = _get_current_tracker()
    snapshot = tracker.snapshot(since=since)

    # Add DB stats for additional context
    try:
        db_stats = get_message_statistics()
    except Exception as exc:
        logger.warning("Failed to load DB message statistics: %s", exc)
        db_stats = {}

    return {
        "range": range,
        "since": since or 0.0,
        "total_input_tokens": snapshot.total_input_tokens,
        "total_output_tokens": snapshot.total_output_tokens,
        "total_tokens": snapshot.total_input_tokens + snapshot.total_output_tokens,
        "total_cost_usd": snapshot.total_cost_usd,
        "call_count": snapshot.call_count,
        "by_model": dict(snapshot.by_model),
        "by_provider": dict(snapshot.by_provider),
        "cost_by_model": dict(snapshot.cost_by_model),
        "db_message_stats": db_stats,
    }


@router.get("/metrics/usage/summary")
async def get_usage_summary(
    range: str = Query("24h", description='Time window: "24h", "7d", "30d" or "all"'),
    limit: int = Query(10, ge=1, le=100),
) -> dict[str, Any]:
    """Return top token consumers and a brief summary.

    Top consumers are the models with the highest token counts.
    """
    since = _parse_range_hint(range)
    tracker = _get_current_tracker()
    snapshot = tracker.snapshot(since=since)

    # Sort by_model to find top consumers
    sorted_models = sorted(
        snapshot.by_model.items(), key=lambda x: x[1], reverse=True
    )[:limit]
    top_consumers = [
        {"model": model, "total_tokens": tokens, "cost_usd": round(snapshot.cost_by_model.get(model, 0.0), 4)}
        for model, tokens in sorted_models
    ]

    # Sort by_provider
    sorted_providers = sorted(
        snapshot.by_provider.items(), key=lambda x: x[1], reverse=True
    )
    top_providers = [
        {"provider": provider, "total_tokens": tokens}
        for provider, tokens in sorted_providers
    ]

    return {
        "range": range,
        "total_input_tokens": snapshot.total_input_tokens,
        "total_output_tokens": snapshot.total_output_tokens,
        "total_tokens": snapshot.total_input_tokens + snapshot.total_output_tokens,
        "total_cost_usd": snapshot.total_cost_usd,
        "call_count": snapshot.call_count,
        "top_consumers_by_model": top_consumers,
        "top_providers": top_providers,
    }


@router.get("/metrics/usage/tracker")
async def get_tracker_status() -> dict[str, Any]:
    """Return the in-memory token tracker status (total calls / tokens)."""
    tracker = _get_current_tracker()
    return {
        "total_calls": tracker.total_calls,
        "total_input_tokens": tracker.total_input_tokens,
        "total_output_tokens": tracker.total_output_tokens,
        "total_cost_usd": tracker.total_cost_usd,
    }
