"""The auth inventory contract: every route is guarded, or public on purpose.

The gap this closes
-------------------
Audit P0.2 found 95 routes on this app answering with no authentication at
all: 84 of them inside 11 routers that were never given the ``require_auth``
dependency (plus 7 individual routes), and the rest legitimately public --
liveness probes, build identity, the Prometheus scrape target, the routes that
*grant* the token, and the FastAPI docs pages.  Nothing in the suite failed
while that was true: an unauthenticated ``GET /api/errors`` is indistinguishable
from a working feature until someone queries it from outside the host.

Four tests make that state impossible to return to silently:

1. ``test_every_route_is_guarded_or_deliberately_public`` -- walks the live
   route tree and demands that every registration either carries
   ``require_auth``/``require_admin`` in its dependency tree or is named in
   ``backend/middleware/public_routes.py``.  A new unguarded route fails here
   with the route to fix.
2. ``test_every_public_allowlist_entry_still_exists_on_the_app`` -- the reverse
   direction: an entry whose route was renamed or removed fails here, so the
   allowlist cannot rot into a list of fictional exceptions that hides a real
   hole.
3. ``test_anonymous_requests_to_protected_routes_are_refused`` and
   ``test_anonymous_websocket_handshakes_are_refused_with_4401`` -- the
   behavioural half: real anonymous requests over the wired middleware stack,
   asserting 401/4401 (405/422 for method and shape mismatches).  This is what
   catches a router that has the dependency but is still mounted somewhere
   without the middleware, or a middleware ordering mistake that lets the
   request through.
4. ``TestDenyByDefaultMiddlewarePlacement`` -- records the measured middleware
   order and the CORS/liveness consequences of getting it wrong.

The route tree is walked directly rather than through ``app.openapi()``:
building the schema emits a pre-existing ``UserWarning: Duplicate Operation
ID`` from ``observability/routes/workflows.py`` and this project runs pytest
with ``filterwarnings = ["error"]``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.routing import APIWebSocketRoute
from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocketDisconnect

from backend.middleware.auth import create_access_token
from backend.middleware.deny_by_default import (
    AUTH_GUARDS,
    DenyByDefaultMiddleware,
    flatten_routes,
    path_format_for,
)
from backend.middleware.public_routes import (
    PUBLIC_DOCS_ROUTES,
    PUBLIC_HTTP_ROUTES,
    PUBLIC_WS_ROUTES,
    is_public_http_route,
    is_public_ws_route,
)
from backend.orchestrator.main import app
from backend.tests.conftest import registered_route_paths

pytestmark = pytest.mark.contract

#: Statuses that mean "the request never reached a handler".  405 is the
#: router's own answer when the path exists for another method; 422 is what a
#: route with no auth dependency at all would raise if it were reached.  Both
#: are refusals, not successes, and neither exposes data.
_REFUSED_STATUSES = frozenset({401, 405, 422})

#: Value substituted for every path parameter when probing routes.
_PARAM_VALUE = "contract-inventory"

#: A route that is protected and needs no state, used for shaping assertions.
_PROTECTED_PROBE = "/api/errors"


@pytest.fixture
def anonymous_client() -> TestClient:
    """A client with no Authorization header at all."""
    return TestClient(app)


@pytest.fixture
def authenticated_client() -> TestClient:
    """A client carrying a real, signed bearer token."""
    token = create_access_token({"sub": "contract", "email": "contract@test.local"})
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def rate_limiter_idle(monkeypatch: pytest.MonkeyPatch):
    """Suspend the app's rate limiter for the duration of one test.

    The exhaustive sweep below fires one request per registered route -- the
    default budget is 200/min per client -- so without this the sweep would be
    answered with 429s that say nothing about authentication, and the exhausted
    quota would leak into whichever test ran next.
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


@dataclass(frozen=True)
class RouteRecord:
    """One registered route, flattened out of the include-router wrappers."""

    path_format: str
    methods: frozenset[str]
    module: str
    qualname: str
    guarded: bool
    is_websocket: bool

    @property
    def location(self) -> str:
        return f"{self.module}::{self.qualname}"


def _original_route(route: Any) -> Any:
    """The user-visible route behind a FastAPI effective-context wrapper."""
    original = getattr(route, "original_route", None)
    if original is not None:
        return original
    return route


def _is_websocket_route(route: Any) -> bool:
    return isinstance(_original_route(route), APIWebSocketRoute)


