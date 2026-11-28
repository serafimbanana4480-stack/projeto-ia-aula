"""Contract tests for the public SWARM request models."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from backend.middleware.auth import create_access_token
from backend.orchestrator.main import app
from backend.persistence.db import close_pool, init_db
from backend.swarm.api import routes
from backend.swarm.api.routes import SwarmRunBody
from backend.swarm.core.types import AgentRole, OperationalMode, SwarmStrategy


def test_run_body_accepts_legacy_uppercase_agent_names() -> None:
    """Regression test for the payload that previously returned HTTP 422."""
    body = SwarmRunBody.model_validate(
        {
            "objective": "Audit and optimise the SWARM implementation",
            "mode": "INVESTIGATION",
            "strategy": "ADAPTIVE",
            "agents": [
                "RESEARCHER",
                "ARCHITECT",
                "ANALYZER",
                "OPTIMIZER",
                "REVIEWER",
            ],
        }
    )

    assert body.mode is OperationalMode.INVESTIGATION
    assert body.strategy is SwarmStrategy.ADAPTIVE
    assert body.agents == [
        AgentRole.RESEARCHER,
        AgentRole.ARCHITECT,
        AgentRole.INVESTIGATOR,
        AgentRole.IMPLEMENTER,
        AgentRole.REVIEWER,
    ]


def test_run_body_deduplicates_aliases_without_reordering_roles() -> None:
    body = SwarmRunBody.model_validate(
        {
            "objective": "Implement the approved proposal",
            "agents": ["CODER", "implementer", "ANALYZER", "investigator"],
        }
    )

    assert body.agents == [AgentRole.IMPLEMENTER, AgentRole.INVESTIGATOR]


def test_run_body_rejects_unknown_agents_with_actionable_message() -> None:
    with pytest.raises(ValidationError) as exc_info:
        SwarmRunBody.model_validate(
            {
                "objective": "Run a task",
                "agents": ["NOT_A_REAL_AGENT"],
            }
        )

    message = str(exc_info.value)
    assert "Unknown agent(s): NOT_A_REAL_AGENT" in message
    assert "Valid roles: coordinator, architect, researcher" in message


def test_run_body_treats_an_empty_agent_list_as_mode_defaults() -> None:
    body = SwarmRunBody.model_validate(
        {
            "objective": "Use the default team",
            "agents": [],
        }
    )

    assert body.agents is None


def test_run_body_defaults_to_autonomous_continuation() -> None:
    body = SwarmRunBody.model_validate({"objective": "Create and verify a report"})

    assert body.autonomous is True


@pytest.mark.asyncio
async def test_swarm_reports_are_durable_and_owned(monkeypatch: pytest.MonkeyPatch) -> None:
    report = {
        "run_id": "swarm-fixture", "objective": "Revê o plano", "mode": "investigation",
        "state": "completed", "scores": {}, "duration_ms": 5, "answer": "resposta guardada",
    }

    async def run(_request):
        return SimpleNamespace(to_dict=lambda: report)

    async def orchestrator(_request):
        return SimpleNamespace(run=run)

    def auth(owner: str) -> dict[str, str]:
        token = create_access_token({"sub": owner, "email": f"{owner}@fixture.test"})
        return {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(routes, "get_orchestrator", orchestrator)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=auth("alice"),
    ) as client:
        launched = await client.post("/api/swarm/run", json={"objective": "Revê o plano", "index_project": False})
        assert launched.status_code == 200, launched.text
        close_pool()
        init_db()
        path = "/api/swarm/runs"
        listed = (await client.get(path)).json()["runs"]
        assert [item["run_id"] for item in listed] == ["swarm-fixture"]
        assert "answer" not in listed[0]
        assert (await client.get(path, params={"full": "true"})).json()["runs"] == [report]
        assert (await client.get(path + "/swarm-fixture", headers=auth("bob"))).status_code == 404
        assert (await client.get(path, headers=auth("bob"))).json()["runs"] == []
        assert (await client.get("/api/swarm/dashboard", headers=auth("bob"))).json()["total_runs"] == 0
