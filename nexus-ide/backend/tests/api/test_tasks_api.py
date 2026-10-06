"""Integration tests for tasks API endpoints."""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.orchestrator.main import app


def test_task_routes_require_authentication() -> None:
    """All task dashboard endpoints reject requests without a valid token."""
    anonymous = TestClient(app)

    for path in (
        "/api/tasks/pipeline",
        "/api/tasks/list",
        "/api/tasks/active",
        "/api/tasks/stream",
    ):
        response = anonymous.get(path)
        assert response.status_code == 401, (
            f"GET {path} answered {response.status_code} without a token; expected 401"
        )


def test_usage_detail_routes_require_authentication() -> None:
    """Token usage summaries are private like the rest of dashboard metrics."""
    anonymous = TestClient(app)

    for path in (
        "/api/metrics/usage/summary",
        "/api/metrics/usage/tracker",
    ):
        response = anonymous.get(path)
        assert response.status_code == 401, (
            f"GET {path} answered {response.status_code} without a token; expected 401"
        )


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
    assert "failed" in data
    
    # Verify active tasks structure
    assert isinstance(data["active"], list)
    if data["active"]:
        task = data["active"][0]
        assert "id" in task
        assert "title" in task
        assert "agent" in task
        assert "status" in task


def test_task_list_supports_paging_with_real_group_totals(client):
    from backend.observability.routes.workflows import get_workflow_tracker

    tracker = get_workflow_tracker()
    older = tracker.create_workflow("page-older", "Older task")
    newer = tracker.create_workflow("page-newer", "Newer task")

    first = client.get("/api/tasks/list?limit=1&offset=0")
    second = client.get("/api/tasks/list?limit=1&offset=1")

    assert first.status_code == second.status_code == 200
    first_data = first.json()
    second_data = second.json()
    assert len(first_data["queued"]) == 1
    assert len(second_data["queued"]) == 1
    assert first_data["queued"][0]["id"] == newer.workflow_id
    assert second_data["queued"][0]["id"] == older.workflow_id
    assert first_data["pagination"]["queued"] == {
        "offset": 0,
        "limit": 1,
        "total": 2,
        "has_more": True,
    }
    assert second_data["pagination"]["queued"]["has_more"] is False


def test_task_endpoints_reflect_workflow_tracker(client):
    """Dashboard tasks are sourced from the live workflow tracker."""
    from backend.observability.routes.workflows import get_workflow_tracker

    tracker = get_workflow_tracker()
    running = tracker.create_workflow("story-running", "Build the API")
    tracker.start_workflow(running.workflow_id)
    step = tracker.add_step(running.workflow_id, "implement", "CODER")
    tracker.complete_step(running.workflow_id, step.step_id)

    queued = tracker.create_workflow("story-queued", "Review the docs")
    failed = tracker.create_workflow("story-failed", "Fix the provider")
    tracker.complete_workflow(failed.workflow_id, "failed")

    response = client.get("/api/tasks/list")
    assert response.status_code == 200
    data = response.json()
    assert [task["id"] for task in data["active"]] == [running.workflow_id]
    assert [task["id"] for task in data["queued"]] == [queued.workflow_id]
    assert [task["id"] for task in data["failed"]] == [failed.workflow_id]
    assert data["active"][0]["agent"] == "CODER"
    assert data["active"][0]["progress"] is None

    active_response = client.get("/api/tasks/active")
    assert active_response.status_code == 200
    assert {task["id"] for task in active_response.json()["tasks"]} == {
        running.workflow_id,
        queued.workflow_id,
    }


