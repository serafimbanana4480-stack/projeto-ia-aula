"""Group composer, owner isolation and persistence.

The composer no longer runs a round-robin provider loop. These tests pin the
new contract: one normal message selects exactly one eligible bot (honouring
``@mentions``) and runs it through the primary runtime.
"""

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
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': name, 'email': name + '@test.local'})}"
        )
    }


class ScriptedProvider:
    provider_name = "lmstudio"
    last_finish_reason = "stop"
    last_usage: dict[str, int] = {}

    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls: list[dict[str, Any]] = []

    async def chat_stream(self, model: str, messages: list[dict], **kwargs: Any):
        self.calls.append({"model": model, "messages": messages, **kwargs})
        yield self.replies.pop(0) if self.replies else "Tarefa concluída."


class _NoModes:
    def build_active_execution_profile(self) -> dict:
        return {}

    def prepare_active_execution_profile(self, _message: str) -> dict:
        return {}


def _configure(monkeypatch: pytest.MonkeyPatch, provider: Any, tmp_path) -> None:
    from backend.core import conversation_log
    from backend.orchestrator import advanced_modes
    from backend.orchestrator.context_manager import ContextStore

    monkeypatch.setenv("NEXUS_PRIMARY_ENABLED", "1")
    monkeypatch.setenv("NEXUS_EXPERIENCE_OFF", "1")
    monkeypatch.setenv("NEXUS_ADVISOR_ENABLED", "0")
    monkeypatch.setenv("NEXUS_NATIVE_TOOL_CALLING", "0")
    monkeypatch.setenv("NEXUS_RUN_LIFECYCLE", "1")
    monkeypatch.setattr(advanced_modes, "get_orchestrator", lambda: _NoModes())
    monkeypatch.setattr(conversation_log, "_DEFAULT_LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(app.state, "llm_client", provider, raising=False)
    monkeypatch.setattr(app.state, "context", ContextStore(), raising=False)


def _manager(provider: Any) -> SimpleNamespace:
    return SimpleNamespace(
        providers={"lmstudio": provider}, free_only=False, provider_name="lmstudio"
    )


def _frames(response: httpx.Response) -> list[dict[str, Any]]:
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


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
async def test_group_composer_persists_one_primary_answer_and_owner_scoped_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    provider = ScriptedProvider(["Resposta do primeiro bot."])
    _configure(monkeypatch, _manager(provider), tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = _auth("alice")
        ids = []
        for name, model, instructions in [
            ("Arquiteta", "model-a", "Investiga e analisa o pedido."),
            ("Revisor", "model-b", "Revê textos."),
        ]:
            result = await client.post("/api/bots", headers=headers, json={
                "name": name, "provider": "lmstudio", "model": model,
                "instructions": instructions,
            })
            assert result.status_code == 201, result.text
            ids.append(result.json()["id"])
        assert (await client.post(
            "/api/bot-groups", headers=_auth("bob"), json={"name": "X", "bot_ids": ids},
        )).status_code == 404
        assert (await client.post(
            "/api/bot-groups", headers=headers,
            json={"name": "X", "bot_ids": [ids[0], ids[0]]},
        )).status_code == 422
        created = await client.post(
            "/api/bot-groups", headers=headers, json={"name": "Equipa", "bot_ids": ids},
        )
        assert created.status_code == 201, created.text
        group_id = created.json()["id"]
        assert created.json()["bot_ids"] == ids
        assert (await client.get(
            f"/api/bot-groups/{group_id}/messages", headers=_auth("bob"),
        )).status_code == 404
        assert (await client.get("/api/bot-groups", headers=_auth("bob"))).json() == {"groups": []}
        assert (await client.post(
            f"/api/bot-groups/{group_id}/messages", headers=headers,
            json={"message": "Olá", "max_turns": 13},
        )).status_code == 422

        result = await client.post(
            f"/api/bot-groups/{group_id}/messages", headers=headers,
            json={"message": "Investiguem isto"},
        )
        assert result.status_code == 200, result.text
        frames = _frames(result)
        assert frames[-1]["type"] == "done"
        assert frames[-1]["status"] == "completed"
        assert [call["model"] for call in provider.calls] == ["model-a"]

        close_pool()
        init_db()
        history = (await client.get(
            f"/api/bot-groups/{group_id}/messages", headers=headers,
        )).json()["messages"]
        assert [item["role"] for item in history] == ["user", "assistant"]
        assert [item["bot_id"] for item in history[1:]] == [ids[0]]
        assert history[0].get("run_id") == frames[0]["run_id"]
        assert (await client.get(
            "/api/bot-groups", headers=headers,
        )).json()["groups"][0]["id"] == group_id
        page = (await client.get(
            f"/api/bot-groups/{group_id}/messages?limit=1", headers=headers,
        )).json()
        assert page["has_more"] is True
        assert [item["id"] for item in page["messages"]] == [history[1]["id"]]
        older = (await client.get(
            f"/api/bot-groups/{group_id}/messages", headers=headers,
            params={"limit": 1, "before": page["next_before"]},
        )).json()
        assert older["has_more"] is False
        assert [item["id"] for item in older["messages"]] == [history[0]["id"]]


@pytest.mark.asyncio
async def test_cancellation_interrupts_the_selected_provider_and_releases_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    class Provider(ScriptedProvider):
        async def chat_stream(self, model: str, messages: list[dict], **kwargs: Any):
            self.calls.append({"model": model, "messages": messages, **kwargs})
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            yield "unreachable"

    provider = Provider()
    _configure(monkeypatch, _manager(provider), tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=_auth("alice")
    ) as client:
        ids = []
        for name in ("A", "B"):
            result = await client.post(
                "/api/bots", json={"name": name, "provider": "lmstudio", "model": "model"},
            )
            ids.append(result.json()["id"])
        group_id = (await client.post(
            "/api/bot-groups", json={"name": "Grupo", "bot_ids": ids},
        )).json()["id"]
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    llm_client=_manager(provider),
                    context=app.state.context,
                )
            )
        )
        response = await routes.send_group_message(
            group_id, routes.GroupTurn(message="Olá"), request, {"user_id": "alice"},
        )
        # A response never consumed must not reserve the group indefinitely.
        assert group_id not in routes._active_groups
        competing = await routes.send_group_message(
            group_id, routes.GroupTurn(message="Outro"), request, {"user_id": "alice"},
        )
        stream = response.body_iterator
        assert json.loads((await anext(stream))[6:])["type"] == "user_message"
        conflict = competing.body_iterator
        assert '"group_error"' in await anext(conflict)
        assert '"rejected"' in await anext(conflict)
        await conflict.aclose()
        while True:
            frame = json.loads((await anext(stream))[6:])
            if frame["type"] == "agent_started":
                break
        running = asyncio.create_task(anext(stream))
        await asyncio.wait_for(entered.wait(), 15)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert cancelled.is_set()
        assert group_id not in routes._active_groups
        history = (await client.get(f"/api/bot-groups/{group_id}/messages")).json()["messages"]
        assert [message["role"] for message in history] == ["user", "error"]
        assert "interrompida" in history[-1]["content"]
        runs = (await client.get(f"/api/bot-groups/{group_id}/runs")).json()["runs"]
        cancelled_run = next(run for run in runs if run["id"] == history[-1]["run_id"])
        assert cancelled_run["status"] == "cancelled"
        assert cancelled_run["run_state"] == "cancelled"


