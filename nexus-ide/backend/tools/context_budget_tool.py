"""Context budget tool — inspect and trim agent context before it exceeds the model window.

Wraps :mod:`backend.orchestrator.context_budget` so agents can self-monitor
their own context size and proactively trim it instead of discovering, mid-
request, that the objective was truncated from the front.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.orchestrator.context_budget import (
    fit_context,
    measure_context,
)
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


async def check_context_size(context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the estimated token size of the current context.

    Args:
        context: Optional context dict to measure. When omitted the tool
            returns guidance only — the agent should pass its own context
            when calling this tool.

    Returns:
        Dict with token estimate and budget guidance.
    """
    if context is None:
        return {
            "ok": True,
            "measured_tokens": 0,
            "note": "No context supplied. Pass your context dict to get a real measurement.",
            "guidance": {
                "typical_4k_budget": 3000,
                "typical_8k_budget": 7000,
                "typical_32k_budget": 28000,
                "typical_128k_budget": 100000,
            },
        }

    tokens = measure_context(context)
    return {
        "ok": True,
        "measured_tokens": tokens,
        "item_count": len(context),
        "guidance": {
            "under_4k": tokens < 3000,
            "under_8k": tokens < 7000,
            "under_32k": tokens < 28000,
            "under_128k": tokens < 100000,
        },
    }


async def get_budget_report(
    context: dict[str, Any] | None = None,
    budget_tokens: int = 4000,
    reserve_ratio: float = 0.15,
) -> dict[str, Any]:
    """Fit *context* into *budget_tokens* and return a BudgetReport.

    The context is never mutated — a trimmed copy is returned alongside the
    report so the agent can decide whether to swap its working context.

    Args:
        context: The context dict to budget.
        budget_tokens: Maximum tokens the context may occupy.
        reserve_ratio: Share of the budget held back for the model reply
            (default 0.15 = 15%).

    Returns:
        Dict with fitted_context and budget report fields.
    """
    if context is None:
        context = {}

    fitted, report = fit_context(
        context,
        int(budget_tokens),
        reserve_ratio=float(reserve_ratio),
    )
    payload = report.to_dict()
    payload["fitted_context"] = fitted
    payload["ok"] = True
    return payload


async def trim_context(
    context: dict[str, Any] | None = None,
    budget_tokens: int = 4000,
    reserve_ratio: float = 0.15,
) -> dict[str, Any]:
    """Trim *context* to fit within *budget_tokens* and return the trimmed copy.

    Use this when you know the context is over budget and you need a smaller
    version to pass to a subagent or model call.

    Args:
        context: The context dict to trim.
        budget_tokens: Maximum tokens the trimmed context may occupy.
        reserve_ratio: Share of the budget held back for the model reply.

    Returns:
        Dict with the trimmed context and a summary of what was dropped.
    """
    if context is None:
        context = {}

    fitted, report = fit_context(
        context,
        int(budget_tokens),
        reserve_ratio=float(reserve_ratio),
    )

    return {
        "ok": True,
        "trimmed_context": fitted,
        "original_tokens": report.original_tokens,
        "final_tokens": report.final_tokens,
        "budget_tokens": report.budget_tokens,
        "trimmed_keys": report.trimmed_keys,
        "dropped_keys": report.dropped_keys,
        "degraded": report.degraded,
        "utilization": round(report.utilisation, 4),
    }


register_tool(
    ToolSpec(
        name="check_context_size",
        description=(
            "Estimate the token size of an agent context dict. Returns the "
            "measured token count and guidance on whether the context fits "
            "within common model windows (4k, 8k, 32k, 128k)."
        ),
        tags=["context", "budget", "monitoring"],
        category="system",
        risk_level="low",
        when_to_use="Before sending a large context to a model or subagent.",
        schema={
            "type": "object",
            "properties": {
                "context": {
                    "type": "object",
                    "description": "Optional context dict to measure. Omit for guidance only.",
                    "default": {},
                },
            },
        },
        handler=check_context_size,
        timeout_seconds=10,
    )
)

register_tool(
    ToolSpec(
        name="get_budget_report",
        description=(
            "Fit a context dict into a token budget and return a BudgetReport "
            "describing what was trimmed and what was dropped. The original "
            "context is never mutated."
        ),
        tags=["context", "budget", "trim"],
        category="system",
        risk_level="low",
        when_to_use="When a context may exceed the model window and you need a "
        "detailed report of how it would be trimmed.",
        schema={
            "type": "object",
            "properties": {
                "context": {
                    "type": "object",
                    "description": "The context dict to budget.",
                    "default": {},
                },
                "budget_tokens": {
                    "type": "integer",
                    "description": "Maximum tokens the context may occupy.",
                    "default": 4000,
                    "minimum": 100,
                },
                "reserve_ratio": {
                    "type": "number",
                    "description": "Share of budget held back for the model reply (0.0–0.5).",
                    "default": 0.15,
                    "minimum": 0.0,
                    "maximum": 0.5,
                },
            },
            "required": [],
        },
        handler=get_budget_report,
        timeout_seconds=15,
    )
)

register_tool(
    ToolSpec(
        name="trim_context",
        description=(
            "Return a trimmed copy of a context dict that fits within a token "
            "budget. CRITICAL keys are never dropped; LOW keys are dropped "
            "first. Use this to proactively shrink context before calling a model."
        ),
        tags=["context", "budget", "trim"],
        category="system",
        risk_level="low",
        when_to_use="When the current context is over budget and you need a "
        "smaller version to pass to a subagent or model call.",
        schema={
            "type": "object",
            "properties": {
                "context": {
                    "type": "object",
                    "description": "The context dict to trim.",
                    "default": {},
                },
                "budget_tokens": {
                    "type": "integer",
                    "description": "Maximum tokens the trimmed context may occupy.",
                    "default": 4000,
                    "minimum": 100,
                },
                "reserve_ratio": {
                    "type": "number",
                    "description": "Share of budget held back for the model reply (0.0–0.5).",
                    "default": 0.15,
                    "minimum": 0.0,
                    "maximum": 0.5,
                },
            },
            "required": [],
        },
        handler=trim_context,
        timeout_seconds=15,
    )
)
