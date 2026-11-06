"""Cross-tenant isolation: every telemetry and file surface is scoped.

The gap this closes
-------------------
The audit found a freshly registered user receiving a **byte-identical**
body to the administrator's from the telemetry endpoints: the structured log
buffer, the guardian log view, the cost ledger and the analytics usage
summary all answered with *every tenant's* data — ``session_id``,
``correlation_id``, agent names, LLM internals, token spend and cost.

The pattern behind it: those surfaces are process-wide.  The log buffer is a
ring buffer shared by every session, the cost ledger is a table shared by
every session, and the usage summary aggregated the whole table.  ``require_auth``
answers "is this a registered user"; it does not answer "is this *your* data".

Every surface below is now scoped to the caller, and the same file pins the
two rules that make a mission and a file path safe to hand out: a mission
belongs to the user who created it, and a file operation stays inside the
project the server resolved.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.middleware.auth import create_access_token
from backend.observability.advanced_logging import get_structured_logger
from backend.orchestrator.main import app
from backend.persistence.db import add_message, create_project, create_session
from backend.tools.registry import ToolSpec, _registry, register_tool

pytestmark = pytest.mark.contract


def _token(user_id: str) -> str:
    """A signed access token for *user_id*."""
    return create_access_token({"sub": user_id, "email": f"{user_id}@test.local"})


def _client(user_id: str) -> TestClient:
    """A client authenticated as *user_id*."""
    return TestClient(app, headers={"Authorization": f"Bearer {_token(user_id)}"})


def _body(response: Any) -> str:
    """The response body as text (whatever shape it has)."""
    try:
        return json.dumps(response.json())
    except Exception:
        return response.text


# ---------------------------------------------------------------------------
# Structured logs
# ---------------------------------------------------------------------------


def test_logs_are_scoped_to_the_caller() -> None:
    """``/api/logs`` shows the caller's own entries and nobody else's."""
    owner = "tenant-logs-owner"
    other = "tenant-logs-other"
    owner_session = create_session(session_id="sess-logs-owner", user_id=owner)["id"]
    other_session = create_session(session_id="sess-logs-other", user_id=other)["id"]

    marker = "LOGS-OWNER-SECRET-MARKER"
    slog = get_structured_logger()
    slog.info(marker, session_id=owner_session, agent="CODER")
    slog.info("other tenant chatter", session_id=other_session, agent="ROUTER")

    seen_by_other = _body(_client(other).get("/api/logs"))
    assert marker not in seen_by_other, (
        "the log buffer is process-wide; the entry of another tenant was served"
    )
    assert "other tenant chatter" in seen_by_other, (
        "the caller must still see their own entries"
    )

    seen_by_owner = _body(_client(owner).get("/api/logs"))
    assert marker in seen_by_owner, "the owner must see their own entries"

    # The aggregate is scoped the same way.
    stats = _client(other).get("/api/logs/stats").json()
    assert stats.get("total", 0) < 2 or all(
        entry.get("session_id") == other_session
        for entry in _client(other).get("/api/logs").json()["logs"]
    )


def test_guardian_logs_are_scoped_to_the_caller() -> None:
    """``/api/guardian/logs`` shows the caller's own entries only."""
    owner = "tenant-guardian-owner"
    other = "tenant-guardian-other"
    owner_session = create_session(session_id="sess-guardian-owner", user_id=owner)["id"]
    other_session = create_session(session_id="sess-guardian-other", user_id=other)["id"]

    marker = "GUARDIAN-OWNER-SECRET-MARKER"
    slog = get_structured_logger()
    slog.info(marker, session_id=owner_session, agent="GUARDIAN")
    slog.info("other tenant guardian chatter", session_id=other_session, agent="GUARDIAN")

    seen_by_other = _body(_client(other).get("/api/guardian/logs"))
    assert marker not in seen_by_other
    assert "other tenant guardian chatter" in seen_by_other

    seen_by_owner = _body(_client(owner).get("/api/guardian/logs"))
    assert marker in seen_by_owner


# ---------------------------------------------------------------------------
# Cost ledger
# ---------------------------------------------------------------------------


