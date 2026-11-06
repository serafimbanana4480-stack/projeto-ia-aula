"""The deny-by-default edge: what a refused request actually looks like.

Two contracts, both about the *shape* of a refusal
---------------------------------------------------
1. **A refused WebSocket handshake must carry a close code the client can
   read.**  The middleware used to send ``websocket.close`` *before*
   ``accept()``; a real ASGI server answers that with an HTTP 403 and no
   close frame, so the client never saw the documented ``4401`` and could
   not tell "authenticate and retry" from "the server broke".  The
   handshake is now accepted and closed with ``4401``, and this file
   asserts it against a **real uvicorn server** — the TestClient surfaces
   the close differently, which is exactly why the old contract test did
   not catch it.

2. **A present-but-invalid token must be refused everywhere.**  The
   middleware checks that a credential is *present* and leaves the
   cryptographic work to ``require_auth``; the inventory contract proves
   every protected route carries that guard.  This file proves the
   behavioural half: with ``Authorization: Bearer garbage`` every protected
   route answers 401, so a route that forgot its guard cannot be reached
   with a made-up token either.
"""

from __future__ import annotations

import re
import socket
import threading
import time
from typing import Any

import pytest
from fastapi.routing import APIWebSocketRoute
from fastapi.testclient import TestClient
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from backend.middleware.deny_by_default import (
    WS_UNAUTHORIZED_CODE,
    flatten_routes,
    path_format_for,
)
from backend.middleware.public_routes import (
    PUBLIC_DOCS_ROUTES,
    PUBLIC_HTTP_ROUTES,
)
from backend.orchestrator.main import app

pytestmark = pytest.mark.contract

#: Value substituted for every path parameter when probing routes.
_PARAM_VALUE = "contract-invalid-token"

#: The credential a probe presents: present, but not a token anybody signed.
_INVALID_TOKEN = "Bearer not-a-real-token"


def _free_port() -> int:
    """A port nobody is listening on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _original_route(route: Any) -> Any:
    original = getattr(route, "original_route", None)
    return original if original is not None else route


def _probe_path(path_format: str) -> str:
    """``/api/x/{id}`` -> ``/api/x/contract-invalid-token``."""
    return re.sub(r"\{[^{}]+\}", _PARAM_VALUE, path_format)


def _protected_probes() -> list[tuple[str, str]]:
    """``(method, path)`` of every protected HTTP route of the app."""
    public = PUBLIC_HTTP_ROUTES | PUBLIC_DOCS_ROUTES
    probes: list[tuple[str, str]] = []
    for route in flatten_routes(getattr(app, "routes", [])):
        if isinstance(_original_route(route), APIWebSocketRoute):
            continue
        path_format = path_format_for(route)
        if path_format is None:
            continue
        for method in sorted((getattr(route, "methods", None) or set()) - {"HEAD"}):
            if (method, path_format) in public:
                continue
            probes.append((method, _probe_path(path_format)))
    return probes


@pytest.fixture
def rate_limiter_idle(monkeypatch: pytest.MonkeyPatch):
    """Suspend the rate limiter for the duration of one test.

    The sweep below fires one request per registered route; the default
    budget is far below that, and a 429 says nothing about authentication.
    """
    limiter = getattr(app.state, "limiter", None)
    if limiter is None:
        yield limiter
        return
    original = limiter.enabled
    monkeypatch.setattr(limiter, "enabled", False)
    try:
        yield limiter
    finally:
        monkeypatch.setattr(limiter, "enabled", original)


def test_anonymous_websocket_receives_the_documented_close_code() -> None:
    """An anonymous handshake is closed with 4401 — against a real server.

    The TestClient cannot answer this question: it surfaces a pre-accept
    close as an exception on ``connect()`` and an accepted-then-closed
    socket as an exception on the first receive, so both shapes look alike.
    A real ASGI server is the only place where the difference is visible:
    a pre-accept close becomes an HTTP 403 and the client never sees the
    code at all.  This test therefore runs uvicorn and talks to it with a
    real WebSocket client.
    """
    import uvicorn

    port = _free_port()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="off",
        ws="websockets",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        if not thread.is_alive():  # pragma: no cover - the server died on startup
            pytest.fail("the uvicorn server did not start")
        time.sleep(0.05)
    assert server.started, "the uvicorn server did not start in time"

    try:
        closed: ConnectionClosed | None = None
        try:
            with connect(f"ws://127.0.0.1:{port}/ws/missions/contract-mission") as websocket:
                websocket.recv()
        except ConnectionClosed as exc:
            closed = exc

        assert closed is not None, (
            "the server accepted the anonymous handshake and never closed it"
        )
        assert closed.rcvd is not None, "no close frame was received"
        assert closed.rcvd.code == WS_UNAUTHORIZED_CODE, (
            f"the handshake was closed with {closed.rcvd.code} instead of "
            f"{WS_UNAUTHORIZED_CODE}; the client cannot tell 'authenticate and "
            "retry' from 'server error'"
        )
    finally:
        server.should_exit = True
        thread.join(timeout=15)


def test_protected_routes_refuse_an_invalid_token(rate_limiter_idle: None) -> None:
    """Every protected route answers a made-up credential with 401.

    The middleware only checks that a credential is *present* — the
    cryptographic work belongs to ``require_auth``, so there is one
    implementation of "is this token good".  That is only safe while every
    protected route actually carries the guard, which the inventory
    contract asserts structurally.  This test asserts the behavioural
    half: a route that forgot ``require_auth`` would answer 200 (or 500)
    here, and a made-up token would be enough to reach it.
    """
    client = TestClient(app)
    probes = _protected_probes()
    assert len(probes) > 100, (
        f"only {len(probes)} protected routes found; the inventory looks truncated"
    )

    failures: list[str] = []
    for method, path in probes:
        response = client.request(method, path, headers={"Authorization": _INVALID_TOKEN})
        if response.status_code != 401:
            failures.append(f"{method} {path} -> {response.status_code}")

    assert not failures, (
        "these routes accepted a present-but-invalid token:\n  "
        + "\n  ".join(failures)
        + "\n\nEvery protected route must carry require_auth (or require_admin); "
        "see backend/tests/contracts/test_route_auth_inventory.py."
    )
