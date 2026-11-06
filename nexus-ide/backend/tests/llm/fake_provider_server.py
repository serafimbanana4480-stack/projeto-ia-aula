"""A local fake LLM server used by the provider tests.

The providers under test speak four different wire dialects (OpenAI-compatible
SSE, Anthropic Messages SSE, Gemini REST SSE and plain JSON).  Reproducing a
defect in any of them needs a server that answers exactly like the real
provider does — including status codes, response headers and streamed frames.

This module runs a *real* HTTP server on ``127.0.0.1`` (a random free port)
so the production httpx code path is exercised end to end: no network access
is required and no test double can hide a bug in the adapter itself.

Usage::

    with FakeLLMServer() as server:
        server.sse("POST", "/v1/chat/completions", frames=[...])
        provider = OpenAIProvider(f"{server.base_url}/v1", api_key="k")
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "FakeLLMServer",
    "RecordedRequest",
    "Response",
    "anthropic_sse",
    "gemini_sse",
    "openai_sse",
]


@dataclass
class RecordedRequest:
    """One request the fake server received."""

    method: str
    path: str
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict[str, Any]:
        """The request body decoded as JSON."""
        if not self.body:
            return {}
        return json.loads(self.body.decode("utf-8"))


@dataclass
class Response:
    """A canned response returned by the fake server."""

    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    content_type: str = "text/plain; charset=utf-8"


Handler = Callable[[RecordedRequest], Response]


def _sse_body(frames: Iterable[str]) -> bytes:
    """Join SSE frames into a response body."""
    return "".join(f"{frame}\n\n" for frame in frames).encode("utf-8")


def openai_sse(frames: Iterable[dict[str, Any]], *, space: bool = True) -> list[str]:
    """Render OpenAI-compatible SSE frames.

    ``space=False`` renders the legal-but-uncommon ``data:{...}`` form (no
    space after the colon), which the SSE specification allows.
    """
    prefix = "data: " if space else "data:"
    return [f"{prefix}{json.dumps(frame)}" for frame in frames]


def anthropic_sse(frames: Iterable[dict[str, Any]], *, space: bool = True) -> list[str]:
    """Render Anthropic Messages SSE frames (event name + data payload)."""
    prefix = "data: " if space else "data:"
    rendered: list[str] = []
    for frame in frames:
        event_type = str(frame.get("type") or "message")
        rendered.append(f"event: {event_type}")
        rendered.append(f"{prefix}{json.dumps(frame)}")
    return rendered


def gemini_sse(frames: Iterable[dict[str, Any]], *, space: bool = True) -> list[str]:
    """Render Gemini REST SSE frames."""
    prefix = "data: " if space else "data:"
    return [f"{prefix}{json.dumps(frame)}" for frame in frames]


class _RequestHandler(BaseHTTPRequestHandler):
    """Routes every request to the owning :class:`FakeLLMServer`."""

    protocol_version = "HTTP/1.1"

    @property
    def _server(self) -> FakeLLMServer:
        return self.server.owner  # type: ignore[attr-defined]

    def _dispatch(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        request = RecordedRequest(
            method=self.command,
            path=urlparse(self.path).path,
            headers={key.lower(): value for key, value in self.headers.items()},
            body=body,
        )
        response = self._server.handle(request)
        payload = response.body or b""
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(payload)))
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    do_GET = _dispatch
    do_POST = _dispatch
    do_PUT = _dispatch
    do_DELETE = _dispatch

    def log_message(self, *args: Any) -> None:  # pragma: no cover - silence the server
        return


class FakeLLMServer:
    """A tiny programmable HTTP server that speaks the provider dialects."""

    def __init__(self) -> None:
        self.requests: list[RecordedRequest] = []
        self._routes: dict[tuple[str, str], Handler] = {}
        self._default: Handler | None = None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -- lifecycle -------------------------------------------------------

    def start(self) -> FakeLLMServer:
        """Start the server on a free localhost port."""
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _RequestHandler)
        httpd.owner = self  # type: ignore[attr-defined]
        httpd.daemon_threads = True
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop the server and release the port."""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> FakeLLMServer:
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    @property
    def port(self) -> int:
        """The port the server listens on."""
        if self._httpd is None:
            raise RuntimeError("server is not running")
        return int(self._httpd.server_address[1])

    @property
    def base_url(self) -> str:
        """The base URL of the running server."""
        return f"http://127.0.0.1:{self.port}"

    # -- routing ---------------------------------------------------------

    def route(self, method: str, path: str, handler: Handler) -> FakeLLMServer:
        """Register a custom handler for ``method path``."""
        self._routes[(method.upper(), path)] = handler
        return self

    def default(self, handler: Handler) -> FakeLLMServer:
        """Register the handler used when no specific route matches."""
        self._default = handler
        return self

    def respond(
        self,
        method: str,
        path: str,
        *,
        status: int = 200,
        json_body: Any = None,
        text: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeLLMServer:
        """Answer ``method path`` with a fixed JSON or text body."""
        extra = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            content_type = "application/json"
        else:
            body = (text or "").encode("utf-8")
            content_type = "text/plain; charset=utf-8"
        self._routes[(method.upper(), path)] = lambda _request: Response(
            status=status,
            body=body,
            headers=extra,
            content_type=content_type,
        )
        return self

    def sse(
        self,
        method: str,
        path: str,
        frames: Iterable[str],
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> FakeLLMServer:
        """Answer ``method path`` with a server-sent-event stream."""
        body = _sse_body(frames)
        self._routes[(method.upper(), path)] = lambda _request: Response(
            status=status,
            body=body,
            headers=dict(headers or {}),
            content_type="text/event-stream",
        )
        return self

    # -- dispatch --------------------------------------------------------

    def handle(self, request: RecordedRequest) -> Response:
        """Return the response for *request*."""
        self.requests.append(request)
        handler = self._routes.get((request.method.upper(), request.path))
        if handler is None:
            handler = self._default
        if handler is None:
            return Response(
                status=404,
                body=f"no route for {request.method} {request.path}".encode(),
            )
        return handler(request)

    # -- assertions helpers ---------------------------------------------

    def last_request(self) -> RecordedRequest:
        """The most recent request received."""
        if not self.requests:
            raise AssertionError("the fake server received no request")
        return self.requests[-1]

    def request_count(self) -> int:
        """How many requests the server received."""
        return len(self.requests)