def test_task_endpoints_include_real_plan_states_and_assigned_steps(client, monkeypatch):
    from backend.orchestrator.dependency_graph import ExecutionPlan, TaskNode, TaskStatus
    from backend.orchestrator.main import app
    from backend.orchestrator.types import OrchestrationState

    plans = []
    states = {}
    approvals = set()
    current_by_session = {}

    for name, agent, plan_status, run_state in [
        ("Review provider", "REVIEWER", TaskStatus.PENDING, OrchestrationState.AWAITING_APPROVAL),
        ("Implement endpoint", "CODER", TaskStatus.RUNNING, OrchestrationState.EXECUTING),
        ("Verify tests", "TESTER", TaskStatus.FAILED, OrchestrationState.FAILED),
        ("Document API", "WRITER", TaskStatus.COMPLETED, OrchestrationState.COMPLETED),
    ]:
        session_id = f"session-{len(plans)}"
        plan = ExecutionPlan.from_steps(
            title=name,
            description=f"Goal: {name}",
            steps=[TaskNode(name=name, description=f"Assigned work: {name}", agent=agent)],
            session_id=session_id,
        )
        plan.created_at = 1_700_000_000 + len(plans)
        plan.approved = run_state != OrchestrationState.AWAITING_APPROVAL
        plan.steps[0].status = plan_status
        plans.append(plan)
        states[session_id] = run_state
        current_by_session[session_id] = plan
        if run_state == OrchestrationState.AWAITING_APPROVAL:
            approvals.add(plan.plan_id)

    class FakePlanEngine:
        def list_plans(self):
            return plans

        def get_state(self, session_id):
            return states[session_id]

        def get_plan_by_session(self, session_id):
            return current_by_session[session_id]

        def request_approval(self, plan_id):
            return object() if plan_id in approvals else None

    monkeypatch.setattr(app.state, "orchestration_engine", FakePlanEngine(), raising=False)

    data = client.get("/api/tasks/list").json()
    assert data["queued"][0]["status"] == "awaiting_approval"
    assert data["queued"][0]["approval_status"] == "awaiting_approval"
    assert data["queued"][0]["progress"] is None
    assert data["queued"][0]["steps"][0]["agent"] == "REVIEWER"
    assert data["active"][0]["status"] == "running"
    assert data["active"][0]["steps"][0]["status"] == "running"
    assert data["failed"][0]["status"] == "failed"
    assert data["completed"][0]["status"] == "completed"
    assert data["completed"][0]["created_at"] == "2023-11-14T22:13:23+00:00"

    active = client.get("/api/tasks/active").json()["tasks"]
    assert {item["id"] for item in active} == {plans[0].plan_id, plans[1].plan_id}


def test_task_list_keeps_available_plans_when_workflow_source_fails(client, monkeypatch):
    from types import SimpleNamespace

    from backend.orchestrator.dependency_graph import ExecutionPlan, TaskNode
    from backend.orchestrator.main import app

    plan = ExecutionPlan.from_steps(
        title="Review the release",
        description="Inspect release changes",
        steps=[TaskNode(name="Inspect release", agent="REVIEWER")],
        session_id="release-session",
    )

    class PlanEngine:
        def list_plans(self):
            return [plan]

        def get_state(self, _session_id):
            return "awaiting_approval"

        def get_plan_by_session(self, _session_id):
            return plan

        def request_approval(self, _plan_id):
            return SimpleNamespace()

    monkeypatch.setattr(app.state, "orchestration_engine", PlanEngine(), raising=False)

    def tracker_unavailable():
        raise RuntimeError("tracker stopped")

    monkeypatch.setattr("backend.observability.routes.workflows.get_workflow_tracker", tracker_unavailable)
    response = client.get("/api/tasks/list")

    assert response.status_code == 200
    data = response.json()
    assert data["queued"][0]["id"] == plan.plan_id
    assert data["sources"]["workflows"]["available"] is False
    assert data["sources"]["plans"]["available"] is True
    assert data["warnings"]


def test_task_list_keeps_workflows_when_plan_source_fails(client, monkeypatch):
    from backend.observability.routes.workflows import get_workflow_tracker
    from backend.orchestrator.main import app

    workflow = get_workflow_tracker().create_workflow("story-preserved", "Keep workflow visible")

    class BrokenPlanEngine:
        def list_plans(self):
            raise RuntimeError("plan cache unavailable")

    monkeypatch.setattr(app.state, "orchestration_engine", BrokenPlanEngine(), raising=False)
    response = client.get("/api/tasks/list")

    assert response.status_code == 200
    data = response.json()
    assert data["queued"][0]["id"] == workflow.workflow_id
    assert data["sources"]["workflows"]["available"] is True
    assert data["sources"]["plans"]["available"] is False
    assert data["warnings"]


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


def test_get_current_mission_endpoint_is_mounted(client, monkeypatch):
    """The dashboard's Mission Control card must reach the real router."""
    from backend.orchestrator.routes import mission

    monkeypatch.setattr(mission, "current_tracker", lambda: None)
    response = client.get("/api/mission/current")

    assert response.status_code == 200
    assert response.json() == {"active": False, "mission": None}