def _endpoint(route: Any) -> Any:
    return getattr(_original_route(route), "endpoint", None)


def _dependant_of(route: Any) -> Any:
    """The dependency tree FastAPI will actually run for this route.

    An included HTTP route carries a rebuilt dependant on the flattened
    ``_EffectiveRouteContext`` (include-time router dependencies included).  A
    WebSocket route inside an included router does not -- its context keeps an
    empty dependant and the real tree lives on the generated
    ``starlette_route``, which is where FastAPI picked up the
    ``dependencies=[Depends(require_websocket_token)]`` the route declares.
    Reading the first tree that has dependencies covers both without guessing.
    """
    candidates = (
        route,
        getattr(route, "starlette_route", None),
        getattr(route, "original_route", None),
    )
    fallback: Any = None
    for candidate in candidates:
        dependant = getattr(candidate, "dependant", None)
        if dependant is None:
            continue
        if fallback is None:
            fallback = dependant
        if getattr(dependant, "dependencies", None):
            return dependant
    return fallback


def _has_guard(dependant: Any, _seen: set[int] | None = None) -> bool:
    """Whether ``require_auth``/``require_admin`` appears anywhere in the tree.

    Recursive because the guard can sit at the router level (the preferred
    arrangement for whole routers) or on a single route decorator -- both land
    in the same dependency tree, at different depths.
    """
    if dependant is None:
        return False
    if _seen is None:
        _seen = set()
    if id(dependant) in _seen:
        return False
    _seen.add(id(dependant))
    if getattr(getattr(dependant, "call", None), "__name__", "") in AUTH_GUARDS:
        return True
    return any(_has_guard(sub, _seen) for sub in getattr(dependant, "dependencies", []) or [])


def _inventory() -> list[RouteRecord]:
    """Every route the app registers, with its auth posture computed."""
    records: list[RouteRecord] = []
    for route in flatten_routes(getattr(app, "routes", [])):
        path_format = path_format_for(route)
        if path_format is None:
            continue
        methods = frozenset(getattr(route, "methods", None) or ())
        endpoint = _endpoint(route)
        records.append(
            RouteRecord(
                path_format=path_format,
                methods=methods,
                module=getattr(endpoint, "__module__", "<unknown>"),
                qualname=getattr(endpoint, "__qualname__", "<unknown>"),
                guarded=_has_guard(_dependant_of(route)),
                is_websocket=_is_websocket_route(route),
            )
        )
    return records


def _probe_path(path_format: str) -> str:
    """``/api/x/{id}`` -> ``/api/x/contract-inventory``."""
    return re.sub(r"\{[^{}]+\}", _PARAM_VALUE, path_format)


def test_every_route_is_guarded_or_deliberately_public() -> None:
    """A route with no auth dependency must be on the public allowlist."""
    unguarded: list[str] = []
    for record in _inventory():
        if record.guarded:
            continue
        if record.is_websocket:
            if is_public_ws_route("WS", record.path_format):
                continue
        else:
            methods = record.methods - {"HEAD"}
            if any(is_public_http_route(method, record.path_format) for method in methods):
                continue
        unguarded.append(f"{record.methods or 'WS'} {record.path_format} -> {record.location}")

    assert not unguarded, (
        "these routes answer anonymous requests:\n  "
        + "\n  ".join(sorted(unguarded))
        + "\n\nFix one of two ways:\n"
        "  1. guard it -- add `dependencies=[Depends(require_auth)]` to the router "
        "constructor (whole router) or to the route decorator (single route);\n"
        "  2. if it really is public, add (method, path_format) to "
        "PUBLIC_HTTP_ROUTES / PUBLIC_WS_ROUTES in backend/middleware/public_routes.py "
        "with a comment saying why -- a probe, a credential-granting route, or a docs page."
    )


def test_every_public_allowlist_entry_still_exists_on_the_app() -> None:
    """An allowlist entry for a route that no longer exists hides a real hole."""
    registered = _inventory()
    http_pairs = {
        (method, record.path_format)
        for record in registered
        if not record.is_websocket
        for method in record.methods
    }
    ws_paths = {record.path_format for record in registered if record.is_websocket}

    stale: list[str] = []
    for method, path_format in sorted(PUBLIC_HTTP_ROUTES | PUBLIC_DOCS_ROUTES):
        if (method, path_format) not in http_pairs:
            stale.append(f"{method} {path_format} (PUBLIC_HTTP_ROUTES/PUBLIC_DOCS_ROUTES)")
    for method, path_format in sorted(PUBLIC_WS_ROUTES):
        if path_format not in ws_paths:
            stale.append(f"{method} {path_format} (PUBLIC_WS_ROUTES)")

    assert not stale, (
        "these allowlist entries no longer match any registered route:\n  "
        + "\n  ".join(stale)
        + "\n\nDelete them from backend/middleware/public_routes.py. A stale entry is "
        "worse than a missing one: it documents an exception nobody re-reads, and the "
        "route it described may have been renamed into something that now needs the guard."
    )


