"""Integration tests for the dashboard API surface.

What changed and why
--------------------
These four tests used to assert that ``GET /api/dashboard/state`` and
``POST /api/dashboard/publish`` exist. They do not, and after the ``skip on 404``
was removed they failed -- correctly, because a missing route is a defect, not an
environment condition.

The investigation that followed showed the *tests* were the defective part, not the
routing. Two routers both declare paths under ``/api/dashboard``:

* ``backend/orchestrator/routes/dashboard.py`` -- **mounted** (main.py:865). Serves
  ``status``, ``alerts``, ``metrics``, ``ask``, ``diagnose``.
* ``backend/observability/routes/dashboard.py`` -- **not mounted**. Declares
  ``state``, ``stream`` and ``publish``, and its own docstring says it must not be
  mounted.

Mounting the second one was measured, not assumed (see
``test_backend_hardening_dashboard_wiring.py``): it does not start the app and it
does not duplicate an operation id, but it *does* register ``GET
/api/dashboard/stream`` a second time, and the frontend's metrics page consumes
that path as an ``EventSource`` (``frontend/stores/metricsStore.ts``). Whichever
registration lost the race would silently win, so one of two different SSE payload
shapes would be served. ``state`` and ``publish`` have no consumer anywhere in
``backend/`` or ``frontend/``, and ``publish`` exists only to inject events for a
demo. So the router stays unmounted and these tests now assert the contract that
actually exists, plus the absence of the two dead paths so the gap cannot reopen
silently.

No test here skips. Every one either exercises a mounted route or asserts a
documented 404.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.orchestrator.main import app
from backend.tests.conftest import registered_route_paths

#: The documented dashboard contract. Anything else under /api/dashboard is a
#: routing mistake in either direction -- an unmounted declaration or a stale one.
MOUNTED_DASHBOARD_ROUTES: dict[str, set[str]] = {
    "/api/dashboard/status": {"GET"},
    "/api/dashboard/alerts": {"GET"},
    "/api/dashboard/metrics": {"GET"},
    "/api/dashboard/ask": {"POST"},
    "/api/dashboard/diagnose": {"POST"},
    # Served by backend/observability/routes/metrics.py, not by either dashboard
    # router: this is the SSE the frontend Metrics page subscribes to.
    "/api/dashboard/stream": {"GET"},
}

#: Declared only by the deprecated, unmounted observability router.
DEPRECATED_DASHBOARD_PATHS = ("/api/dashboard/state", "/api/dashboard/publish")


def _registered() -> set[str]:
    return registered_route_paths(app)


def test_dashboard_surface_is_exactly_the_documented_contract() -> None:
    """Every mounted dashboard route exists, and nothing undeclared is served."""
    paths = _registered()
    missing = sorted(p for p in MOUNTED_DASHBOARD_ROUTES if p not in paths)
    assert not missing, f"documented dashboard routes are not registered: {missing}"

    served = {p for p in paths if p.startswith("/api/dashboard/")}
    undeclared = sorted(served - set(MOUNTED_DASHBOARD_ROUTES))
    assert not undeclared, (
        f"undeclared paths are served under /api/dashboard: {undeclared}. "
        f"Either they belong in MOUNTED_DASHBOARD_ROUTES or their router should "
        f"not be mounted."
    )


def test_dashboard_state_is_served_by_the_mounted_status_route(client: TestClient) -> None:
    """Dashboard *state* is a real product need, served by ``/dashboard/status``.

    This replaces the old ``/api/dashboard/state`` test. ``/dashboard/status`` is
    the surface the frontend actually calls (``frontend/lib/api.ts``) and it is
    backed by the same ``get_metrics_collector()`` singleton the SSE stream reads.
    """
    assert "/api/dashboard/status" in _registered()

    response = client.get("/api/dashboard/status")

    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data, dict)
    # The health snapshot the dashboard renders. ``health_score`` is legitimately
    # null before the first sample, so its presence is asserted, not its value.
    for key in ("health_score", "snapshot", "active_alerts", "critical_alerts"):
        assert key in data, f"{key!r} missing from /dashboard/status payload: {data!r}"


def test_deprecated_dashboard_state_path_is_not_served(client: TestClient) -> None:
    """``/api/dashboard/state`` must stay absent, and say why when asked.

    A 404 here is the *expected* answer, asserted directly. This is the inverse
    of the old test: previously "not registered" was a failure to be fixed by
    mounting the router; now it is the contract, so a future change that mounts
    the deprecated router fails here instead of shipping a second SSE stream.
    """
    assert "/api/dashboard/state" not in _registered(), (
        "/api/dashboard/state is registered again. It is declared only by the "
        "deprecated backend/observability/routes/dashboard.py, whose /dashboard/stream "
        "route would collide with the SSE endpoint the frontend consumes. If a real "
        "state payload is wanted, extend /api/dashboard/status instead."
    )
    assert client.get("/api/dashboard/state").status_code == 404


def test_deprecated_dashboard_publish_path_is_not_served(client: TestClient) -> None:
    """``/api/dashboard/publish`` must stay absent: a demo hook, not an endpoint.

    The handler published straight onto ``DashboardState._bus`` (a private
    attribute) with no payload validation. It has no consumer in ``backend/`` or
    ``frontend/``; mounting it would add an event-injection surface to the
    production API to satisfy a test.
    """
    assert "/api/dashboard/publish" not in _registered(), (
        "/api/dashboard/publish is registered again. It is a test/demo hook that "
        "publishes onto a private bus; it is not part of the dashboard API."
    )
    assert client.post("/api/dashboard/publish", params={"event_type": "x"}).status_code == 404


def test_dashboard_routes_require_authentication(client: TestClient) -> None:
    """Every mounted dashboard route is behind ``require_auth``.

    Checks the *unauthenticated* client explicitly, because "the authenticated
    client got 200" says nothing about whether the route is protected -- and a
    monitoring surface leaking health and alert data unauthenticated is exactly
    the kind of regression these tests exist to catch.
    """
    anonymous = TestClient(app)
    for path, methods in MOUNTED_DASHBOARD_ROUTES.items():
        for method in methods:
            response = anonymous.request(method, path)
            assert response.status_code in {401, 422}, (
                f"{method} {path} answered {response.status_code} without a token; "
                f"expected 401 (auth enforced) or 422 (body validation ran first)"
            )
    # A 401 on a POST that requires a body is only meaningful if auth is what
    # rejected it, so assert the unauthenticated GET paths are unambiguously 401.
    for path in ("/api/dashboard/status", "/api/dashboard/alerts"):
        assert anonymous.get(path).status_code == 401
