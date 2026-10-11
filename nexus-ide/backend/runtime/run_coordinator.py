"""Persistent core of a run's lifecycle (Fase 1a).

A *run* is one unit of user-visible work carried out by the primary agent: a
goal, the requirements it must satisfy, the constraints it must respect and an
explicit definition of done. This module owns that lifecycle in SQLite so a
crash, a restart or a context change cannot make the run silently disappear.

What lives here
---------------
``RunCoordinator`` persists and enforces six things:

1. **State machine** — :class:`RunState` plus an explicit transition table.
   An illegal move raises :class:`InvalidRunTransition` and leaves the stored
   state untouched; it is logged, never swallowed.
2. **Progress** — the plan, the current task, retries, provider, memory refs,
   artifacts and changed files, refreshed by :meth:`RunCoordinator.update_progress`
   together with a heartbeat.
3. **Checkpoints** — a payload per phase boundary (``after_planning``,
   ``before_side_effect``, ``after_side_effect``, ``after_task``,
   ``before_verification``, ``after_verification``, ``pause``,
   ``provider_failover``, ``heartbeat``). :meth:`RunCoordinator.restore` returns
   the newest one and moves the run to ``RECOVERING``.
4. **Idempotency** — ``run_side_effects`` is a ``UNIQUE(run_id,
   idempotency_key)`` ledger, so replaying an already-confirmed side effect is a
   no-op instead of a second real-world action (a second charge, a second email).
5. **Budgets** — hard limits accumulated by ``record_usage`` with a single
   atomic ``INSERT ... ON CONFLICT DO UPDATE``; exceeding one returns
   ``BudgetVerdict.ok = False`` with a human-readable ``exceeded`` entry.
6. **Definition of done** — :meth:`RunCoordinator.verify_definition_of_done`
   requires evidence per requirement; ``UNKNOWN`` on a required requirement
   blocks completion, and :meth:`RunCoordinator.complete` refuses to reach
   ``COMPLETED`` while any is unproven (:class:`DoDNotSatisfied`).

Everything is persisted through :mod:`backend.persistence.db`, which owns the
SQL, the schema (``backend/persistence/schemas.sql`` is canonical) and the
Alembic revision that creates these tables. The coordinator itself holds no
SQL beyond the row-to-dataclass mapping.

Thread-safety: one re-entrant lock per coordinator instance serialises the
read-validate-write sequences (a transition, in particular, must never observe
a state it then overwrites blindly). That is what a single-process async
application needs; SQLite keeps the file consistent across processes.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "BUDGET_LIMITS",
    "CHECKPOINT_PHASES",
    "DEAD_LETTER_STATES",
    "TERMINAL_RUN_STATES",
    "BudgetVerdict",
    "Checkpoint",
    "DoDNotSatisfied",
    "InvalidRunTransition",
    "RunCoordinator",
    "RunRecord",
    "RunState",
]


class RunState(StrEnum):
    """The states a run can occupy.

    ``CREATED`` → ``PLANNING`` → ``RUNNING`` → ``VERIFYING`` → ``COMPLETED`` is
    the happy path; the waiting states are where a run parks while it waits for
    an external actor (a tool, a human approval, a provider).
    """

    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_TOOL = "waiting_tool"
    WAITING_APPROVAL = "waiting_approval"
    VERIFYING = "verifying"
    RECOVERING = "recovering"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


#: States that own no future work. Nothing leaves them, and retention only
#: deletes runs that are in one of them.
TERMINAL_RUN_STATES = frozenset(
    {
        RunState.COMPLETED,
        RunState.FAILED,
        RunState.CANCELLED,
        RunState.EXPIRED,
    }
)

#: The explicit state machine. Every legal move is listed here; anything not
#: listed is refused by :meth:`RunCoordinator.transition` with an
#: :class:`InvalidRunTransition` and no state change.
#:
#: * ``CREATED`` starts a run: plan it, give up, or let it expire.
#: * ``PLANNING`` either produces a plan and starts executing, or needs human
#:   approval of the plan before any side effect happens.
#: * ``RUNNING`` is the execution loop: it waits for tools, waits for
#:   approvals, verifies, pauses, fails, is cancelled, or expires.
#: * ``WAITING_TOOL`` returns to execution, or moves on to verification.
#: * ``WAITING_APPROVAL`` returns to execution once approved.
#: * ``VERIFYING`` either closes the run or sends it back for another round.
#: * ``RECOVERING`` re-enters execution after a restore. It may transition to
#:   itself: a crash *during* recovery must not dead-end the run.
#: * ``PAUSED`` resumes into a state the caller names explicitly.
#: * the four terminal states have no outgoing transition — ``restore`` of a
#:   finished run is refused, not silently resurrected.
_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.CREATED: frozenset(
        {RunState.PLANNING, RunState.CANCELLED, RunState.EXPIRED, RunState.FAILED}
    ),
    RunState.PLANNING: frozenset(
        {
            RunState.RUNNING,
            RunState.WAITING_APPROVAL,
            RunState.PAUSED,
            RunState.RECOVERING,
            RunState.CANCELLED,
            RunState.EXPIRED,
            RunState.FAILED,
        }
    ),
    RunState.RUNNING: frozenset(
        {
            RunState.WAITING_TOOL,
            RunState.WAITING_APPROVAL,
            RunState.VERIFYING,
            RunState.PAUSED,
            RunState.RECOVERING,
            RunState.COMPLETED,
            RunState.CANCELLED,
            RunState.EXPIRED,
            RunState.FAILED,
        }
    ),
    RunState.WAITING_TOOL: frozenset(
        {
            RunState.RUNNING,
            RunState.VERIFYING,
            RunState.PAUSED,
            RunState.RECOVERING,
            RunState.CANCELLED,
            RunState.EXPIRED,
            RunState.FAILED,
        }
    ),
    RunState.WAITING_APPROVAL: frozenset(
        {
            RunState.RUNNING,
            RunState.PAUSED,
            RunState.RECOVERING,
            RunState.CANCELLED,
            RunState.EXPIRED,
            RunState.FAILED,
        }
    ),
    RunState.VERIFYING: frozenset(
        {
            RunState.RUNNING,
            RunState.WAITING_TOOL,
            RunState.PAUSED,
            RunState.COMPLETED,
            RunState.CANCELLED,
            RunState.EXPIRED,
            RunState.FAILED,
        }
    ),
    RunState.RECOVERING: frozenset(
        {
            RunState.RUNNING,
            RunState.PLANNING,
            RunState.VERIFYING,
            RunState.WAITING_TOOL,
            RunState.PAUSED,
            # A crash while recovering must be able to recover again.
            RunState.RECOVERING,
            RunState.FAILED,
            RunState.CANCELLED,
            RunState.EXPIRED,
        }
    ),
    RunState.PAUSED: frozenset(
        {
            RunState.RUNNING,
            RunState.PLANNING,
            RunState.VERIFYING,
            RunState.WAITING_TOOL,
            RunState.FAILED,
            RunState.CANCELLED,
            RunState.EXPIRED,
        }
    ),
    RunState.COMPLETED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
    RunState.EXPIRED: frozenset(),
}

#: The checkpoint phases a run records. Mirrors the ``run_checkpoints`` CHECK
#: constraint in ``backend/persistence/schemas.sql``.
CHECKPOINT_PHASES = frozenset(
    {
        "after_planning",
        "before_side_effect",
        "after_side_effect",
        "after_task",
        "before_verification",
        "after_verification",
        "pause",
        "provider_failover",
        "heartbeat",
    }
)

#: Lifecycle of a parked failure. Mirrors the ``run_dead_letters`` CHECK
#: constraint in ``backend/persistence/schemas.sql``.
DEAD_LETTER_STATES = frozenset(
    {
        "open",
        "retrying",
        "requeued",
        "replanned",
        "abandoned",
        "escalated",
    }
)

#: Budget limits accepted in ``RunRecord.budget`` (``None`` means "no limit").
BUDGET_LIMITS: tuple[str, ...] = (
    "max_tokens",
    "max_cost_usd",
    "max_tool_calls",
    "max_retries",
    "max_browser_actions",
    "max_subagents",
    "max_runtime_seconds",
    "max_provider_calls",
)

#: (usage metric, budget limit, label used in ``BudgetVerdict.exceeded``).
#: The label is the short form callers see in UI and logs: ``cost`` for
#: ``cost_usd``, everything else keeps its metric name.
_USAGE_TO_LIMIT: tuple[tuple[str, str, str], ...] = (
    ("tokens", "max_tokens", "tokens"),
    ("cost_usd", "max_cost_usd", "cost"),
    ("tool_calls", "max_tool_calls", "tool_calls"),
    ("retries", "max_retries", "retries"),
    ("browser_actions", "max_browser_actions", "browser_actions"),
    ("subagents", "max_subagents", "subagents"),
    ("runtime_seconds", "max_runtime_seconds", "runtime_seconds"),
    ("provider_calls", "max_provider_calls", "provider_calls"),
)


class InvalidRunTransition(RuntimeError):
    """Raised when a run is asked to move somewhere it cannot go.

    Carries ``run_id``, ``from_state`` and ``to_state`` so a caller can react to
    the specific illegal move. The stored state is never changed by this error.
    """

    def __init__(self, run_id: str, from_state: RunState, to_state: RunState) -> None:
        self.run_id = run_id
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"invalid run transition for run {run_id}: "
            f"{from_state.value} -> {to_state.value}"
        )


class DoDNotSatisfied(RuntimeError):
    """Raised by :meth:`RunCoordinator.complete` when the definition of done
    is not met.

    ``details`` is the ``missing`` list produced by
    :meth:`RunCoordinator.verify_definition_of_done`: one entry per requirement
    that was never reported, failed, or is still ``UNKNOWN``.
    """

    def __init__(self, run_id: str, details: list[dict[str, Any]]) -> None:
        self.run_id = run_id
        self.details = details
        names = ", ".join(str(item.get("requirement", "?")) for item in details) or "none"
        super().__init__(
            f"definition of done not satisfied for run {run_id}: {len(details)} "
            f"unsatisfied requirement(s): {names}"
        )


@dataclass
class RunRecord:
    """One durable run. All timestamps are UTC ISO-8601 strings (``...Z``)."""

    run_id: str
    goal: str = ""
    project_id: str = ""
    user_id: str = ""
    session_id: str = ""
    requirements: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    definition_of_done: list[str] = field(default_factory=list)
    state: RunState = RunState.CREATED
    plan: dict[str, Any] | None = None
    current_task_id: str | None = None
    retry_count: int = 0
    budget: dict[str, Any] = field(default_factory=dict)
    provider: dict[str, Any] = field(default_factory=dict)
    memory_refs: list[Any] = field(default_factory=list)
    artifacts: list[Any] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    heartbeat_at: str = ""
    stop_reason: str = ""


@dataclass
class Checkpoint:
    """One phase boundary of a run, with the payload needed to continue."""

    checkpoint_id: str
    run_id: str
    phase: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass
class BudgetVerdict:
    """The verdict of comparing accumulated usage against the run's limits.

    ``exceeded`` is empty while the run is inside budget; otherwise it maps the
    short metric label to ``"<used>><<limit>"`` (for example
    ``{"cost": "0.42>0.25"}``). ``usage`` is the accumulated usage the verdict
    was computed from.
    """

    ok: bool
    exceeded: dict[str, str] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)


def _new_id() -> str:
    """Return a short random id, matching ``persistence.db._new_id``."""
    return uuid.uuid4().hex[:16]


def _now_iso() -> str:
    """Return ``now`` as an ISO-8601 UTC string with a ``Z`` suffix."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _cutoff_iso(days: int, now: datetime) -> str:
    """Return the ISO-8601 UTC cutoff for a retention window of ``days``."""
    return (now - timedelta(days=days)).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(value)