def test_costs_ledger_is_scoped_to_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/api/metrics/costs/ledger`` lists the caller's own billed calls."""
    from backend.observability.routes import costs as costs_module
    from backend.persistence import db as persistence_db

    # The costs router binds DB_PATH at import time; point it at the
    # per-test database so the test never touches the developer's data.
    monkeypatch.setattr(costs_module, "DB_PATH", persistence_db.DB_PATH)

    owner = "tenant-costs-owner"
    other = "tenant-costs-other"
    owner_session = create_session(session_id="sess-costs-owner", user_id=owner)["id"]
    other_session = create_session(session_id="sess-costs-other", user_id=other)["id"]

    from backend.persistence.db import get_db

    with get_db() as conn:
        conn.execute(
            "INSERT INTO usage_ledger (ts, day, provider, model, input_tokens, "
            "output_tokens, cost_usd, session_id, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-01-01T00:00:00Z",
                "2026-01-01",
                "openai",
                "gpt-test",
                10,
                20,
                0.5,
                owner_session,
                "run-owner",
            ),
        )
        conn.execute(
            "INSERT INTO usage_ledger (ts, day, provider, model, input_tokens, "
            "output_tokens, cost_usd, session_id, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-01-01T00:00:00Z",
                "2026-01-01",
                "openai",
                "gpt-test",
                1,
                2,
                0.1,
                other_session,
                "run-other",
            ),
        )

    seen_by_other = _body(_client(other).get("/api/metrics/costs/ledger"))
    assert owner_session not in seen_by_other, (
        "the cost ledger is shared by every session; another tenant's row was served"
    )
    assert "run-owner" not in seen_by_other
    assert "run-other" in seen_by_other, "the caller must still see their own rows"

    seen_by_owner = _body(_client(owner).get("/api/metrics/costs/ledger"))
    assert "run-owner" in seen_by_owner
    assert "run-other" not in seen_by_owner


# ---------------------------------------------------------------------------
# Analytics usage summary
# ---------------------------------------------------------------------------


def test_analytics_usage_is_scoped_to_the_caller() -> None:
    """``/api/analytics/usage/summary`` counts the caller's own messages."""
    owner = "tenant-analytics-owner"
    other = "tenant-analytics-other"
    owner_session = create_session(session_id="sess-analytics-owner", user_id=owner)["id"]
    other_session = create_session(session_id="sess-analytics-other", user_id=other)["id"]

    for _ in range(3):
        add_message(owner_session, "user", "owner message", tokens_in=5, tokens_out=7, cost_usd=0.25)
    add_message(other_session, "user", "other message", tokens_in=1, tokens_out=1, cost_usd=0.5)

    owner_summary = _client(owner).get("/api/analytics/usage/summary").json()
    other_summary = _client(other).get("/api/analytics/usage/summary").json()

    assert owner_summary["total_messages"] == 3
    assert owner_summary["total_tokens"] == 36
    assert owner_summary["total_conversations"] == 1
    assert other_summary["total_messages"] == 1
    assert other_summary["total_tokens"] == 2
    assert other_summary["total_conversations"] == 1

    assert owner_summary != other_summary, (
        "the usage summary is a global aggregate; it answered the same numbers "
        "for two different tenants"
    )


# ---------------------------------------------------------------------------
# Mission ownership
# ---------------------------------------------------------------------------


def test_mission_websocket_refuses_another_users_mission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A handshake on somebody else's mission is refused, not served."""
    from backend.orchestrator.meta import MetaOrchestrator, Mission

    owner = "tenant-mission-owner"
    other = "tenant-mission-other"

    mission = Mission(objective="owner secret objective", metadata={"user_id": owner})
    # The mission store is private to the orchestrator; the test injects the
    # mission directly because creating one for real would start the mission
    # (and its LLM calls) as a side effect of a test.
    meta = MetaOrchestrator(engine=None, event_bus=None, llm_client=None, registry={})
    meta._missions[mission.id] = mission
    monkeypatch.setattr(app.state, "meta_orchestrator", meta, raising=False)

    client = _client(other)
    with (
        pytest.raises(WebSocketDisconnect) as excinfo,
        client.websocket_connect(f"/ws/missions/{mission.id}?token={_token(other)}") as ws,
    ):
        ws.receive_text()
    assert excinfo.value.code == 4403, (
        "a handshake for another tenant's mission must be closed with 4403 "
        f"(forbidden), not {excinfo.value.code}"
    )

    # The REST surface is scoped the same way: the mission is not found for
    # anybody but its owner.
    response = _client(other).get(f"/api/missions/{mission.id}")
    assert response.status_code == 404
    assert "owner secret objective" not in response.text

    assert _client(owner).get(f"/api/missions/{mission.id}").status_code == 200


# ---------------------------------------------------------------------------
# The files API and the project boundary
# ---------------------------------------------------------------------------


def test_files_api_rejects_a_client_supplied_project_path(tmp_path: Path) -> None:
    """The request may not point the API at a directory of its choosing."""
    outside = tmp_path / "not-a-project"
    outside.mkdir()
    (outside / "secret.txt").write_text("CLIENT-CHOOSES-ROOT", encoding="utf-8")

    response = _client("tenant-files").post(
        "/api/files/read",
        json={"path": "secret.txt", "project_path": str(outside)},
    )

    assert response.status_code == 400, (
        "a project_path that names no known project must be refused; the client "
        "cannot choose the filesystem root"
    )
    assert "CLIENT-CHOOSES-ROOT" not in response.text


