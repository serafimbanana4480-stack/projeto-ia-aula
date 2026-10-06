"""Integration tests for workflows API endpoints.

Every test here previously began with

    if response.status_code == 500:
        pytest.skip("Workflow tracker not initialized")

A 500 is a server-side defect, not an uninitialised optional subsystem, so the
skip is gone: the status is asserted. ``GET /api/workflows`` and
``GET /api/workflows/active`` are both registered (``main.py:799`` includes
``backend.observability.routes.workflows`` under the ``/api`` prefix), so these
tests exercise real routes and a 500 is a genuine regression.

LOUD NOTE: these tests were dormant -- the skip fired before any assertion, so
the tracker path was never actually verified. They may well fail on first run
now that the assertions are reachable. Any failure here is a real pre-existing
bug in the workflow tracker, not a test defect; fix the route, do not re-add a
skip.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.orchestrator.main import app
from backend.tests.conftest import registered_route_paths


def _assert_route_exists(path: str) -> None:
    paths = registered_route_paths(app)
    assert path in paths, (
        f"GET {path} is not registered on the app, so this test can never pass. "
        f"Workflow paths currently registered: "
        f"{sorted(p for p in paths if 'workflow' in p)}"
    )


def test_list_workflows(client: TestClient) -> None:
    """Test GET /api/workflows endpoint."""
    _assert_route_exists("/api/workflows")

    response = client.get("/api/workflows")

    assert response.status_code == 200, response.text
    data = response.json()

    assert isinstance(data, list)


def test_list_workflows_with_status(client: TestClient) -> None:
    """Test GET /api/workflows with status filter."""
    _assert_route_exists("/api/workflows")

    response = client.get("/api/workflows?status=active")

    assert response.status_code == 200, response.text
    data = response.json()

    assert isinstance(data, list)


def test_list_workflows_with_limit(client: TestClient) -> None:
    """Test GET /api/workflows with limit parameter."""
    _assert_route_exists("/api/workflows")

    response = client.get("/api/workflows?limit=10")

    assert response.status_code == 200, response.text
    data = response.json()

    assert isinstance(data, list)
    assert len(data) <= 10


def test_list_active_workflows(client: TestClient) -> None:
    """Test GET /api/workflows/active endpoint."""
    _assert_route_exists("/api/workflows/active")

    response = client.get("/api/workflows/active")

    assert response.status_code == 200, response.text
    data = response.json()

    # The route declares response_model=list[WorkflowInfo], so an error dict
    # here would itself be the bug. Previously this branch silently returned.
    assert isinstance(data, list), f"expected a list, got {type(data).__name__}: {data!r}"

    if data:
        workflow = data[0]
        for field in ("workflow_id", "story_id", "goal", "status", "start_time", "steps"):
            assert field in workflow, f"{field!r} missing from workflow payload: {workflow!r}"