@pytest.mark.asyncio
async def test_composer_does_not_run_a_round_robin(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    provider = ScriptedProvider(["Análise única."])
    _configure(monkeypatch, _manager(provider), tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
        headers=_auth("round-robin"),
    ) as client:
        ids = []
        for name in ("Primeiro", "Segundo"):
            bot = await client.post(
                "/api/bots", json={"name": name, "provider": "lmstudio", "model": name},
            )
            ids.append(bot.json()["id"])
        group_id = (await client.post(
            "/api/bot-groups", json={"name": "Sem voltas", "bot_ids": ids},
        )).json()["id"]
        response = await client.post(
            f"/api/bot-groups/{group_id}/messages", json={"message": "Analisem isto"},
        )
        frames = _frames(response)
        assert frames[-1]["status"] == "completed"
        assert len(provider.calls) == 1
        history = (await client.get(f"/api/bot-groups/{group_id}/messages")).json()["messages"]
        assert [message["role"] for message in history] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_mention_selects_who_responds(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    provider = ScriptedProvider(["Feito por Atlas.", "Feito pelo primeiro."])
    _configure(monkeypatch, _manager(provider), tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
        headers=_auth("mention"),
    ) as client:
        ids = []
        for name, model in [("Pixel", "model-pixel"), ("Atlas", "model-atlas")]:
            bot = await client.post(
                "/api/bots", json={"name": name, "provider": "lmstudio", "model": model},
            )
            ids.append(bot.json()["id"])
        group_id = (await client.post(
            "/api/bot-groups", json={"name": "Mencoes", "bot_ids": ids},
        )).json()["id"]

        result = await client.post(
            f"/api/bot-groups/{group_id}/messages", json={"message": "@Atlas trata disto"},
        )
        frames = _frames(result)
        assert frames[-1]["status"] == "completed"
        assert [call["model"] for call in provider.calls] == ["model-atlas"]

        provider.calls.clear()
        result = await client.post(
            f"/api/bot-groups/{group_id}/messages", json={"message": "E agora?"},
        )
        frames = _frames(result)
        assert frames[-1]["status"] == "completed"
        # No mention is not a cue to wake everyone: one competent bot answers.
        assert len(provider.calls) == 1
        assert provider.calls[0]["model"] == "model-pixel"


@pytest.mark.asyncio
async def test_unavailable_provider_is_reported_without_anonymous_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    class FailingProvider(ScriptedProvider):
        async def chat_stream(self, model: str, messages: list[dict], **kwargs: Any):
            self.calls.append({"model": model, "messages": messages, **kwargs})
            raise RuntimeError("kilo unavailable")
            yield ""  # pragma: no cover - keeps this an async generator

    provider = FailingProvider([])
    _configure(
        monkeypatch,
        SimpleNamespace(providers={"kilo": provider}, free_only=True, provider_name="kilo"),
        tmp_path,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
        headers=_auth("kilo-test"),
    ) as client:
        ids = []
        for name in ("A", "B"):
            response = await client.post(
                "/api/bots", json={"name": name, "provider": "kilo", "model": "example/model:free"},
            )
            assert response.status_code == 201, response.text
            ids.append(response.json()["id"])
        group = await client.post("/api/bot-groups", json={"name": "Kilo", "bot_ids": ids})
        response = await client.post(
            f"/api/bot-groups/{group.json()['id']}/messages", json={"message": "@A Olá"},
        )
        # The failure is explicit; no anonymous adapter silently takes over and
        # the other member is not woken as a round-robin fallback.
        assert response.status_code == 200, response.text
        frames = _frames(response)
        assert frames[-1]["type"] == "done"
        assert frames[-1]["status"] == "failed"
        assert [call["model"] for call in provider.calls] == ["example/model:free"]