def test_files_api_respects_the_project_boundary(tmp_path: Path) -> None:
    """Every path the request touches has to resolve inside the project."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "inside.txt").write_text("inside content", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("OUTSIDE-THE-PROJECT", encoding="utf-8")

    project_path = str(project.resolve())
    create_project(name="boundary probe", path=project_path)
    client = _client("tenant-files-boundary")

    # Inside the project: served.
    inside = client.post(
        "/api/files/read",
        json={"path": "inside.txt", "project_path": project_path},
    )
    assert inside.status_code == 200
    assert inside.json()["content"] == "inside content"

    # An absolute path outside the project: refused.
    absolute = client.post(
        "/api/files/read",
        json={"path": str(outside / "secret.txt"), "project_path": project_path},
    )
    assert "error" in absolute.json()
    assert "OUTSIDE-THE-PROJECT" not in absolute.text

    # A traversal out of the project: refused.
    traversal = client.post(
        "/api/files/read",
        json={"path": "../outside/secret.txt", "project_path": project_path},
    )
    assert "error" in traversal.json()
    assert "OUTSIDE-THE-PROJECT" not in traversal.text

    # A write outside the project: refused, and nothing was written.
    written = client.post(
        "/api/files/write",
        json={
            "path": str(outside / "written.txt"),
            "content": "should not exist",
            "project_path": project_path,
        },
    )
    assert "error" in written.json()
    assert not (outside / "written.txt").exists()


# ---------------------------------------------------------------------------
# The tool execution endpoint
# ---------------------------------------------------------------------------

#: A probe tool with an observable side effect, used to prove whether the
#: endpoint actually executed anything.
PROBE_TOOL = "tenant_isolation_probe"

#: A second probe that the registry does *not* gate: the shape of the
#: code-execution tools, which the registry runs straight away.
UNGATED_PROBE_TOOL = "tenant_isolation_ungated_probe"


@pytest.fixture
def probe_tool(monkeypatch: pytest.MonkeyPatch):
    """Register the probe tools and yield the list of calls they received."""
    before = _registry.copy()
    calls: list[dict] = []

    async def handler(**kwargs: Any) -> dict:
        calls.append(kwargs)
        return {"content": "probe ran"}

    register_tool(
        ToolSpec(
            name=PROBE_TOOL,
            description="probe",
            handler=handler,
            requires_confirmation=True,
        )
    )
    register_tool(
        ToolSpec(
            name=UNGATED_PROBE_TOOL,
            description="probe",
            handler=handler,
        )
    )
    # The tool-result cache would answer from a previous call instead of
    # reaching the handler.
    monkeypatch.setattr("backend.tools.registry._HAVE_TOOL_CACHE", False)
    try:
        yield calls
    finally:
        _registry.clear()
        _registry.update(before)


def test_tool_execute_cannot_self_approve(probe_tool: list[dict]) -> None:
    """A client cannot approve its own tool call."""
    session = create_session(session_id="sess-tool-self-approve", user_id="tenant-tool")["id"]

    response = _client("tenant-tool").post(
        "/api/tools/execute",
        json={
            "tool_name": PROBE_TOOL,
            "args": {"value": 1},
            "session_id": session,
            "confirmed": True,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("ok") is not True, "the tool ran on the client's own say-so"
    assert body.get("confirmation_required") is True
    assert body.get("confirmation_id"), "the caller was not offered the approval flow"
    assert probe_tool == [], "the tool ran even though nobody approved the call"


async def test_tool_execute_requires_a_real_confirmation(probe_tool: list[dict]) -> None:
    """Only a confirmation the backend issued and a human approved opens the gate."""
    from backend.tools.confirmations import create_confirmation, resolve_confirmation

    user_id = "tenant-tool-confirm"
    session = create_session(session_id="sess-tool-confirm", user_id=user_id)["id"]
    args = {"value": 1}
    client = _client(user_id)

    # 1. A tool the registry does not gate would run straight away, so it is
    #    refused without an approval.
    ungated = client.post(
        "/api/tools/execute",
        json={
            "tool_name": UNGATED_PROBE_TOOL,
            "args": args,
            "session_id": session,
        },
    )
    assert ungated.status_code == 403
    assert probe_tool == []

    # 2. A made-up confirmation id: refused, and nothing ran.
    forged = client.post(
        "/api/tools/execute",
        json={
            "tool_name": UNGATED_PROBE_TOOL,
            "args": args,
            "session_id": session,
            "confirmation_id": "confirm-forged-by-the-caller",
        },
    )
    assert forged.status_code == 409
    assert probe_tool == []

    # 3. A confirmation the backend issued and the user approved: the tool runs.
    confirmation_id = await create_confirmation(
        session,
        PROBE_TOOL,
        args,
        retry_enabled=True,
        user_id=user_id,
    )
    assert await resolve_confirmation(confirmation_id, True) is True

    approved = client.post(
        "/api/tools/execute",
        json={
            "tool_name": PROBE_TOOL,
            "args": args,
            "session_id": session,
            "confirmation_id": confirmation_id,
        },
    )
    assert approved.status_code == 200
    assert len(probe_tool) == 1, "the approved call did not reach the tool"

    # 4. The approval is consumed: the same confirmation cannot be replayed.
    replayed = client.post(
        "/api/tools/execute",
        json={
            "tool_name": PROBE_TOOL,
            "args": args,
            "session_id": session,
            "confirmation_id": confirmation_id,
        },
    )
    assert replayed.status_code == 409
    assert len(probe_tool) == 1
