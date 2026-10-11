"""Handler registry for autonomous tasks.

A ``Task`` cannot be fully deserialised from SQLite: callables live only in the
running process. What survives a restart is the handler *name* stored in the
``scheduled_tasks.handler`` column. This registry is the single place that maps
that persisted name back onto a live async callable.

The contract that keeps recovery honest:

* A task whose persisted handler name resolves here re-attaches to the real
  implementation and can run again (subject to the resume policy).
* A task whose handler name is **not** registered here is a "not available in
  this build" task. It is never silently executed, never silently dropped: the
  scheduler marks it FAILED with an explicit ``handler '<name>' not registered
  in this build`` error, persists that state, emits ``task_failed`` and keeps it
  out of the run queue.

The ``read_only`` flag recorded per handler lets the resume policy tell a pure
observability handler (safe to run at boot) apart from one with side effects
(which must wait for the operator's ``NEXUS_TASKS_RESUME_PENDING`` opt-in).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HandlerEntry:
    """A registered handler and its resume-safety classification."""

    name: str
    call: Callable
    read_only: bool = False


class HandlerRegistry:
    """Name -> callable registry with alias and read-only classification."""

    def __init__(self) -> None:
        self._entries: dict[str, HandlerEntry] = {}
        self._aliases: dict[str, str] = {}

    def register(self, name: str, call: Callable, *, read_only: bool = False) -> None:
        """Register *call* under *name*.

        Raises:
            TypeError: If *call* is not callable.
        """
        if not callable(call):
            raise TypeError(f"handler '{name}' is not callable")
        if not isinstance(name, str) or not name:
            raise ValueError("handler name must be a non-empty string")
        self._entries[name] = HandlerEntry(name=name, call=call, read_only=read_only)

    def alias(self, name: str, target: str) -> bool:
        """Register *name* as an alias of an already-registered *target*.

        Aliases exist only for API compatibility. They resolve to the target's
        callable but do not create new behaviour, and are rejected unless
        *target* is already registered.
        """
        if target in self._entries and name and name not in self._entries:
            self._aliases[name] = target
            return True
        return False

    def resolve(self, name: str | None) -> HandlerEntry | None:
        """Return the entry for *name*, following aliases, or ``None``."""
        if not name:
            return None
        entry = self._entries.get(name)
        if entry is not None:
            return entry
        target = self._aliases.get(name)
        if target is not None:
            return self._entries.get(target)
        return None

    def resolve_callable(self, name: str | None) -> Callable | None:
        """Return the live callable for *name*, or ``None`` if unregistered."""
        entry = self.resolve(name)
        return entry.call if entry is not None else None

    def is_registered(self, name: str | None) -> bool:
        return self.resolve(name) is not None

    def is_read_only(self, name: str | None) -> bool:
        entry = self.resolve(name)
        return bool(entry and entry.read_only)

    def names(self) -> list[str]:
        """Every resolvable name (real handlers + aliases), sorted."""
        return sorted(set(self._entries) | set(self._aliases))

    def primary_names(self) -> list[str]:
        """Names backed by a real (non-aliased) handler, sorted."""
        return sorted(self._entries)

    def callables(self) -> dict[str, Callable]:
        """Return ``{name: callable}`` for every resolvable name."""
        result = {name: entry.call for name, entry in self._entries.items()}
        for alias, target in self._aliases.items():
            entry = self._entries.get(target)
            if entry is not None:
                result[alias] = entry.call
        return result
