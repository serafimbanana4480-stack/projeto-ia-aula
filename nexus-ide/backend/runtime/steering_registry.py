"""Process-wide map of live runs to their STOP / CONTINUE channel.

The UI's stop button and the run it stops are two different HTTP requests.
This registry is the only thing they share: the SSE handler publishes its
:class:`~backend.runtime.primary.SteeringChannel` here for the lifetime of
the run, and ``POST /api/chat/{run_id}/stop`` looks it up.

Entries are removed in the SSE handler's ``finally`` block, so a client that
disconnects mid-run does not leak one. ``sweep`` exists as a backstop for a
process that crashed inside a handler.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from backend.runtime.primary import SteeringChannel

__all__ = [
    "get_channel",
    "list_active_runs",
    "register_run",
    "sweep",
    "unregister_run",
]


@dataclass
class _Entry:
    channel: SteeringChannel
    session_id: str
    created_at: float


_LOCK = threading.Lock()
_RUNS: dict[str, _Entry] = {}
#: A run older than this cannot still be steered by a human.
_MAX_AGE_SECONDS = 6 * 60 * 60
#: Opportunistic sweep throttle — the registry has no dedicated worker, so
#: ``register_run`` sweeps stale entries at most this often (audit
#: 2026-08-26: the previous backstop was never scheduled).
_SWEEP_INTERVAL_SECONDS = 15 * 60
_LAST_SWEEP = -_SWEEP_INTERVAL_SECONDS


def _sweep_locked(now: float) -> int:
    """Drop entries too old to belong to a live run. Caller holds _LOCK."""
    cutoff = now - _MAX_AGE_SECONDS
    stale = [run_id for run_id, entry in _RUNS.items() if entry.created_at < cutoff]
    for run_id in stale:
        _RUNS.pop(run_id, None)
    return len(stale)


def register_run(run_id: str, channel: SteeringChannel, *, session_id: str = "") -> None:
    global _LAST_SWEEP
    with _LOCK:
        now = time.monotonic()
        if now - _LAST_SWEEP >= _SWEEP_INTERVAL_SECONDS and _RUNS:
            _LAST_SWEEP = now
            _sweep_locked(now)
        _RUNS[run_id] = _Entry(channel, session_id, now)


def unregister_run(run_id: str) -> None:
    with _LOCK:
        _RUNS.pop(run_id, None)


def get_channel(run_id: str) -> SteeringChannel | None:
    with _LOCK:
        entry = _RUNS.get(run_id)
    return entry.channel if entry else None


def list_active_runs(session_id: str = "") -> list[str]:
    with _LOCK:
        return [
            run_id
            for run_id, entry in _RUNS.items()
            if not session_id or entry.session_id == session_id
        ]


def sweep(now: float | None = None) -> int:
    """Drop entries too old to belong to a live run. Returns how many."""
    with _LOCK:
        return _sweep_locked(now if now is not None else time.monotonic())
