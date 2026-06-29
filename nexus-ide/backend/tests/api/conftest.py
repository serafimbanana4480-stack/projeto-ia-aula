"""Fixtures for API integration tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.orchestrator.main import app
from backend.observability.routes.workflows import init_workflow_tracker
from backend.observability.dashboard_state import DashboardState
from backend.observability.event_bus import EventBus


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    # Initialize workflow tracker for tests
    init_workflow_tracker()

    # Initialize dashboard state with an in-memory EventBus (no Redis/Ollama needed)
    import backend.observability.routes.dashboard as dashboard_routes
    dashboard_state = DashboardState(event_bus=EventBus())
    dashboard_routes._dashboard_state = dashboard_state

    # Disable auth for tests so TestClient requests don't need Bearer tokens
    app.state.auth_disabled = True
    return TestClient(app)


@pytest.fixture
def test_app():
    """Get the FastAPI app instance."""
    return app