def test_the_inventory_walker_sees_the_same_paths_as_the_shared_walker() -> None:
    """Cross-check the local walker against the suite's shared route walker.

    ``registered_route_paths`` is used elsewhere in the suite as the canonical
    "what is mounted" answer; if this file's walker silently missed routes, the
    tests above would be measuring fiction.  It returns a *set of paths*, so
    the comparison is on paths -- a path registered for two methods counts
    once there and twice here, which is exactly the duplication this file cares
    about.
    """
    shared = registered_route_paths(app)
    local = {record.path_format for record in _inventory()}
    assert local == set(shared), (
        "the deny-by-default inventory walker disagrees with "
        "backend.tests.conftest.registered_route_paths. FastAPI's router layout "
        "changed or the wrapper resolution broke; fix the walker before trusting "
        "the auth inventory.\n"
        f"  shared walker: {len(shared)} paths\n"
        f"  local walker:  {len(local)} paths\n"
        f"  local-only: {sorted(local - set(shared))[:5]}\n"
        f"  shared-only: {sorted(set(shared) - local)[:5]}"
    )


def test_anonymous_websocket_handshakes_are_refused_with_4401(
    anonymous_client: TestClient,
) -> None:
    """Both WebSocket routes must reject an anonymous handshake before accept.

    Closing with 4401 (not 1008, not an accepted-then-immediately-closed
    socket) is what lets the client distinguish "authenticate and retry" from
    "server went away".
    """
    ws_routes = [record.path_format for record in _inventory() if record.is_websocket]
    assert ws_routes, "no WebSocket routes found -- the walker lost them"

    for path_format in ws_routes:
        with (
            pytest.raises(WebSocketDisconnect) as excinfo,
            anonymous_client.websocket_connect(_probe_path(path_format)),
        ):
            pass  # pragma: no cover - the handshake is refused before accept
        assert excinfo.value.code == 4401, (
            f"WS {path_format} closed with {excinfo.value.code} instead of 4401; "
            "an anonymous handshake must be refused by the deny-by-default middleware "
            "or by the route's own guard."
        )


def test_anonymous_http_requests_to_protected_routes_are_refused(
    anonymous_client: TestClient,
    rate_limiter_idle: None,
) -> None:
    """Every protected route answers an anonymous request with a refusal.

    Exercised through the real middleware stack (``backend.orchestrator.main``
    as wired), not a stripped-down app, so this is also the guard against the
    middleware being registered in the wrong order or not at all.
    """
    public_pairs = PUBLIC_HTTP_ROUTES | PUBLIC_DOCS_ROUTES
    probes: list[tuple[str, str, str]] = []
    for record in _inventory():
        if record.is_websocket:
            continue
        for method in sorted(record.methods - {"HEAD"}):
            if (method, record.path_format) in public_pairs:
                continue
            probes.append((method, record.path_format, record.location))

    assert len(probes) > 100, (
        f"only {len(probes)} protected routes found; the inventory looks truncated"
    )

    failures: list[str] = []
    for method, path_format, location in probes:
        response = anonymous_client.request(method, _probe_path(path_format))
        if response.status_code not in _REFUSED_STATUSES:
            failures.append(
                f"{method} {_probe_path(path_format)} -> {response.status_code} ({location})"
            )

    assert not failures, (
        "these routes answered an anonymous request:\n  "
        + "\n  ".join(failures)
        + "\n\nExpected 401 from backend/middleware/deny_by_default.py, 405 from the "
        "router (path exists for another method), or 422 (route reached without a "
        "guard -- see test_every_route_is_guarded_or_deliberately_public)."
    )


def test_the_401_is_a_www_authenticate_challenge(anonymous_client: TestClient) -> None:
    """The 401 must be shaped like the one ``require_auth`` emits.

    One shape, one frontend code path: a differently-worded body here would
    mean the deny-by-default 401 and the dependency 401 need separate handling.
    """
    response = anonymous_client.get(_PROTECTED_PROBE)
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
    assert response.json() == {"detail": "Authentication required"}
    assert response.headers["content-type"].startswith("application/json")