def _json_loads(value: Any, default: Any) -> Any:
    """Parse a JSON column, returning ``default`` for SQL NULL.

    A corrupt value raises instead of being hidden: silently falling back to an
    empty default is how a run "loses" its plan.
    """
    if value is None:
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt JSON in run state column: {value!r}") from exc


def _as_state(value: RunState | str) -> RunState:
    """Coerce a state name into a :class:`RunState`, raising when unknown."""
    if isinstance(value, RunState):
        return value
    try:
        return RunState(str(value))
    except ValueError as exc:
        valid = ", ".join(state.value for state in RunState)
        raise ValueError(f"unknown run state {value!r}; expected one of: {valid}") from exc


def _require_mapping(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be a dict, got {type(value).__name__}")
    return value


def _require_sequence(name: str, value: Any) -> list[Any]:
    """Copy an ordered collection of items, rejecting strings and mappings.

    A string is a sequence of characters, not a sequence of requirements, and a
    mapping has no order — both would be silent data corruption if accepted.
    Any other iterable (list, tuple, generator) is materialised.
    """
    if isinstance(value, str | bytes | Mapping) or not isinstance(value, Iterable):
        raise TypeError(f"{name} must be a sequence, got {type(value).__name__}")
    return list(value)


def _coerce_int(value: Any, name: str) -> int:
    """Coerce a usage/attempt counter to ``int``, rejecting nonsense loudly."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ValueError(f"{name} must be an integer, got {value!r}")


def _format_number(value: Any) -> str:
    """Render a usage/limit number compactly: ``1200``, ``0.42``, ``1.5``."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return str(value)
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def _row_to_record(row: dict[str, Any]) -> RunRecord:
    """Map a ``run_state`` row to a :class:`RunRecord`."""
    return RunRecord(
        run_id=str(row["run_id"]),
        goal=str(row.get("goal") or ""),
        project_id=str(row.get("project_id") or ""),
        user_id=str(row.get("user_id") or ""),
        session_id=str(row.get("session_id") or ""),
        requirements=list(_json_loads(row.get("requirements_json"), [])),
        constraints=list(_json_loads(row.get("constraints_json"), [])),
        definition_of_done=list(_json_loads(row.get("definition_of_done_json"), [])),
        state=RunState(str(row["state"])),
        plan=_json_loads(row.get("plan_json"), None),
        current_task_id=row.get("current_task_id"),
        retry_count=_coerce_int(row.get("retry_count"), "retry_count"),
        budget=dict(_json_loads(row.get("budget_json"), {})),
        provider=dict(_json_loads(row.get("provider_json"), {})),
        memory_refs=list(_json_loads(row.get("memory_refs_json"), [])),
        artifacts=list(_json_loads(row.get("artifacts_json"), [])),
        changed_files=list(_json_loads(row.get("changed_files_json"), [])),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
        heartbeat_at=str(row.get("heartbeat_at") or ""),
        stop_reason=str(row.get("stop_reason") or ""),
    )


def _row_to_checkpoint(row: dict[str, Any]) -> Checkpoint:
    payload = _json_loads(row.get("payload_json"), {})
    if not isinstance(payload, dict):
        raise ValueError(
            f"checkpoint {row.get('checkpoint_id')!r} payload is not an object: {payload!r}"
        )
    return Checkpoint(
        checkpoint_id=str(row["checkpoint_id"]),
        run_id=str(row["run_id"]),
        phase=str(row["phase"]),
        payload=payload,
        created_at=str(row.get("created_at") or ""),
    )


def _row_to_dead_letter(row: dict[str, Any]) -> dict[str, Any]:
    """Map a ``run_dead_letters`` row to the dict shape callers read."""
    entry = dict(row)
    entry["last_evidence"] = _json_loads(entry.pop("last_evidence_json", None), {})
    return entry


def _normalize_budget(budget: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and copy budget limits.

    Unknown keys raise: a typo like ``max_cost`` would otherwise silently mean
    "no cost limit", which is the failure this whole mechanism exists to
    prevent. Values must be numeric or ``None`` (no limit).
    """
    if not budget:
        return {}
    _require_mapping("budget", budget)
    unknown = set(budget) - set(BUDGET_LIMITS)
    if unknown:
        raise ValueError(f"unknown budget limits: {sorted(unknown)}")
    normalized: dict[str, Any] = {}
    for key in BUDGET_LIMITS:
        if key not in budget:
            continue
        value = budget[key]
        if value is None:
            normalized[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"budget limit {key!r} must be a number or None, got {value!r}")
        normalized[key] = value
    return normalized


def _normalize_dod_results(results: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and copy definition-of-done verdicts.

    Returns a new list where every entry has ``requirement``, ``verdict``
    (upper-cased to ``PASS`` / ``FAIL`` / ``UNKNOWN``) and ``evidence`` (a
    dict, defaulting to ``{}``).
    """
    _require_sequence("results", results)
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(results):
        _require_mapping(f"results[{index}]", raw)
        requirement = raw.get("requirement")
        if not isinstance(requirement, str) or not requirement.strip():
            raise ValueError(f"results[{index}].requirement must be a non-empty string")
        verdict = raw.get("verdict")
        if not isinstance(verdict, str):
            raise ValueError(f"results[{index}].verdict must be a string")
        verdict = verdict.strip().upper()
        if verdict not in {"PASS", "FAIL", "UNKNOWN"}:
            raise ValueError(
                f"results[{index}].verdict must be PASS, FAIL or UNKNOWN, got {verdict!r}"
            )
        evidence = raw.get("evidence", {})
        if evidence is None:
            evidence = {}
        _require_mapping(f"results[{index}].evidence", evidence)
        normalized.append(
            {"requirement": requirement, "verdict": verdict, "evidence": evidence}
        )
    return normalized


def _budget_verdict(budget: dict[str, Any], usage: dict[str, Any]) -> BudgetVerdict:
    """Compare accumulated usage against the limits of one run."""
    exceeded: dict[str, str] = {}
    for usage_key, limit_key, label in _USAGE_TO_LIMIT:
        limit = budget.get(limit_key)
        if limit is None:
            continue
        used = usage.get(usage_key) or 0
        if used > limit:
            exceeded[label] = f"{_format_number(used)}>{_format_number(limit)}"
    return BudgetVerdict(ok=not exceeded, exceeded=exceeded, usage=dict(usage))


class RunCoordinator:
    """Durable owner of a run's state, progress, checkpoints and budgets.

    Args:
        db_path: Database file to persist into. ``None`` uses
            ``backend.persistence.db.DB_PATH``, i.e. the application database
            resolved at import time (so a test that repoints ``DB_PATH`` keeps
            working). The run tables are created if missing.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path: Path | None = Path(db_path) if db_path is not None else None
        # Re-entrant: complete() -> verify_definition_of_done() -> transition()
        # are nested calls on the same instance.
        self._lock = threading.RLock()
        if self._db_path is not None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        from backend.persistence import db

        db.ensure_run_state_schema(self._db_path)

    @property
    def db_path(self) -> str:
        """The database file this coordinator persists into."""
        if self._db_path is not None:
            return str(self._db_path)
        from backend.persistence import db

        return str(db.DB_PATH)

    # ───── runs ───────────────────────────────────────────────────────────

    def create_run(
        self,
        *,
        goal: str,
        requirements: Sequence[str],
        constraints: Sequence[str] | None = None,
        definition_of_done: Sequence[str] | None = None,
        project_id: str = "",
        user_id: str = "",
        session_id: str = "",
        budget: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> RunRecord:
        """Create a run in ``CREATED`` and return it.

        ``requirements`` and ``definition_of_done`` are plain strings; the
        latter is the checklist :meth:`complete` later enforces. An explicit
        ``run_id`` that already exists raises ``sqlite3.IntegrityError`` — a
        duplicate id is a caller bug, not something to paper over.
        """
        from backend.persistence import db

        resolved_run_id = run_id or _new_id()
        row = db.create_run_row(
            run_id=resolved_run_id,
            project_id=project_id,
            user_id=user_id,
            session_id=session_id,
            goal=goal,
            requirements=[str(item) for item in _require_sequence("requirements", requirements)],
            constraints=[
                str(item) for item in _require_sequence("constraints", constraints or [])
            ],
            definition_of_done=[
                str(item) for item in _require_sequence("definition_of_done", definition_of_done or [])
            ],
            state=RunState.CREATED.value,
            plan=None,
            budget=_normalize_budget(budget),
            db_path=self._db_path,
        )
        record = _row_to_record(row)
        logger.debug(
            "Run %s created (project=%s session=%s requirements=%d dod=%d)",
            record.run_id,
            record.project_id,
            record.session_id,
            len(record.requirements),
            len(record.definition_of_done),
        )
        return record

    def get_run(self, run_id: str) -> RunRecord | None:
        """Return a run, or ``None`` when it does not exist."""
        from backend.persistence import db

        row = db.get_run_row(run_id, db_path=self._db_path)
        return _row_to_record(row) if row else None

    def transition(self, run_id: str, new_state: RunState, *, reason: str = "") -> RunRecord:
        """Move a run to ``new_state``, returning the updated record.

        The transition table in this module is the only authority: an
        unlisted move logs a warning, raises :class:`InvalidRunTransition` and
        leaves the stored state exactly as it was. ``reason`` is stored as
        ``stop_reason``, so it always explains the latest transition.
        """
        from backend.persistence import db

        target = _as_state(new_state)
        with self._lock:
            current = self.get_run(run_id)
            if current is None:
                raise ValueError(f"unknown run_id: {run_id}")
            if target not in _TRANSITIONS.get(current.state, frozenset()):
                logger.warning(
                    "Invalid run transition %s: %s -> %s (refused)",
                    run_id,
                    current.state.value,
                    target.value,
                )
                raise InvalidRunTransition(run_id, current.state, target)
            row = db.update_run_row(
                run_id,
                {"state": target.value, "stop_reason": reason, "updated_at": _now_iso()},
                db_path=self._db_path,
            )
        if row is None:  # pragma: no cover - guarded by get_run above
            raise ValueError(f"unknown run_id: {run_id}")
        logger.debug("Run %s transitioned to %s (%s)", run_id, target.value, reason or "-")
        return _row_to_record(row)

    def list_runs(
        self,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        states: Sequence[RunState | str] | None = None,
        limit: int = 100,
    ) -> list[RunRecord]:
        """Return runs matching the filters, most recently updated first."""
        from backend.persistence import db

        state_names = [_as_state(state).value for state in states] if states else None
        rows = db.list_run_rows(
            project_id=project_id,
            session_id=session_id,
            user_id=user_id,
            states=state_names,
            limit=limit,
            db_path=self._db_path,
        )
        return [_row_to_record(row) for row in rows]

    def find_resumable_runs(
        self,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> list[RunRecord]:
        """Return runs that still own work, most recently updated first.

        "Resumable" means "not terminal": ``CREATED``, ``PLANNING``,
        ``RUNNING``, ``WAITING_TOOL``, ``WAITING_APPROVAL``, ``VERIFYING``,
        ``RECOVERING`` and ``PAUSED``. A completed, failed, cancelled or
        expired run is never offered, however fresh it is.
        """
        resumable = [state for state in RunState if state not in TERMINAL_RUN_STATES]
        return self.list_runs(
            project_id=project_id,
            session_id=session_id,
            user_id=user_id,
            states=resumable,
        )

    # ───── progresso/estado executável ────────────────────────────────────

    def update_progress(
        self,
        run_id: str,
        *,
        plan: dict[str, Any] | None = None,
        current_task_id: str | None = None,
        retry_count: int | None = None,
        provider: dict[str, Any] | None = None,
        memory_refs: Sequence[Any] | None = None,
        artifacts: Sequence[Any] | None = None,
        changed_files: Sequence[str] | None = None,
        heartbeat: bool = True,
    ) -> RunRecord:
        """Refresh the executable state of a run and return it.

        ``None`` means "leave this field unchanged"; pass ``[]`` to clear a
        list. ``heartbeat=False`` writes the field updates without touching
        ``heartbeat_at`` (useful for a bulk write that should not look like a
        liveness signal). ``updated_at`` always moves.
        """
        from backend.persistence import db

        updates: dict[str, Any] = {"updated_at": _now_iso()}
        if plan is not None:
            updates["plan_json"] = _json_dumps(_require_mapping("plan", plan))
        if current_task_id is not None:
            updates["current_task_id"] = str(current_task_id)
        if retry_count is not None:
            updates["retry_count"] = _coerce_int(retry_count, "retry_count")
        if provider is not None:
            updates["provider_json"] = _json_dumps(_require_mapping("provider", provider))
        if memory_refs is not None:
            updates["memory_refs_json"] = _json_dumps(_require_sequence("memory_refs", memory_refs))
        if artifacts is not None:
            updates["artifacts_json"] = _json_dumps(_require_sequence("artifacts", artifacts))
        if changed_files is not None:
            updates["changed_files_json"] = _json_dumps(
                [str(item) for item in _require_sequence("changed_files", changed_files)]
            )
        if heartbeat:
            updates["heartbeat_at"] = updates["updated_at"]
        with self._lock:
            row = db.update_run_row(run_id, updates, db_path=self._db_path)
        if row is None:
            raise ValueError(f"unknown run_id: {run_id}")
        return _row_to_record(row)

    # ───── checkpoints ────────────────────────────────────────────────────

    def checkpoint(
        self, run_id: str, *, phase: str, payload: dict[str, Any]
    ) -> Checkpoint:
        """Record a checkpoint at a phase boundary and return it."""
        from backend.persistence import db

        if phase not in CHECKPOINT_PHASES:
            raise ValueError(
                f"unknown checkpoint phase {phase!r}; expected one of: "
                f"{', '.join(sorted(CHECKPOINT_PHASES))}"
            )
        _require_mapping("payload", payload)
        with self._lock:
            if db.get_run_row(run_id, db_path=self._db_path) is None:
                raise ValueError(f"unknown run_id: {run_id}")
            row = db.insert_checkpoint_row(
                checkpoint_id=_new_id(),
                run_id=run_id,
                phase=phase,
                payload_json=_json_dumps(payload),
                db_path=self._db_path,
            )
        return _row_to_checkpoint(row)

    def latest_checkpoint(self, run_id: str, *, phase: str | None = None) -> Checkpoint | None:
        """Return the newest checkpoint, optionally restricted to one phase."""
        from backend.persistence import db

        row = db.latest_checkpoint_row(run_id, phase=phase, db_path=self._db_path)
        return _row_to_checkpoint(row) if row else None

    def list_checkpoints(self, run_id: str, *, limit: int = 50) -> list[Checkpoint]:
        """Return a run's checkpoints, newest first."""
        from backend.persistence import db

        rows = db.list_checkpoint_rows(run_id, limit=limit, db_path=self._db_path)
        return [_row_to_checkpoint(row) for row in rows]

    def restore(self, run_id: str, *, checkpoint_id: str | None = None) -> Checkpoint:
        """Return the checkpoint a run should continue from.

        Uses ``checkpoint_id`` when given, otherwise the newest checkpoint of
        the run, then moves the run to ``RECOVERING`` so the recovery path is
        visible in the state machine (and a crash during recovery can itself be
        recovered). Raises when the run is unknown or has no checkpoint, and
        propagates :class:`InvalidRunTransition` if the run cannot recover.
        """
        from backend.persistence import db

        with self._lock:
            if db.get_run_row(run_id, db_path=self._db_path) is None:
                raise ValueError(f"unknown run_id: {run_id}")
            if checkpoint_id is None:
                row = db.latest_checkpoint_row(run_id, db_path=self._db_path)
            else:
                row = db.get_checkpoint_row(checkpoint_id, db_path=self._db_path)
                if row is not None and str(row["run_id"]) != run_id:
                    raise ValueError(
                        f"checkpoint {checkpoint_id} belongs to run {row['run_id']}, "
                        f"not {run_id}"
                    )
            if row is None:
                raise ValueError(f"run {run_id} has no checkpoint to restore")
            recovered = _row_to_checkpoint(row)
            self.transition(run_id, RunState.RECOVERING, reason=f"restored {recovered.checkpoint_id}")
        logger.info(
            "Run %s restored from checkpoint %s (phase=%s)",
            run_id,
            recovered.checkpoint_id,
            recovered.phase,
        )
        return recovered

    # ───── idempotência de side effects ───────────────────────────────────

    def is_side_effect_confirmed(self, run_id: str, idempotency_key: str) -> bool:
        """Return whether a side effect is already recorded for this key."""
        from backend.persistence import db

        return (
            db.get_side_effect_row(run_id, idempotency_key, db_path=self._db_path) is not None
        )

    def record_side_effect(
        self, run_id: str, idempotency_key: str, *, kind: str, result_digest: str
    ) -> None:
        """Record a side effect so a replay is recognised as already done.

        Idempotent: the first call for a ``(run_id, idempotency_key)`` pair
        wins, and a later call with the same pair changes nothing. Use
        :meth:`get_side_effect` to read back what was actually stored.
        """
        from backend.persistence import db

        with self._lock:
            if db.get_run_row(run_id, db_path=self._db_path) is None:
                raise ValueError(f"unknown run_id: {run_id}")
            db.insert_side_effect_row(
                run_id,
                idempotency_key,
                kind=kind,
                result_digest=result_digest,
                db_path=self._db_path,
            )

    def get_side_effect(
        self, run_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        """Return the recorded side effect, or ``None`` when unconfirmed."""
        from backend.persistence import db

        row = db.get_side_effect_row(run_id, idempotency_key, db_path=self._db_path)
        return dict(row) if row else None

    # ───── orçamentos (hard limits) ───────────────────────────────────────

    def record_usage(
        self,
        run_id: str,
        *,
        tokens: int = 0,
        cost_usd: float = 0.0,
        tool_calls: int = 0,
        retries: int = 0,
        browser_actions: int = 0,
        subagents: int = 0,
        runtime_seconds: float = 0.0,
        provider_calls: int = 0,
    ) -> BudgetVerdict:
        """Accumulate usage for a run and return the resulting verdict.

        The accumulation is one atomic statement, so concurrent writers cannot
        lose each other's increment. ``ok=False`` means at least one hard limit
        is now exceeded and the caller must stop the run.
        """
        from backend.persistence import db

        usage_tokens = _coerce_int(tokens, "tokens")
        usage_cost = float(cost_usd)
        usage_tool_calls = _coerce_int(tool_calls, "tool_calls")
        usage_retries = _coerce_int(retries, "retries")
        usage_browser_actions = _coerce_int(browser_actions, "browser_actions")
        usage_subagents = _coerce_int(subagents, "subagents")
        usage_runtime = float(runtime_seconds)
        usage_provider_calls = _coerce_int(provider_calls, "provider_calls")
        with self._lock:
            usage = db.record_usage_row(
                run_id,
                tokens=usage_tokens,
                cost_usd=usage_cost,
                tool_calls=usage_tool_calls,
                retries=usage_retries,
                browser_actions=usage_browser_actions,
                subagents=usage_subagents,
                runtime_seconds=usage_runtime,
                provider_calls=usage_provider_calls,
                db_path=self._db_path,
            )
            run = self.get_run(run_id)
        if run is None:  # pragma: no cover - record_usage_row raises for unknown runs
            raise ValueError(f"unknown run_id: {run_id}")
        return _budget_verdict(run.budget, usage)

    def budget_status(self, run_id: str) -> BudgetVerdict:
        """Return the current usage of a run against its limits."""
        from backend.persistence import db

        with self._lock:
            run = self.get_run(run_id)
            if run is None:
                raise ValueError(f"unknown run_id: {run_id}")
            usage = db.get_usage_row(run_id, db_path=self._db_path)
        return _budget_verdict(run.budget, usage)

    # ───── definição de done ──────────────────────────────────────────────

    def verify_definition_of_done(
        self, run_id: str, results: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Check the run's definition of done against reported evidence.

        ``results`` carries one dict per requirement with ``requirement``,
        ``evidence`` and ``verdict`` (``PASS`` / ``FAIL`` / ``UNKNOWN``).
        Returns ``{"ok": bool, "requirements": [...], "missing": [...]}``:
        ``missing`` holds one entry per unmet requirement — never reported
        (``reason="not_reported"``), failed, or still ``UNKNOWN``. An
        ``UNKNOWN`` on a required requirement makes ``ok`` ``False``: absence of
        evidence is not evidence.

        The normalised verdicts are persisted on the run so the definition of
        done can be audited after the fact.
        """
        from backend.persistence import db

        with self._lock:
            run = self.get_run(run_id)
            if run is None:
                raise ValueError(f"unknown run_id: {run_id}")
            normalized = _normalize_dod_results(results)
            by_requirement = {entry["requirement"]: entry for entry in normalized}
            missing: list[dict[str, Any]] = []
            for requirement in run.definition_of_done:
                entry = by_requirement.get(requirement)
                if entry is None:
                    missing.append(
                        {"requirement": requirement, "verdict": "UNKNOWN", "reason": "not_reported"}
                    )
                elif entry["verdict"] == "PASS":
                    continue
                else:
                    missing.append(
                        {
                            "requirement": requirement,
                            "verdict": entry["verdict"],
                            "reason": "failed" if entry["verdict"] == "FAIL" else "unknown",
                        }
                    )
            db.update_run_row(
                run_id,
                {"dod_results_json": _json_dumps(normalized), "updated_at": _now_iso()},
                db_path=self._db_path,
            )
        verdict = {
            "ok": not missing,
            "requirements": normalized,
            "missing": missing,
        }
        logger.debug(
            "Definition of done for run %s: ok=%s missing=%d",
            run_id,
            verdict["ok"],
            len(missing),
        )
        return verdict

    def complete(self, run_id: str, dod_results: list[dict[str, Any]]) -> RunRecord:
        """Close a run as ``COMPLETED``, but only if the definition of done is
        satisfied.

        The run must be in a state that can reach ``COMPLETED`` (``RUNNING`` or
        ``VERIFYING`` in practice): the state machine refuses a run that never
        ran, and this method does not bypass it. Raises
        :class:`DoDNotSatisfied` — carrying the unmet requirements — when the
        definition of done is not met, leaving the run in its current state so
        the caller can keep working instead of losing the result.
        """
        with self._lock:
            verdict = self.verify_definition_of_done(run_id, dod_results)
            if not verdict["ok"]:
                raise DoDNotSatisfied(run_id, verdict["missing"])
            return self.transition(run_id, RunState.COMPLETED, reason="definition_of_done satisfied")

    # ───── DLQ ────────────────────────────────────────────────────────────

    def enqueue_dead_letter(self, entry: dict[str, Any]) -> str:
        """Park a failed unit in the dead-letter queue and return its id.

        ``entry`` accepts ``task_id``, ``run_id``, ``error_class``,
        ``sanitized_traceback``, ``attempts``, ``last_tool``,
        ``last_provider``, ``last_evidence``, ``recoverability`` and
        ``retry_after``; anything missing defaults to empty. The traceback must
        already be sanitised — this queue is read by humans.
        """
        from backend.persistence import db

        _require_mapping("entry", entry)
        last_evidence = entry.get("last_evidence")
        if last_evidence is None:
            evidence_json = "{}"
        elif isinstance(last_evidence, str):
            evidence_json = last_evidence
        else:
            evidence_json = _json_dumps(_require_mapping("last_evidence", last_evidence))
        retry_after = entry.get("retry_after")
        entry_id = _new_id()
        db.insert_dead_letter_row(
            entry_id=entry_id,
            run_id=str(entry.get("run_id") or ""),
            task_id=str(entry.get("task_id") or ""),
            error_class=str(entry.get("error_class") or ""),
            sanitized_traceback=str(entry.get("sanitized_traceback") or ""),
            attempts=_coerce_int(entry.get("attempts"), "attempts"),
            last_tool=str(entry.get("last_tool") or ""),
            last_provider=str(entry.get("last_provider") or ""),
            last_evidence_json=evidence_json,
            recoverability=str(entry.get("recoverability") or "unknown"),
            retry_after=None if retry_after is None else str(retry_after),
            db_path=self._db_path,
        )
        logger.info(
            "Dead letter %s enqueued (run=%s task=%s error_class=%s recoverability=%s)",
            entry_id,
            entry.get("run_id") or "",
            entry.get("task_id") or "",
            entry.get("error_class") or "",
            entry.get("recoverability") or "unknown",
        )
        return entry_id

    def list_dead_letters(
        self,
        *,
        run_id: str | None = None,
        state: str | None = "open",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return dead-letter entries, newest first.

        ``state=None`` returns entries in every state, ``state="open"`` (the
        default) only the ones nobody has dealt with yet.
        """
        from backend.persistence import db

        if state is not None and state not in DEAD_LETTER_STATES:
            raise ValueError(
                f"unknown dead letter state {state!r}; expected one of: "
                f"{', '.join(sorted(DEAD_LETTER_STATES))}"
            )
        rows = db.list_dead_letter_rows(
            run_id=run_id, state=state, limit=limit, db_path=self._db_path
        )
        return [_row_to_dead_letter(row) for row in rows]

    def update_dead_letter(
        self, entry_id: str, *, state: str, note: str = ""
    ) -> dict[str, Any]:
        """Move a dead-letter entry to a new state, appending ``note``.

        Returns the updated entry; raises when the id is unknown or the state
        is not one of ``open``, ``retrying``, ``requeued``, ``replanned``,
        ``abandoned`` or ``escalated``.
        """
        from backend.persistence import db

        if state not in DEAD_LETTER_STATES:
            raise ValueError(
                f"unknown dead letter state {state!r}; expected one of: "
                f"{', '.join(sorted(DEAD_LETTER_STATES))}"
            )
        with self._lock:
            row = db.update_dead_letter_row(
                entry_id, state=state, note=note, db_path=self._db_path
            )
        if row is None:
            raise ValueError(f"unknown dead letter entry: {entry_id}")
        return _row_to_dead_letter(row)

    # ───── retenção/TTL ───────────────────────────────────────────────────

    def prune(
        self,
        *,
        runs_days: int = 30,
        checkpoints_days: int = 14,
        dead_letters_days: int = 90,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Apply retention to run state, checkpoints, dead letters and the
        scheduled-task queue.

        Only terminal runs older than ``runs_days`` are deleted (their
        checkpoints, side effects and dead letters go with them), checkpoints
        older than ``checkpoints_days`` and dead letters older than
        ``dead_letters_days`` are dropped, and completed scheduled tasks older
        than ``runs_days`` are pruned. ``dry_run`` reports the counts without
        deleting. The returned dict always has the keys ``runs``,
        ``checkpoints``, ``side_effects``, ``dead_letters`` and
        ``scheduled_tasks``.
        """
        from backend.persistence import db

        now = datetime.now(UTC)
        counts = db.prune_run_state_tables(
            runs_cutoff=_cutoff_iso(runs_days, now),
            checkpoints_cutoff=_cutoff_iso(checkpoints_days, now),
            dead_letters_cutoff=_cutoff_iso(dead_letters_days, now),
            dry_run=dry_run,
            db_path=self._db_path,
        )
        # Scheduled tasks are retention-managed with the run window: they are
        # the table that grows ~1440 rows/day and they carry no run_id.
        counts["scheduled_tasks"] = db.prune_scheduled_tasks(
            runs_days, dry_run=dry_run, db_path=self._db_path
        )
        logger.debug("Run-state prune: %s (dry_run=%s)", counts, dry_run)
        return counts
