"""Tests for backend.orchestrator.routes.agent_mentions — GET /api/agents/mentions."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.middleware import auth as auth_module
from backend.orchestrator.routes.agent_mentions import (
    AGENT_MENTION_SEEDS,
    AgentMention,
    AgentMentionsResponse,
    router,
)


# Override require_auth so tests don't depend on JWT signature secrets
async def _fake_user() -> dict:
    return {"user_id": "test", "email": "t@t"}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[auth_module.require_auth] = _fake_user
    with TestClient(app) as c:
        yield c


class TestAgentMentionsRoute:
    def test_returns_200(self, client) -> None:
        r = client.get("/api/agents/mentions")
        assert r.status_code == 200

    def test_schema_fields(self, client) -> None:
        data = client.get("/api/agents/mentions").json()
        assert set(data) == {"mentions", "count"}
        assert data["count"] == len(data["mentions"])
        for mention in data["mentions"]:
            assert set(mention) == {"id", "name", "description"}

    def test_core_agents_present_and_unique(self, client) -> None:
        ids = [m["id"] for m in client.get("/api/agents/mentions").json()["mentions"]]
        for expected in ("auto", "coder", "analyzer", "architect", "reviewer"):
            assert expected in ids
        assert len(ids) == len(set(ids))

    def test_unauthenticated_rejected(self) -> None:
        app = FastAPI()
        app.include_router(router, prefix="/api")
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/agents/mentions")
        # require_auth is enforced (401), not silently bypassed.
        assert r.status_code == 401


class TestAgentMentionsModels:
    def test_pydantic_model_from_seed(self) -> None:
        seed = AGENT_MENTION_SEEDS[0]
        mention = AgentMention(**seed)
        assert mention.id == "auto"

    def test_response_model_counts(self) -> None:
        mentions = [AgentMention(**seed) for seed in AGENT_MENTION_SEEDS]
        resp = AgentMentionsResponse(mentions=mentions, count=len(mentions))
        assert resp.count == len(resp.mentions)
        assert resp.count >= 10
