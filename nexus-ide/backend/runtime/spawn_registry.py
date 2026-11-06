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

The registry is keyed by **run id**, not by session id. A session can have
several runs in flight at the same time (the user sent two messages, or a
client retried with the same ``Idempotency-Key``), and keying by session made
those runs share one policy: run A consulted run B's counters, and when A
finished it removed B's policy, so B silently fell back to a throwaway
``SpawnPolicy()`` with no parallel cap and no write-scope serialisation.

Deliberately tiny and process-local: this is a coherence mechanism, not state
that anything is allowed to depend on. When nothing is registered the tool
falls back to a default policy, which is still an honest answer rather than an
invented one.
"""

from __future__ import annotations

from backend.runtime.spawn_policy import SpawnPolicy

__all__ = [
    "clear_policy",
    "clear_run_project",
    "get_policy",
    "get_run_project",
    "register_policy",
    "register_run_project",
]

_POLICIES: dict[str, SpawnPolicy] = {}

#: The trusted project root of each live run. The model may not choose the
#: filesystem root a run works in, so the root travels with the run and the
#: ``spawn_task`` tool uses it instead of whatever the model supplied.
_RUN_PROJECTS: dict[str, str] = {}


def register_policy(run_id: str, policy: SpawnPolicy) -> None:
    """Publish the policy of one run. The run id is the key, never a session."""
    if run_id:
        _POLICIES[run_id] = policy


def get_policy(run_id: str) -> SpawnPolicy | None:
    """The policy of *run_id*, or ``None`` when the run published none."""
    return _POLICIES.get(run_id) if run_id else None


def clear_policy(run_id: str) -> None:
    """Drop the policy of one run. Other runs of the same session are untouched."""
    _POLICIES.pop(run_id, None)


def register_run_project(run_id: str, project_path: str) -> None:
    """Publish the trusted project root of one run."""
    if run_id and str(project_path or "").strip():
        _RUN_PROJECTS[run_id] = str(project_path).strip()


def get_run_project(run_id: str) -> str:
    """The trusted project root of *run_id* (``""`` when unknown)."""
    return _RUN_PROJECTS.get(run_id, "") if run_id else ""


def clear_run_project(run_id: str) -> None:
    """Forget the trusted project root of one run."""
    _RUN_PROJECTS.pop(run_id, None)
