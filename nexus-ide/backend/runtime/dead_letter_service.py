"""Fase 1c — the dead-letter service: no failed unit disappears silently.

When a run or an autonomous task fails, the failure is parked in the
``run_dead_letters`` queue by the coordinator. Parking it is not enough: a queue
nobody reads is where failures go to die quietly. This module is the read/write
API over that queue and the only place that decides *what a failure means*:

* :func:`classify_error` answers "can this be retried?" — a ``429`` or a
  ``503`` is waiting for the provider to come back, a ``ValueError`` from a
  schema check never will. The two must not be treated alike, or the queue
  fills with permanent failures being retried forever (and transient ones
  abandoned after one attempt).
* :class:`DeadLetterService` answers "what do we do with this entry now?" —
  ``inspect``, ``retry``, ``requeue``, ``replan``, ``abandon``, ``escalate``,
  each one a state transition of the entry plus, where the action re-arms work,
  the real delegation to the task manager that owns it.

The retry/requeue pair deliberately *delegates*: this service holds no
execution authority of its own. Re-arming a task is the task manager's call (it
knows the handler registry, the quarantine list and the running set), so when
there is no manager — the scheduler is disabled, or this runs outside the app
lifespan — the action fails loudly with :class:`DeadLetterUnavailable` instead
of pretending it worked.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from backend.runtime.run_coordinator import DEAD_LETTER_STATES, RunCoordinator

logger = logging.getLogger(__name__)

__all__ = [
    "RECOVERABILITY_PERMANENT",
    "RECOVERABILITY_TRANSIENT",
    "RECOVERABILITY_UNKNOWN",
    "DeadLetterActionName",
    "DeadLetterError",
    "DeadLetterNotFound",
    "DeadLetterRejected",
    "DeadLetterService",
    "DeadLetterUnavailable",
    "classify_error",
    "format_dead_letter",
]

RECOVERABILITY_TRANSIENT = "transient"
RECOVERABILITY_PERMANENT = "permanent"
RECOVERABILITY_UNKNOWN = "unknown"

#: Error classes that mean "the world said not now" — retrying later works.
_TRANSIENT_CLASS_NAMES = frozenset(
    {
        "apierror",
        "apiconnectionerror",
        "apitimeouterror",
        "connectionerror",
        "connecttimeout",
        "readtimeout",
        "timeouterror",
        "timeout",
        "ratelimiterror",
        "serviceunavailableerror",
        "internalerror",
        "badgatewayerror",
        "gatewaytimeout",
        "httpstatuserror",
        "remoteerror",
        "temporaryfailure",
        "unavailable",
        "throttled",
        "overloaded",
        "circuitbreakeropen",
    }
)

#: Error classes that mean "this will always be wrong" — a retry wastes a turn.
_PERMANENT_CLASS_NAMES = frozenset(
    {
        "valueerror",
        "typeerror",
        "keyerror",
        "indexerror",
        "attributeerror",
        "assertionerror",
        "notimplementederror",
        "jsondecodeerror",
        "validationerror",
        "schemaerror",
        "configerror",
        "configurationerror",
        "invalidruntransition",
        "dodnotsatisfied",
        "permissionerror",
        "filenotfounderror",
        "isadirectoryerror",
        "notadirectoryerror",
        "zerodivisionerror",
        "recursionerror",
        "syntaxerror",
        "unicodeerror",
        "stopiteration",
    }
)

#: HTTP status hints scraped from the error *text*: the raised exception often
#: carries only a message ("429 Too Many Requests") from a client that mapped
#: the status onto a generic type.
_TRANSIENT_STATUS_RE = re.compile(
    r"\b(?:429|408|425|500|502|503|504|509|599)\b"
    r"|\brate[ -]?limit|\bthrottl|\boverload|\btemporar|\btime ?d? ?out\b"
    r"|\bconnection (?:reset|refused|aborted)|\bnetwork (?:error|unreachable)",
    re.IGNORECASE,
)
_PERMANENT_TEXT_RE = re.compile(
    r"\b(?:400|401|403|404|405|409|410|415|422)\b"
    r"|\binvalid|\bmalformed|\bschema|\bnot (?:allowed|permitted|found|supported)"
    r"|\bmisconfigur|\bunknown (?:budget|run|tool|handler|argument)",
    re.IGNORECASE,
)

#: How long to wait before a transient failure is worth retrying again.
DEFAULT_TRANSIENT_RETRY_AFTER_SECONDS = 60.0


def _error_class_name(error: Any) -> str:
    """The exception's class name (or a plain string's own name), lower-cased."""
    if isinstance(error, BaseException):
        return type(error).__name__.strip().lower()
    text = str(error or "").strip()
    return text.rsplit(".", 1)[-1].rsplit(":", 1)[-1].strip().lower() if text else ""


def _error_text(error: Any) -> str:
    """A single line of evidence about the error, for logs and classification."""
    if isinstance(error, BaseException):
        return str(error).strip()
    return str(error or "").strip()


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def classify_error(error: Any) -> dict[str, Any]:
    """Classify a failure as retryable or not, with the delay to retry after.

    Returns ``{"recoverability": ..., "retry_after": ..., "error_class": ...,
    "reason": ...}``:

    * ``transient`` — the failure is about the world, not the work: a rate
      limit, a 5xx, a timeout, a connection reset. Retrying later is the correct
      response, and ``retry_after`` says how much later.
    * ``permanent`` — the failure is about the work: a schema/type/value error,
      an illegal transition, a missing handler. A retry reproduces it exactly,
      so the entry needs a human (``replan``/``abandon``/``escalate``).
    * ``unknown`` — nothing recognisable. Treated as needing a human, but
      ``retry_after`` is still populated so an operator can re-arm it.

    ``error`` may be an exception, an exception *class*, an error-class name or
    a plain message: a caller reading a dead-letter row back off disk has no
    exception object any more, only the ``error_class`` string it stored.
    """
    class_name = _error_class_name(error)
    text = _error_text(error)

    if class_name in _PERMANENT_CLASS_NAMES:
        return _verdict(
            RECOVERABILITY_PERMANENT,
            class_name,
            f"{class_name} is a defect in the request or the configuration; a retry repeats it",
        )
    if class_name in _TRANSIENT_CLASS_NAMES:
        return _verdict(
            RECOVERABILITY_TRANSIENT,
            class_name,
            f"{class_name} is a provider/transport failure; retrying later can succeed",
        )

    if _TRANSIENT_STATUS_RE.search(text):
        return _verdict(
            RECOVERABILITY_TRANSIENT,
            class_name,
            "the error text reports a retryable status or transport failure",
        )
    if _PERMANENT_TEXT_RE.search(text):
        return _verdict(
            RECOVERABILITY_PERMANENT,
            class_name,
            "the error text reports an invalid or refused request",
        )
    return _verdict(
        RECOVERABILITY_UNKNOWN,
        class_name,
        "the failure does not look like a known transient or permanent error",
    )


def _verdict(recoverability: str, error_class: str, reason: str) -> dict[str, Any]:
    retry_after = (
        DEFAULT_TRANSIENT_RETRY_AFTER_SECONDS
        if recoverability == RECOVERABILITY_TRANSIENT
        else None
    )
    return {
        "recoverability": recoverability,
        "retry_after": retry_after,
        "error_class": error_class,
        "reason": reason,
    }


def format_dead_letter(entry: Mapping[str, Any]) -> dict[str, Any]:
    """The API shape of one entry: the stored columns plus a classification.

    ``recoverability`` is the *effective* answer: the stored value when the
    entry was parked by :meth:`DeadLetterService.park`, otherwise what the
    stored ``error_class`` classifies as now. An entry parked by another
    producer without a classification must not read as unexplained.
    """
    payload = dict(entry)
    classification = classify_error(str(payload.get("error_class") or ""))
    stored = str(payload.get("recoverability") or "").strip().lower()
    if stored in {"", RECOVERABILITY_UNKNOWN}:
        stored = str(classification["recoverability"])
    payload["recoverability"] = stored
    payload["classification"] = classification
    return payload


class DeadLetterError(RuntimeError):
    """Base class for the operational failures this service reports.

    ``http_status`` is the status an HTTP route should map it to, so the route
    layer stays a thin translation instead of re-deriving the meaning.
    """

    http_status = 500


class DeadLetterNotFound(DeadLetterError):
    """The entry does not exist (or was pruned by retention)."""

    http_status = 404


class DeadLetterUnavailable(DeadLetterError):
    """The action needs the task manager and none is reachable."""

    http_status = 503


class DeadLetterRejected(DeadLetterError):
    """The task manager refused the action (running, unregistered, too soon)."""

    http_status = 409


class DeadLetterActionName(StrEnum):
    """The six operator actions over one queue entry."""

    INSPECT = "inspect"
    RETRY = "retry"
    REQUEUE = "requeue"
    REPLAN = "replan"
    ABANDON = "abandon"
    ESCALATE = "escalate"


#: The state each action writes back to the queue.
_ACTION_STATES: dict[DeadLetterActionName, str] = {
    DeadLetterActionName.RETRY: "retrying",
    DeadLetterActionName.REQUEUE: "requeued",
    DeadLetterActionName.REPLAN: "replanned",
    DeadLetterActionName.ABANDON: "abandoned",
    DeadLetterActionName.ESCALATE: "escalated",
}


@dataclass
class DeadLetterAction:
    """The outcome of one action: what the queue says and what work did."""

    action: DeadLetterActionName
    entry_id: str
    state: str
    task_id: str = ""
    run_id: str = ""
    detail: str = ""
    task_result: str = ""
    classification: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "entry_id": self.entry_id,
            "state": self.state,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "detail": self.detail,
            "task_result": self.task_result,
            "classification": dict(self.classification),
        }


class DeadLetterService:
    """Read and act on the dead-letter queue.

    Args:
        coordinator: Owns the queue. Every read and every state change goes
            through it, so the service adds behaviour, not a second source.
        task_manager: Optional ``AutonomousTaskManager``-shaped object exposing
            ``async requeue_task(task_id)``. Required only by the actions that
            re-arm work (``retry``/``requeue``).
    """

    def __init__(self, coordinator: RunCoordinator, *, task_manager: Any | None = None) -> None:
        self._coordinator = coordinator
        self._task_manager = task_manager

    # ───── classification ───────────────────────────────────────────────

    def classify(self, error: Any) -> dict[str, Any]:
        """:func:`classify_error` as a service method (same contract)."""
        return classify_error(error)

    # ───── reads ────────────────────────────────────────────────────────

    def list(
        self,
        *,
        run_id: str | None = None,
        state: str | None = "open",
        recoverability: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Entries, newest first, optionally filtered by run/state/class.

        ``state=None`` returns every state; ``recoverability`` is matched
        against the *effective* value (see :func:`format_dead_letter`), so a
        filter by ``transient`` also finds an entry another producer parked
        without a classification.
        """
        entries = self._coordinator.list_dead_letters(
            run_id=run_id, state=state, limit=limit
        )
        if recoverability:
            wanted = str(recoverability).strip().lower()
            entries = [
                entry
                for entry in entries
                if format_dead_letter(entry)["recoverability"] == wanted
            ]
        return [format_dead_letter(entry) for entry in entries]

    def inspect(self, entry_id: str) -> dict[str, Any]:
        """One entry with its classification, or :class:`DeadLetterNotFound`."""
        entry = self.get(entry_id)
        return format_dead_letter(entry)

    def get(self, entry_id: str) -> dict[str, Any]:
        """The raw entry, or raise :class:`DeadLetterNotFound`."""
        for entry in self._coordinator.list_dead_letters(state=None, limit=500):
            if str(entry.get("id") or "") == str(entry_id):
                return entry
        raise DeadLetterNotFound(f"dead letter entry not found: {entry_id}")

    # ───── parking ──────────────────────────────────────────────────────

    def park(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        """Classify and enqueue a failure, returning the stored entry.

        Fills in ``recoverability``/``retry_after`` from :func:`classify_error`
        when the caller did not, so a parked failure always carries an answer
        to "why is this here and can it be retried?".
        """
        payload = dict(entry)
        error_class = str(payload.get("error_class") or "")
        if not payload.get("recoverability"):
            payload["recoverability"] = classify_error(error_class)["recoverability"]
        if "retry_after" not in payload and payload["recoverability"] == RECOVERABILITY_TRANSIENT:
            payload["retry_after"] = _iso(
                datetime.now(UTC) + timedelta(seconds=DEFAULT_TRANSIENT_RETRY_AFTER_SECONDS)
            )
        entry_id = self._coordinator.enqueue_dead_letter(payload)
        logger.info(
            "[DLQ] parked %s (run=%s task=%s error_class=%s recoverability=%s retry_after=%s)",
            entry_id,
            payload.get("run_id") or "",
            payload.get("task_id") or "",
            error_class,
            payload.get("recoverability"),
            payload.get("retry_after") or "-",
        )
        return self.inspect(entry_id)

    # ───── actions ──────────────────────────────────────────────────────

    async def retry(self, entry_id: str) -> DeadLetterAction:
        """Re-arm the task now, keeping the same plan.

        Refuses while ``retry_after`` is still in the future: a rate-limited
        provider does not un-throttle because an operator pressed retry.

        Async because it delegates to the task manager, whose ``requeue_task``
        is a coroutine.
        """
        return await self._rearm(entry_id, DeadLetterActionName.RETRY)

    async def requeue(self, entry_id: str) -> DeadLetterAction:
        """Re-arm the task for a normal pass, ignoring the retry delay.

        An operator's explicit requeue outranks ``retry_after``: the point of
        the queue is that a human can decide the wait is over.
        """
        return await self._rearm(entry_id, DeadLetterActionName.REQUEUE)

    def replan(self, entry_id: str, *, plan: str | None = None) -> DeadLetterAction:
        """Mark the failure as needing a new plan; do not re-arm the work.

        The entry stays parked until an orchestrator produces the new plan, so
        "replanned" is a handover, not a claim that anything ran.
        """
        entry = self.get(entry_id)
        note = "replan requested"
        if plan:
            note = f"{note}: {plan}"
        updated = self._coordinator.update_dead_letter(
            entry_id, state=_ACTION_STATES[DeadLetterActionName.REPLAN], note=note
        )
        logger.info(
            "[DLQ] %s replanned (task=%s run=%s)", entry_id, entry.get("task_id"), entry.get("run_id")
        )
        return self._result(DeadLetterActionName.REPLAN, updated, detail=note)

    def abandon(self, entry_id: str, *, reason: str = "") -> DeadLetterAction:
        """Close the entry as not worth pursuing, with the reason recorded."""
        self.get(entry_id)  # raises DeadLetterNotFound before any write happens
        note = "abandoned by operator"
        if reason:
            note = f"{note}: {reason}"
        updated = self._coordinator.update_dead_letter(
            entry_id, state=_ACTION_STATES[DeadLetterActionName.ABANDON], note=note
        )
        logger.info("[DLQ] %s abandoned (%s)", entry_id, reason or "no reason given")
        return self._result(DeadLetterActionName.ABANDON, updated, detail=note)

    def escalate(self, entry_id: str, *, reason: str = "") -> DeadLetterAction:
        """Mark the entry as needing a human decision and record why."""
        self.get(entry_id)  # raises DeadLetterNotFound before any write happens
        note = "escalated to a human"
        if reason:
            note = f"{note}: {reason}"
        updated = self._coordinator.update_dead_letter(
            entry_id, state=_ACTION_STATES[DeadLetterActionName.ESCALATE], note=note
        )
        logger.warning("[DLQ] %s escalated (%s)", entry_id, reason or "no reason given")
        return self._result(DeadLetterActionName.ESCALATE, updated, detail=note)

    # ───── internals ────────────────────────────────────────────────────

    async def _rearm(self, entry_id: str, action: DeadLetterActionName) -> DeadLetterAction:
        """Re-arm the parked unit through the task manager, then re-state it."""
        entry = self.get(entry_id)
        task_id = str(entry.get("task_id") or "").strip()
        if not task_id:
            raise DeadLetterRejected(
                f"entry {entry_id} has no task_id; nothing to re-arm (replan or abandon instead)"
            )
        if action is DeadLetterActionName.RETRY and not self._retry_due(entry):
            retry_after = entry.get("retry_after")
            raise DeadLetterRejected(
                f"retry_after {retry_after} has not passed yet; use requeue to override"
            )

        manager = self._task_manager
        if manager is None:
            raise DeadLetterUnavailable(
                "no task manager is reachable, so the unit cannot be re-armed; "
                "start the autonomous task scheduler or act on a running process"
            )
        task_result = await self._delegate_rearm(manager, task_id)
        if task_result not in {"requeued", "requeue requested"}:
            raise DeadLetterRejected(
                f"task manager refused to re-arm task {task_id}: {task_result}"
            )

        note = f"{action.value} requested by operator (task manager: {task_result})"
        updated = self._coordinator.update_dead_letter(
            entry_id, state=_ACTION_STATES[action], note=note
        )
        logger.info("[DLQ] %s %s -> task %s (%s)", entry_id, action.value, task_id, task_result)
        return self._result(action, updated, task_result=str(task_result))

    @staticmethod
    async def _delegate_rearm(manager: Any, task_id: str) -> str:
        """Call the manager's re-arm entry point and return what it answered.

        The manager owns the handler registry, the quarantine list and the
        running set, so this is a delegation and never a direct state write.
        """
        method = getattr(manager, "requeue_task", None)
        if not callable(method):
            raise DeadLetterUnavailable(
                "the task manager exposes no requeue_task(); this build cannot re-arm work"
            )
        result = method(task_id)
        if hasattr(result, "__await__"):
            result = await result
        return str(result or "")

    @staticmethod
    def _retry_due(entry: Mapping[str, Any]) -> bool:
        """Whether ``retry_after`` (if any) has passed."""
        raw = str(entry.get("retry_after") or "").strip()
        if not raw:
            return True
        try:
            due = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("[DLQ] unparseable retry_after %r; treating it as due", raw)
            return True
        if due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        return datetime.now(UTC) >= due

    def _result(
        self,
        action: DeadLetterActionName,
        entry: Mapping[str, Any],
        *,
        detail: str = "",
        task_result: str = "",
    ) -> DeadLetterAction:
        return DeadLetterAction(
            action=action,
            entry_id=str(entry.get("id") or ""),
            state=str(entry.get("state") or ""),
            task_id=str(entry.get("task_id") or ""),
            run_id=str(entry.get("run_id") or ""),
            detail=detail,
            task_result=task_result,
            classification=classify_error(str(entry.get("error_class") or "")),
        )


def assert_states_are_known() -> tuple[str, ...]:
    """Return the states this service writes, asserting the coordinator knows them."""
    written = tuple(sorted(set(_ACTION_STATES.values())))
    unknown = sorted(set(written) - set(DEAD_LETTER_STATES))
    if unknown:  # pragma: no cover - a coding error, caught by the test suite
        raise RuntimeError(f"dead letter states unknown to the coordinator: {unknown}")
    return written
