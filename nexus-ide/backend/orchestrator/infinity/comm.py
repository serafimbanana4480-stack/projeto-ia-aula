"""Typed AI↔AI message envelopes for the Infinity v3 subsystem.

Every inter-agent message (director→worker, advisor→primary, worker→director)
travels as an :class:`Envelope` with a monotonic per-sender sequence, a
dedupe key, and an explicit type. The FIFO log gives consumers cheap
exact-duplicate suppression (same guard omp applies to advisor notes).
"""

from __future__ import annotations

import re
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EnvelopeType(StrEnum):
    DIRECTIVE = "directive"
    RESULT = "result"
    NOTE = "note"
    STEER = "steer"


_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def normalize_text(text: str) -> str:
    """omp-style normalization: lowercase, NFKC-ish collapse to alphanumerics."""
    return _NORMALIZE_RE.sub("", text.lower())


@dataclass(frozen=True, slots=True)
class Envelope:
    type: EnvelopeType
    sender: str
    recipient: str
    body: str
    seq: int = 0
    ts: float = field(default_factory=time.time)
    severity: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def dedupe_key(self) -> tuple[str, str]:
        return (self.sender, normalize_text(self.body))

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type.value,
            "sender": self.sender,
            "recipient": self.recipient,
            "body": self.body,
            "seq": self.seq,
            "ts": self.ts,
        }
        if self.severity is not None:
            data["severity"] = self.severity
        if self.meta:
            data["meta"] = dict(self.meta)
        return data


class CommLog:
    """Append-only FIFO with exact-duplicate detection per sender."""

    def __init__(self, maxlen: int = 4096) -> None:
        self._entries: deque[Envelope] = deque(maxlen=maxlen)
        self._seen: set[tuple[str, str]] = set()
        self._seq = 0

    def append(self, envelope_type: EnvelopeType, *, sender: str, recipient: str,
               body: str, severity: str | None = None,
               meta: dict[str, Any] | None = None) -> Envelope | None:
        """Append unless an identical body from the same sender is still in
        the window; returns the stored envelope or ``None`` when suppressed."""
        draft = Envelope(
            type=envelope_type,
            sender=sender,
            recipient=recipient,
            body=body,
            seq=self._seq + 1,
            severity=severity,
            meta=dict(meta or {}),
        )
        key = draft.dedupe_key
        if key in self._seen:
            return None
        self._seq += 1
        self._entries.append(draft)
        self._seen.add(key)
        if len(self._entries) == self._entries.maxlen and len(self._seen) > len(self._entries):
            # Rebuild the seen-set lazily once it drifts beyond the window.
            self._seen = {e.dedupe_key for e in self._entries}
        return draft

    def __len__(self) -> int:
        return len(self._entries)

    def tail(self, n: int = 50) -> list[Envelope]:
        return list(self._entries)[-n:]

    def __iter__(self) -> Iterator[Envelope]:
        return iter(self._entries)


__all__ = ["CommLog", "Envelope", "EnvelopeType", "normalize_text"]
