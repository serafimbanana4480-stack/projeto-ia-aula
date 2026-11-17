"""A deterministic, loopback Ollama-compatible provider for end-to-end tests.

The tests in this package validate the *runtime*, never the model.  They may
therefore script what the model says, but they must not replace the coordinator,
the persistence layer, the tool registry or the UI under test.

This module provides the smallest possible model double that satisfies that
rule: a real HTTP server, listening on loopback, that speaks the Ollama
``/api/chat`` wire format (newline-delimited JSON) and records every prompt it
receives.  The backend connects to it through its normal provider adapter, so
the full provider plumbing (tool schema, streaming, usage, retries) is real.

The server also supports three test-only controls:

* hold a chosen call open (a provider that has not answered);
* fail a chosen call with a real HTTP 500;
* report whether the HTTP client disconnected while a call was held.

Those controls are the only levers; they never touch application state.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

Responder = Callable[["ProviderCall"], str]
"""Return the assistant text for one provider call."""


@dataclass
class ProviderCall:
    """Everything the provider observed for one ``/api/chat`` request."""

    index: int
    model: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    stream: bool
    started_at: float
    finished_at: float | None = None
    response_text: str = ""
    client_disconnected: bool = False

    @property
    def prompt_text(self) -> str:
        parts: list[str] = []
        for message in self.messages:
            role = str(message.get("role") or "")
            content = message.get("content")
            if isinstance(content, str) and content:
                parts.append(f"[{role}] {content}")
        return "\n".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "model": self.model,
            "messages": self.messages,
            "tools": [str((tool.get("function") or {}).get("name") or "") for tool in self.tools],
            "stream": self.stream,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "response_text": self.response_text,
            "client_disconnected": self.client_disconnected,
        }


@dataclass
class ScriptedProvider:
    """Scriptable response source, independent of the HTTP transport."""

    responses: list[str] = field(default_factory=list)
    responder: Responder | None = None
    default_response: str = "sem guião"

    def reset(self) -> None:
        self.responses.clear()
        self.responder = None

    def load(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.responder = None

    def respond(self, call: ProviderCall) -> str:
        if self.responder is not None:
            return self.responder(call)
        if not self.responses:
            return self.default_response
        index = min(call.index, len(self.responses) - 1)
        return self.responses[index]


def tool_call(name: str, arguments: dict[str, Any]) -> str:
    """Render one tool call in the single dialect the agent parser accepts."""
    return "<tool_call>" + json.dumps(
        {"name": name, "arguments": arguments}, ensure_ascii=False
    ) + "</tool_call>"


def tool_then_answer(
    name: str,
    arguments: dict[str, Any],
    answer: str | Callable[[ProviderCall], str],
) -> Responder:
    """Call ``name`` on the first turn, then answer from the tool result.

    The responder waits for a ``tool_result`` marker in the next prompt so a
    backend that *claims* to call the tool but never executes it cannot pass:
    the final answer is only produced after the real result is in the model
    context.
    """

    def respond(call: ProviderCall) -> str:
        prompt = call.prompt_text
        if "tool_result" in prompt or "tool completed" in prompt or "resultado" in prompt:
            return answer(call) if callable(answer) else answer
        if call.index == 0:
            return tool_call(name, arguments)
        return answer(call) if callable(answer) else answer

    return respond


class _ProviderHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], provider: LoopbackProvider) -> None:
        self.provider = provider
        super().__init__(address, _Handler)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _ProviderHTTPServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        self.server.provider.record_transport_log(format % args)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        if self.path.rstrip("/") in {"/api/tags", "/api/version"}:
            self._json({"models": [{"name": self.server.provider.model}]})
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        path = self.path.split("?", 1)[0]
        if path not in {"/api/chat", "/v1/chat/completions"}:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            self.send_error(400, "invalid JSON")
            return
        self.server.provider.handle_chat(self, body)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)

    def write_chunk(self, data: bytes) -> bool:
        """Write one HTTP chunk; return ``False`` when the client is gone."""
        if not data:
            return True
        try:
            self.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
            self.wfile.write(data)
            self.wfile.write(b"\r\n")
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def start_chunked(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "close")
        self.end_headers()

    def finish_chunked(self) -> bool:
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False


class LoopbackProvider:
    """A real HTTP server that scripts the model and records every prompt."""

    def __init__(self, *, model: str = "scripted:latest") -> None:
        self.model = model
        self.scripted = ScriptedProvider()
        self.calls: list[ProviderCall] = []
        self._lock = threading.Lock()
        self._server: _ProviderHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.transport_log: list[str] = []
        #: Call indexes that must stay open until :meth:`release` is set.
        self.hold_calls: set[int] = set()
        self.hold_timeout_seconds = 120.0
        self.entered_hold = threading.Event()
        self._release = threading.Event()
        #: Call indexes that answer HTTP 500.
        self.fail_calls: set[int] = set()
        #: Optional per-chunk cadence, in seconds.
        self.chunk_delay_seconds = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> LoopbackProvider:
        server = _ProviderHTTPServer(("127.0.0.1", 0), self)
        self._server = server
        thread = threading.Thread(target=server.serve_forever, name="scripted-provider", daemon=True)
        thread.start()
        self._thread = thread
        return self

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("provider not started")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.release()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> LoopbackProvider:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------
    def load(self, responses: list[str]) -> None:
        self.scripted.load(responses)

    def set_responder(self, responder: Responder) -> None:
        self.scripted.responder = responder

    def release(self) -> None:
        self._release.set()

    def block_on(self, *indexes: int) -> None:
        self.hold_calls.update(indexes)

    def fail_on(self, *indexes: int) -> None:
        self.fail_calls.update(indexes)

    def wait_until_called(self, index: int, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.chat_calls > index:
                return True
            time.sleep(0.02)
        return False

    # ------------------------------------------------------------------
    # Recording / script evaluation
    # ------------------------------------------------------------------
    @property
    def chat_calls(self) -> int:
        with self._lock:
            return len(self.calls)

    @property
    def chat_prompts(self) -> list[str]:
        with self._lock:
            return [call.prompt_text for call in self.calls]

    @property
    def chat_models(self) -> list[str]:
        with self._lock:
            return [call.model for call in self.calls]

    def record_transport_log(self, line: str) -> None:
        with self._lock:
            self.transport_log.append(line)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "url": self.url,
                "model": self.model,
                "chat_calls": len(self.calls),
                "calls": [call.as_dict() for call in self.calls],
                "transport_log": list(self.transport_log[-80:]),
            }

    def handle_chat(self, handler: _Handler, body: dict[str, Any]) -> None:
        with self._lock:
            index = len(self.calls)
            call = ProviderCall(
                index=index,
                model=str(body.get("model") or ""),
                messages=list(body.get("messages") or []),
                tools=list(body.get("tools") or []),
                stream=bool(body.get("stream", True)),
                started_at=time.time(),
            )
            self.calls.append(call)
        if index in self.fail_calls:
            with self._lock:
                call.finished_at = time.time()
            handler._json({"error": "scripted provider failure"}, status=500)
            return

        if index in self.hold_calls:
            self.entered_hold.set()
            # Send the response headers before blocking: the backend is then
            # genuinely waiting for the first model token, exactly like a slow
            # remote provider.  No frame is written until the test releases it.
            handler.start_chunked()
            released = self._release.wait(timeout=self.hold_timeout_seconds)
            if not released:
                with self._lock:
                    call.client_disconnected = True
                    call.finished_at = time.time()
                handler.close_connection = True
                return
        else:
            handler.start_chunked()

        try:
            text = self.scripted.respond(call)
        except Exception as exc:  # pragma: no cover - test harness guard
            text = f"scripted provider error: {type(exc).__name__}: {exc}"
        with self._lock:
            call.response_text = text

        if index in self.hold_calls and not self._release.is_set():
            # Only reachable when release was cleared again; keep the call open.
            self._release.wait(timeout=self.hold_timeout_seconds)

        ok = True
        if text:
            chunks = _text_chunks(text)
            for chunk in chunks:
                if self.chunk_delay_seconds:
                    time.sleep(self.chunk_delay_seconds)
                payload = json.dumps(
                    {
                        "model": call.model or self.model,
                        "message": {"role": "assistant", "content": chunk},
                        "done": False,
                    },
                    ensure_ascii=False,
                ).encode("utf-8") + b"\n"
                if not handler.write_chunk(payload):
                    ok = False
                    break
        if ok:
            final = json.dumps(
                {
                    "model": call.model or self.model,
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": max(1, len(call.prompt_text) // 4),
                    "eval_count": max(1, len(text) // 4),
                }
            ).encode("utf-8") + b"\n"
            ok = handler.write_chunk(final)
        if ok:
            ok = handler.finish_chunked()
        with self._lock:
            call.finished_at = time.time()
            if not ok:
                call.client_disconnected = True
        handler.close_connection = True


def _text_chunks(text: str, size: int = 48) -> list[str]:
    """Split a scripted answer into small model-like deltas."""
    if len(text) <= size:
        return [text]
    return [text[offset : offset + size] for offset in range(0, len(text), size)]


def free_port() -> int:
    """Return an unused loopback TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


__all__ = [
    "LoopbackProvider",
    "ProviderCall",
    "ScriptedProvider",
    "free_port",
    "tool_call",
    "tool_then_answer",
]
