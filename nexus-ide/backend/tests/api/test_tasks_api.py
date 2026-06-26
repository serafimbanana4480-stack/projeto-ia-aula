"""Integration tests for tasks API endpoints."""
from __future__ import annotations


def test_get_task_pipeline(client):
    """Test GET /api/tasks/pipeline endpoint."""
    response = client.get("/api/tasks/pipeline")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert "phases" in data
    assert "active_runs" in data
    
    # Verify phases structure
    assert isinstance(data["phases"], list)
    if data["phases"]:
        phase = data["phases"][0]
        assert "name" in phase
        assert "status" in phase
        assert "count" in phase


def test_get_tasks_list(client):
    """Test GET /api/tasks/list endpoint."""
    response = client.get("/api/tasks/list")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert "active" in data
    assert "queued" in data
    assert "completed" in data
    
    # Verify active tasks structure
    assert isinstance(data["active"], list)
    if data["active"]:
        task = data["active"][0]
        assert "id" in task
        assert "title" in task
        assert "agent" in task
        assert "status" in task


def test_get_active_tasks(client):
    """Test GET /api/tasks/active endpoint."""
    response = client.get("/api/tasks/active")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert "tasks" in data
    
    # Verify active tasks structure
    assert isinstance(data["tasks"], list)
    if data["tasks"]:
        task = data["tasks"][0]
        assert "id" in task
        assert "title" in task
        assert "agent" in task
        assert "status" in task
        assert "progress" in task
        assert "created_at" in task
