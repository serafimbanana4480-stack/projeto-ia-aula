"""Durable, owner-scoped group executions (projection + legacy executor).

The canonical identity of one composer request is the primary runtime's
``run_id`` (``run_state.run_id``). A ``primary`` group run stores the same id in
``bot_group_runs.id``; a ``legacy_file`` run predates that path and only lives
here. Either way this module keeps the task rows durable and enforces the rules
the group runtime depends on:

* **One owner per attempt.** ``attempt`` is a retry counter. Every
  :func:`claim_task` also mints a fresh ``attempt_id`` (a fencing token).
  Writes are accepted only from the worker + token pair that still owns the
  row, so an old attempt is rejected even when it reuses the same
  ``worker_id``.
* **Atomic claims.** Claims run inside ``BEGIN IMMEDIATE``; the in-memory
  ``_claim_context`` only carries the token a caller received, never the
  authority. Two executors (threads, processes or a restarted backend) cannot
  run the same task.
* **Leases, not free retries.** Clearing or losing a lease keeps ``attempt``,
  ``attempt_id`` and every accumulated run budget untouched. A live lease
  cannot be stolen; an expired one can be taken over, which rotates the token.
* **Explicit outcomes.** ``pending``, ``running``, ``interrupted`` (process
  loss), ``retryable`` (transient provider error), ``failed`` (terminal),
  ``skipped`` (the plan did not run it), ``blocked`` (needs reconciliation),
  ``cancelled`` and ``completed`` are distinct. ``completed`` never runs again
  and a ``cancelled`` run never resurrects.
* **Crash after a write.** :func:`begin_effect` reserves an intent in the
  primary ``run_side_effects`` ledger before a real-world action;
  :func:`interrupt_unfinished` uses the ledger plus on-disk evidence to mark a
  task ``blocked`` instead of replaying the write blind.

Single-process SQLite is the supported deployment. The atomic claim is still
persisted and proven with two real processes, but a shared multi-worker
deployment is not claimed.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.persistence.db import _now_iso, get_db

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "RUN_TERMINAL_STATUSES",
    "TASK_STATUSES",
    "TERMINAL_TASK_STATUSES",
    "TaskOwnershipError",
    "begin_effect",
    "cancel_run",
    "claim_run",
    "claim_task",
    "complete_task",
    "confirm_effect",
    "create",
    "fail_task",
    "get",
    "get_effect_state",
    "heartbeat_run",
    "heartbeat_task",
    "interrupt_unfinished",
    "list_blocked_runs",
    "list_interrupted_runs",
    "list_runs",
    "owns_run",
    "record",
    "release_run",
    "release_task",
    "set_run",
    "set_task",
]

#: Retry counter ceiling per task. ``attempt`` is not reset when a lease is
#: cleared, so a crash cannot buy extra retries.
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_LEASE_SECONDS = 300.0

TASK_STATUSES = frozenset(
    {
        "pending",
        "running",
        "interrupted",
        "retryable",
        "failed",
        "skipped",
        "blocked",
        "cancelled",
        "completed",
    }
)
TERMINAL_TASK_STATUSES = frozenset(
    {"completed", "failed", "skipped", "cancelled", "blocked"}
)
RUN_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

#: Statuses a new claim may start from. ``failed``/``skipped`` are terminal
#: outcomes; only an explicit operator reset may return them to ``pending``.
_RETRYABLE_TASK_STATUSES = frozenset({"pending", "interrupted", "retryable"})

#: Run statuses that make every task unclaimable. ``blocked`` is a
#: reconciliation gate, not a retry.
_BLOCKING_RUN_STATUSES = frozenset({"completed", "cancelled", "blocked"})

#: The token a legacy caller received from :func:`claim_task` in this context.
#: It is only a convenience for the old ``set_task(worker_id=...)`` signature;
#: every write is still validated against the token persisted in SQLite.
_claim_context: ContextVar[dict[str, str] | None] = ContextVar(
    "group_task_claims", default=None
)


class TaskOwnershipError(RuntimeError):
    """Raised when a write no longer owns the task's current attempt."""


