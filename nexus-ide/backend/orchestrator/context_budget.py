"""Fitting a large, detailed task context into a subagent's token budget.

THE PROBLEM THIS SOLVES

`SubagentManager.run_phase` accepted an arbitrary `context: dict[str, Any]` and
forwarded it verbatim to `AgentLifecycleManager.spawn`, alongside a
`token_budget` that was only ever recorded as metadata. Nothing measured the
context, and nothing trimmed it. For small tasks that is harmless. For the
large, detailed tasks subagents exist to handle — a research phase carrying
twenty file excerpts, a build phase carrying a full diff and the reviewer's
notes — the context silently exceeded the model's window and the request either
failed at the provider or, worse, was truncated from the *front*, discarding
the objective and system framing while keeping trailing boilerplate.

THE APPROACH

Budgeting, not truncating. Each context key is classified by how load-bearing
it is, and the budget is spent in that order:

    CRITICAL   never dropped, never trimmed (objective, constraints, IDs)
    HIGH       trimmed before dropping (plan, diff, errors)
    NORMAL     trimmed, then dropped if still over (file excerpts, history)
    LOW        dropped first (telemetry, breadcrumbs, prior transcripts)

Within a tier, larger values are trimmed first, because reclaiming 2 000 tokens
from one oversized blob preserves more distinct information than deleting four
small ones. Trimming keeps the head *and* the tail of a value: the head carries
what the thing is, the tail usually carries the conclusion or the most recent
event, and it is the undifferentiated middle that is safe to elide.

Every reduction is recorded in `BudgetReport`, so a phase that ran with a
degraded context says so instead of quietly producing a worse answer.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    """Eviction order. Lower value is evicted first."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


# Keys whose meaning is stable across phases. Anything unlisted defaults to
# NORMAL, which is the safe middle: trimmed under pressure but not discarded
# before things we know are disposable.
DEFAULT_PRIORITIES: dict[str, Priority] = {
    # The task itself. Losing any of this makes the run meaningless.
    "objective": Priority.CRITICAL,
    "goal": Priority.CRITICAL,
    "task": Priority.CRITICAL,
    "constraints": Priority.CRITICAL,
    "acceptance_criteria": Priority.CRITICAL,
    "mission_id": Priority.CRITICAL,
    "session_id": Priority.CRITICAL,
    "phase": Priority.CRITICAL,
    # Direct inputs to the current decision.
    "plan": Priority.HIGH,
    "diff": Priority.HIGH,
    "errors": Priority.HIGH,
    "error": Priority.HIGH,
    "test_failures": Priority.HIGH,
    "review_notes": Priority.HIGH,
    "previous_output": Priority.HIGH,
    "requirements": Priority.HIGH,
    # Useful supporting material.
    "files": Priority.NORMAL,
    "file_excerpts": Priority.NORMAL,
    "search_results": Priority.NORMAL,
    "documentation": Priority.NORMAL,
    "history": Priority.NORMAL,
    # Nice to have; the first thing to go.
    "metrics": Priority.LOW,
    "telemetry": Priority.LOW,
    "timings": Priority.LOW,
    "transcript": Priority.LOW,
    "debug": Priority.LOW,
    "breadcrumbs": Priority.LOW,
}

#: Characters per token. 4.0 is the usual English figure; code and JSON are
#: denser in punctuation and tokenize worse, so 3.6 keeps the estimate on the
#: conservative side. Overestimating wastes a little budget; underestimating
#: overflows the window, which is the failure we are trying to prevent.
CHARS_PER_TOKEN = 3.6

#: Below this, trimming a value costs more clarity than it saves budget.
MIN_TRIM_TOKENS = 48

#: Inserted where the middle of a value was removed.
ELISION = "\n… [{removed} tokens omitidos] …\n"


