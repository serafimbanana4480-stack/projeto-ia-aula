"""SWARM memory layers — five orthogonal memory stores.

- ``short_term``   : rolling context for the current run/session
- ``long_term``    : cross-session knowledge the swarm has learned
- ``project``      : per-project facts (file structure, conventions, decisions)
- ``decision``     : architectural & implementation decision log (ADRs)
- ``architecture`` : high-level architecture memory (modules, boundaries, contracts)

All five are persisted to the existing ``MemoryStore`` from
``backend.knowledge.memory`` so SWARM memories participate in the same
embedding-backed recall as the rest of NEXUS.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


LAYER_NAMES: tuple[str, ...] = (
    "short_term",
    "long_term",
    "project",
    "decision",
    "architecture",
)


@dataclass
class MemoryEntry:
    """A single memory entry."""

    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    layer: str = "short_term"
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    importance: float = 0.5
    timestamp: float = field(default_factory=time.time)
    run_id: str = ""
    session_id: str = ""
    project_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "layer": self.layer,
            "content": self.content,
            "metadata": self.metadata,
            "tags": self.tags,
            "importance": self.importance,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "project_id": self.project_id,
        }


class MemoryLayer:
    """A single memory layer with bounded capacity + tag index."""

    def __init__(self, name: str, capacity: int = 500) -> None:
        self.name = name
        self.capacity = capacity
        self._entries: list[MemoryEntry] = []
        self._by_tag: dict[str, list[str]] = defaultdict(list)  # tag -> [entry_id]

    def add(self, entry: MemoryEntry) -> None:
        if entry.layer != self.name:
            entry.layer = self.name
        self._entries.append(entry)
        for tag in entry.tags:
            self._by_tag[tag].append(entry.entry_id)
        self._evict()

    def _evict(self) -> None:
        if len(self._entries) <= self.capacity:
            return
        # Keep the top-K by importance
        self._entries.sort(key=lambda e: e.importance, reverse=True)
        # Rebuild tag index
        self._by_tag.clear()
        kept = self._entries[: self.capacity]
        self._entries = kept
        for e in kept:
            for tag in e.tags:
                self._by_tag[tag].append(e.entry_id)

    def query(
        self,
        tags: Iterable[str] | None = None,
        text: str | None = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        ids: set[str] | None = None
        if tags:
            ids = set()
            for tag in tags:
                ids.update(self._by_tag.get(tag, []))
        results: list[MemoryEntry] = []
        for e in reversed(self._entries):  # most recent first
            if ids is not None and e.entry_id not in ids:
                continue
            if text and text.lower() not in e.content.lower():
                continue
            results.append(e)
            if len(results) >= limit:
                break
        return results

    def recent(self, limit: int = 20) -> list[MemoryEntry]:
        return list(reversed(self._entries[-limit:]))

    def clear(self) -> None:
        self._entries.clear()
        self._by_tag.clear()

    def __len__(self) -> int:
        return len(self._entries)


class MemoryStore:
    """Five-layer memory store for SWARM."""

    def __init__(self, capacity_per_layer: int = 500) -> None:
        self._layers: dict[str, MemoryLayer] = {
            name: MemoryLayer(name, capacity_per_layer) for name in LAYER_NAMES
        }

    # Convenience accessors --------------------------------------------------

    @property
    def short_term(self) -> MemoryLayer:
        return self._layers["short_term"]

    @property
    def long_term(self) -> MemoryLayer:
        return self._layers["long_term"]

    @property
    def project(self) -> MemoryLayer:
        return self._layers["project"]

    @property
    def decision(self) -> MemoryLayer:
        return self._layers["decision"]

    @property
    def architecture(self) -> MemoryLayer:
        return self._layers["architecture"]

    def layer(self, name: str) -> MemoryLayer:
        if name not in self._layers:
            raise KeyError(f"Unknown memory layer: {name!r}")
        return self._layers[name]

    def add(
        self,
        layer: str,
        content: str,
        tags: list[str] | None = None,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
        run_id: str = "",
        session_id: str = "",
        project_id: str = "",
    ) -> MemoryEntry:
        entry = MemoryEntry(
            layer=layer,
            content=content,
            tags=tags or [],
            importance=importance,
            metadata=metadata or {},
            run_id=run_id,
            session_id=session_id,
            project_id=project_id,
        )
        self._layers[layer].add(entry)
        return entry

    def query(
        self,
        text: str,
        layers: Iterable[str] | None = None,
        tags: Iterable[str] | None = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        results: list[MemoryEntry] = []
        for name in layers or LAYER_NAMES:
            results.extend(self._layers[name].query(tags=tags, text=text, limit=limit))
        # Sort by importance desc
        results.sort(key=lambda e: (e.importance, e.timestamp), reverse=True)
        return results[:limit]

    def stats(self) -> dict[str, int]:
        return {name: len(layer) for name, layer in self._layers.items()}

    def clear(self) -> None:
        for layer in self._layers.values():
            layer.clear()

    # ------------------------------------------------------------------
    # Persistence to the shared NEXUS memory store (best-effort)
    # ------------------------------------------------------------------

    def persist_to_nexus(self, layer: str, run_id: str = "") -> int:
        """Push entries from ``layer`` to the shared NEXUS memory store.

        Returns the number of entries successfully persisted. Failures are
        logged but never raised — memory is best-effort.
        """
        try:
            from backend.knowledge.memory import MemoryType, get_memory_store
        except Exception as exc:  # pragma: no cover - optional dep
            logger.debug("NEXUS memory store unavailable: %s", exc)
            return 0
        try:
            store = get_memory_store()
        except Exception as exc:
            logger.debug("Could not get memory store: %s", exc)
            return 0

        n = 0
        for entry in self._layers[layer].recent(limit=self._layers[layer].capacity):
            try:
                # Best-effort async push; in sync context we just skip
                import asyncio

                async def _push(_entry=entry) -> None:
                    await store.store(
                        content=_entry.content,
                        memory_type=MemoryType.DOCUMENTATION,
                        session_id=_entry.session_id,
                        tags=_entry.tags + [f"swarm:{layer}", f"run:{run_id}"],
                        importance=_entry.importance,
                        source=f"SWARM_{layer.upper()}",
                    )

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Don't block an active loop; schedule instead
                        loop.create_task(_push())
                    else:
                        loop.run_until_complete(_push())
                except RuntimeError:
                    asyncio.run(_push())
                n += 1
            except Exception as exc:  # pragma: no cover
                logger.debug("persist_to_nexus failed for entry %s: %s", entry.entry_id, exc)
        return n


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    """Return the global SWARM memory store (created lazily)."""
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


def reset_memory_store() -> None:
    """Reset the global store (mostly for tests)."""
    global _store
    _store = None


__all__ = [
    "LAYER_NAMES",
    "MemoryEntry",
    "MemoryLayer",
    "MemoryStore",
    "get_memory_store",
    "reset_memory_store",
]