def _max_attempts() -> int:
    raw = os.environ.get("NEXUS_GROUP_TASK_MAX_ATTEMPTS", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MAX_ATTEMPTS
    except ValueError:
        value = DEFAULT_MAX_ATTEMPTS
    return max(1, value)


def _lease_seconds(value: float | None) -> float:
    if value is not None:
        return max(0.01, float(value))
    raw = os.environ.get("NEXUS_GROUP_TASK_LEASE_SECONDS", "").strip()
    try:
        parsed = float(raw) if raw else DEFAULT_LEASE_SECONDS
    except ValueError:
        parsed = DEFAULT_LEASE_SECONDS
    return max(1.0, parsed)


def _deadline(seconds: float | None = None) -> str:
    return (
        (datetime.now(UTC) + timedelta(seconds=_lease_seconds(seconds)))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _lease_is_live(value: Any) -> bool:
    if not value:
        return False
    try:
        deadline = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return deadline > datetime.now(UTC)


def _remember_claim(task_id: str, attempt_id: str) -> None:
    tokens = dict(_claim_context.get() or {})
    tokens[task_id] = attempt_id
    _claim_context.set(tokens)


def _remembered_claim(task_id: str) -> str | None:
    return (_claim_context.get() or {}).get(task_id)


@contextmanager
def _write_transaction() -> Iterator[Any]:
    """One write transaction serialised across connections and processes."""
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise


def _validate_task_status(status: str) -> str:
    value = str(status)
    if value not in TASK_STATUSES:
        raise ValueError(
            f"unknown group task status {value!r}; expected one of: "
            f"{', '.join(sorted(TASK_STATUSES))}"
        )
    return value


def _task_row(conn: Any, task_id: str) -> Any:
    return conn.execute(
        """SELECT t.*, r.user_id, r.group_id, r.project_root, r.status AS run_status,
                  r.lease_owner AS run_lease_owner,
                  r.lease_attempt_id AS run_lease_attempt_id,
                  r.lease_expires_at AS run_lease_expires_at
           FROM bot_group_run_tasks t
           JOIN bot_group_runs r ON r.id = t.run_id
           WHERE t.id = ?""",
        (task_id,),
    ).fetchone()


def _owns_row(row: Any, worker_id: str, attempt_id: str | None) -> str:
    if not worker_id:
        raise TaskOwnershipError("worker_id is required for an owner-scoped write")
    token = attempt_id or _remembered_claim(str(row["id"]))
    if not token:
        raise TaskOwnershipError(
            f"task {row['id']} has no attempt token in this context; claim it first"
        )
    if row["worker_id"] != worker_id or row["attempt_id"] != token:
        raise TaskOwnershipError(
            f"task {row['id']} is owned by attempt {row['attempt_id']!r}, "
            f"not {token!r} (worker {worker_id})"
        )
    return token


def _assert_owner(row: Any, worker_id: str, attempt_id: str | None) -> str:
    token = _owns_row(row, worker_id, attempt_id)
    if row["status"] != "running":
        raise TaskOwnershipError(
            f"task {row['id']} is {row['status']}, not running; refusing the write"
        )
    return token


def create(
    owner: str,
    group_id: str,
    request: str,
    root: str,
    path: str,
    profiles: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    execution_engine: str = "legacy_file",
) -> str:
    """Create one group run and its task rows atomically.

    ``run_id`` lets the primary path reuse ``run_state.run_id`` so the group
    projection and the durable execution share one identity. Legacy callers
    keep the old positional signature and get a generated id.
    """
    resolved_run_id = run_id or uuid4().hex
    engine = str(execution_engine or "legacy_file")
    now = _now_iso()
    with _write_transaction() as conn:
        conn.execute(
            "INSERT INTO bot_group_runs "
            "(id, group_id, user_id, request, project_root, file_path, status, "
            "execution_engine, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            (resolved_run_id, group_id, owner, request, root, path, engine, now, now),
        )
        for position, profile in enumerate(profiles):
            conn.execute(
                "INSERT INTO bot_group_run_tasks "
                "(id, run_id, position, bot_id, bot_name, provider, model, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
                (
                    uuid4().hex,
                    resolved_run_id,
                    position,
                    profile["id"],
                    profile["name"],
                    profile["provider"],
                    profile["model"],
                ),
            )
    return resolved_run_id


def get(owner: str, group_id: str, run_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, group_id, request, project_root, file_path, status, "
            "execution_engine, lease_owner, lease_attempt_id, lease_expires_at, "
            "stop_reason, created_at, updated_at "
            "FROM bot_group_runs WHERE id=? AND group_id=? AND user_id=?",
            (run_id, group_id, owner),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["tasks"] = [
            dict(item)
            for item in conn.execute(
                "SELECT * FROM bot_group_run_tasks WHERE run_id=? ORDER BY position",
                (run_id,),
            )
        ]
        result["records"] = [
            {**dict(item), "payload": json.loads(item["payload"])}
            for item in conn.execute(
                "SELECT * FROM bot_group_run_records WHERE run_id=? ORDER BY rowid",
                (run_id,),
            )
        ]
        return result


def list_runs(owner: str, group_id: str) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id FROM bot_group_runs WHERE user_id=? AND group_id=? "
            "ORDER BY rowid DESC LIMIT 50",
            (owner, group_id),
        ).fetchall()
    return [
        run
        for row in rows
        if (run := get(owner, group_id, row["id"])) is not None
    ]


def set_run(run_id: str, status: str) -> bool:
    """Project a run status, refusing to resurrect a terminal outcome.

    A completed run never leaves ``completed`` and a cancelled run never leaves
    ``cancelled``. Clearing the lease on a terminal projection is safe: it
    changes ownership, never the retry counter or the primary run's budget.
    """
    target = str(status)
    with _write_transaction() as conn:
        row = conn.execute(
            "SELECT status FROM bot_group_runs WHERE id=?", (run_id,)
        ).fetchone()
        if row is None:
            return False
        current = str(row["status"])
        if current == "completed" and target != "completed":
            return False
        if current == "cancelled" and target != "cancelled":
            return False
        if current == "blocked" and target == "running":
            # Reconciliation is a gate; an operator must clear it explicitly.
            return False
        if target == "completed" and current in {"cancelled", "blocked"}:
            return False
        now = _now_iso()
        if target in RUN_TERMINAL_STATUSES or target in {"blocked", "interrupted"}:
            conn.execute(
                "UPDATE bot_group_runs SET status=?, stop_reason=?, updated_at=?, "
                "lease_owner=NULL, lease_attempt_id=NULL, lease_expires_at=NULL "
                "WHERE id=?",
                (target, "run " + target, now, run_id),
            )
            # The projection going terminal releases the primary lease without
            # touching the run's state, retry counters or accumulated budget.
            conn.execute(
                "UPDATE run_state SET owner_id='', attempt_id=NULL, "
                "lease_expires_at=NULL WHERE run_id=?",
                (run_id,),
            )
        else:
            conn.execute(
                "UPDATE bot_group_runs SET status=?, updated_at=? WHERE id=?",
                (target, now, run_id),
            )
    return True


def claim_run(
    run_id: str,
    worker_id: str,
    *,
    lease_seconds: float | None = None,
    force: bool = False,
) -> str | None:
    """Atomically claim the right to resume one run.

    Two concurrent resumes produce exactly one token. ``force`` is reserved for
    startup/manual recovery after the previous process is known dead; it still
    rotates the token, so the old executor's writes are fenced off. The claim
    also mirrors into ``run_state`` when the primary row exists, keeping one
    authority and one attempt identity across both projections.
    """
    if not worker_id:
        raise ValueError("worker_id is required")
    now = _now_iso()
    deadline = _deadline(lease_seconds)
    with _write_transaction() as conn:
        row = conn.execute(
            "SELECT status, lease_owner, lease_attempt_id, lease_expires_at, project_root "
            "FROM bot_group_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        status = str(row["status"])
        if status in _BLOCKING_RUN_STATUSES:
            return None
        group_live = _lease_is_live(row["lease_expires_at"])
        same_group_owner = str(row["lease_owner"] or "") == worker_id
        if group_live and not same_group_owner and not force:
            return None
        attempt_id = (
            str(row["lease_attempt_id"])
            if group_live and same_group_owner and row["lease_attempt_id"] and not force
            else uuid4().hex
        )
        primary = conn.execute(
            "SELECT state, owner_id, attempt_id, lease_expires_at, reconciliation_json "
            "FROM run_state WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if primary is not None:
            if str(primary["state"]) in {"completed", "failed", "cancelled", "expired"}:
                return None
            if primary["reconciliation_json"]:
                return None
            primary_live = _lease_is_live(primary["lease_expires_at"])
            same_primary_owner = primary_live and (
                str(primary["owner_id"] or "") == worker_id
            )
            if primary_live and str(primary["owner_id"] or "") != worker_id and not force:
                return None
            if same_primary_owner and primary["attempt_id"] and not force:
                # Adopt the primary attempt identity instead of rotating it:
                # the caller may already hold this token (RunLifecycle claim).
                attempt_id = str(primary["attempt_id"])
            conn.execute(
                "UPDATE run_state SET owner_id=?, attempt_id=?, lease_expires_at=?, "
                "updated_at=?, heartbeat_at=? WHERE run_id=?",
                (worker_id, attempt_id, deadline, now, now, run_id),
            )
        conn.execute(
            "UPDATE bot_group_runs SET status='running', lease_owner=?, "
            "lease_attempt_id=?, lease_expires_at=?, updated_at=? WHERE id=?",
            (worker_id, attempt_id, deadline, now, run_id),
        )
    return attempt_id


def owns_run(run_id: str, attempt_id: str) -> bool:
    """Whether ``attempt_id`` still owns the run projection."""
    if not attempt_id:
        return False
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM bot_group_runs WHERE id=? AND lease_attempt_id=?",
            (run_id, attempt_id),
        ).fetchone()
    return row is not None


def heartbeat_run(
    run_id: str,
    worker_id: str,
    attempt_id: str,
    *,
    lease_seconds: float | None = None,
) -> bool:
    """Extend a live run lease without touching attempts or budget."""
    deadline = _deadline(lease_seconds)
    now = _now_iso()
    with _write_transaction() as conn:
        cursor = conn.execute(
            "UPDATE bot_group_runs SET lease_expires_at=?, updated_at=? "
            "WHERE id=? AND lease_owner=? AND lease_attempt_id=? AND status='running'",
            (deadline, now, run_id, worker_id, attempt_id),
        )
        conn.execute(
            "UPDATE run_state SET lease_expires_at=?, updated_at=?, heartbeat_at=? "
            "WHERE run_id=? AND owner_id=? AND attempt_id=?",
            (deadline, now, now, run_id, worker_id, attempt_id),
        )
        return bool(cursor.rowcount == 1)


def release_run(
    run_id: str,
    worker_id: str,
    attempt_id: str,
    *,
    status: str | None = None,
) -> bool:
    """Release a run lease while preserving the attempt history."""
    with _write_transaction() as conn:
        cursor = conn.execute(
            "UPDATE bot_group_runs SET lease_owner=NULL, lease_attempt_id=NULL, "
            "lease_expires_at=NULL, updated_at=? "
            "WHERE id=? AND lease_owner=? AND lease_attempt_id=?",
            (_now_iso(), run_id, worker_id, attempt_id),
        )
        conn.execute(
            "UPDATE run_state SET owner_id='', attempt_id=NULL, lease_expires_at=NULL "
            "WHERE run_id=? AND owner_id=? AND attempt_id=?",
            (run_id, worker_id, attempt_id),
        )
        released = bool(cursor.rowcount == 1)
    if released and status:
        set_run(run_id, status)
    return released


def cancel_run(run_id: str, *, reason: str = "") -> bool:
    """Cancel a run and every task that has not completed.

    Cancellation is terminal for this execution: a later ``set_run``/claim
    cannot move it back to running.
    """
    detail = (reason or "Execução cancelada.")[:400]
    with _write_transaction() as conn:
        row = conn.execute(
            "SELECT status FROM bot_group_runs WHERE id=?", (run_id,)
        ).fetchone()
        if row is None or str(row["status"]) in {"completed", "cancelled"}:
            return False
        now = _now_iso()
        conn.execute(
            "UPDATE bot_group_run_tasks SET status='cancelled', error=?, "
            "error_class='cancelled', finished_at=?, worker_id=NULL, claimed_at=NULL, "
            "lease_expires_at=NULL WHERE run_id=? AND status IN ('pending','running','interrupted','retryable')",
            (detail, now, run_id),
        )
        conn.execute(
            "UPDATE bot_group_runs SET status='cancelled', stop_reason=?, updated_at=?, "
            "lease_owner=NULL, lease_attempt_id=NULL, lease_expires_at=NULL WHERE id=?",
            (detail, now, run_id),
        )
        conn.execute(
            "UPDATE run_state SET owner_id='', attempt_id=NULL, lease_expires_at=NULL "
            "WHERE run_id=?",
            (run_id,),
        )
    return True


def _ensure_run_lease(
    conn: Any, row: Any, worker_id: str, *, lease_seconds: float | None
) -> bool:
    """Acquire/renew the run-level lease for the executor claiming a task.

    A task claim is also a run resume: without this, two processes could each
    win a different task of the same run and execute it concurrently. The
    contract is one owner per run. The primary ``run_state`` lease is mirrored
    when the row exists, so the authority and the projection agree on the same
    fencing token.
    """
    now = _now_iso()
    deadline = _deadline(lease_seconds)
    run_id = str(row["run_id"])
    primary = conn.execute(
        "SELECT state, owner_id, attempt_id, lease_expires_at, reconciliation_json "
        "FROM run_state WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if primary is not None:
        if str(primary["state"]) in {"completed", "failed", "cancelled", "expired"}:
            return False
        if primary["reconciliation_json"]:
            return False
    primary_live = primary is not None and _lease_is_live(primary["lease_expires_at"])
    group_live = _lease_is_live(row["run_lease_expires_at"])
    if primary_live and str(primary["owner_id"]) != worker_id:
        return False
    if group_live and str(row["run_lease_owner"] or "") != worker_id:
        return False

    if primary_live and str(primary["owner_id"]) == worker_id:
        token = str(primary["attempt_id"] or uuid4().hex)
        conn.execute(
            "UPDATE run_state SET lease_expires_at=?, updated_at=?, heartbeat_at=? "
            "WHERE run_id=? AND attempt_id=?",
            (deadline, now, now, run_id, token),
        )
    elif primary is not None:
        token = uuid4().hex
        conn.execute(
            "UPDATE run_state SET owner_id=?, attempt_id=?, lease_expires_at=?, "
            "updated_at=?, heartbeat_at=? WHERE run_id=?",
            (worker_id, token, deadline, now, now, run_id),
        )
    else:
        token = str(row["run_lease_attempt_id"] or uuid4().hex)

    if group_live and str(row["run_lease_owner"] or "") == worker_id:
        conn.execute(
            "UPDATE bot_group_runs SET lease_expires_at=?, updated_at=? WHERE id=?",
            (deadline, now, run_id),
        )
    else:
        conn.execute(
            "UPDATE bot_group_runs SET lease_owner=?, lease_attempt_id=?, "
            "lease_expires_at=?, updated_at=? WHERE id=?",
            (worker_id, token, deadline, now, run_id),
        )
    return True


def _claim_one(
    conn: Any,
    task_id: str,
    worker_id: str,
    *,
    lease_seconds: float | None,
    max_attempts: int,
) -> str | None:
    row = _task_row(conn, task_id)
    if row is None:
        return None
    run_status = str(row["run_status"])
    if run_status in _BLOCKING_RUN_STATUSES:
        return None
    status = str(row["status"])
    if status == "running":
        if _lease_is_live(row["lease_expires_at"]):
            return None
        # Expired lease: takeover is allowed, but the old token is rotated.
    elif status not in _RETRYABLE_TASK_STATUSES:
        return None
    attempt = int(row["attempt"] or 0)
    if attempt >= max_attempts:
        conn.execute(
            "UPDATE bot_group_run_tasks SET status='failed', error_class='retry_exhausted', "
            "error=?, finished_at=?, worker_id=NULL, claimed_at=NULL, lease_expires_at=NULL "
            "WHERE id=?",
            (
                f"Limite de {max_attempts} tentativas atingido.",
                _now_iso(),
                task_id,
            ),
        )
        return None
    if not _ensure_run_lease(conn, row, worker_id, lease_seconds=lease_seconds):
        return None
    token = uuid4().hex
    now = _now_iso()
    cursor = conn.execute(
        """UPDATE bot_group_run_tasks
           SET status='running', worker_id=?, attempt_id=?, claimed_at=?,
               lease_expires_at=?, attempt=attempt+1, result=NULL, error=NULL,
               error_class=NULL, finished_at=NULL
           WHERE id=? AND status=? AND attempt=? AND attempt_id IS ?""",
        (
            worker_id,
            token,
            now,
            _deadline(lease_seconds),
            task_id,
            status,
            attempt,
            row["attempt_id"],
        ),
    )
    if cursor.rowcount != 1:
        return None
    # A claimed task means the run is executing again: keep the projection in
    # step with the ownership row (terminal/blocked runs were refused above).
    conn.execute(
        "UPDATE bot_group_runs SET status='running', updated_at=? "
        "WHERE id=? AND status IN ('pending','interrupted','failed')",
        (now, str(row["run_id"])),
    )
    return token


def claim_task(
    task_id: str,
    worker_id: str,
    *,
    lease_seconds: float | None = None,
    max_attempts: int | None = None,
) -> str | None:
    """Atomically claim a pending/interrupted/retryable or stale task.

    Returns the new ``attempt_id`` (truthy, so the historical boolean usage
    keeps working) or ``None`` when another live attempt owns the task, the
    task is completed/skipped/failed/blocked, the run is cancelled/completed,
    or the retry ceiling was reached.
    """
    if not worker_id:
        raise ValueError("worker_id is required")
    limit = _max_attempts() if max_attempts is None else max(1, int(max_attempts))
    with _write_transaction() as conn:
        token = _claim_one(
            conn, task_id, worker_id, lease_seconds=lease_seconds, max_attempts=limit
        )
    if token:
        _remember_claim(task_id, token)
    return token


def heartbeat_task(
    task_id: str,
    worker_id: str,
    attempt_id: str | None = None,
    *,
    lease_seconds: float | None = None,
) -> bool:
    """Renew the task lease for the current owner + attempt only."""
    token = attempt_id or _remembered_claim(task_id)
    if not token:
        return False
    with _write_transaction() as conn:
        cursor = conn.execute(
            "UPDATE bot_group_run_tasks SET lease_expires_at=? "
            "WHERE id=? AND worker_id=? AND attempt_id=? AND status='running'",
            (_deadline(lease_seconds), task_id, worker_id, token),
        )
        renewed = bool(cursor.rowcount == 1)
        if renewed:
            now = _now_iso()
            deadline = _deadline(lease_seconds)
            task = conn.execute(
                "SELECT run_id FROM bot_group_run_tasks WHERE id=?", (task_id,)
            ).fetchone()
            if task is not None:
                run_id = str(task["run_id"])
                conn.execute(
                    "UPDATE bot_group_runs SET lease_expires_at=?, updated_at=? "
                    "WHERE id=? AND lease_owner=?",
                    (deadline, now, run_id, worker_id),
                )
                conn.execute(
                    "UPDATE run_state SET lease_expires_at=?, updated_at=?, heartbeat_at=? "
                    "WHERE run_id=? AND owner_id=?",
                    (deadline, now, now, run_id, worker_id),
                )
        return renewed


def _write_task(
    task_id: str,
    status: str,
    *,
    result: str | None,
    error: str | None,
    worker_id: str | None,
    attempt_id: str | None,
    error_class: str | None,
) -> bool:
    target = _validate_task_status(status)
    with _write_transaction() as conn:
        row = _task_row(conn, task_id)
        if row is None:
            return False
        current = str(row["status"])
        run_status = str(row["run_status"])
        if run_status == "completed":
            # A completed run is terminal: no task write can mutate its result.
            return False
        # A completed task can never go back to work: ``pending``/``running``
        # and a new claim are refused. The legacy executor reuses one row for
        # its read + analysis phases, so the same owning attempt may still
        # upgrade the final result or report that its provider failed.
        if current == "completed":
            if worker_id is not None:
                _owns_row(row, worker_id, attempt_id)
            if target == "completed":
                if result is not None:
                    conn.execute(
                        "UPDATE bot_group_run_tasks SET result=?, lease_expires_at=NULL "
                        "WHERE id=?",
                        (result, task_id),
                    )
                return True
            if target in {"interrupted", "cancelled", "failed"}:
                conn.execute(
                    "UPDATE bot_group_run_tasks SET status=?, error=?, error_class=?, "
                    "finished_at=?, lease_expires_at=NULL WHERE id=?",
                    (target, error, error_class, _now_iso(), task_id),
                )
                return True
            return False
        if run_status == "cancelled" and target in {"pending", "running", "completed"}:
            return False
        if run_status == "completed" and target in {"pending", "running"}:
            return False
        if current == "blocked" and target not in {"blocked", "failed", "cancelled"}:
            # Reconciliation is a gate, not a retry slot.
            return False
        token: str | None = None
        if worker_id is not None:
            token = _assert_owner(row, worker_id, attempt_id)
        now = _now_iso()
        finished = now if target in TERMINAL_TASK_STATUSES else None
        if worker_id is not None:
            # Keep the owner + token as audit evidence; only the lease expires.
            cursor = conn.execute(
                "UPDATE bot_group_run_tasks SET status=?, result=?, error=?, "
                "error_class=?, finished_at=?, lease_expires_at=NULL "
                "WHERE id=? AND worker_id=? AND attempt_id=? AND status='running'",
                (
                    target,
                    result,
                    error,
                    error_class,
                    finished,
                    task_id,
                    worker_id,
                    token,
                ),
            )
            return bool(cursor.rowcount == 1)
        # Administrative write (operator reset / cancellation): clear the
        # lease but preserve ``attempt`` and ``attempt_id``. Deleting either
        # would silently refund a spent retry or un-fence a stale writer.
        cursor = conn.execute(
            "UPDATE bot_group_run_tasks SET status=?, result=?, error=?, "
            "error_class=?, finished_at=?, worker_id=NULL, claimed_at=NULL, "
            "lease_expires_at=NULL WHERE id=?",
            (
                target,
                result,
                error,
                error_class,
                None if target in {"pending", "running"} else finished,
                task_id,
            ),
        )
        return bool(cursor.rowcount == 1)


def set_task(
    task_id: str,
    status: str,
    result: str | None = None,
    error: str | None = None,
    worker_id: str | None = None,
    *,
    attempt_id: str | None = None,
    error_class: str | None = None,
) -> bool:
    """Write a task outcome, fenced by the current attempt when owned.

    ``worker_id`` (the legacy signature) resolves its fencing token from the
    claim this context received. Passing ``attempt_id`` explicitly is preferred
    for new code and is the only way to prove a write belongs to an older
    attempt. An owner-scoped write without a token raises
    :class:`TaskOwnershipError` instead of writing blind.
    """
    return _write_task(
        task_id,
        status,
        result=result,
        error=error,
        worker_id=worker_id,
        attempt_id=attempt_id,
        error_class=error_class,
    )


def complete_task(
    task_id: str,
    worker_id: str,
    attempt_id: str,
    *,
    result: str | None = None,
) -> bool:
    """Complete a task only while ``worker_id`` + ``attempt_id`` still own it."""
    return _write_task(
        task_id,
        "completed",
        result=result,
        error=None,
        worker_id=worker_id,
        attempt_id=attempt_id,
        error_class=None,
    )


def fail_task(
    task_id: str,
    worker_id: str,
    attempt_id: str,
    *,
    status: str = "failed",
    error: str | None = None,
    error_class: str | None = None,
) -> bool:
    """Record a non-completed outcome for the owning attempt.

    ``status`` must be one of ``retryable``, ``failed``, ``interrupted``,
    ``skipped``, ``blocked`` or ``cancelled``; ``completed`` goes through
    :func:`complete_task` so a failure cannot be mistaken for success.
    """
    target = _validate_task_status(status)
    if target == "completed":
        raise ValueError("use complete_task() to complete a task")
    return _write_task(
        task_id,
        target,
        result=None,
        error=error,
        worker_id=worker_id,
        attempt_id=attempt_id,
        error_class=error_class,
    )


def release_task(
    task_id: str,
    worker_id: str,
    *,
    attempt_id: str | None = None,
    status: str = "interrupted",
) -> bool:
    """Drop a lease without refunding the attempt or the run budget."""
    target = _validate_task_status(status)
    if target == "completed":
        raise ValueError("release_task() cannot complete a task")
    with _write_transaction() as conn:
        row = _task_row(conn, task_id)
        if row is None:
            return False
        token = _assert_owner(row, worker_id, attempt_id)
        cursor = conn.execute(
            "UPDATE bot_group_run_tasks SET status=?, worker_id=NULL, claimed_at=NULL, "
            "lease_expires_at=NULL, error=COALESCE(error, ?), finished_at=? "
            "WHERE id=? AND worker_id=? AND attempt_id=? AND status='running'",
            (target, "Lease libertada.", _now_iso(), task_id, worker_id, token),
        )
        if cursor.rowcount != 1:
            return False
        # An executor that holds no other running task has given up the run:
        # release the run lease too (without refunding attempts or budget), so
        # a replacement worker can resume after the interruption.
        remaining = conn.execute(
            "SELECT 1 FROM bot_group_run_tasks WHERE run_id=? AND worker_id=? "
            "AND status='running' AND id<>? LIMIT 1",
            (str(row["run_id"]), worker_id, task_id),
        ).fetchone()
        if remaining is None:
            now = _now_iso()
            conn.execute(
                "UPDATE bot_group_runs SET lease_owner=NULL, lease_attempt_id=NULL, "
                "lease_expires_at=NULL, updated_at=? "
                "WHERE id=? AND lease_owner=?",
                (now, str(row["run_id"]), worker_id),
            )
            conn.execute(
                "UPDATE run_state SET owner_id='', attempt_id=NULL, "
                "lease_expires_at=NULL, updated_at=? "
                "WHERE run_id=? AND owner_id=?",
                (now, str(row["run_id"]), worker_id),
            )
        return True


def record(
    run_id: str, task_id: str, kind: str, payload: dict[str, Any]
) -> str:
    record_id = uuid4().hex
    with get_db() as conn:
        conn.execute(
            "INSERT INTO bot_group_run_records (id, run_id, task_id, kind, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (record_id, run_id, task_id, kind, json.dumps(payload, ensure_ascii=False)),
        )
    return record_id


# ───── effect ledger / reconciliation ──────────────────────────────────────


def begin_effect(
    task_id: str,
    worker_id: str,
    attempt_id: str,
    *,
    key: str,
    kind: str,
    evidence_paths: Sequence[str] = (),
) -> bool:
    """Reserve one real-world effect before invoking it.

    Returns ``True`` only when this call created the pending intent, which is
    the caller's permission to perform the action. ``False`` means the ledger
    already has the key (pending => outcome unknown, confirmed => already
    applied); the caller must not repeat the write.

    The intent is stored in the primary ``run_side_effects`` ledger, so the
    ``run_state`` row must already exist. The task row records the key, kind
    and the relative evidence paths recovery should inspect after a crash.
    """
    if not key:
        raise ValueError("an idempotency key is required")
    paths = [str(item) for item in evidence_paths if str(item).strip()]
    with _write_transaction() as conn:
        row = _task_row(conn, task_id)
        if row is None:
            return False
        _assert_owner(row, worker_id, attempt_id)
        run_id = str(row["run_id"])
        exists = conn.execute(
            "SELECT 1 FROM run_state WHERE run_id=?", (run_id,)
        ).fetchone()
        if exists is None:
            raise ValueError(
                f"run {run_id} has no run_state row; the effect ledger is owned by "
                "the primary runtime"
            )
        cursor = conn.execute(
            """INSERT INTO run_side_effects (run_id, idempotency_key, kind, status)
               VALUES (?, ?, ?, 'pending')
               ON CONFLICT (run_id, idempotency_key) DO NOTHING""",
            (run_id, key, str(kind)),
        )
        reserved = bool(cursor.rowcount == 1)
        conn.execute(
            "UPDATE bot_group_run_tasks SET effect_key=?, effect_kind=?, "
            "effect_evidence_json=? WHERE id=?",
            (key, str(kind), json.dumps(paths), task_id),
        )
        return reserved


def confirm_effect(
    task_id: str,
    worker_id: str,
    attempt_id: str,
    *,
    result_digest: str,
) -> bool:
    """Confirm a previously reserved effect for the owning attempt."""
    with _write_transaction() as conn:
        row = _task_row(conn, task_id)
        if row is None:
            return False
        _assert_owner(row, worker_id, attempt_id)
        key = row["effect_key"]
        if not key:
            return False
        cursor = conn.execute(
            "UPDATE run_side_effects SET status='confirmed', result_digest=? "
            "WHERE run_id=? AND idempotency_key=? AND status='pending'",
            (str(result_digest), str(row["run_id"]), str(key)),
        )
        return bool(cursor.rowcount == 1)


def get_effect_state(run_id: str, key: str) -> str | None:
    """Return ``pending`` / ``confirmed`` for a ledger key, or ``None``."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM run_side_effects WHERE run_id=? AND idempotency_key=?",
            (run_id, key),
        ).fetchone()
    return str(row["status"]) if row else None


def _existing_evidence(root: str, paths: Iterable[str]) -> list[str]:
    """Return the recorded relative paths that actually exist under ``root``."""
    try:
        base = Path(root).expanduser().resolve()
    except OSError:
        return []
    found: list[str] = []
    for relative in paths:
        try:
            candidate = (base / relative).resolve()
        except (OSError, ValueError):
            continue
        if candidate != base and base not in candidate.parents:
            continue
        if candidate.exists():
            found.append(relative)
    return found


def _effect_reconciliation(
    conn: Any, task: Any, run: Any
) -> tuple[str, str, str] | None:
    """Classify a crashed task that reserved an effect.

    Returns ``(status, error_class, message)`` or ``None`` when no effect was
    reserved. Anything other than "no effect at all" blocks the task: the
    ledger proves an intent existed, and a blind retry could duplicate it.
    """
    key = task["effect_key"]
    if not key:
        return None
    ledger = conn.execute(
        "SELECT status FROM run_side_effects WHERE run_id=? AND idempotency_key=?",
        (str(task["run_id"]), str(key)),
    ).fetchone()
    try:
        paths = json.loads(task["effect_evidence_json"] or "[]")
        if not isinstance(paths, list):
            paths = []
    except (TypeError, ValueError):
        paths = []
    evidence = _existing_evidence(str(run["project_root"]), [str(item) for item in paths])
    kind = str(task["effect_kind"] or "efeito")
    if ledger is not None and str(ledger["status"]) == "confirmed":
        return (
            "blocked",
            "effect_confirmed_result_missing",
            f"{kind} confirmado no ledger mas a conclusão da tarefa não foi gravada; "
            "requer reconciliação (não repetir).",
        )
    if evidence:
        return (
            "blocked",
            "reconciliation_required",
            f"{kind} presente no workspace ({', '.join(evidence)}) sem conclusão "
            "gravada; requer reconciliação (não repetir a escrita).",
        )
    if ledger is not None:
        return (
            "blocked",
            "reconciliation_required",
            f"{kind} reservado no ledger com resultado desconhecido; requer "
            "reconciliação antes de qualquer nova tentativa.",
        )
    return (
        "blocked",
        "reconciliation_required",
        f"{kind} tem evidência configurada mas o ledger não foi encontrado; "
        "resultado desconhecido, não repetir.",
    )


def interrupt_unfinished() -> dict[str, int]:
    """Mark work left by a dead process without reviving terminal outcomes.

    * ``completed``/``skipped``/``cancelled`` tasks are left untouched.
    * A running task that had reserved a real-world effect becomes ``blocked``
      (reconciliation required); it is never returned to ``pending`` and a new
      claim cannot pick it up.
    * Every other unfinished task becomes ``interrupted``. Its lease is cleared
      and its ``attempt_id`` rotated, so a survivor of the old process cannot
      write with the stale token. ``attempt`` (the retry counter) is preserved.
    * The run becomes ``interrupted``, or ``blocked`` when any task needs
      reconciliation. Runs already terminal are ignored.

    Returns counts for the startup log. This is the projection-level half of
    startup recovery; :meth:`RunCoordinator.recover_stale_claims` performs the
    primary-runtime half for group runs that have a ``run_state`` row.
    """
    counts = {"runs": 0, "interrupted": 0, "blocked": 0, "untouched": 0}
    recovered_run_ids: list[str] = []
    with _write_transaction() as conn:
        runs = conn.execute(
            "SELECT id, project_root FROM bot_group_runs "
            "WHERE status IN ('pending', 'running')"
        ).fetchall()
        for run in runs:
            run_id = str(run["id"])
            tasks = conn.execute(
                "SELECT * FROM bot_group_run_tasks WHERE run_id=? ORDER BY position",
                (run_id,),
            ).fetchall()
            pending_effect = conn.execute(
                "SELECT 1 FROM run_side_effects WHERE run_id=? AND status='pending' LIMIT 1",
                (run_id,),
            ).fetchone()
            blocked = 1 if pending_effect else 0
            interrupted = 0
            for task in tasks:
                status = str(task["status"])
                if status in {
                    "completed",
                    "skipped",
                    "cancelled",
                    "failed",
                    "retryable",
                }:
                    # A terminal/skipped/already-retryable outcome is not
                    # "interrupted": keep the distinction the executor wrote.
                    # The fencing token is still rotated so a survivor of the
                    # dead process cannot write with its old attempt, while the
                    # status/result/attempt counter stay untouched.
                    conn.execute(
                        "UPDATE bot_group_run_tasks SET attempt_id=?, claimed_at=NULL, "
                        "lease_expires_at=NULL WHERE id=?",
                        (uuid4().hex, str(task["id"])),
                    )
                    counts["untouched"] += 1
                    continue
                if status == "blocked":
                    conn.execute(
                        "UPDATE bot_group_run_tasks SET attempt_id=?, claimed_at=NULL, "
                        "lease_expires_at=NULL WHERE id=?",
                        (uuid4().hex, str(task["id"])),
                    )
                    blocked += 1
                    continue
                outcome = None
                if status == "running":
                    outcome = _effect_reconciliation(conn, task, run)
                error_class: str | None = None
                detail: str | None = None
                if outcome is not None:
                    next_status, error_class, detail = outcome
                    blocked += 1
                else:
                    next_status = "interrupted"
                    detail = "Backend reiniciado antes da conclusão."
                    interrupted += 1
                conn.execute(
                    "UPDATE bot_group_run_tasks SET status=?, error=COALESCE(error, ?), "
                    "error_class=?, worker_id=NULL, claimed_at=NULL, lease_expires_at=NULL, "
                    "attempt_id=?, finished_at=? WHERE id=?",
                    (
                        next_status,
                        detail,
                        error_class,
                        uuid4().hex,
                        _now_iso() if next_status in TERMINAL_TASK_STATUSES else None,
                        str(task["id"]),
                    ),
                )
            counts["interrupted"] += interrupted
            counts["blocked"] += blocked
            all_completed = bool(tasks) and all(
                str(task["status"]) == "completed" for task in tasks
            )
            if all_completed and not blocked:
                # The process died after the last task write but before the run
                # projection was closed. The tasks are the evidence: reconcile
                # the run as completed instead of inventing an interruption.
                run_status = "completed"
                stop_reason = "all tasks completed before restart"
            else:
                run_status = "blocked" if blocked else "interrupted"
                stop_reason = (
                    "reconciliation required" if blocked else "backend restarted"
                )
            conn.execute(
                "UPDATE bot_group_runs SET status=?, updated_at=?, lease_owner=NULL, "
                "lease_attempt_id=NULL, lease_expires_at=NULL, stop_reason=? WHERE id=?",
                (run_status, _now_iso(), stop_reason, run_id),
            )
            counts["runs"] += 1
            recovered_run_ids.append(run_id)
    if recovered_run_ids:
        _recover_primary_leases(recovered_run_ids)
    return counts


def _recover_primary_leases(run_ids: Sequence[str]) -> None:
    """Recover the ``run_state`` half for group runs that have a primary row.

    Imported lazily to keep the persistence module independent from the runtime
    at import time. A failure is logged, never allowed to break startup.
    """
    try:
        from backend.runtime.run_coordinator import RunCoordinator

        coordinator = RunCoordinator()
        coordinator.recover_stale_claims(run_ids=run_ids, reason="startup recovery")
    except Exception:
        logger.warning("Could not recover primary leases for group runs", exc_info=True)


def list_interrupted_runs() -> list[tuple[str, str, str]]:
    """Runs a startup/manual resume may take; blocked runs are excluded."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, group_id, user_id FROM bot_group_runs WHERE status='interrupted'"
        ).fetchall()
    return [(str(r["user_id"]), str(r["group_id"]), str(r["id"])) for r in rows]


def list_blocked_runs() -> list[tuple[str, str, str]]:
    """Runs parked for human reconciliation (never auto-resumed)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, group_id, user_id FROM bot_group_runs WHERE status='blocked'"
        ).fetchall()
    return [(str(r["user_id"]), str(r["group_id"]), str(r["id"])) for r in rows]
