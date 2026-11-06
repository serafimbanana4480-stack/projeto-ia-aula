"""Vibe Director — persistent worker sessions (port of omp's vibe mode).

The director never edits/builds itself. It drives workers:

- ``spawn(tier="fast"|"good", prompt, name?)`` — blank worker, self-contained
  brief, returns immediately.
- ``send(session, message)`` — steers a streaming turn at its next step
  boundary; queues when busy-but-not-interruptible; starts a fresh turn when
  idle.
- ``wait(sessions?, timeout?)`` — first watched turn to settle; reissuable.
- ``kill(session)`` — cancel in-flight turn, clear queue, mark dead.
- ``list()`` — spawn-order roster with tier/state/turns/model/preview.

Workers are keep-alive conversations: each accumulates its own history and is
steered with ``send``, never respawned for follow-ups. A worker never sees the
director's conversation. Worker completion ≠ correctness; the caller verifies.

This module owns ONLY the session machinery: the actual agent execution is an
injected ``runner`` coroutine ``(worker, message) -> str`` so the logic stays
testable without any LLM.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock
from typing import Any

from backend.orchestrator.infinity.vibe_store import STORE_VERSION, VibeStateStore

logger = logging.getLogger(__name__)

WORKER_NAME_MAX = 48
PREVIEW_CHARS = 1_600
DEFAULT_WAIT_TIMEOUT_S = 30.0


class WorkerState(StrEnum):
    SPAWNING = "spawning"
    STREAMING = "streaming"
    IDLE = "idle"
    DEAD = "dead"


def sanitize_name(name: str | None) -> str:
    raw = (name or "").strip()
    cleaned = re.sub(r"[^\w .-]", "", raw)[:WORKER_NAME_MAX].strip()
    return cleaned or f"worker-{uuid.uuid4().hex[:6]}"


@dataclass
class WorkerSession:
    id: str
    name: str
    tier: str
    model_id: str
    is_default: bool = False
    state: WorkerState = WorkerState.SPAWNING
    turn_count: int = 0
    queued_count: int = 0
    error: str | None = None
    last_result: str | None = None
    last_activity: float = field(default_factory=time.time)
    history: list[dict[str, str]] = field(default_factory=list)
    _queue: deque[tuple[str, Any]] = field(default_factory=deque)
    _settlement_sequence: int = 0
    _acknowledged_sequence: int = 0
    _settlements: deque[dict[str, Any]] = field(default_factory=deque)
    _inflight_message: str | None = None
    task: asyncio.Task[None] | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tier": self.tier,
            "state": self.state.value,
            "model": self.model_id,
            "default": self.is_default,
            "turns": self.turn_count,
            "queued": len(self._queue),
            "error": self.error,
            "preview": (self.last_result or "")[:240],
            "last_activity": self.last_activity,
        }


Runner = Callable[[WorkerSession, str], Any]  # async (worker, message) -> str


class VibeDirector:
    """Scoped worker registry for one chat session."""

    def __init__(self, *, session_id: str, runner: Runner,
                 tier_models: dict[str, str] | None = None,
                 on_update: Callable[[WorkerSession, str], None] | None = None,
                 persistence_store: VibeStateStore | None = None) -> None:
        self.session_id = session_id
        self._runner = runner
        self._workers: dict[str, WorkerSession] = {}
        self._order: list[str] = []
        self._tier_models = tier_models or {}
        self._on_update = on_update
        self._persistence_store = persistence_store
        if persistence_store is not None:
            self._restore_state(persistence_store.load())

    def _restore_state(self, payload: dict[str, Any]) -> None:
        records = payload.get("workers")
        if not isinstance(records, list):
            raise RuntimeError("Vibe worker state has an invalid worker roster")
        for record in records:
            if not isinstance(record, dict):
                raise RuntimeError("Vibe worker state contains an invalid worker")
            worker_id = record.get("id")
            name = record.get("name")
            tier = record.get("tier")
            model_id = record.get("model_id", "")
            if not all(isinstance(value, str) and value for value in (worker_id, name, tier)):
                raise RuntimeError("Vibe worker state contains an invalid identity")
            if tier not in ("fast", "good") or worker_id in self._workers:
                raise RuntimeError("Vibe worker state contains an invalid tier or duplicate id")

            try:
                state = WorkerState(str(record.get("state", WorkerState.IDLE.value)))
            except ValueError as exc:
                raise RuntimeError("Vibe worker state contains an invalid status") from exc
            history = record.get("history", [])
            if not isinstance(history, list) or any(
                not isinstance(item, dict)
                or item.get("role") not in ("user", "assistant")
                or not isinstance(item.get("content"), str)
                for item in history
            ):
                raise RuntimeError("Vibe worker state contains invalid history")
            settlements = record.get("settlements", [])
            if not isinstance(settlements, list) or any(
                not isinstance(item, dict)
                or not isinstance(item.get("sequence"), int)
                or item.get("outcome") not in ("completed", "failed", "cancelled", "interrupted")
                for item in settlements
            ):
                raise RuntimeError("Vibe worker state contains invalid settlements")

            worker = WorkerSession(
                id=worker_id,
                name=name,
                tier=tier,
                model_id=model_id if isinstance(model_id, str) else "",
                is_default=bool(record.get("is_default", False)),
                state=state,
                turn_count=max(0, int(record.get("turn_count", 0))),
                error=record.get("error") if isinstance(record.get("error"), str) else None,
                last_result=(
                    record.get("last_result")
                    if isinstance(record.get("last_result"), str)
                    else None
                ),
                last_activity=float(record.get("last_activity", time.time())),
                history=[{"role": item["role"], "content": item["content"]} for item in history],
                _settlement_sequence=max(0, int(record.get("settlement_sequence", 0))),
                _acknowledged_sequence=max(0, int(record.get("acknowledged_sequence", 0))),
                _settlements=deque(dict(item) for item in settlements),
            )
            worker.model_id = self._tier_models.get(worker.tier, worker.model_id)
            self._workers[worker.id] = worker
            self._order.append(worker.id)

            queued_count = max(0, int(record.get("queued_count", 0)))
            was_running = state in (WorkerState.SPAWNING, WorkerState.STREAMING)
            if was_running:
                inflight = record.get("inflight_message")
                if isinstance(inflight, str) and inflight:
                    worker.history.append({"role": "user", "content": inflight})
                worker.state = WorkerState.IDLE
                queue_note = (
                    f" {queued_count} queued follow-up(s) were discarded."
                    if queued_count
                    else ""
                )
                worker.error = (
                    "Turn interrupted by backend restart; resubmit it to continue."
                    + queue_note
                )
                self._record_settlement(worker, "interrupted")
            elif queued_count:
                worker.error = (
                    "Queued follow-up(s) were discarded by backend restart; resubmit them."
                )
                self._record_settlement(worker, "interrupted")
            worker._inflight_message = None

        if records and self._persistence_store is not None:
            self._save_state()

    def _state_payload(self) -> dict[str, Any]:
        workers: list[dict[str, Any]] = []
        for worker_id in self._order:
            worker = self._workers.get(worker_id)
            if worker is None:
                continue
            workers.append(
                {
                    "id": worker.id,
                    "name": worker.name,
                    "tier": worker.tier,
                    "model_id": worker.model_id,
                    "is_default": worker.is_default,
                    "state": worker.state.value,
                    "turn_count": worker.turn_count,
                    "error": worker.error,
                    "last_result": worker.last_result,
                    "last_activity": worker.last_activity,
                    "history": worker.history[-12:],
                    "settlement_sequence": worker._settlement_sequence,
                    "acknowledged_sequence": worker._acknowledged_sequence,
                    "settlements": list(worker._settlements),
                    "queued_count": len(worker._queue),
                    "inflight_message": worker._inflight_message,
                }
            )
        return {
            "version": STORE_VERSION,
            "session_id": self.session_id,
            "workers": workers,
        }

    def _save_state(self) -> None:
        if self._persistence_store is not None:
            self._persistence_store.save(self._state_payload())

    @staticmethod
    def _record_settlement(worker: WorkerSession, outcome: str) -> None:
        worker._settlement_sequence += 1
        worker._settlements.append(
            {
                "sequence": worker._settlement_sequence,
                "outcome": outcome,
                "turns": worker.turn_count,
                "result": worker.last_result,
                "error": worker.error,
            }
        )

    def discard_persisted_state(self) -> None:
        """Detach and delete session state when its owning chat is deleted."""
        store = self._persistence_store
        self._persistence_store = None
        if store is not None:
            store.delete()

    # ── roster ───────────────────────────────────────────────────────────
    def list_workers(self) -> list[dict[str, Any]]:
        return [self._workers[wid].summary() for wid in self._order if wid in self._workers]

    def get(self, worker_id: str) -> WorkerSession | None:
        return self._workers.get(worker_id)

    def set_runner(self, runner: Runner, *, tier_models: dict[str, str] | None = None) -> None:
        """Refresh request-scoped execution dependencies for the next turn.

        Directors live for the chat session, while providers and project
        selection can change between requests. The running turn already holds
        its runner coroutine; replacing this reference only affects later
        turns, including queued messages.
        """
        self._runner = runner
        if tier_models is not None:
            self._tier_models = dict(tier_models)
            for worker in self._workers.values():
                worker.model_id = self._tier_models.get(worker.tier, worker.model_id)
            self._save_state()

    def full_output(self, worker_id: str) -> dict[str, Any] | None:
        worker = self._workers.get(worker_id)
        if worker is None:
            return None
        return {
            "id": worker.id,
            "name": worker.name,
            "tier": worker.tier,
            "state": worker.state.value,
            "turns": worker.turn_count,
            "history": list(worker.history),
            "last_result": worker.last_result,
            "error": worker.error,
        }

    # ── omp tool semantics ───────────────────────────────────────────────
    def spawn(
        self,
        *,
        tier: str,
        prompt: str,
        name: str | None = None,
        is_default: bool = False,
        runner: Runner | None = None,
    ) -> dict[str, Any]:
        if tier not in ("fast", "good"):
            raise ValueError("tier must be 'fast' or 'good'")
        worker = WorkerSession(
            id=f"w-{uuid.uuid4().hex[:8]}",
            name=sanitize_name(name),
            tier=tier,
            model_id=self._tier_models.get(tier, ""),
            is_default=is_default,
        )
        worker.state = WorkerState.IDLE
        self._workers[worker.id] = worker
        self._order.append(worker.id)
        try:
            self._save_state()
        except Exception:
            self._workers.pop(worker.id, None)
            self._order.remove(worker.id)
            raise
        self._announce(worker, "spawned")
        self.send(worker.id, prompt, runner=runner)
        return worker.summary()

    def send(
        self, worker_id: str, message: str, *, runner: Runner | None = None
    ) -> dict[str, Any]:
        worker = self._workers.get(worker_id)
        if worker is None:
            raise KeyError(f"unknown worker: {worker_id}")
        if worker.state in (WorkerState.STREAMING, WorkerState.SPAWNING):
            worker._queue.append((message, runner or self._runner))
            worker.queued_count += 1
            try:
                self._save_state()
            except Exception:
                worker._queue.pop()
                worker.queued_count -= 1
                raise
            self._announce(worker, "queued")
            return {"worker": worker_id, "action": "queued"}
        if worker.state is WorkerState.DEAD:
            raise RuntimeError(f"worker {worker_id} is dead")
        self._start_turn(worker, message, runner or self._runner)
        return {"worker": worker_id, "action": "started"}

    async def wait(
        self,
        worker_ids: list[str] | None = None,
        timeout: float = DEFAULT_WAIT_TIMEOUT_S,
    ) -> list[dict[str, Any]]:
        selected_ids = self._order if worker_ids is None else worker_ids
        watched = [self._workers[w] for w in selected_ids if w in self._workers]
        active = {
            worker.id: worker.task
            for worker in watched
            if worker.state in (WorkerState.STREAMING, WorkerState.SPAWNING)
            and worker.task is not None
        }
        def next_settlement(worker: WorkerSession) -> dict[str, Any] | None:
            return next(
                (
                    settlement
                    for settlement in worker._settlements
                    if int(settlement["sequence"]) > worker._acknowledged_sequence
                ),
                None,
            )

        settled_workers = {
            worker.id for worker in watched if next_settlement(worker) is not None
        }
        tasks = {task for task in active.values() if task is not None}
        completed: set[asyncio.Task[None]] = set()
        if not settled_workers and tasks:
            done, _ = await asyncio.wait(
                tasks,
                timeout=max(0.0, timeout),
                return_when=asyncio.FIRST_COMPLETED,
            )
            completed = done
            settled_workers = {
                worker_id
                for worker_id, task in active.items()
                if task in completed
            }

        results: list[dict[str, Any]] = []
        acknowledged_any = False
        ack_before: dict[str, tuple[int, deque[dict[str, Any]]]] = {}
        for worker in watched:
            result = worker.summary()
            settlement = next_settlement(worker)
            result["settled"] = settlement is not None
            result["settlement"] = dict(settlement) if settlement is not None else None
            if settlement is not None:
                ack_before[worker.id] = (
                    worker._acknowledged_sequence,
                    deque(worker._settlements),
                )
                worker._acknowledged_sequence = int(settlement["sequence"])
                acknowledged_any = True
                while (
                    worker._settlements
                    and int(worker._settlements[0]["sequence"])
                    <= worker._acknowledged_sequence
                ):
                    worker._settlements.popleft()
            results.append(result)
        if acknowledged_any:
            try:
                self._save_state()
            except Exception:
                for worker in watched:
                    previous = ack_before.get(worker.id)
                    if previous is not None:
                        worker._acknowledged_sequence = previous[0]
                        worker._settlements = previous[1]
                raise
        return results

    async def wait_any_settled(self, timeout: float = DEFAULT_WAIT_TIMEOUT_S) -> list[dict[str, Any]]:
        """Alias kept for route-level ergonomics; identical semantics."""
        return await self.wait(None, timeout)

    def kill(self, worker_id: str) -> dict[str, Any]:
        worker = self._workers.get(worker_id)
        if worker is None:
            raise KeyError(f"unknown worker: {worker_id}")
        worker._queue.clear()
        task = worker.task
        previous_state = worker.state
        previous_queue = deque(worker._queue)
        worker.state = WorkerState.DEAD
        worker._queue.clear()
        try:
            self._save_state()
        except Exception:
            worker.state = previous_state
            worker._queue = previous_queue
            raise
        worker.task = None
        if task is not None and not task.done():
            task.cancel()
        self._announce(worker, "killed")
        return {"worker": worker_id, "state": "dead"}

    def kill_all(self) -> int:
        killed = 0
        for worker_id in list(self._order):
            worker = self._workers.get(worker_id)
            if worker and worker.state is not WorkerState.DEAD:
                self.kill(worker_id)
                killed += 1
        return killed

    # ── turn engine ──────────────────────────────────────────────────────
    def _start_turn(self, worker: WorkerSession, message: str, runner: Runner) -> None:
        previous_state = worker.state
        previous_error = worker.error
        worker.error = None
        worker.state = WorkerState.STREAMING
        worker._inflight_message = message
        try:
            self._save_state()
        except Exception:
            worker.state = previous_state
            worker.error = previous_error
            worker._inflight_message = None
            raise
        self._announce(worker, "turn_started")
        task = asyncio.get_running_loop().create_task(self._run_turn(worker, message, runner))
        worker.task = task

    async def _run_turn(self, worker: WorkerSession, message: str, runner: Runner) -> None:
        outcome = "completed"
        try:
            result = await runner(worker, message)
            worker.turn_count += 1
            worker.last_result = str(result or "")
            worker.last_activity = time.time()
            worker.history.append({"role": "user", "content": message})
            worker.history.append({"role": "assistant", "content": worker.last_result})
            worker._inflight_message = None
        except asyncio.CancelledError:
            outcome = "cancelled"
            worker.last_activity = time.time()
            worker._inflight_message = None
            raise
        except Exception as exc:  # noqa: BLE001 — worker failures are data
            outcome = "failed"
            worker.error = f"{type(exc).__name__}: {exc}"
            worker._inflight_message = None
            logger.warning("vibe worker %s failed: %s", worker.id, exc)
        finally:
            if worker.task is asyncio.current_task():
                worker.task = None
            became_idle = worker.state is WorkerState.STREAMING
            if became_idle:
                worker.state = WorkerState.IDLE
            self._record_settlement(worker, outcome)
            persistence_ok = True
            try:
                self._save_state()
            except Exception as exc:  # noqa: BLE001 — completion remains visible but not durable
                persistence_ok = False
                outcome = "failed"
                worker.error = "Vibe state could not be saved; this result may not survive restart."
                worker._settlements[-1]["outcome"] = outcome
                worker._settlements[-1]["error"] = worker.error
                logger.error("vibe worker %s state persistence failed: %s", worker.id, exc)
            if persistence_ok and outcome == "completed":
                self._announce(worker, "turn_completed")
            if became_idle:
                self._announce(worker, "idle")
            if not persistence_ok or outcome == "cancelled":
                # A cancelled turn must not silently run what was queued behind
                # it: "stop" has to actually stop. The queued messages are
                # dropped here and the worker settles as cancelled, so the user
                # sees the stop took effect instead of the agent resuming work
                # they just cancelled.
                worker._queue.clear()
                worker.queued_count = 0
            nxt = worker._queue.popleft() if persistence_ok and worker._queue else None
            if nxt is not None and worker.state is WorkerState.IDLE:
                try:
                    self._start_turn(worker, nxt[0], nxt[1])
                except Exception as exc:  # noqa: BLE001 — do not lose a visible queue failure
                    worker.error = (
                        "A queued Vibe turn could not start because its state was not saved."
                    )
                    logger.error("vibe worker %s queued turn could not start: %s", worker.id, exc)

    # ── events ───────────────────────────────────────────────────────────
    def _announce(self, worker: WorkerSession, action: str) -> None:
        worker.last_activity = time.time()
        if self._on_update is not None:
            try:
                self._on_update(worker, action)
            except Exception:  # noqa: BLE001 — observers never break workers
                logger.debug("vibe on_update observer failed", exc_info=True)


# ── registry scoped per chat session ────────────────────────────────────
_DIRECTORS: dict[str, VibeDirector] = {}
_DIRECTORS_LOCK = RLock()


def get_director(session_id: str) -> VibeDirector | None:
    with _DIRECTORS_LOCK:
        return _DIRECTORS.get(session_id)


def get_or_create_director(
    *, session_id: str, runner: Runner, tier_models: dict[str, str] | None = None
) -> VibeDirector:
    """Atomically bind a chat session to its reusable Vibe director."""
    key = str(session_id or "").strip()
    if not key:
        raise ValueError("a chat session id is required")
    with _DIRECTORS_LOCK:
        director = _DIRECTORS.get(key)
        if director is None:
            director = VibeDirector(
                session_id=key,
                runner=runner,
                tier_models=tier_models,
                persistence_store=VibeStateStore.for_session(key),
            )
            _DIRECTORS[key] = director
        else:
            director.set_runner(runner, tier_models=tier_models)
        return director


def register_director(director: VibeDirector) -> None:
    with _DIRECTORS_LOCK:
        _DIRECTORS[director.session_id] = director


def drop_director(session_id: str) -> None:
    key = str(session_id or "").strip()
    if not key:
        return
    with _DIRECTORS_LOCK:
        director = _DIRECTORS.pop(key, None)
    store = (
        director._persistence_store
        if director is not None and director._persistence_store is not None
        else VibeStateStore.for_session(key)
    )
    if director is not None:
        director._persistence_store = None
        director.kill_all()
    store.delete()


__all__ = [
    "DEFAULT_WAIT_TIMEOUT_S",
    "PREVIEW_CHARS",
    "WorkerSession",
    "WorkerState",
    "VibeDirector",
    "drop_director",
    "get_director",
    "get_or_create_director",
    "register_director",
    "sanitize_name",
]
