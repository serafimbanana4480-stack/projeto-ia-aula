"""Wire protocol for the control frames the ReAct loop mixes into its stream.

The agent loop yields two different kinds of thing on the *same* async
generator: model tokens, and control frames such as
``<event>tool_result|read_file|{...}</event>``.  Before this module the frames
were written with the payload interpolated verbatim, which meant any payload
that happened to contain ``<thinking>``, ``<tool_call>`` or a literal
``</event>`` desynchronised the frontend parser and leaked the raw protocol
into the chat (audit 2026-08-16, P2/P11/P12).  Reading a *file* that mentions
those tags was enough: the NEXUS repo itself, any agent project, any prompt
engineering repo.

The fix is to make the payload a closed alphabet.  ``encode_event`` escapes the
three characters that can be confused with markup (``&``, ``<``, ``>``) and
``decode_payload`` reverses it.  The escaping is:

* reversible and lossless;
* idempotent-safe (``&`` is escaped first, unescaped last);
* cheap — three ``str.replace`` calls per frame;
* backwards compatible — frames produced by an older build (unescaped) still
  parse, they simply carry no escapes to reverse.

Both sides of the wire import from here so the encoding can never drift.
"""

from __future__ import annotations

import json
import re
from typing import Any

__all__ = [
    "EVENT_CLOSE",
    "EVENT_OPEN",
    "EVENT_RE",
    "decode_payload",
    "encode_event",
    "escape_payload",
    "strip_events",
]

EVENT_OPEN = "<event>"
EVENT_CLOSE = "</event>"

#: A complete control frame.  ``[^|>]+`` for the type keeps it anchored to the
#: short identifiers the loop emits and refuses to match arbitrary HTML.
EVENT_RE = re.compile(r"<event>([^|>]+)(?:\|(.*?))?</event>", re.DOTALL)

_ESCAPES: tuple[tuple[str, str], ...] = (
    ("&", "&amp;"),
    ("<", "&lt;"),
    (">", "&gt;"),
)


def escape_payload(value: str) -> str:
    """Escape markup characters so a payload can never close its own frame."""
    for raw, encoded in _ESCAPES:
        value = value.replace(raw, encoded)
    return value


def decode_payload(value: str) -> str:
    """Reverse :func:`escape_payload`. Safe on payloads that were never escaped."""
    for raw, encoded in reversed(_ESCAPES):
        value = value.replace(encoded, raw)
    return value


def encode_event(event_type: str, *parts: Any) -> str:
    """Build one control frame with every dynamic part escaped.

    ``parts`` are joined with ``|`` exactly like the historical format, so the
    consumer side keeps its ``tool_name|json_args`` splitting.  Non-string
    parts are JSON-encoded first (that is what the callers were doing inline).
    """
    encoded_parts: list[str] = []
    for part in parts:
        text = part if isinstance(part, str) else json.dumps(part, default=str)
        encoded_parts.append(escape_payload(text))
    if not encoded_parts:
        return f"{EVENT_OPEN}{event_type}{EVENT_CLOSE}"
    return f"{EVENT_OPEN}{event_type}|{'|'.join(encoded_parts)}{EVENT_CLOSE}"


def strip_events(text: str) -> str:
    """Remove every control frame from ``text``.

    Used when one agent's output becomes another agent's *input* (A2A
    consultation, swarm aggregation): the sub-run's control frames are not
    part of its answer and must never be replayed into a parent stream.
    """
    if EVENT_OPEN not in text:
        return text
    return EVENT_RE.sub("", text)


def split_stream(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Split a raw agent stream into visible text and decoded control frames.

    Returns ``(clean_text, frames)`` where ``frames`` is a list of
    ``(event_type, decoded_payload)``. Aggregators that join an agent's tokens
    into a single string (swarm strategies, A2A consultations) must use this
    instead of ``"".join(parts)``: the frames are the *transport*, not the
    agent's answer, and replaying them into a parent stream is what leaked the
    protocol to the user (audit 2026-08-16, P11/P12).
    """
    if EVENT_OPEN not in text:
        return text, []
    frames: list[tuple[str, str]] = []
    out: list[str] = []
    last = 0
    for match in EVENT_RE.finditer(text):
        out.append(text[last : match.start()])
        frames.append((match.group(1), decode_payload(match.group(2) or "")))
        last = match.end()
    out.append(text[last:])
    return "".join(out), frames
