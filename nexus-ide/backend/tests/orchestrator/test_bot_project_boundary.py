"""Bot turns: "no project selected" must stay "no project selected".

A bot turn used to resolve an empty ``project_path`` through the same helper the
file APIs use, which substitutes the session's project, then the first
registered project, then the server's working directory. On an instance with
one registered project that silently handed the bot — and its in-project
auto-accept — a folder the user never chose, while the chat reported none.

These tests pin the real HTTP seam with a scripted provider: no LLM inference,
no network. They prove what the backend *does*, not what the UI shows.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from backend.middleware.auth import create_access_token
from backend.orchestrator.main import app


def _auth(user: str) -> dict[str, str]:
    token = create_access_token({"sub": user, "email": f"{user}@test.local"})
    return {"Authorization": f"Bearer {token}"}


def _frames(response: httpx.Response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


class _ScriptedProvider:
    """Controlled test double. Never evidence of real-model inference."""

    provider_name = "lmstudio"
    last_finish_reason = "stop"
    last_usage: dict[str, int] = {}

    def __init__(self) -> None:
        # Per-instance on purpose: a class-level list would leak one test's
        # calls into the next test's assertions.
        self.calls: list[dict[str, Any]] = []

    async def chat_stream(self, model: str, messages: list[dict], **kwargs: Any):
        self.calls.append({"model": model, "messages": messages, **kwargs})
        yield "Resposta curta."


class _NoModes:
    def build_active_execution_profile(self) -> dict:
        return {}

    def prepare_active_execution_profile(self, _message: str) -> dict:
        return {}


def _configure(monkeypatch: pytest.MonkeyPatch, provider: _ScriptedProvider, tmp_path) -> None:
    from backend.core import conversation_log
    from backend.orchestrator import advanced_modes
    from backend.orchestrator.context_manager import ContextStore
    from backend.orchestrator.routes import chat_primary

    monkeypatch.setenv("NEXUS_PRIMARY_ENABLED", "1")
    monkeypatch.setenv("NEXUS_EXPERIENCE_OFF", "1")
    monkeypatch.setenv("NEXUS_ADVISOR_ENABLED", "0")
    monkeypatch.setattr(chat_primary, "run_integration_enabled", lambda: False)
    monkeypatch.setattr(advanced_modes, "get_orchestrator", lambda: _NoModes())
    monkeypatch.setattr(conversation_log, "_DEFAULT_LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(app.state, "llm_client", provider, raising=False)
    monkeypatch.setattr(app.state, "context", ContextStore(), raising=False)


@pytest.fixture
def _isolated_db() -> None:
    """The suite's autouse ``temp_db`` already redirects ``DB_PATH``."""
    return None


@pytest.mark.asyncio
async def test_bot_turn_without_a_project_keeps_the_project_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path, _isolated_db
) -> None:
    provider = _ScriptedProvider()
    _configure(monkeypatch, provider, tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://nexus.local", headers=_auth("alice")) as client:
        bot = (await client.post("/api/bots", json={
            "name": "Pixel", "instructions": "Responde com precisão",
            "provider": "lmstudio", "model": "model-pixel",
        })).json()

        response = await client.post("/api/chat", json={
            "session_id": bot["session_id"], "message": "Olá!", "project_path": "",
        })
        assert response.status_code == 200, response.text
        frames = _frames(response)
        assert not [frame for frame in frames if frame["type"] == "error"], frames

        # The provider saw a turn whose system addon says there is no project,
        # so the bot policy itself was built from an empty project root.
        system = provider.calls[0]["messages"][0]["content"]
        assert "Não há projeto selecionado" in system
        assert "PERFIL DO BOT DEFINIDO PELO UTILIZADOR" in system
        assert "Nenhum caminho foi usado" not in system


@pytest.mark.asyncio
async def test_bot_turn_with_a_project_is_confined_to_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path, _isolated_db
) -> None:
    provider = _ScriptedProvider()
    _configure(monkeypatch, provider, tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://nexus.local", headers=_auth("alice")) as client:
        bot = (await client.post("/api/bots", json={
            "name": "Pixel", "instructions": "Responde com precisão",
            "provider": "lmstudio", "model": "model-pixel",
            "capabilities": {
                "read": True, "research": True, "tasks": True, "memory": True,
                "write": False, "shell": False, "browser": False, "mcp": False,
                "auto_accept": False,
            },
        })).json()
        project = tmp_path / "chosen"
        project.mkdir()
        created = await client.post("/api/projects", json={
            "name": "escolhido", "path": str(project),
        })
        assert created.status_code in {200, 201}, created.text

        response = await client.post("/api/chat", json={
            "session_id": bot["session_id"], "message": "Olá!",
            "project_path": str(project),
        })
        assert response.status_code == 200, response.text
        frames = _frames(response)
        assert not [frame for frame in frames if frame["type"] == "error"], frames
        assert "Projeto selecionado e limitado" in provider.calls[0]["messages"][0]["content"]
        assert "Não há projeto selecionado" not in provider.calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_an_unknown_project_is_still_refused_for_a_bot(
    monkeypatch: pytest.MonkeyPatch, tmp_path, _isolated_db
) -> None:
    """The empty-project fix must not open a door to arbitrary directories."""
    provider = _ScriptedProvider()
    _configure(monkeypatch, provider, tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://nexus.local", headers=_auth("alice")) as client:
        bot = (await client.post("/api/bots", json={
            "name": "Pixel", "instructions": "Responde com precisão",
            "provider": "lmstudio", "model": "model-pixel",
        })).json()

        outside = tmp_path / "not-registered"
        outside.mkdir()
        response = await client.post("/api/chat", json={
            "session_id": bot["session_id"], "message": "Olá!",
            "project_path": str(outside),
        })
        assert response.status_code == 400, response.text


def test_memory_tools_are_always_granted_to_a_bot_that_may_remember() -> None:
    """Memory is the capability that matters most with no project."""
    from backend.orchestrator.routes.chat_primary import (
        _BOT_MEMORY_NO_PROJECT_TOOLS,
        _bot_capability_policy,
    )

    profile = {
        "capabilities": {
            "read": True, "research": True, "tasks": True, "memory": True,
            "write": False, "shell": False, "browser": False, "mcp": False,
            "auto_accept": False,
        }
    }
    _flags, granted = _bot_capability_policy(profile)
    assert granted >= _BOT_MEMORY_NO_PROJECT_TOOLS

    without_memory = {
        "capabilities": {
            "read": True, "research": False, "tasks": False, "memory": False,
            "write": False, "shell": False, "browser": False, "mcp": False,
            "auto_accept": False,
        }
    }
    _flags, granted_without = _bot_capability_policy(without_memory)
    assert not (_BOT_MEMORY_NO_PROJECT_TOOLS & granted_without)
