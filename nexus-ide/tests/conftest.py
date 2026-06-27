"""Test configuration and fixtures."""
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    """Create test client."""
    from backend.orchestrator.main import app
    return TestClient(app)
