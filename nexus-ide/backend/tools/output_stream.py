"""Bounded, best-effort redacted output from a real shell tool invocation.

The callback is request-local and is captured before pipe-reader threads start.
It does not change command validation, approvals, execution, or cancellation.
"""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import contextvars
import re
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from backend.runtime.activity_redaction import redact_activity

_current_channel: contextvars.ContextVar[CommandOutputChannel | None] = contextvars.ContextVar(
    "nexus_command_output_channel", default=None
)
_MAX_OUTPUT_CHARS = 128_000
_MAX_OUTPUT_EVENTS = 256
_MAX_LINE_CHARS = 8_000
_PRIVATE_BEGIN = re.compile(r"-----BEGIN [^-\r\n]*PRIVATE KEY-----", re.IGNORECASE)
_PRIVATE_END = re.compile(r"-----END [^-\r\n]*PRIVATE KEY-----", re.IGNORECASE)
_SENSITIVE_COMMAND_PATH = re.compile(
    r"(?i)(?:\.env(?:\b|\.)|\.git-credentials\b|\.netrc\b|\.npmrc\b|"
    r"\.pypirc\b|credentials(?:\.json)?\b|id_rsa\b|id_ed25519\b|"
    r"\.(?:pem|key|p12|pfx|keystore)\b)"
)


class CommandOutputChannel:
    """A bounded bridge from pipe-reader threads to the agent's event loop."""

    def __init__(self) -> None:
        self.loop = asyncio.get_running_loop()
        # Reservations are capped below this size, even if the consumer stalls.
        self.queue: asyncio.Queue[dict[str, str]] = asyncio.Queue(maxsize=_MAX_OUTPUT_EVENTS + 1)
        self._lock = threading.Lock()
        self._chars = 0
        self._events = 0
        self._truncated = False

    def writer(self, stream: str) -> OutputWriter:
        return OutputWriter(self, stream)

    def emit(self, stream: str, text: str) -> None:
        if not text:
            return
        with self._lock:
            for offset in range(0, len(text), 4_000):
                if self._truncated:
                    return
                part = text[offset:offset + 4_000]
                if self._events >= _MAX_OUTPUT_EVENTS or self._chars + len(part) > _MAX_OUTPUT_CHARS:
                    self._truncated = True
                    item = {"stream": stream, "text": "\n[saída adicional omitida do stream]\n"}
                else:
                    self._events += 1
                    self._chars += len(part)
                    item = {"stream": stream, "text": part}
                self.loop.call_soon_threadsafe(self.queue.put_nowait, item)


class OutputWriter:
    """Buffer complete lines so a secret split across reads is not exposed."""

    def __init__(self, channel: CommandOutputChannel, stream: str) -> None:
        self.channel = channel
        self.stream = stream
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.pending = ""
        self.private_key = False
        self.omit_remainder = False

    def _line(self, line: str) -> str:
        if self.private_key:
            if _PRIVATE_END.search(line):
                self.private_key = False
            return ""
        if _PRIVATE_BEGIN.search(line):
            self.private_key = not bool(_PRIVATE_END.search(line))
            return "[chave privada omitida]\n"
        return str(redact_activity(line))

    def feed(self, chunk: bytes, *, final: bool = False) -> None:
        text = self.decoder.decode(chunk, final=final)
        if self.omit_remainder:
            return
        pieces = text.splitlines(keepends=True)
        visible: list[str] = []
        for part in pieces:
            ended = part.endswith(("\n", "\r"))
            self.pending += part
            if len(self.pending) > _MAX_LINE_CHARS:
                self.pending = ""
                # A private-key header could be hidden within the omitted
                # portion. Fail closed for the remainder of this stream.
                self.omit_remainder = True
                visible.append("[linha longa e saída seguinte omitidas do stream]\n")
                break
            elif ended:
                visible.append(self._line(self.pending))
                self.pending = ""
        if final and self.pending:
            visible.append(self._line(self.pending))
            self.pending = ""
        self.channel.emit(self.stream, "".join(visible))

    def finish(self) -> None:
        self.feed(b"", final=True)


def current_output_channel() -> CommandOutputChannel | None:
    return _current_channel.get()


def shell_output_allowed(command: str) -> bool:
    """Fail closed for common sensitive file names in shell commands."""
    return not _SENSITIVE_COMMAND_PATH.search(command)


async def observe_tool_output(
    invoke: Callable[[], Awaitable[dict[str, Any]]], *, enabled: bool,
) -> AsyncIterator[tuple[dict[str, str] | None, dict[str, Any] | None]]:
    """Yield output while the tool runs, then its one actual result.

    Closing or cancelling the consumer cancels the tool and awaits its normal
    cleanup. A disabled observer does not alter the existing execution path.
    """
    if not enabled:
        yield None, await invoke()
        return

    channel = CommandOutputChannel()

    async def run() -> dict[str, Any]:
        token = _current_channel.set(channel)
        try:
            return await invoke()
        finally:
            _current_channel.reset(token)

    task = asyncio.create_task(run())
    waiter: asyncio.Task[dict[str, str]] | None = None
    try:
        while not task.done():
            waiter = asyncio.create_task(channel.queue.get())
            completed, _ = await asyncio.wait((task, waiter), return_when=asyncio.FIRST_COMPLETED)
            if waiter in completed:
                yield waiter.result(), None
            else:
                waiter.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await waiter
            waiter = None
        while not channel.queue.empty():
            yield channel.queue.get_nowait(), None
        yield None, await task
    finally:
        if waiter is not None and not waiter.done():
            waiter.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await waiter
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
