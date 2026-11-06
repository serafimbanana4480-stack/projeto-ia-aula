"""Deny-by-default authentication for the NEXUS IDE HTTP/WS surface.

The policy
----------
Every registered route answers anonymous callers **only** if its
``(method, path_format)`` pair is named in
:mod:`backend.middleware.public_routes`.  Everything else is refused with
``401 {"detail": "Authentication required"}`` (or a ``4401`` WebSocket close)
before the request ever reaches a handler.

That is the opposite of the previous policy, and the measurement is why: the
app registers ~386 routes and 95 of them used to answer with no credentials at
all.  Ninety-five individual decisions to leave a hole open, each reasonable in
isolation, is not a security posture.

Deliberately *not* done here
----------------------------
For **HTTP**, the middleware does **not** validate the token's signature,
expiry, or subject.  It checks that *a* bearer credential is present and
lets the real guard — ``require_auth`` / ``require_admin`` via
:func:`backend.middleware.auth.get_current_user` — do the cryptographic work.
Two reasons:

1. one source of truth for token semantics (signature algorithm, ``type``
   refresh claims, revocation) instead of two implementations that drift;
2. a malformed token must still reach ``get_current_user`` so the client gets
   the precise ``401 Could not validate credentials`` it already handles,
   rather than a second, differently-worded rejection path.

For **WebSockets** the rule is different, and the difference is forced by the
protocol.  A handshake has no dependency layer behind the edge: the route's
own guard runs *after* the handshake was already accepted or closed, and a
close sent before ``accept()`` is answered by a real ASGI server with an
HTTP 403 and no close frame — the client cannot read the code and cannot
tell "authenticate and retry" from "the server broke".  The edge therefore
validates the handshake credential itself, with the *same* decoder the route
guard uses (:func:`backend.middleware.auth.decode_access_token`), and refuses
the handshake by **accepting it and closing it with ``4401``**.  One
implementation of "is this token good" still; a close code the client can
actually read.

Why a pure ASGI middleware
--------------------------
``BaseHTTPMiddleware`` runs the whole downstream stack inside a wrapper task
and buffers: it breaks WebSocket scopes, it changes streaming semantics, and
Starlette deprecates it for exactly this use.  Route resolution needs
``route.matches(scope)`` on the raw scope, and a WebSocket rejection has to
happen in the ASGI message stream — both are plain ASGI operations, so this
is a plain ASGI middleware.

Placement in the stack (measured, see tests/contracts/
test_route_auth_inventory.py)
--------------------------------------------------------------------
Starlette's ``add_middleware`` inserts each new middleware as the **outermost**
one, so ordering is the reverse of the call order.  This middleware is added
*after* ``SecurityHeadersMiddleware`` and *before* ``CORSMiddleware``, which
puts it:

* **inside CORS** — a preflight ``OPTIONS`` is answered by ``CORSMiddleware``
  itself and never reaches this middleware, so browser CORS keeps working; and
  the ``401`` this middleware produces on its way out gains the
  ``Access-Control-Allow-*`` headers, so the frontend sees a real 401 instead
  of an opaque CORS failure.
* **outside the router** — unauthenticated requests are refused before any
  handler, dependency, or database read runs.
* **inside the rate limiter** — anonymous traffic still consumes quota, so the
  401 path cannot be used as an unmetered probe.
* **outside the security-headers middleware** — that middleware decorates app
  responses only; a 401 carries no document, so nothing is lost.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qs
from weakref import WeakKeyDictionary

from fastapi import WebSocketException
from starlette.routing import Match
from starlette.websockets import WebSocket

from backend.middleware.public_routes import is_public_http_route, is_public_ws_route

logger = logging.getLogger(__name__)

#: Detail body of the HTTP rejection.  Identical to ``require_auth``'s so the
#: frontend has exactly one "not authenticated" shape to handle.
UNAUTHORIZED_DETAIL = "Authentication required"

#: WebSocket close code for a rejected handshake.  4401 is in the
#: application-private range (4000-4999) and is the WS analogue of HTTP 401.
WS_UNAUTHORIZED_CODE = 4401

#: WebSocket close code for a handshake that authenticated but was refused on
#: ownership grounds ("this mission is not yours").  Also in the
#: application-private range; the frontend already treats it as final.
WS_FORBIDDEN_CODE = 4403

#: Methods that are always allowed through.
#:
#: ``OPTIONS`` is the CORS preflight method.  A browser sends it *without*
#: credentials — it cannot authenticate a preflight, and forbidding it would
#: break every cross-origin call to a protected route before the real request
#: is even made.  Starlette's ``CORSMiddleware`` answers preflights itself,
#: but a non-preflight ``OPTIONS`` (an ``Origin`` without
#: ``Access-Control-Request-Method``) still reaches the app, and both shapes
#: must pass here.  An ``OPTIONS`` response carries no protected payload: at
#: worst it names the methods a route accepts.
PREFLIGHT_METHODS = frozenset({"OPTIONS"})

#: Dependency callables that count as authentication for this policy.
#:
#: Referenced by the route-inventory contract test
#: (``backend/tests/contracts/test_route_auth_inventory.py``) as the single
#: source of truth for "this route is guarded".  ``get_current_user`` is
#: deliberately absent: it returns ``None`` for an anonymous caller instead of
#: rejecting it, so a route that depends on it alone is still public.
#: ``require_websocket_token`` is the WebSocket analogue: a FastAPI dependency
#: that raises ``WebSocketException(4401)`` when the handshake carries no valid
#: credential.
AUTH_GUARDS = frozenset({"require_auth", "require_admin", "require_websocket_token"})

#: ``path_format`` → flattened-route cache, per app instance.
#:
#: Flattening walks ``_IncludedRouter.effective_candidates()`` (FastAPI keeps
#: included routers as wrapper nodes, so a flat ``app.routes`` scan sees five
#: routes out of ~390).  FastAPI caches the effective candidates internally, so
#: rebuilding is cheap — but it is still one tree walk per request, and this
#: middleware sits on every request.  Keyed weakly so a discarded app (tests
#: build several) cannot leak, and invalidated whenever the route count moves,
#: which is the only thing a live app changes at runtime.
_ROUTE_CACHE: WeakKeyDictionary[Any, tuple[int, list[Any]]] = WeakKeyDictionary()


def flatten_routes(routes: Iterable[Any] | None) -> list[Any]:
    """Flatten a FastAPI/Starlette route tree into matchable leaf routes.

    Resolves both shapes this app can present:

    * ``_IncludedRouter`` nodes (FastAPI >= 0.140) — resolved through
      ``effective_candidates()``, which also applies the include-time prefix,
      so a flattened route's ``path_format`` is the app-visible path;
    * plain ``Route`` / ``APIRoute`` / ``APIWebSocketRoute`` / ``Mount``
      objects — already leaves.
    """
    flat: list[Any] = []
    for route in routes or []:
        candidates_of = getattr(route, "effective_candidates", None)
        if callable(candidates_of):
            try:
                flat.extend(flatten_routes(candidates_of()))
            except Exception:  # pragma: no cover - defensive: never block a request
                logger.debug("Could not flatten route %r", route, exc_info=True)
            continue
        flat.append(route)
    return flat


def routes_for(app: Any) -> list[Any]:
    """Flattened, per-app-cached route list for ``scope['app']``."""
    routes = getattr(app, "routes", None)
    if routes is None:
        return []
    try:
        signature = len(routes)
    except TypeError:  # pragma: no cover - exotic routes object
        return flatten_routes(routes)

    cached = _ROUTE_CACHE.get(app)
    if cached is not None and cached[0] == signature:
        return cached[1]

    flat = flatten_routes(routes)
    # Apps that refuse to be weak-referenced simply lose the cache.
    with contextlib.suppress(TypeError):  # pragma: no cover - depends on app class
        _ROUTE_CACHE[app] = (signature, flat)
    return flat


def path_format_for(route: Any, child_scope: Any = None) -> str | None:
    """The route template that matched, preferring the scope's own report.

    Starlette puts ``path_format`` in the child scope for routes it compiled.
    FastAPI's ``_EffectiveRouteContext`` carries one too -- except for routes
    that are not ``APIRoute`` (WebSocket routes, ``Mount``, ``Host``), where the
    prefixed template lives on the generated ``starlette_route`` and the
    context's own ``path``/``path_format`` stay empty.  Either way the result is
    the *template* (``/api/x/{id}``), never the concrete request path -- which is
    what makes a single allowlist entry cover every path parameter.
    """
    if isinstance(child_scope, dict):
        candidate = child_scope.get("path_format")
        if isinstance(candidate, str) and candidate:
            return candidate
    for owner in (route, getattr(route, "starlette_route", None)):
        if owner is None:
            continue
        for attribute in ("path_format", "path"):
            candidate = getattr(owner, attribute, None)
            if isinstance(candidate, str) and candidate:
                return candidate
    return None


def matched_path_formats(scope: Any, routes: Iterable[Any]) -> list[str]:
    """Templates of every route that fully matches *scope*.

    A request can legitimately full-match more than one registration — a
    literal path and a parameterised one (``/api/x/me`` plus
    ``/api/x/{id}``), or a duplicate registration — so every match is
    collected and the caller decides.
    """
    formats: list[str] = []
    for route in routes:
        matches = getattr(route, "matches", None)
        if not callable(matches):
            continue
        try:
            match, child_scope = matches(scope)
        except Exception:  # pragma: no cover - defensive: never block a request
            logger.debug("Route %r failed to match", route, exc_info=True)
            continue
        if match is not Match.FULL:
            continue
        path_format = path_format_for(route, child_scope)
        if path_format is not None:
            formats.append(path_format)
    return formats


def _header(scope: Any, name: str) -> str | None:
    """First raw header value, compared case-insensitively (ASGI lowercases)."""
    target = name.lower().encode("latin-1")
    headers: Any = scope.get("headers") or []
    for key, value in headers:
        if key.lower() == target:
            decoded: str = value.decode("latin-1")
            return decoded
    return None


def bearer_token(scope: Any) -> str | None:
    """The bearer token from ``Authorization: Bearer <token>``, if any.

    Presence only — the signature is validated downstream by
    ``get_current_user``.  A malformed or empty scheme is treated as absent.
    """
    header = _header(scope, "authorization")
    if not header:
        return None
    schema, _, param = header.partition(" ")
    if schema.lower() != "bearer":
        return None
    token = param.strip()
    return token or None


def websocket_token_candidates(scope: Any) -> list[str]:
    """Every credential a WebSocket handshake offered, best candidate first.

    WebSocket clients cannot always set request headers (the browser API only
    allows ``Sec-WebSocket-Protocol``), so the query string is accepted *here*
    even though HTTP routes refuse it: a WS handshake has no other place to
    carry a credential.  Order is header-first so a client that can set
    ``Authorization`` never leaks its token into a URL that may be logged.

    ``Sec-WebSocket-Protocol`` is a comma-separated list, and a client that
    negotiates a named protocol sends ``["nexus-v1", "<token>"]`` -- hence more
    than one candidate.  All of them are returned so the validator can try
    them in order; the edge check only needs the first.
    """
    candidates: list[str] = []

    header = bearer_token(scope)
    if header:
        candidates.append(header)

    protocol = _header(scope, "sec-websocket-protocol")
    if protocol:
        candidates.extend(
            value.strip() for value in protocol.split(",") if value.strip()
        )

    query_string = scope.get("query_string") or b""
    if query_string:
        params = parse_qs(query_string.decode("latin-1"), keep_blank_values=True)
        candidates.extend(value.strip() for value in params.get("token") or [] if value.strip())

    # Preserve order, drop duplicates: a client that sends the same token in
    # two places must not produce two decode attempts with different errors.
    return list(dict.fromkeys(candidates))


def websocket_token(scope: Any) -> str | None:
    """The first credential a WebSocket handshake offered, if any."""
    candidates = websocket_token_candidates(scope)
    return candidates[0] if candidates else None


async def _send_unauthorized(send: Any) -> None:
    """Emit ``401 {"detail": "Authentication required"}`` with ``WWW-Authenticate``."""
    body = json.dumps({"detail": UNAUTHORIZED_DETAIL}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _close_unauthorized(send: Any) -> None:
    """Refuse a WebSocket handshake with the documented close code.

    The handshake is **accepted first** and closed immediately afterwards.

    A close sent *before* ``accept()`` is answered by a real ASGI server
    with an HTTP 403 and no close frame at all, so the client never sees
    the code and cannot tell "authenticate and retry" from "the server
    broke".  Accepting and then closing hands the client the ``4401`` close
    frame the contract documents, and no application data is exchanged
    either way.
    """
    await send({"type": "websocket.accept", "subprotocol": None, "headers": []})
    await send({"type": "websocket.close", "code": WS_UNAUTHORIZED_CODE})


class DenyByDefaultMiddleware:
    """ASGI middleware that enforces :mod:`backend.middleware.public_routes`."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        scope_type = scope.get("type")

        # Lifespan (startup/shutdown) has no request to authenticate.
        if scope_type == "lifespan":
            await self.app(scope, receive, send)
            return

        app = scope.get("app")
        routes = routes_for(app) if app is not None else []
        if not routes:
            # No app in scope (a bare ASGI mount) or an app with no routes yet:
            # there is nothing this middleware could resolve, so it must not
            # become a blanket rejection of unrelated traffic.
            logger.debug("deny-by-default: no routes resolvable for %r", scope.get("path"))
            await self.app(scope, receive, send)
            return

        if scope_type == "websocket":
            await self._handle_websocket(scope, receive, send, routes)
            return

        if scope_type != "http":  # pragma: no cover - future ASGI scope types
            await self.app(scope, receive, send)
            return

        await self._handle_http(scope, receive, send, routes)

    async def _handle_http(self, scope: Any, receive: Any, send: Any, routes: list[Any]) -> None:
        method = (scope.get("method") or "").upper()
        if method in PREFLIGHT_METHODS:
            # CORS preflight cannot carry credentials; see PREFLIGHT_METHODS.
            await self.app(scope, receive, send)
            return

        # Starlette registers HEAD alongside GET, so a probe's HEAD is matched
        # by the GET template; look the allowlist up the same way.
        allowlist_method = "GET" if method == "HEAD" else method

        for path_format in matched_path_formats(scope, routes):
            if is_public_http_route(allowlist_method, path_format):
                # Public — but keep scanning: a later registration could still
                # match this same request as a protected route.
                continue
            if bearer_token(scope) is None:
                logger.debug(
                    "deny-by-default: anonymous %s %s blocked", method, scope.get("path")
                )
                await _send_unauthorized(send)
                return
            # Token present: validation is get_current_user's job.
            await self.app(scope, receive, send)
            return

        # No route matched (404 territory), or every match is public.
        await self.app(scope, receive, send)

    async def _handle_websocket(self, scope: Any, receive: Any, send: Any, routes: list[Any]) -> None:
        for path_format in matched_path_formats(scope, routes):
            if is_public_ws_route("WS", path_format):
                continue
            if websocket_caller(scope) is None:
                logger.debug(
                    "deny-by-default: WS handshake without a valid credential blocked for %s",
                    scope.get("path"),
                )
                await _close_unauthorized(send)
                return
            await self.app(scope, receive, send)
            return

        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# WebSocket handshake validation for the handlers themselves