class TestDenyByDefaultMiddlewarePlacement:
    """Ordering, CORS survival, and the public routes -- measured, not assumed.

    Starlette's ``add_middleware`` inserts each new middleware as the
    *outermost* one, so the registration order in ``main.py`` is the reverse of
    the runtime order.  Getting that wrong is silent: the 401 still happens, it
    just arrives without CORS headers (so the browser reports an opaque network
    error instead of a 401) or after the rate limiter has already counted the
    request.
    """

    def _order(self) -> list[str]:
        return [
            getattr(middleware.cls, "__name__", str(middleware.cls))
            for middleware in app.user_middleware
        ]

    def test_middleware_is_registered(self) -> None:
        order = self._order()
        assert DenyByDefaultMiddleware.__name__ in order, (
            f"DenyByDefaultMiddleware is not registered; order={order}. Add "
            "app.add_middleware(DenyByDefaultMiddleware) in backend/orchestrator/main.py."
        )

    def test_deny_sits_inside_cors_so_the_401_carries_cors_headers(
        self, anonymous_client: TestClient
    ) -> None:
        """CORS must wrap the 401, or the frontend sees a CORS error, not a 401."""
        order = self._order()
        assert "CORSMiddleware" in order and "DenyByDefaultMiddleware" in order
        assert order.index("CORSMiddleware") < order.index("DenyByDefaultMiddleware"), (
            f"CORS is inside deny-by-default (order={order}); the 401 would reach "
            "the browser without Access-Control-Allow-* headers."
        )

        response = anonymous_client.get(
            "/api/errors", headers={"Origin": "http://localhost:3000"}
        )
        assert response.status_code == 401
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000", (
            "the 401 has no CORS headers, so CORS is not wrapping the middleware"
        )

    def test_cors_preflight_is_not_answered_with_401(
        self, anonymous_client: TestClient
    ) -> None:
        """A preflight cannot carry credentials; refusing it breaks every call."""
        preflight = anonymous_client.options(
            "/api/errors",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert preflight.status_code == 200, (
            f"preflight answered {preflight.status_code}; browsers send OPTIONS "
            "without credentials, so a 401 here fails the real request before it "
            "is made"
        )
        assert preflight.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_public_routes_still_answer_anonymous_callers(
        self, anonymous_client: TestClient, rate_limiter_idle: None
    ) -> None:
        """The routes every probe, Prometheus and the login form depend on.

        ``/openapi.json``, ``/docs`` and ``/redoc`` are deliberately not probed
        here: serving them builds the schema, which emits the pre-existing
        ``UserWarning: Duplicate Operation ID`` that ``filterwarnings = error``
        turns into a failure.  They are covered structurally by the allowlist
        test above, which asserts they are still registered.
        """
        for path in (
            "/health",
            "/api/health",
            "/api/ready",
            "/version",
            "/api/version",
            "/metrics",
        ):
            response = anonymous_client.get(path)
            assert response.status_code == 200, f"GET {path} -> {response.status_code}"

    def test_authenticated_request_still_reaches_the_handler(
        self, authenticated_client: TestClient
    ) -> None:
        """Deny-by-default must not break the happy path."""
        response = authenticated_client.get("/api/errors")
        assert response.status_code == 200

    def test_present_but_invalid_token_is_rejected_by_the_guard_not_the_middleware(
        self, anonymous_client: TestClient
    ) -> None:
        """A malformed credential must reach ``get_current_user``.

        The middleware deliberately does not validate signatures; if it 401s a
        present-but-invalid token itself, this test catches the drift toward a
        second, divergent token implementation.
        """
        response = anonymous_client.get(
            "/api/errors", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert response.status_code == 401
        # The dependency's wording, not the middleware's: a different detail
        # proves the request reached the guard instead of dying at the edge.
        assert response.json()["detail"] != "Authentication required"


def test_lifespan_is_never_gated() -> None:
    """Startup/shutdown scopes have no request to authenticate."""
    seen: list[str] = []

    async def inner_app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    middleware = DenyByDefaultMiddleware(inner_app)

    async def receive() -> Scope:  # pragma: no cover - never awaited
        return {}

    async def send(message: Scope) -> None:  # pragma: no cover - never awaited
        return None

    import anyio

    anyio.run(middleware, {"type": "lifespan"}, receive, send)
    assert seen == ["lifespan"]
