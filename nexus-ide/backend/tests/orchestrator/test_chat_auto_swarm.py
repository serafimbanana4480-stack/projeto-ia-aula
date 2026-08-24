"""End-to-end tests for POST /api/chat auto and swarm modes.

Uses a fake agent registry so no real Ollama inference is required.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.agents.base import AgentBase, AgentRequest
from backend.middleware.auth import create_access_token
from backend.models.api import AgentName
from backend.orchestrator import main as main_module
from backend.tests.conftest import make_stream_response
from backend.tools.ollama_client import OllamaClient


def _install_mock_ollama(tokens: list[str]) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/chat":
            return make_stream_response(tokens)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


class FakeAgent(AgentBase):
    """Minimal agent that yields canned tokens."""

    name: AgentName = "CODER"
    model_key: str = "fast"
    prompt_file: str = "coder"

    def __init__(self, name: AgentName = "CODER"):
        self.name = name

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        for token in [f"[{self.name}]", " answer"]:
            yield token

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        async for token in self._execute(request):
            yield token


@pytest.fixture
def client_with_fake_agents(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """FastAPI TestClient with mocked Ollama and a minimal fake registry."""
    # These tests exercise the LEGACY pipeline contracts (routing events,
    # fake agent registry). The NEXUS primary runtime bypasses both and would
    # dispatch real provider requests from CI, so pin the legacy lane.
    monkeypatch.setenv("NEXUS_PRIMARY_ENABLED", "0")
    mock_transport = _install_mock_ollama(["ok"])

    original = OllamaClient.__init__

    def patched_init(self, base_url: str = "", *, transport=None, timeout=None, limits=None):  # type: ignore[no-redef]
        kwargs: dict = {"transport": mock_transport}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if limits is not None:
            kwargs["limits"] = limits
        return original(self, base_url, **kwargs)

    monkeypatch.setattr(OllamaClient, "__init__", patched_init)

    # Pin the app-level LLM client to the mocked local provider. Without
    # this, routing/model classification dispatched REAL requests to whatever
    # cloud provider the developer machine had configured.
    from backend.llm.factory import create_llm_client

    monkeypatch.setattr(
        "backend.llm.create_llm_client",
        lambda: create_llm_client(
            multi_llm_enabled=False,
            llm_provider="ollama",
            ollama_host="http://ollama.test",
            free_only=False,
        ),
    )

    # Reset any previously cached app state
    for attr in ("ollama", "llm_client"):
        if hasattr(main_module.app.state, attr):
            delattr(main_module.app.state, attr)

    # Inject a fake registry so agents don't hit real Ollama. NEXUS is
    # registered so tests that re-enable the primary runtime (phase-3
    # contract) can resolve it without touching the network.
    fake_registry: dict[AgentName, AgentBase] = {
        "CODER": FakeAgent("CODER"),
        "ANALYZER": FakeAgent("ANALYZER"),
        "ARCHITECT": FakeAgent("ARCHITECT"),
        "DEBUGGER": FakeAgent("DEBUGGER"),
        "DOCUMENTER": FakeAgent("DOCUMENTER"),
        "MICRO": FakeAgent("MICRO"),
        "NEXUS": FakeAgent("NEXUS"),
    }
    main_module.app.state.registry = fake_registry

    # Also patch the global registry so lifespan/context logic uses fakes
    global _registry_instance
    _registry_instance = fake_registry

    token = create_access_token({"sub": "test-user", "email": "test@test.com"})
    with TestClient(main_module.app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client

    # Restore global registry to avoid leaking fakes to other tests
    _registry_instance = None


def _iter_sse_events(body: bytes) -> list[dict]:
    events: list[dict] = []
    for line in body.decode().splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: ") :]))
    return events


class TestAutoMode:
    def test_auto_mode_routes_and_streams(
        self, client_with_fake_agents: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Phase-3 contract lives on the primary runtime; re-enable it for this
        # test (the fixture pins the legacy lane for the rest of the class).
        monkeypatch.setenv("NEXUS_PRIMARY_ENABLED", "1")
        response = client_with_fake_agents.post(
            "/api/chat",
            json={
                "message": "create a function that sorts a list",
                "session_id": "t-auto",
                "mode": "auto",
            },
        )
        assert response.status_code == 200
        events = _iter_sse_events(response.content)
        types = [e["type"] for e in events]

        assert "routing" in types
        # Phase 3 moved ownership of a normal turn to NEXUS PRIMARY: the router
        # no longer picks a specialist up front. The contract that MUST hold is
        # that the routing frame names the agent that will answer and explains
        # why — clients label the message from it.
        routing_event = next(e for e in events if e["type"] == "routing")
        routing = routing_event["routing"]
        assert routing is not None, "routing frame must carry a routing decision"
        assert routing["primary_agent"] == "NEXUS"
        assert routing["routing_reason"].startswith("triage:")
        assert routing_event["data"]["path"] == "nexus_primary"
        assert routing_event["data"]["triage"]["class"] in {"direct", "conversational", "planned"}

        assert "agent_started" in types
        assert types[-1] == "done"

    def test_auto_mode_upgrades_lightweight_agent(
        self, client_with_fake_agents: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Phase-3 contract lives on the primary runtime (see the sibling test).
        monkeypatch.setenv("NEXUS_PRIMARY_ENABLED", "1")
        # A short informational question must stay on the direct CHAT lane.
        response = client_with_fake_agents.post(
            "/api/chat",
            json={
                "message": "what is HTTP?",
                "session_id": "t-auto-upgrade",
                "mode": "auto",
            },
        )
        assert response.status_code == 200
        events = _iter_sse_events(response.content)
        routing = next(e for e in events if e["type"] == "routing")["routing"]
        # Phase 3: NEXUS PRIMARY owns the turn; triage records that a short
        # informational question needs no tools, instead of picking MICRO.
        assert routing["primary_agent"] == "NEXUS"
        assert routing["routing_reason"] == "triage:conversational"

    def test_auto_mode_persists_history(self, client_with_fake_agents: TestClient) -> None:
        sid = "t-auto-history"
        client_with_fake_agents.post(
            "/api/chat",
            json={"message": "write a hello world function", "session_id": sid, "mode": "auto"},
        )
        resp = client_with_fake_agents.get(f"/api/sessions/{sid}/history")
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"


class TestSwarmMode:
    def test_swarm_mode_routes_and_streams(self, client_with_fake_agents: TestClient) -> None:
        response = client_with_fake_agents.post(
            "/api/chat",
            json={
                "message": "design a caching system",
                "session_id": "t-swarm",
                "mode": "swarm",
                "swarm_agents": ["CODER", "ANALYZER"],
                "swarm_strategy": "ensemble",
            },
        )
        assert response.status_code == 200
        events = _iter_sse_events(response.content)
        types = [e["type"] for e in events]

        assert "agent_started" in types
        assert "agent_finished" in types
        assert types[-1] == "done"

        agents_started = {e["agent"] for e in events if e["type"] == "agent_started"}
        assert "SWARM" in agents_started

    def test_swarm_mode_uses_default_agents(self, client_with_fake_agents: TestClient) -> None:
        response = client_with_fake_agents.post(
            "/api/chat",
            json={
                "message": "review this module",
                "session_id": "t-swarm-default",
                "mode": "swarm",
            },
        )
        assert response.status_code == 200
        events = _iter_sse_events(response.content)
        assert any(e["type"] == "done" for e in events)

    def test_swarm_mode_persists_history(self, client_with_fake_agents: TestClient) -> None:
        sid = "t-swarm-history"
        client_with_fake_agents.post(
            "/api/chat",
            json={"message": "design an API", "session_id": sid, "mode": "swarm"},
        )
        resp = client_with_fake_agents.get(f"/api/sessions/{sid}/history")
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert len(messages) == 2