# ---------------------------------------------------------------------------
# The middleware refuses *absent* credentials at the edge, but a WebSocket
# handler is also mounted directly on the app (``/ws/missions/{id}``) and is
# worth of its own guard: if that route is ever served without the middleware
# (a sub-application, a test harness), it must still authenticate.  Unlike the
# edge check, this dependency validates the token, because by this point the
# handshake is already accepted-or-closed territory.


def extract_websocket_tokens(websocket: WebSocket) -> list[str]:
    """Every credential offered by the handshake, best candidate first."""
    return websocket_token_candidates(websocket.scope)


def extract_websocket_token(websocket: WebSocket) -> str | None:
    """The first credential offered by the handshake, if any."""
    return websocket_token(websocket.scope)


def websocket_caller(scope: Any) -> dict[str, Any] | None:
    """The caller a WebSocket handshake authenticated, or ``None``.

    Unlike the HTTP edge -- which only checks that a bearer credential is
    *present* and leaves the cryptographic work to ``get_current_user`` -- a
    WebSocket handshake has no dependency layer behind it: the route's own
    guard runs *after* the handshake was already accepted or closed, and a
    close sent before ``accept()`` reaches the client as an HTTP 403 with no
    close code.  So the edge validates the credential itself, using the very
    same decoder the route guard uses
    (:func:`backend.middleware.auth.decode_access_token`): there is still one
    implementation of "is this token good", and a handshake without a valid
    one is refused with the documented ``4401`` close.
    """
    from backend.middleware.auth import decode_access_token

    for candidate in websocket_token_candidates(scope):
        try:
            payload = decode_access_token(candidate)
        except Exception:
            continue
        if isinstance(payload, dict) and payload.get("sub"):
            return {
                "user_id": payload.get("sub"),
                "email": payload.get("email"),
                "exp": payload.get("exp"),
            }
    return None


async def require_websocket_token(websocket: WebSocket) -> dict[str, Any]:
    """FastAPI dependency for WebSocket routes: the caller, or a 4401 rejection.

    Used as ``Depends(require_websocket_token)`` on the route, which is what
    puts it in the route's dependency tree: the inventory contract test sees
    the guard structurally instead of trusting a docstring, and FastAPI turns
    the raised ``WebSocketException`` into a ``4401`` close *before* the
    handler (and therefore before ``accept()``) runs.

    Accepts the token from ``?token=`` or ``Sec-WebSocket-Protocol`` as well as
    the ``Authorization`` header, because a browser ``WebSocket`` cannot set
    arbitrary request headers.  Every offered candidate is tried in order, so a
    client that negotiates a named subprotocol (``["nexus-v1", "<token>"]``)
    still authenticates.

    This is the last-resort guard for a route served *without* the middleware.
    With the middleware wired, the edge has already refused an invalid
    credential with an accepted-then-closed ``4401`` -- the shape a real
    client can actually read.
    """
    user = websocket_caller(websocket.scope)
    if user is not None:
        return user

    raise WebSocketException(code=WS_UNAUTHORIZED_CODE)
