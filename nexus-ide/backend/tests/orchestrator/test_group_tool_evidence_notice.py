"""Group prose is not tool evidence.

The composer now runs through the primary runtime, which records real tool
calls in the group projection. A model sentence claiming it ran something must
not be presented as a verified action when no tool call exists.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from backend.middleware.auth import create_access_token
from backend.orchestrator.main import app


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

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[str] = []

    async def chat_stream(self, model: str, _messages: list[dict], **_kwargs: Any):
        self.calls.append(model)
        yield self.reply


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


@pytest.mark.asyncio
async def test_false_tool_claim_is_marked_as_unverified_in_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    provider = ScriptedProvider("Corri os testes e passaram.")
    _configure(monkeypatch, provider, tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
        headers=_auth("evidence-owner"),
    ) as client:
        registered = await client.post(
            "/api/projects", json={"name": "evidence", "path": str(project)}
        )
        assert registered.status_code in {200, 201}, registered.text
        ids = []
        for name in ("Um", "Dois"):
            response = await client.post("/api/bots", json={
                "name": name, "provider": "lmstudio", "model": "test-model",
            })
            assert response.status_code == 201, response.text
            ids.append(response.json()["id"])
        group = await client.post("/api/bot-groups", json={
            "name": "Evidência", "bot_ids": ids,
        })
        group_id = group.json()["id"]
        response = await client.post(
            f"/api/bot-groups/{group_id}/messages",
            json={"message": "Corre os testes", "project_path": str(project)},
        )
        frames = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        # The primary runtime may or may not reach this answer through a tool
        # call. What matters is the evidence the group projection recorded.
        runs = (await client.get(f"/api/bot-groups/{group_id}/runs")).json()["runs"]
        run_id = frames[0]["run_id"]
        run = next(item for item in runs if item["id"] == run_id)
        tool_records = [
            record for record in run["records"] if record["kind"].startswith("tool_")
        ]
        history = (
            await client.get(f"/api/bot-groups/{group_id}/messages")
        ).json()["messages"]
        assert [item["role"] for item in history[:1]] == ["user"]
        if not tool_records:
            assert "nenhuma ferramenta foi executada" in history[-1]["content"]
        else:
            assert "**Ferramentas:**" in history[-1]["content"]
