"""Group chat persistence, isolation and sequential participant context."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from backend.middleware.auth import create_access_token
from backend.orchestrator.main import app
from backend.orchestrator.routes import bot_groups as routes
from backend.orchestrator.routes.chat_primary import _request_provider_client
from backend.persistence.db import close_pool, init_db


def _auth(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': name, 'email': name + '@test.local'})}"}


@pytest.mark.asyncio
async def test_provider_selection_does_not_fall_back_to_another_bot_provider() -> None:
    local = SimpleNamespace(provider_name="lmstudio")
    remote = SimpleNamespace(provider_name="ollama")
    manager = SimpleNamespace(providers={"lmstudio": local, "ollama": remote}, free_only=False)
    selected, error = await _request_provider_client(
        SimpleNamespace(provider="ollama", model="model-b", model_is_concrete=True), manager,
    )
    assert error is None
    assert selected.primary is remote
    assert selected.fallbacks == []
    selected, error = await _request_provider_client(
        SimpleNamespace(provider="openai", model="model-c", model_is_concrete=True), manager,
    )
    assert selected is None
    assert error and "openai" in error


@pytest.mark.asyncio
async def test_free_kilo_group_uses_anonymous_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.llm.kilo_provider as kilo

    calls = []

    class FreeProvider:
        async def chat_stream(self, model, messages):
            calls.append(model)
            yield "Feito\n[OBJETIVO_CONCLUIDO]"

        async def aclose(self):
            calls.append("closed")

    async def unavailable(*args):
        return None, "blocked"

    monkeypatch.setattr(kilo, "AnonymousFreeKiloProvider", FreeProvider)
    monkeypatch.setattr(routes, "_request_provider_client", unavailable)
    monkeypatch.setattr(app.state, "llm_client", SimpleNamespace(free_only=True), raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=_auth("kilo-test")) as client:
        ids = []
        for name in ("A", "B"):
            response = await client.post("/api/bots", json={"name": name, "provider": "kilo", "model": "example/model:free"})
            ids.append(response.json()["id"])
        group = await client.post("/api/bot-groups", json={"name": "Kilo", "bot_ids": ids})
        response = await client.post(f"/api/bot-groups/{group.json()['id']}/messages", json={"message": "Olá"})
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert frames[-1] == {"type": "done", "status": "completed"}
        assert calls == ["example/model:free", "closed"] * 2


@pytest.mark.asyncio
async def test_group_discussion_uses_profiles_history_and_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, list[dict[str, str]]]] = []

    class Provider:
        def __init__(self, provider: str) -> None:
            self.provider = provider

        async def chat_stream(self, model: str, messages: list[dict[str, str]]):
            calls.append((self.provider, model, messages))
            if model == "model-b":
                raise RuntimeError("connection failed")
            yield f"Resposta de {model}"

    async def resolve(req: Any, _client: Any):
        return Provider(req.provider), None

    monkeypatch.setattr(routes, "_request_provider_client", resolve)
    monkeypatch.setattr(app.state, "llm_client", object(), raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        headers = _auth("alice")
        ids = []
        for name, provider, model in [("Arquiteta", "lmstudio", "model-a"), ("Revisor", "ollama", "model-b")]:
            result = await client.post("/api/bots", headers=headers, json={
                "name": name, "provider": provider, "model": model,
            })
            assert result.status_code == 201, result.text
            ids.append(result.json()["id"])
        assert (await client.post("/api/bot-groups", headers=_auth("bob"), json={"name": "X", "bot_ids": ids})).status_code == 404
        assert (await client.post("/api/bot-groups", headers=headers, json={"name": "X", "bot_ids": [ids[0], ids[0]]})).status_code == 422
        created = await client.post("/api/bot-groups", headers=headers, json={"name": "Equipa", "bot_ids": ids})
        assert created.status_code == 201, created.text
        group_id = created.json()["id"]
        assert created.json()["bot_ids"] == ids
        assert (await client.get(f"/api/bot-groups/{group_id}/messages", headers=_auth("bob"))).status_code == 404
        assert (await client.get("/api/bot-groups", headers=_auth("bob"))).json() == {"groups": []}
        assert (await client.post(f"/api/bot-groups/{group_id}/messages", headers=headers, json={"message": "Olá", "max_turns": 13})).status_code == 422

        result = await client.post(f"/api/bot-groups/{group_id}/messages", headers=headers,
                                   json={"message": "Investiguem isto"})
        assert result.status_code == 200
        frames = [json.loads(line[6:]) for line in result.text.splitlines() if line.startswith("data: ")]
        assert frames[-1] == {"type": "done", "status": "partial"}
        assert [f["type"] for f in frames].count("agent_error") == 1
        assert [(provider, model) for provider, model, _ in calls] == [
            ("lmstudio", "model-a"), ("ollama", "model-b")
        ]
        assert "Resposta de model-a" in calls[1][2][-1]["content"]
        assert "Investiguem isto" in calls[1][2][-1]["content"]
        assert "Não tens acesso a ferramentas" in calls[1][2][0]["content"]

        close_pool()
        init_db()
        history = (await client.get(f"/api/bot-groups/{group_id}/messages", headers=headers)).json()["messages"]
        assert [item["role"] for item in history] == ["user", "assistant", "error"]
        assert [item["bot_id"] for item in history[1:]] == [ids[0], ids[1]]
        assert (await client.get("/api/bot-groups", headers=headers)).json()["groups"][0]["id"] == group_id
        page = (await client.get(f"/api/bot-groups/{group_id}/messages?limit=2", headers=headers)).json()
        assert page["has_more"] is True
        assert [item["id"] for item in page["messages"]] == [item["id"] for item in history[1:]]
        older = (await client.get(f"/api/bot-groups/{group_id}/messages", headers=headers,
                                  params={"limit": 2, "before": page["next_before"]})).json()
        assert older["has_more"] is False
        assert [item["id"] for item in older["messages"]] == [item["id"] for item in history[:1]]


@pytest.mark.asyncio
async def test_cancellation_interrupts_provider_and_releases_group(monkeypatch: pytest.MonkeyPatch) -> None:
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    class Provider:
        async def chat_stream(self, _model: str, _messages: list[dict[str, str]]):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            yield "unreachable"

    async def resolve(_req: Any, _client: Any):
        return Provider(), None

    monkeypatch.setattr(routes, "_request_provider_client", resolve)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=_auth("alice")) as client:
        ids = []
        for name in ("A", "B"):
            result = await client.post("/api/bots", json={"name": name, "provider": "lmstudio", "model": "model"})
            ids.append(result.json()["id"])
        group_id = (await client.post("/api/bot-groups", json={"name": "Grupo", "bot_ids": ids})).json()["id"]
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(llm_client=object())))
        response = await routes.send_group_message(
            group_id, routes.GroupTurn(message="Olá"), request, {"user_id": "alice"},
        )
        # A response never consumed must not reserve the group indefinitely.
        assert group_id not in routes._active_groups
        competing = await routes.send_group_message(
            group_id, routes.GroupTurn(message="Outro"), request, {"user_id": "alice"},
        )
        stream = response.body_iterator
        assert '"user_message"' in await anext(stream)
        conflict = competing.body_iterator
        assert '"group_error"' in await anext(conflict)
        assert '"rejected"' in await anext(conflict)
        await conflict.aclose()
        assert '"agent_started"' in await anext(stream)
        running = asyncio.create_task(anext(stream))
        await asyncio.wait_for(entered.wait(), 2)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert cancelled.is_set()
        assert group_id not in routes._active_groups
        history = (await client.get(f"/api/bot-groups/{group_id}/messages")).json()["messages"]
        assert [message["role"] for message in history] == ["user", "error"]
        assert "interrompida" in history[-1]["content"]

@pytest.mark.asyncio
async def test_group_requires_unanimity_in_same_round(monkeypatch: pytest.MonkeyPatch) -> None:
    """Consensus completes only when every member approves the SAME round.

    Stale approvals from earlier rounds must not finish the conversation:
    approvals are cleared at each round boundary. The run stays inside the
    default global round cap (see ``group_cycles_limit``).
    """
    calls = []

    class Provider:
        async def chat_stream(self, model, messages):
            calls.append(model)
            approved = len(calls) in (1, 5, 6)
            yield "Análise " + str(len(calls)) + ("\n[OBJETIVO_CONCLUIDO]" if approved else "")

    async def resolve(_selected, _client):
        return Provider(), None

    monkeypatch.setattr(routes, "_request_provider_client", resolve)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=_auth("consensus")) as client:
        ids = []
        for name in ("Primeiro", "Segundo"):
            bot = await client.post("/api/bots", json={"name": name, "provider": "lmstudio", "model": name})
            ids.append(bot.json()["id"])
        group = await client.post("/api/bot-groups", json={"name": "Consenso", "bot_ids": ids})
        group_id = group.json()["id"]
        response = await client.post(f"/api/bot-groups/{group_id}/messages", json={"message": "Analisem"})
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        # Members speak in order: A(siga)→B(não)→A(não)→B(siga) → round 2 fails;
        # A(siga)→B(siga) → round 3 has unanimous approval.
        assert len(calls) == 6
        assert frames[-1] == {"type": "done", "status": "completed"}
        assert "[OBJETIVO_CONCLUIDO]" not in response.text
        history = (await client.get(f"/api/bot-groups/{group_id}/messages")).json()["messages"]
        assert len(history) == 7
        assert all("[OBJETIVO_CONCLUIDO]" not in item["content"] for item in history)
