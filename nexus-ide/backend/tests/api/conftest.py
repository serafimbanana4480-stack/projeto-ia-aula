"""Fixtures for API integration tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.middleware.auth import create_access_token
from backend.observability.dashboard_state import DashboardState
from backend.observability.event_bus import EventBus
from backend.observability.routes.workflows import init_workflow_tracker
from backend.orchestrator.main import app


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    # Initialize workflow tracker for tests
    init_workflow_tracker()

    # Initialize dashboard state with an in-memory EventBus (no Redis/Ollama needed)
    import backend.observability.routes.dashboard as dashboard_routes
    dashboard_state = DashboardState(event_bus=EventBus())
    dashboard_routes._dashboard_state = dashboard_state

    # Exercise the real authentication dependency with a signed local token;
    # toggling arbitrary app state no longer bypasses auth (and should not).
    token = create_access_token({"sub": "api-test", "email": "api@test.local"})
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def test_app():
    """Get the FastAPI app instance."""
    return app
