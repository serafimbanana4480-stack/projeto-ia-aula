"""Bounds that still matter after the composer moved to the primary runtime.

The composer no longer loops over participants, so round/consensus bounds are
gone with it. The legacy file-reading executor keeps its own wall-clock budget;
these tests make sure that bound still stops it and that the composer cannot
silently behave like the old round-robin.
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


def _auth(name: str) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': name, 'email': name + '@test.local'})}"
        )
    }


def _frames(sse_text: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[6:])
        for line in sse_text.splitlines()
        if line.startswith("data: ")
    ]


class ScriptedProvider:
    provider_name = "lmstudio"
    last_finish_reason = "stop"
    last_usage: dict[str, int] = {}

    def __init__(self, replies: list[str] | None = None, delay: float = 0.0) -> None:
        self.replies = list(replies or [])
        self.delay = delay
        self.calls: list[str] = []

    async def chat_stream(self, model: str, _messages: list[dict], **_kwargs: Any):
        self.calls.append(model)
        if self.delay:
            await asyncio.sleep(self.delay)
        yield self.replies.pop(0) if self.replies else "Resposta"


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
    manager = SimpleNamespace(
        providers={"lmstudio": provider}, free_only=False, provider_name="lmstudio"
    )
    monkeypatch.setattr(app.state, "llm_client", manager, raising=False)
    monkeypatch.setattr(app.state, "context", ContextStore(), raising=False)


async def _bots(client: httpx.AsyncClient, names: tuple[str, ...]) -> list[str]:
    ids: list[str] = []
    for name in names:
        bot = await client.post(
            "/api/bots", json={"name": name, "provider": "lmstudio", "model": name}
        )
        assert bot.status_code == 201, bot.text
        ids.append(bot.json()["id"])
    return ids


@pytest.mark.asyncio
async def test_composer_ignores_legacy_round_cap_and_runs_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    provider = ScriptedProvider(["Resposta única"])
    _configure(monkeypatch, provider, tmp_path)
    monkeypatch.setenv("NEXUS_GROUP_MAX_CYCLES", "1")
    monkeypatch.delenv("NEXUS_GROUP_MAX_SECONDS", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers=_auth("round-cap"),
    ) as client:
        ids = await _bots(client, ("Primeiro", "Segundo"))
        group_id = (
            await client.post("/api/bot-groups", json={"name": "Limite", "bot_ids": ids})
        ).json()["id"]
        response = await client.post(
            f"/api/bot-groups/{group_id}/messages", json={"message": "Analisa isto"}
        )
        parsed = _frames(response.text)
        assert len(provider.calls) == 1
        assert parsed[-1]["type"] == "done"
        assert parsed[-1]["status"] == "completed"


@pytest.mark.asyncio
async def test_legacy_file_execution_stops_at_its_global_time_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "example.txt").write_text("evidência", encoding="utf-8")
    provider = ScriptedProvider(["análise"], delay=0.25)
    _configure(monkeypatch, provider, tmp_path)
    monkeypatch.setattr(routes, "_run_seconds_limit", lambda: 0.2)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers=_auth("turn-cap"),
    ) as client:
        registered = await client.post(
            "/api/projects", json={"name": "tempo", "path": str(project)}
        )
        assert registered.status_code in {200, 201}, registered.text
        ids = await _bots(client, ("Primeiro", "Segundo"))
        group_id = (
            await client.post("/api/bot-groups", json={"name": "Lento", "bot_ids": ids})
        ).json()["id"]
        created = await client.post(
            f"/api/bot-groups/{group_id}/runs",
            json={
                "message": "Analisa",
                "file_path": "example.txt",
                "project_path": str(project),
            },
        )
        assert created.status_code == 202, created.text
        run_id = created.json()["id"]
        from backend.persistence import bot_group_runs

        run = None
        for _ in range(100):
            run = bot_group_runs.get("turn-cap", group_id, run_id)
            if run and run["status"] in {"interrupted", "failed", "completed"}:
                break
            await asyncio.sleep(0.05)
        assert run is not None
        # The bound stops the sequence after the first provider turn: the
        # second member is never woken and no round-robin continues.
        assert run["status"] in {"interrupted", "failed"}, run
        assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_legacy_file_execution_completes_within_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "example.txt").write_text("evidência", encoding="utf-8")
    provider = ScriptedProvider(["análise A", "análise B"])
    _configure(monkeypatch, provider, tmp_path)
    monkeypatch.setattr(routes, "_run_seconds_limit", lambda: 10.0)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers=_auth("legacy-ok"),
    ) as client:
        registered = await client.post(
            "/api/projects", json={"name": "legado", "path": str(project)}
        )
        assert registered.status_code in {200, 201}, registered.text
        ids = await _bots(client, ("A", "B"))
        group_id = (
            await client.post("/api/bot-groups", json={"name": "OK", "bot_ids": ids})
        ).json()["id"]
        created = await client.post(
            f"/api/bot-groups/{group_id}/runs",
            json={
                "message": "Analisa",
                "file_path": "example.txt",
                "project_path": str(project),
            },
        )
        assert created.status_code == 202, created.text
        run_id = created.json()["id"]
        from backend.persistence import bot_group_runs

        run = None
        for _ in range(100):
            run = bot_group_runs.get("legacy-ok", group_id, run_id)
            if run and run["status"] in {"completed", "failed", "interrupted"}:
                break
            await asyncio.sleep(0.05)
        assert run is not None
        assert run["status"] == "completed", run
        assert len(provider.calls) == 2