def estimate_tokens(value: Any) -> int:
    """Approximate the token cost of any context value.

    A heuristic, deliberately: calling a real tokenizer would mean importing a
    model-specific dependency into the orchestrator and paying for it on every
    context assembly. Consistency matters more than precision here — the number
    is used to compare candidates against a budget, not to bill anyone.
    """
    if value is None:
        return 0
    if isinstance(value, str):
        text = value
    elif isinstance(value, (int, float, bool)):
        return 1
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    return max(1, int(len(text) / CHARS_PER_TOKEN))


@dataclass
class BudgetReport:
    """What the budgeter had to do to make the context fit.

    Surfaced on `SubagentResult` so a caller can tell a clean run from one that
    answered on partial information.
    """

    budget_tokens: int
    original_tokens: int
    final_tokens: int
    trimmed_keys: list[str] = field(default_factory=list)
    dropped_keys: list[str] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        """True when the agent saw less than the caller supplied."""
        return bool(self.trimmed_keys or self.dropped_keys)

    @property
    def utilisation(self) -> float:
        """Fraction of the budget actually used, 0–1."""
        if self.budget_tokens <= 0:
            return 0.0
        return self.final_tokens / self.budget_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_tokens": self.budget_tokens,
            "original_tokens": self.original_tokens,
            "final_tokens": self.final_tokens,
            "trimmed_keys": list(self.trimmed_keys),
            "dropped_keys": list(self.dropped_keys),
            "degraded": self.degraded,
            "utilisation": round(self.utilisation, 4),
        }


def _trim_text(text: str, target_tokens: int) -> str:
    """Shrink `text` to roughly `target_tokens`, keeping head and tail.

    The middle is the safest part to lose: the opening establishes what the
    value is and the ending usually holds the conclusion, the latest error, or
    the most recent turn. A plain `text[:n]` would keep the preamble and throw
    away the answer.
    """
    target_chars = max(0, int(target_tokens * CHARS_PER_TOKEN))
    if target_chars <= 0 or len(text) <= target_chars:
        return text

    removed_tokens = estimate_tokens(text) - target_tokens
    marker = ELISION.format(removed=max(1, removed_tokens))

    # Reserve room for the marker itself so the result really does fit.
    usable = target_chars - len(marker)
    if usable < 80:
        # Too small to keep both ends meaningfully; keep the tail, which holds
        # the most recent and usually most actionable content.
        return text[-max(target_chars, 1) :]

    head = int(usable * 0.6)
    tail = usable - head
    return f"{text[:head]}{marker}{text[-tail:]}"


def _shrink_value(value: Any, target_tokens: int) -> Any | None:
    """Reduce any context value to roughly `target_tokens`.

    WHY THIS EXISTS: an earlier version could only trim strings, so a dict of
    twelve file excerpts — the single most valuable thing a BUILD phase carries
    — was all-or-nothing and got dropped whole. The budgeter then finished at
    44% utilisation: it had discarded 9 000 tokens of highly relevant material
    while leaving that much budget unspent. Being able to keep *part* of a
    collection is what turns eviction from a cliff into a gradient.

    Returns `None` when the value cannot be usefully shrunk to that size, which
    the caller reads as "drop this key".
    """
    if target_tokens < MIN_TRIM_TOKENS:
        return None

    if isinstance(value, str):
        return _trim_text(value, target_tokens)

    # Collections give back whole elements. Truncating their serialised form
    # would emit invalid JSON, and the consumer on the other side has to parse
    # it. Keeping the first N entries preserves whatever ordering the caller
    # chose, which is normally most-relevant-first.
    if isinstance(value, (list, tuple)):
        kept: list[Any] = []
        used = 0
        for item in value:
            cost = estimate_tokens(item)
            if used + cost > target_tokens:
                break
            kept.append(item)
            used += cost
        if not kept:
            return None
        omitted = len(value) - len(kept)
        if omitted:
            kept.append(f"… [{omitted} de {len(value)} entradas omitidas por orçamento]")
        return kept

    if isinstance(value, dict):
        kept_map: dict[Any, Any] = {}
        used = 0
        for key, item in value.items():
            cost = estimate_tokens(item) + estimate_tokens(key)
            if used + cost > target_tokens:
                continue  # Skip this one but keep scanning: a later entry may fit.
            kept_map[key] = item
            used += cost
        if not kept_map:
            return None
        omitted = len(value) - len(kept_map)
        if omitted:
            kept_map["__omitido__"] = f"{omitted} de {len(value)} entradas omitidas por orçamento"
        return kept_map

    # Scalars are already ~1 token; there is nothing to reclaim.
    return None


