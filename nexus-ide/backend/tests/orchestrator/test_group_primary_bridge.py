"""Composer -> primary runtime bridge (group integration, closeout v3).

These tests use the real ASGI app and a scripted provider. They prove the
execution identity, participant selection, tool evidence, verification and
durable reload without mocking the coordinator or the primary loop.
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

TOOL_TAG_OPEN = "<" + "tool_call" + ">"
TOOL_TAG_CLOSE = "</" + "tool_call" + ">"


def _auth(user: str) -> dict[str, str]:
    token = create_access_token({"sub": user, "email": f"{user}@test.local"})
    return {"Authorization": f"Bearer {token}"}


def _frames(response: httpx.Response) -> list[dict[str, Any]]:
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _tool_call(name: str, arguments: dict[str, Any]) -> str:
    return (
        f"{TOOL_TAG_OPEN}"
        f"{json.dumps({'name': name, 'arguments': arguments}, sort_keys=True)}"
        f"{TOOL_TAG_CLOSE}"
    )


class ScriptedProvider:
    """Controlled provider; never evidence of real-model inference."""

    provider_name = "lmstudio"
    last_finish_reason = "stop"
    last_usage: dict[str, int] = {}

    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls: list[dict[str, Any]] = []

    async def chat_stream(self, model: str, messages: list[dict], **kwargs: Any):
        self.calls.append({"model": model, "messages": messages, **kwargs})
        reply = self.replies.pop(0) if self.replies else "Tarefa concluída."
        yield reply


class _NoModes:
    def build_active_execution_profile(self) -> dict:
        return {}

    def prepare_active_execution_profile(self, _message: str) -> dict:
        return {}


def _configure(monkeypatch: pytest.MonkeyPatch, provider: ScriptedProvider, tmp_path) -> None:
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
    manager = SimpleNamespace(
        providers={"lmstudio": provider},
        free_only=False,
        provider_name="lmstudio",
    )
    monkeypatch.setattr(app.state, "llm_client", manager, raising=False)
    monkeypatch.setattr(app.state, "context", ContextStore(), raising=False)


async def _create_bot(
    client: httpx.AsyncClient,
    *,
    name: str,
    model: str,
    instructions: str = "",
    capabilities: dict[str, bool] | None = None,
    provider: str = "lmstudio",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "provider": provider,
        "model": model,
        "instructions": instructions,
    }
    if capabilities is not None:
        payload["capabilities"] = capabilities
    response = await client.post("/api/bots", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _register_project(client: httpx.AsyncClient, path) -> None:
    response = await client.post("/api/projects", json={"name": "bridge", "path": str(path)})
    assert response.status_code in {200, 201}, response.text


@pytest.mark.asyncio
async def test_composer_runs_one_primary_bot_with_tool_and_verification(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "example.txt").write_text("conteudo verificavel", encoding="utf-8")
    provider = ScriptedProvider(
        [
            _tool_call("read_file", {"path": "example.txt"}),
            "Li example.txt: conteudo verificavel.",
        ]
    )
    _configure(monkeypatch, provider, tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://nexus.local",
        headers=_auth("bridge-owner"),
    ) as client:
        await _register_project(client, project)
        reader = await _create_bot(
            client,
            name="Leitor",
            model="model-reader",
            instructions="Especialista em ler ficheiros e verificar conteúdo.",
        )
        writer = await _create_bot(
            client,
            name="Escritor",
            model="model-writer",
            instructions="Escreve textos criativos.",
        )
        group = await client.post(
            "/api/bot-groups",
            json={"name": "Equipa", "bot_ids": [reader["id"], writer["id"]]},
        )
        assert group.status_code == 201, group.text
        group_id = group.json()["id"]

        response = await client.post(
            f"/api/bot-groups/{group_id}/messages",
            json={
                "message": "Lê o ficheiro example.txt e diz-me o conteúdo.",
                "project_path": str(project),
            },
        )
        assert response.status_code == 200, response.text
        frames = _frames(response)
        types = [frame["type"] for frame in frames]
        assert "user_message" in types
        assert "agent_started" in types
        assert "agent_tool" in types
        assert types[-1] == "done"
        assert frames[-1]["status"] == "completed", frames[-1]
        run_id = frames[0]["run_id"]
        assert run_id.startswith("run-")
        assert all(frame.get("run_id") == run_id for frame in frames)
        assert all(isinstance(frame.get("seq"), int) for frame in frames)
        assert [frame["bot_id"] for frame in frames if frame["type"] == "agent_started"] == [
            reader["id"]
        ]
        assert provider.calls[0]["model"] == "model-reader"

        history = (
            await client.get(f"/api/bot-groups/{group_id}/messages")
        ).json()["messages"]
        assert [message["role"] for message in history] == ["user", "assistant"]
        assert history[0]["run_id"] == run_id
        assert history[1]["run_id"] == run_id
        assert "Li example.txt" in history[1]["content"]
        assert "Verificação" in history[1]["content"]

        runs = (await client.get(f"/api/bot-groups/{group_id}/runs")).json()["runs"]
        primary = next(run for run in runs if run["id"] == run_id)
        assert primary["execution_engine"] == "primary"
        assert primary["run_state"] == "completed"
        assert [task["status"] for task in primary["tasks"]] == ["completed"]
        kinds = [record["kind"] for record in primary["records"]]
        assert "tool_call" in kinds
        assert "tool_result" in kinds
        assert "verification" in kinds
        assert "triage" in kinds
        assert "selection" in kinds
        assert "group_message" in kinds

        # Restart-proof: the rows and the API projection survive a pool reset.
        from backend.persistence.db import close_pool, init_db

        close_pool()
        init_db()
        reloaded = (
            await client.get(f"/api/bot-groups/{group_id}/messages")
        ).json()["messages"]
        assert [message.get("run_id") for message in reloaded] == [run_id, run_id]
        runs_after = (await client.get(f"/api/bot-groups/{group_id}/runs")).json()["runs"]
        assert next(run for run in runs_after if run["id"] == run_id)["run_state"] == "completed"


@pytest.mark.asyncio
async def test_mention_selects_the_mentioned_bot_without_round_robin(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    provider = ScriptedProvider(["Atlas respondeu."])
    _configure(monkeypatch, provider, tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://nexus.local",
        headers=_auth("mention-owner"),
    ) as client:
        await _register_project(client, project)
        pixel = await _create_bot(client, name="Pixel", model="model-pixel")
        atlas = await _create_bot(client, name="Atlas", model="model-atlas")
        group = await client.post(
            "/api/bot-groups", json={"name": "Menções", "bot_ids": [pixel["id"], atlas["id"]]}
        )
        group_id = group.json()["id"]

        response = await client.post(
            f"/api/bot-groups/{group_id}/messages",
            json={"message": "@Atlas trata disto", "project_path": str(project)},
        )
        assert response.status_code == 200, response.text
        frames = _frames(response)
        assert frames[-1]["status"] == "completed"
        assert [call["model"] for call in provider.calls] == ["model-atlas"]
        started = [frame for frame in frames if frame["type"] == "agent_started"]
        assert [frame["bot_id"] for frame in started] == [atlas["id"]]


@pytest.mark.asyncio
async def test_unavailable_provider_is_an_explicit_block_not_a_silent_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    provider = ScriptedProvider(["não devia correr"])
    _configure(monkeypatch, provider, tmp_path)
    # Only ``ollama`` is registered in this process. The offline member points
    # at ``lmstudio``, so its profile is configured but unavailable.
    monkeypatch.setattr(
        app.state,
        "llm_client",
        SimpleNamespace(
            providers={"ollama": provider}, free_only=False, provider_name="ollama"
        ),
        raising=False,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://nexus.local",
        headers=_auth("blocked-owner"),
    ) as client:
        await _register_project(client, project)
        missing = await _create_bot(
            client, name="Offline", model="model-offline", provider="lmstudio"
        )
        available = await _create_bot(
            client, name="Online", model="model-online", provider="ollama"
        )
        group = await client.post(
            "/api/bot-groups",
            json={"name": "Indisponível", "bot_ids": [missing["id"], available["id"]]},
        )
        group_id = group.json()["id"]

        blocked = await client.post(
            f"/api/bot-groups/{group_id}/messages",
            json={"message": "@Offline trata disto", "project_path": str(project)},
        )
        assert blocked.status_code == 409, blocked.text
        assert "não pode executar" in blocked.json()["detail"]
        assert provider.calls == []
        history = (
            await client.get(f"/api/bot-groups/{group_id}/messages")
        ).json()["messages"]
        assert history == []
        runs = (await client.get(f"/api/bot-groups/{group_id}/runs")).json()["runs"]
        assert runs == []


@pytest.mark.asyncio
async def test_legacy_file_run_stays_readable_and_is_not_resumed_by_primary(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "example.txt").write_text("evidência legada", encoding="utf-8")
    provider = ScriptedProvider(["análise legada"])
    _configure(monkeypatch, provider, tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://nexus.local",
        headers=_auth("legacy-owner"),
    ) as client:
        await _register_project(client, project)
        first = await _create_bot(client, name="Um", model="model-one")
        second = await _create_bot(client, name="Dois", model="model-two")
        group = await client.post(
            "/api/bot-groups", json={"name": "Legado", "bot_ids": [first["id"], second["id"]]}
        )
        group_id = group.json()["id"]
        created = await client.post(
            f"/api/bot-groups/{group_id}/runs",
            json={
                "message": "Analisa o ficheiro",
                "file_path": "example.txt",
                "project_path": str(project),
            },
        )
        assert created.status_code == 202, created.text
        legacy_run_id = created.json()["id"]
        for _ in range(200):
            runs = (await client.get(f"/api/bot-groups/{group_id}/runs")).json()["runs"]
            run = next(item for item in runs if item["id"] == legacy_run_id)
            if run["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.01)
        assert run["status"] == "completed", run
        assert run["execution_engine"] == "legacy_file"

        composer = await client.post(
            f"/api/bot-groups/{group_id}/messages",
            json={"message": "Olá", "project_path": str(project)},
        )
        assert composer.status_code == 200, composer.text
        composer_frames = _frames(composer)
        primary_run_id = composer_frames[0]["run_id"]

        resumed = await client.post(
            f"/api/bot-groups/{group_id}/runs/{legacy_run_id}/resume"
        )
        assert resumed.status_code == 202
        assert resumed.json()["resumed"] is False

        resumed_primary = await client.post(
            f"/api/bot-groups/{group_id}/runs/{primary_run_id}/resume"
        )
        assert resumed_primary.status_code == 202
        assert resumed_primary.json()["resumed"] is False
        assert "runtime principal" in resumed_primary.json()["detail"]


@pytest.mark.asyncio
async def test_provider_failure_is_terminal_and_does_not_try_another_bot(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    provider = ScriptedProvider([])

    class FailingProvider(ScriptedProvider):
        async def chat_stream(self, model: str, messages: list[dict], **kwargs: Any):
            self.calls.append({"model": model, "messages": messages, **kwargs})
            raise RuntimeError("provider down")
            yield ""  # pragma: no cover - keeps this an async generator

    failing = FailingProvider([])
    _configure(monkeypatch, provider, tmp_path)
    manager = SimpleNamespace(
        providers={"lmstudio": failing}, free_only=False, provider_name="lmstudio"
    )
    monkeypatch.setattr(app.state, "llm_client", manager, raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://nexus.local",
        headers=_auth("failure-owner"),
    ) as client:
        await _register_project(client, project)
        broken = await _create_bot(client, name="Quebrado", model="model-broken")
        spare = await _create_bot(client, name="Reserva", model="model-spare")
        group = await client.post(
            "/api/bot-groups", json={"name": "Falha", "bot_ids": [broken["id"], spare["id"]]}
        )
        group_id = group.json()["id"]
        response = await client.post(
            f"/api/bot-groups/{group_id}/messages",
            json={"message": "@Quebrado trata disto", "project_path": str(project)},
        )
        assert response.status_code == 200, response.text
        frames = _frames(response)
        assert frames[-1]["type"] == "done"
        assert frames[-1]["status"] == "failed"
        assert [call["model"] for call in failing.calls] == ["model-broken"]
        assert provider.calls == []
        history = (
            await client.get(f"/api/bot-groups/{group_id}/messages")
        ).json()["messages"]
        assert [message["role"] for message in history] == ["user", "error"]
