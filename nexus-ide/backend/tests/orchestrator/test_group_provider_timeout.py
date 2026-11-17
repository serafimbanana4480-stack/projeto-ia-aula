"""A stalled selected bot must fail the turn, not wake another participant.

The composer now owns one execution. There is no "next participant" to take
over a timeout: switching bots here would be the silent fallback the closeout
contract forbids. The primary runtime's per-signal timeout bounds the wait.
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


def _auth(name: str) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': name, 'email': name + '@test.local'})}"
        )
    }


class SelectedProvider:
    provider_name = "lmstudio"
    last_finish_reason = "stop"
    last_usage: dict[str, int] = {}

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.cancelled = asyncio.Event()

    async def chat_stream(self, model: str, _messages: list[dict], **_kwargs: Any):
        self.calls.append(model)
        if model == "stalled":
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
        yield "Resposta do bot disponível"


class _NoModes:
    def build_active_execution_profile(self) -> dict:
        return {}

    def prepare_active_execution_profile(self, _message: str) -> dict:
        return {}


def _configure(monkeypatch: pytest.MonkeyPatch, providers: dict[str, Any], tmp_path) -> None:
    from backend.core import conversation_log
    from backend.orchestrator import advanced_modes
    from backend.orchestrator.context_manager import ContextStore

    monkeypatch.setenv("NEXUS_PRIMARY_ENABLED", "1")
    monkeypatch.setenv("NEXUS_EXPERIENCE_OFF", "1")
    monkeypatch.setenv("NEXUS_ADVISOR_ENABLED", "0")
    monkeypatch.setenv("NEXUS_NATIVE_TOOL_CALLING", "0")
    monkeypatch.setenv("NEXUS_RUN_LIFECYCLE", "1")
    monkeypatch.setenv("NEXUS_PRIMARY_SIGNAL_TIMEOUT", "8.0")
    monkeypatch.setattr(advanced_modes, "get_orchestrator", lambda: _NoModes())
    monkeypatch.setattr(conversation_log, "_DEFAULT_LOG_DIR", tmp_path / "logs")
    manager = SimpleNamespace(providers=providers, free_only=False, provider_name="lmstudio")
    monkeypatch.setattr(app.state, "llm_client", manager, raising=False)
    monkeypatch.setattr(app.state, "context", ContextStore(), raising=False)


@pytest.mark.asyncio
async def test_stalled_selected_provider_fails_without_waking_the_other_bot(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    selected = SelectedProvider()
    _configure(monkeypatch, {"lmstudio": selected}, tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
        headers=_auth("timeout-owner"),
    ) as client:
        first = await client.post(
            "/api/bots", json={"name": "Primeiro", "provider": "lmstudio", "model": "stalled"},
        )
        second = await client.post(
            "/api/bots", json={"name": "Segundo", "provider": "lmstudio", "model": "working"},
        )
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        group = await client.post(
            "/api/bot-groups",
            json={"name": "Timeout", "bot_ids": [first.json()["id"], second.json()["id"]]},
        )
        group_id = group.json()["id"]
        response = await client.post(
            f"/api/bot-groups/{group_id}/messages",
            json={"message": "@Primeiro analisa isto"},
        )
        frames = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        assert frames[-1]["type"] == "done"
        assert frames[-1]["status"] == "failed", frames[-1]
        assert selected.calls, [frames[3].get("reason"), frames[3].get("message")]
        assert set(selected.calls) == {"stalled"}
        assert "working" not in selected.calls
        history = (
            await client.get(f"/api/bot-groups/{group_id}/messages")
        ).json()["messages"]
        assert [item["role"] for item in history] == ["user", "error"]
        detail = history[-1]["content"].lower()
        assert "fornecedor" in detail or "tempo" in detail or "provider" in detail