def fit_context(
    context: dict[str, Any] | None,
    budget_tokens: int,
    *,
    priorities: dict[str, Priority] | None = None,
    reserve_ratio: float = 0.15,
) -> tuple[dict[str, Any], BudgetReport]:
    """Return a copy of `context` that fits within `budget_tokens`.

    Args:
        context: Arbitrary task context. `None` is treated as empty.
        budget_tokens: Total tokens the context may occupy.
        priorities: Per-key overrides merged over `DEFAULT_PRIORITIES`. Use this
            when a phase knows something the generic table cannot — a VERIFY
            phase, for instance, should mark `test_failures` CRITICAL.
        reserve_ratio: Share of the budget held back for the model's reply and
            the system framing. Spending the entire window on input leaves no
            room to answer.

    Returns:
        `(fitted_context, report)`. The input dict is never mutated.
    """
    report_budget = max(0, int(budget_tokens * (1.0 - reserve_ratio)))
    source = dict(context or {})

    if not source:
        return {}, BudgetReport(budget_tokens=report_budget, original_tokens=0, final_tokens=0)

    table = {**DEFAULT_PRIORITIES, **(priorities or {})}
    sizes = {key: estimate_tokens(value) for key, value in source.items()}
    original_total = sum(sizes.values())

    report = BudgetReport(
        budget_tokens=report_budget,
        original_tokens=original_total,
        final_tokens=original_total,
    )

    if original_total <= report_budget:
        return source, report

    fitted = dict(source)
    current = original_total

    # Evict cheapest-priority first; within a tier, biggest first — one large
    # blob usually carries less distinct information than several small keys.
    order = sorted(
        source.keys(),
        key=lambda k: (table.get(k, Priority.NORMAL), -sizes[k]),
    )

    for key in order:
        if current <= report_budget:
            break

        priority = table.get(key, Priority.NORMAL)
        if priority is Priority.CRITICAL:
            continue  # Never touched, even if that means overshooting.

        excess = current - report_budget
        size = sizes[key]

        # Ask this key to give back exactly the overshoot and no more. Dropping
        # it outright would usually free far more than needed, and that surplus
        # is information the agent could have had for free.
        keep = size - excess
        shrunk = _shrink_value(fitted[key], keep) if keep >= MIN_TRIM_TOKENS else None

        if shrunk is not None:
            fitted[key] = shrunk
            current -= size - estimate_tokens(shrunk)
            report.trimmed_keys.append(key)
            continue

        del fitted[key]
        current -= size
        report.dropped_keys.append(key)

    report.final_tokens = sum(estimate_tokens(v) for v in fitted.values())

    if report.degraded:
        logger.info(
            "Context budgeted | budget=%d original=%d final=%d trimmed=%s dropped=%s",
            report_budget,
            original_total,
            report.final_tokens,
            report.trimmed_keys,
            report.dropped_keys,
        )
    if report.final_tokens > report_budget:
        # Only reachable when CRITICAL keys alone exceed the budget. Loud,
        # because it means the phase is misconfigured rather than merely busy.
        logger.warning(
            "Context still over budget after eviction | final=%d budget=%d "
            "critical keys alone exceed the phase budget",
            report.final_tokens,
            report_budget,
        )

    return fitted, report


def measure_context(context: dict[str, Any] | None) -> int:
    """Total estimated tokens for a context dict. Handy for logs and tests."""
    if not context:
        return 0
    return sum(estimate_tokens(value) for value in context.values())
