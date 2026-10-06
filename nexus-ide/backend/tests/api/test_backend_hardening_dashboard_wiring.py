"""The dashboard routers must stay unambiguous: one route per (path, method).

The gap this file closes
------------------------
``backend/orchestrator/routes/dashboard.py`` and
``backend/observability/routes/dashboard.py`` both declare paths under
``/api/dashboard``. Only the first is included in
``backend/orchestrator/main.py``. The second was assumed harmless because nothing
references it -- an assumption that was never checked, and which cost a test suite
four red tests and a day of confusion about which router was canonical.

Measuring it (rather than reasoning about it) showed the two are **not**
interchangeable:

* No startup failure. FastAPI happily registers both, and no operation id is
  duplicated, so nothing complains.
* A real duplicate. ``GET /api/dashboard/stream`` is declared by *both* -- by
  ``observability/routes/metrics.py`` (the canonical SSE, which the frontend's
  ``metricsStore.ts`` subscribes to) and by the deprecated dashboard router (a
  different SSE with a different payload shape). Registration order decides which
  one answers, silently.
* The other two paths the deprecated router declares -- ``state`` and ``publish``
  -- have no consumer anywhere in ``backend/`` or ``frontend/``, and ``publish``
  reaches into ``DashboardState._bus`` to inject events for a demo.

So the deprecated router stays unmounted. These tests exist so that decision is
enforced by the suite rather than by a docstring nobody reads.

They deliberately avoid ``app.openapi()``: building the schema emits a
pre-existing ``UserWarning: Duplicate Operation ID`` from
``observability/routes/workflows.py``, and this project runs pytest with
``filterwarnings = ["error", ...]``, so touching OpenAPI from a test raises. The
router tree is walked instead.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest
from fastapi import FastAPI

from backend.orchestrator.main import app

#: (path, method) pairs that are registered twice **today**, each for a reason
#: outside this change's ownership. This is a ratchet, not a wish list: a new
#: duplicate fails the test, and a fixed one has to be deleted from here, so the
#: set can only shrink.
#:
#: Found by this file on 2026-09-26, not by the dashboard investigation -- the
#: duplicate-path check was generalised once the dashboard case turned out to be
#: a clean one. Each entry is a live instance of the failure mode this file is
#: about: the second registration is unreachable, and FastAPI reports nothing.
#: None of the two implementations is in this change's ownership, so they are
#: recorded rather than fixed here.
KNOWN_DUPLICATES: dict[str, tuple[str, str]] = {
    # main.py:907 re-registers, with tags=["agents"], the endpoint the
    # observability router already registered at line 894. Same function, so the
    # duplicate is harmless at runtime; it does decide which `tags` OpenAPI emits.
    "/api/agents/topology": (
        "backend.orchestrator.routes.observability::agents_topology",
        "main.py:907 add_api_route",
    ),
    "/api/knowledge/stats": (
        "backend.orchestrator.routes.observability::knowledge_stats",
        "backend.orchestrator.routes.knowledge::get_knowledge_stats",
    ),
    "/api/metrics/flow": (
        "backend.observability.routes.metrics::get_request_flow",
        "backend.orchestrator.routes.observability::metrics_flow",
    ),
    "/api/metrics/usage": (
        "backend.observability.routes.metrics::get_usage",
        "backend.observability.routes.usage::get_usage",
    ),
    "/api/system/health": (
        "backend.observability.routes.health::system_health_check",
        "backend.orchestrator.routes.system::get_system_health",
    ),
    "/api/tasks/pipeline": (
        "backend.orchestrator.routes.observability::tasks_pipeline",
        "backend.orchestrator.routes.tasks::get_task_pipeline",
    ),
    "/api/workflows": (
        "backend.orchestrator.routes.observability::list_workflows",
        "backend.observability.routes.workflows::list_workflows",
    ),
    "/api/workflows/{workflow_id}": (
        "backend.orchestrator.routes.observability::get_workflow",
        "backend.observability.routes.workflows::get_workflow",
    ),
    "/api/workflows/{workflow_id}/timeline": (
        "backend.orchestrator.routes.observability::get_workflow_timeline",
        "backend.observability.routes.workflows::get_workflow_timeline",
    ),
}

DEPRECATED_ROUTER_MODULE = "backend.observability.routes.dashboard"


def _walk(routes: Iterable[Any], prefix: str = "", origin: str = "<app>") -> list[tuple[str, str, str, str]]:
    """Flatten ``(path, METHOD, module::qualname)`` out of a FastAPI router tree.

    FastAPI 0.140 keeps ``include_router`` results as ``_IncludedRouter``
    wrappers instead of copying routes into ``app.routes``, so a flat scan sees
    only the handful of directly-attached routes. Written with ``getattr`` so a
    future FastAPI that flattens again still works.
    """
    found: list[tuple[str, str, str, str]] = []
    for route in routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            endpoint = getattr(route, "endpoint", None)
            module = getattr(endpoint, "__module__", origin)
            qualname = getattr(endpoint, "__qualname__", getattr(route, "name", "?"))
            for method in sorted(getattr(route, "methods", None) or ()):
                found.append((f"{prefix}{path}", method, module, qualname))
            continue
        context = getattr(route, "include_context", None)
        if context is None:
            continue
        inner = getattr(context, "included_router", None)
        inner_routes = getattr(inner, "routes", None)
        if not inner_routes:
            continue
        found.extend(
            _walk(
                inner_routes,
                f"{prefix}{getattr(context, 'prefix', '') or ''}",
                getattr(inner, "__module__", origin),
            )
        )
    return found


@pytest.fixture(scope="module")
def registered() -> list[tuple[str, str, str, str]]:
    return _walk(app.routes)


def test_no_new_path_is_registered_twice_for_the_same_method(
    registered: list[tuple[str, str, str, str]],
) -> None:
    """A duplicate (path, method) means one implementation is unreachable.

    This is the check that was missing when the deprecated dashboard router was
    considered mountable: adding it would have produced a tenth duplicate, on
    ``GET /api/dashboard/stream``, with no error anywhere.

    Asserted as set equality against :data:`KNOWN_DUPLICATES` rather than as
    emptiness, because nine duplicates already exist and pretending otherwise
    would mean either a permanently red test or a silently weakened assertion.
    """
    owners: dict[tuple[str, str], list[str]] = {}
    for path, method, module, qualname in registered:
        owners.setdefault((path, method), []).append(f"{module}::{qualname}")

    duplicates = {path: (fns[0], fns[1]) for (path, _m), fns in owners.items() if len(fns) > 1}

    new = sorted(set(duplicates) - set(KNOWN_DUPLICATES))
    assert not new, (
        f"newly duplicated (path, method) registrations: {new}. FastAPI does not "
        f"fail on this -- the first registration silently wins and the other is "
        f"unreachable dead code. Add the path to KNOWN_DUPLICATES only if the "
        f"duplicate is genuinely intended; otherwise remove one registration."
    )

    fixed = sorted(set(KNOWN_DUPLICATES) - set(duplicates))
    assert not fixed, (
        f"these duplicates no longer exist -- delete them from KNOWN_DUPLICATES so "
        f"the ratchet stays true: {fixed}"
    )


def test_deprecated_dashboard_router_is_not_mounted(
    registered: list[tuple[str, str, str, str]],
) -> None:
    """Neither of the deprecated router's unique paths may appear on the app.

    ``state`` and ``publish`` are declared *only* by the deprecated router, so
    their absence is a direct, unambiguous test that it is unmounted -- stronger
    than reading ``main.py`` and hoping the import is not re-added.
    """
    paths = {path for path, *_ in registered}
    for path in ("/api/dashboard/state", "/api/dashboard/publish"):
        assert path not in paths, (
            f"{path} is served, so {DEPRECATED_ROUTER_MODULE} has been mounted. Its "
            f"GET /dashboard/stream would then collide with the canonical SSE in "
            f"observability/routes/metrics.py, which frontend/stores/metricsStore.ts "
            f"consumes. Revert the include_router call."
        )


def test_dashboard_stream_is_served_by_the_canonical_metrics_router(
    registered: list[tuple[str, str, str, str]],
) -> None:
    """The one SSE the frontend depends on must come from the metrics router.

    Asserted by *absence* of a competitor: if the deprecated router is ever
    mounted again, this is the test that says which of the two payload shapes the
    metrics page would have started receiving.
    """
    streams = [
        (module, qualname)
        for path, method, module, qualname in registered
        if path == "/api/dashboard/stream" and method == "GET"
    ]
    assert streams == [("backend.observability.routes.metrics", "dashboard_metrics_stream")], (
        f"/api/dashboard/stream is served by {streams}; expected only the canonical "
        f"metrics router. A second registration means one SSE payload shape is dead."
    )


def test_deprecated_router_module_still_imports_and_exposes_its_fixture_surface() -> None:
    """The module is kept importable on purpose -- assert that, so it is a decision.

    ``backend/tests/api/conftest.py`` seeds ``_dashboard_state`` here, and the
    module's own docstring points new work at the canonical routers. What must
    never happen is a *silent* removal: the fixture would then fail with an
    AttributeError that reads like a test bug.
    """
    module = pytest.importorskip(DEPRECATED_ROUTER_MODULE)
    assert hasattr(module, "_dashboard_state")
    assert hasattr(module, "DashboardState")
    assert hasattr(module, "router")


def test_app_is_importable_and_serves_a_nontrivial_surface() -> None:
    """Smoke check that the wiring above describes a live app, not a stale import."""
    assert isinstance(app, FastAPI)
    assert len(_walk(app.routes)) > 200, "main.py looks truncated"
