"""Global bounds for group bot conversations (rounds and wall clock).

The group conversation previously looped forever while members kept answering
without consensus. These tests fail the suite if that bound vanishes again.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from backend.middleware.auth import create_access_token
from backend.orchestrator.main import app
from backend.orchestrator.routes import bot_groups as routes
from backend.persistence.db import close_pool, init_db


def _auth(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': name, 'email': name + '@test.local'})}"}


def _frames(sse_text: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in sse_text.splitlines() if line.startswith("data: ")]


@pytest.mark.asyncio
async def test_group_conversation_stops_at_global_round_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Provider:
        async def chat_stream(self, model: str, _messages: list[dict[str, str]]):
            calls.append(model)
            yield "Análise " + str(len(calls))

    async def resolve(_selected: Any, _client: Any):
        return Provider(), None

    monkeypatch.setattr(routes, "_request_provider_client", resolve)
    monkeypatch.setenv("NEXUS_GROUP_MAX_CYCLES", "1")
    monkeypatch.delenv("NEXUS_GROUP_MAX_SECONDS", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=_auth("round-cap"),
    ) as client:
        ids = []
        for name in ("Primeiro", "Segundo"):
            bot = await client.post("/api/bots", json={"name": name, "provider": "lmstudio", "model": name})
            ids.append(bot.json()["id"])
        group_id = (await client.post("/api/bot-groups", json={"name": "Limite", "bot_ids": ids})).json()["id"]
        response = await client.post(f"/api/bot-groups/{group_id}/messages", json={"message": "Analisa"})
        parsed = _frames(response.text)
        # One full round of both members, then an honest global stop — not a
        # fourth provider attempt.
        assert len(calls) == 2, calls
        assert parsed[-1]["type"] == "done"
        assert parsed[-1]["status"] == "unresolved"
        assert parsed[-1].get("reason"), parsed[-1]
        assert ("1 volta" in parsed[-1]["reason"]) or ("limite de 1" in parsed[-1]["reason"])


@pytest.mark.asyncio
async def test_global_time_budget_stops_between_provider_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Provider:
        async def chat_stream(self, model: str, _messages: list[dict[str, str]]):
            calls.append(model)
            await asyncio.sleep(0.2)
            yield "Resposta lenta"

    async def resolve(_selected: Any, _client: Any):
        return Provider(), None

    monkeypatch.setattr(routes, "_request_provider_client", resolve)
    # First turn is admitted; after it completes the budget is exhausted, so
    # the next participant must not start.
    monkeypatch.setattr(routes, "group_seconds_limit", lambda: 0.1)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=_auth("turn-cap"),
    ) as client:
        ids = []
        for name in ("Primeiro", "Segundo"):
            bot = await client.post("/api/bots", json={"name": name, "provider": "lmstudio", "model": name})
            ids.append(bot.json()["id"])
        group_id = (await client.post("/api/bot-groups", json={"name": "Lento", "bot_ids": ids})).json()["id"]
        response = await client.post(f"/api/bot-groups/{group_id}/messages", json={"message": "Analisa"})
        parsed = _frames(response.text)
        assert len(calls) == 1, calls
        assert parsed[-1]["type"] == "done"
        assert parsed[-1]["status"] == "unresolved"
        assert "limite" in parsed[-1]["reason"]


@pytest.mark.asyncio
async def test_round_cap_still_completes_when_consensus_is_earlier(monkeypatch: pytest.MonkeyPatch) -> None:
    """A group that reaches consensus before the cap completes normally."""

    class Provider:
        async def chat_stream(self, _model: str, _messages: list[dict[str, str]]):
            yield "Concordo.\n[OBJETIVO_CONCLUIDO]"

    async def resolve(_selected: Any, _client: Any):
        return Provider(), None

    monkeypatch.setattr(routes, "_request_provider_client", resolve)
    monkeypatch.setenv("NEXUS_GROUP_MAX_CYCLES", "2")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=_auth("cap-consensus"),
    ) as client:
        ids = []
        for name in ("A", "B"):
            bot = await client.post("/api/bots", json={"name": name, "provider": "lmstudio", "model": name})
            ids.append(bot.json()["id"])
        group_id = (await client.post("/api/bot-groups", json={"name": "OK", "bot_ids": ids})).json()["id"]
        response = await client.post(f"/api/bot-groups/{group_id}/messages", json={"message": "Olá"})
        assert _frames(response.text)[-1] == {"type": "done", "status": "completed"}


@pytest.mark.asyncio
async def test_round_cap_durable_reload_and_usage_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    """After a capped conversation the group remains usable and consistent."""
    calls: list[str] = []

    class Provider:
        async def chat_stream(self, model: str, _messages: list[dict[str, str]]):
            calls.append(model)
            yield "Resposta do bot"

    async def resolve(_selected: Any, _client: Any):
        return Provider(), None

    monkeypatch.setattr(routes, "_request_provider_client", resolve)
    monkeypatch.setenv("NEXUS_GROUP_MAX_CYCLES", "1")
    monkeypatch.delenv("NEXUS_GROUP_MAX_SECONDS", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=_auth("cap-reload"),
    ) as client:
        ids = []
        for name in ("Um", "Dois"):
            bot = await client.post("/api/bots", json={"name": name, "provider": "lmstudio", "model": name})
            ids.append(bot.json()["id"])
        group_id = (await client.post("/api/bot-groups", json={"name": "R", "bot_ids": ids})).json()["id"]
        await client.post(f"/api/bot-groups/{group_id}/messages", json={"message": "Analisa"})
        assert len(calls) == 2
        # The group was released and can host a fresh conversation.
        assert group_id not in routes._active_groups
        close_pool()
        init_db()
        history = (await client.get(f"/api/bot-groups/{group_id}/messages")).json()["messages"]
        # user message + one assistant answer per member; the cap consumed no
        # further provider turns and nothing partial was persisted.
        assert [message["role"] for message in history] == ["user", "assistant", "assistant"]
