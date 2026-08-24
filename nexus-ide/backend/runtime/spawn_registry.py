"""Per-run registry of the live :class:`SpawnPolicy`.

``spawn_task`` (the tool the model calls) and ``PrimaryLoop`` (the runtime that
decides whether delegating is worthwhile) used to reach opposite conclusions in
the same run: the runtime emitted "the primary agent handles this directly"
while the tool returned ``{"status": "spawned", "instance_id": ...}`` for a
subagent that never existed (audit 2026-08-16, P10).

The tool cannot import the loop's state, and the loop cannot intercept a tool
result, so they need a meeting point. This registry is it: the chat route
publishes the policy object it built for the run, and the tool consults the
*same* object — same conditions, same backpressure counters, one verdict.

Deliberately tiny and process-local: this is a coherence mechanism, not state
that anything is allowed to depend on. When nothing is registered the tool
falls back to a default policy, which is still an honest answer rather than an
invented one.
"""

from __future__ import annotations

from backend.runtime.spawn_policy import SpawnPolicy

__all__ = [
    "clear_policy",
    "get_policy",
    "register_policy",
]

_POLICIES: dict[str, SpawnPolicy] = {}


def register_policy(session_id: str, policy: SpawnPolicy) -> None:
    if session_id:
        _POLICIES[session_id] = policy


def get_policy(session_id: str) -> SpawnPolicy | None:
    return _POLICIES.get(session_id) if session_id else None


def clear_policy(session_id: str) -> None:
    _POLICIES.pop(session_id, None)
