"""The active-run channel used by tool accounting (Fase 1c).

A tool call has to be charged to a run, but ``execute_tool`` has no ``run_id``
parameter and its signature is public API used by the agents, the MCP server
and the e2e scenarios: adding one there would mean touching every caller for a
value most of them do not have. The run is instead published in a
:class:`~contextvars.ContextVar` by whoever opens it (the primary loop, a
plan task, a subagent) and read by whoever needs it.

Why a context variable and not a module global:

* A context variable is *per-task* under ``asyncio``. Two concurrent runs must
  not charge each other's tool calls, and a global would. Setting the run id
  inside the coroutine that owns the run gives every ``await`` below it the
  right value and leaks nothing into a sibling task.
* It is explicit about ownership: the value is set once at the top of the run
  and reset when it ends, so a stale run id cannot survive into unrelated work.

The empty string means "no active run". Every consumer must treat that as a
no-op rather than an error: a tool called outside a run (the dashboard, the
e2e scenarios, a direct MCP invocation) is not an accounting failure.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar, Token

__all__ = [
    "active_run",
    "current_run_id",
    "current_task_id",
    "get_current_run_id",
    "get_current_task_id",
    "reset_current_run_id",
    "reset_current_task_id",
    "set_current_run_id",
    "set_current_task_id",
]

#: The run the current coroutine is executing for. ``""`` means no run.
current_run_id: ContextVar[str] = ContextVar("nexus_current_run_id", default="")

#: The task within that run (e.g. ``cycle-2``). ``""`` means run-wide keys.
current_task_id: ContextVar[str] = ContextVar("nexus_current_task_id", default="")


def get_current_run_id() -> str:
    """Return the run id of the current execution context, or ``""``.

    Never raises: an unset or blank context is the normal state of any tool
    call made outside a run.
    """
    try:
        value = current_run_id.get()
    except LookupError:  # pragma: no cover - a default is always present
        return ""
    return str(value or "").strip()


def set_current_run_id(run_id: str | None) -> Token[str]:
    """Publish *run_id* for the current context and return the reset token.

    Pass ``None``/``""`` to clear the run for the current context (the value
    stays cleared for anything this coroutine awaits, but not for a sibling
    task, which is the point of using a context variable).
    """
    return current_run_id.set(str(run_id or "").strip())


def reset_current_run_id(token: Token[str]) -> None:
    """Undo a :func:`set_current_run_id` for the context that made it."""
    with contextlib.suppress(ValueError):
        # A token created in a different Context is a caller bug; refusing to
        # raise keeps tool execution alive, and the log makes it visible.
        current_run_id.reset(token)


def get_current_task_id() -> str:
    """Return the task id scoped to the current run, or ``""`` when unset."""
    try:
        value = current_task_id.get()
    except LookupError:  # pragma: no cover
        return ""
    return str(value or "").strip()


def set_current_task_id(task_id: str | None) -> Token[str]:
    """Publish *task_id* for side-effect idempotency keys in this context."""
    return current_task_id.set(str(task_id or "").strip())


def reset_current_task_id(token: Token[str]) -> None:
    """Undo a :func:`set_current_task_id` for the context that made it."""
    with contextlib.suppress(ValueError):
        current_task_id.reset(token)


@contextlib.contextmanager
def active_run(run_id: str | None) -> Iterator[str]:
    """Run a block with *run_id* published, then restore the previous value.

    Use for the synchronous/blocking parts of a run; prefer
    :func:`set_current_run_id` directly inside a coroutine that also wants to
    keep the token for an early return.
    """
    token = set_current_run_id(run_id)
    try:
        yield get_current_run_id()
    finally:
        reset_current_run_id(token)
