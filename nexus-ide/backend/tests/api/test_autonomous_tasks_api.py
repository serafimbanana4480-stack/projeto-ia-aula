"""API integration tests for the autonomous tasks endpoints (P0.4).

These exercise the real router mounted in the FastAPI app. The scheduler/task
manager is a lifespan-owned singleton; tests install a controlled instance on
``app.state.task_manager`` (which the routes now read) so they can assert
against real task states without depending on background-service toggles.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.middleware.auth import create_access_token
from backend.observability.event_system import EventBus
from backend.orchestrator.main import app
from backend.persistence.db import load_scheduled_tasks
from backend.tasks.autonomous_tasks import (
    AutonomousTaskManager,
    Task,
    TaskStatus,
    TaskType,
)


@pytest.fixture
def auth_client(monkeypatch) -> TestClient:
    """A TestClient with a valid token, independent of the background stack."""
    token = create_access_token({"sub": "api-test", "email": "api@test.local"})
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _install_task_manager(monkeypatch, manager: AutonomousTaskManager) -> AutonomousTaskManager:
    monkeypatch.setattr(app.state, "task_manager", manager, raising=False)
    return manager


async def _wait_until(predicate, *, timeout: float = 5.0, step: float = 0.02) -> bool:
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        await asyncio.sleep(step)
        waited += step
    return predicate()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_task_routes_require_authentication() -> None:
    anonymous = TestClient(app)
    for path in ("/api/tasks", "/api/tasks/running", "/api/tasks/stats", "/api/tasks/types"):
        response = anonymous.get(path)
        assert response.status_code == 401, f"GET {path} -> {response.status_code}"


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


def test_create_task_with_valid_handler(auth_client, monkeypatch) -> None:
    _install_task_manager(monkeypatch, AutonomousTaskManager(EventBus()))
    response = auth_client.post(
        "/api/tasks",
        json={
            "name": "manual health",
            "task_type": "health_check",
            "handler_name": "health_monitoring",
            "parameters": {},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "scheduled"
    task_id = body["task_id"]

    fetch = auth_client.get(f"/api/tasks/{task_id}")
    assert fetch.status_code == 200
    assert fetch.json()["task"]["name"] == "manual health"


def test_create_task_with_invalid_handler_lists_available(auth_client, monkeypatch) -> None:
    _install_task_manager(monkeypatch, AutonomousTaskManager(EventBus()))
    response = auth_client.post(
        "/api/tasks",
        json={"name": "nope", "task_type": "monitoring", "handler_name": "does_not_exist"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "does_not_exist" in detail
    assert "health_monitoring" in detail  # the available-handler list is surfaced


def test_create_task_with_invalid_task_type_is_400(auth_client, monkeypatch) -> None:
    _install_task_manager(monkeypatch, AutonomousTaskManager(EventBus()))
    response = auth_client.post(
        "/api/tasks",
        json={"name": "x", "task_type": "not_a_type", "handler_name": "health_monitoring"},
    )
    assert response.status_code == 400
    assert "task_type" in response.json()["detail"]


def test_create_task_with_invalid_priority_is_400(auth_client, monkeypatch) -> None:
    _install_task_manager(monkeypatch, AutonomousTaskManager(EventBus()))
    response = auth_client.post(
        "/api/tasks",
        json={
            "name": "x",
            "task_type": "monitoring",
            "priority": "whenever",
            "handler_name": "health_monitoring",
        },
    )
    assert response.status_code == 400
    assert "priority" in response.json()["detail"]


def test_create_task_with_invalid_scheduled_at_is_400(auth_client, monkeypatch) -> None:
    _install_task_manager(monkeypatch, AutonomousTaskManager(EventBus()))
    response = auth_client.post(
        "/api/tasks",
        json={
            "name": "x",
            "task_type": "monitoring",
            "handler_name": "health_monitoring",
            "scheduled_at": "not-a-timestamp",
        },
    )
    assert response.status_code == 400
    assert "scheduled_at" in response.json()["detail"]


def test_status_filter_accepts_only_real_states(auth_client, monkeypatch) -> None:
    manager = _install_task_manager(monkeypatch, AutonomousTaskManager(EventBus()))
    task = Task(name="real", task_type=TaskType.MONITORING, status=TaskStatus.RUNNING)
    manager.scheduler.tasks[task.task_id] = task
    manager.scheduler.running_tasks[task.task_id] = task

    assert _ids(auth_client.get("/api/tasks/running")) == {task.task_id}
    # An unknown status is not an error: it simply matches nothing.
    assert _ids(auth_client.get("/api/tasks/completed")) == set()
    assert _ids(auth_client.get("/api/tasks/failed")) == set()
    assert task.task_id in _ids(auth_client.get("/api/tasks"))


# ---------------------------------------------------------------------------
# Real-state reads
# ---------------------------------------------------------------------------


def test_state_endpoints_reflect_real_states(auth_client, monkeypatch) -> None:
    manager = _install_task_manager(monkeypatch, AutonomousTaskManager(EventBus()))
    scheduler = manager.scheduler

    completed = Task(name="done", task_type=TaskType.CLEANUP, status=TaskStatus.COMPLETED)
    failed = Task(name="broken", task_type=TaskType.CLEANUP, status=TaskStatus.FAILED, error="x")
    running = Task(name="busy", task_type=TaskType.MONITORING, status=TaskStatus.RUNNING)
    for task in (completed, failed, running):
        scheduler.tasks[task.task_id] = task
    scheduler.running_tasks[running.task_id] = running

    completed_ids = _ids(auth_client.get("/api/tasks/completed"))
    failed_ids = _ids(auth_client.get("/api/tasks/failed"))
    running_ids = _ids(auth_client.get("/api/tasks/running"))

    assert completed.task_id in completed_ids
    assert failed.task_id in failed_ids
    assert running.task_id in running_ids
    # No cross-contamination between distinct states.
    assert running.task_id not in completed_ids
    assert running.task_id not in failed_ids
    assert failed.task_id not in completed_ids


def test_routes_read_the_lifespan_owned_manager(auth_client, monkeypatch) -> None:
    """The routes act on ``app.state.task_manager``, not a process singleton."""
    first = _install_task_manager(monkeypatch, AutonomousTaskManager(EventBus()))
    first_task = Task(name="from-first-manager", task_type=TaskType.MONITORING)
    first.scheduler.tasks[first_task.task_id] = first_task

    second = _install_task_manager(monkeypatch, AutonomousTaskManager(EventBus()))
    second_task = Task(name="from-second-manager", task_type=TaskType.MONITORING)
    second.scheduler.tasks[second_task.task_id] = second_task

    listed = _ids(auth_client.get("/api/tasks"))
    assert second_task.task_id in listed
    assert first_task.task_id not in listed, "stale manager must not be served"

    single = auth_client.get(f"/api/tasks/{second_task.task_id}")
    assert single.status_code == 200
    assert single.json()["task"]["name"] == "from-second-manager"
    assert auth_client.get(f"/api/tasks/{first_task.task_id}").status_code == 404


def test_handlers_endpoint_lists_registered_names(auth_client, monkeypatch) -> None:
    _install_task_manager(monkeypatch, AutonomousTaskManager(EventBus()))
    response = auth_client.get("/api/tasks/handlers")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "health_monitoring" in body["handlers"]
    assert "system_cleanup" in body["handlers"]
    assert set(body["primary"]) <= set(body["handlers"])


def test_requeue_endpoint_approves_a_quarantined_task(auth_client, monkeypatch) -> None:
    manager = _install_task_manager(monkeypatch, AutonomousTaskManager(EventBus()))
    task = Task(
        name="quarantined",
        task_type=TaskType.MONITORING,
        handler_name="health_monitoring",
        status=TaskStatus.WAITING,
    )
    manager.scheduler.tasks[task.task_id] = task
    manager.scheduler._quarantined.add(task.task_id)

    response = auth_client.post(f"/api/tasks/{task.task_id}/requeue")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "requeued"

    fetch = auth_client.get(f"/api/tasks/{task.task_id}").json()["task"]
    assert fetch["status"] == "pending"
    assert fetch["handler"] == "health_monitoring"


def test_requeue_endpoint_rejects_unregistered_handler(auth_client, monkeypatch) -> None:
    manager = _install_task_manager(monkeypatch, AutonomousTaskManager(EventBus()))
    task = Task(name="ghost", handler_name="ghost_handler", status=TaskStatus.WAITING)
    manager.scheduler.tasks[task.task_id] = task

    response = auth_client.post(f"/api/tasks/{task.task_id}/requeue")
    assert response.status_code == 400
    assert "not registered" in response.json()["detail"]


def test_requeue_endpoint_404_for_unknown_task(auth_client, monkeypatch) -> None:
    _install_task_manager(monkeypatch, AutonomousTaskManager(EventBus()))
    assert auth_client.post("/api/tasks/task-nope/requeue").status_code == 404


def test_cancel_endpoint_cancels_a_running_task(auth_client, monkeypatch) -> None:
    manager = _install_task_manager(monkeypatch, AutonomousTaskManager(EventBus()))
    task = Task(
        name="bye",
        task_type=TaskType.MONITORING,
        handler_name="health_monitoring",
        status=TaskStatus.RUNNING,
    )
    manager.scheduler.tasks[task.task_id] = task
    manager.scheduler.running_tasks[task.task_id] = task

    response = auth_client.post(f"/api/tasks/{task.task_id}/cancel")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert task.status == TaskStatus.CANCELLED
    assert task.task_id not in manager.scheduler.running_tasks

    fetched = auth_client.get(f"/api/tasks/{task.task_id}")
    assert fetched.status_code == 200
    assert fetched.json()["task"]["status"] == "cancelled"

    # The row is gone from the DB, so a restart cannot resurrect it.
    assert [r for r in load_scheduled_tasks(source="custom") if r["id"] == task.task_id] == []
    assert auth_client.post("/api/tasks/task-nope/cancel").status_code == 404


def _ids(response) -> set[str]:
    assert response.status_code == 200, response.text
    return {t["task_id"] for t in response.json()["tasks"]}


# ---------------------------------------------------------------------------
# Restart / resume across a fresh instance (NEXUS_TASKS_RESUME_PENDING=true)
# ---------------------------------------------------------------------------


def test_pending_task_survives_restart_and_executes(auth_client, monkeypatch) -> None:
    calls: list[int] = []

    async def probe(**_kwargs) -> dict[str, bool]:
        calls.append(1)
        return {"ok": True}

    # 1) First instance schedules a pending task (persisted to the DB).
    first = AutonomousTaskManager(EventBus())
    first.handlers.register("probe", probe, read_only=False)
    task_id = asyncio.run(
        first.create_custom_task(
            name="survive-restart", task_type=TaskType.MONITORING, handler_name="probe"
        )
    )
    # 2) Shut it down (as an OS restart would).
    asyncio.run(first.stop())

    # 3) A brand-new instance resumes and executes it (opt-in via the flag).
    second = AutonomousTaskManager(EventBus())
    second.handlers.register("probe", probe, read_only=False)

    async def drive() -> None:
        await second.start(resume_pending=True)
        assert await _wait_until(
            lambda: _status(second, task_id) == TaskStatus.COMPLETED
        )
        await second.stop()

    asyncio.run(drive())

    assert calls == [1]
    task = asyncio.run(second.get_task(task_id))
    assert task is not None and task.status == TaskStatus.COMPLETED


def test_scheduled_for_future_is_reported(auth_client, monkeypatch) -> None:
    _install_task_manager(monkeypatch, AutonomousTaskManager(EventBus()))
    future = (datetime.now() + timedelta(hours=2)).isoformat()
    response = auth_client.post(
        "/api/tasks",
        json={
            "name": "later",
            "task_type": "maintenance",
            "handler_name": "system_cleanup",
            "scheduled_at": future,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scheduled_for"] is not None

    task_id = body["task_id"]
    fetched = auth_client.get(f"/api/tasks/{task_id}").json()["task"]
    assert fetched["status"] == "scheduled"


def _status(manager: AutonomousTaskManager, task_id: str) -> TaskStatus | None:
    task = manager.scheduler.tasks.get(task_id)
    return task.status if task is not None else None
