"""Bot profiles reuse sessions without granting tools or leaking across users."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from backend.middleware.auth import create_access_token
from backend.orchestrator.main import app
from backend.persistence.db import add_message, close_pool, get_messages, init_db


def _auth(user: str) -> dict[str, str]:
    token = create_access_token({"sub": user, "email": f"{user}@test.local"})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_profile_lifecycle_is_owner_scoped_and_durable() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://nexus.local") as client:
        assert (await client.get("/api/bots")).status_code == 401
        response = await client.post("/api/bots", headers=_auth("alice"), json={
            "name": "Pixel", "description": "UI", "instructions": "Sê preciso",
            "provider": "lmstudio", "model": "local-model",
        })
        assert response.status_code == 201, response.text
        bot = response.json()
        add_message(bot["session_id"], "user", "mensagem guardada")
        assert (await client.get("/api/bots", headers=_auth("bob"))).json() == {"bots": []}
        assert (await client.patch(f"/api/bots/{bot['id']}", headers=_auth("bob"), json={"name": "Outro"})).status_code == 404
        assert (await client.get(f"/api/sessions/{bot['session_id']}/messages", headers=_auth("bob"))).status_code == 404
        changed = await client.patch(f"/api/bots/{bot['id']}", headers=_auth("alice"), json={"model": "different-model", "archived": True})
        assert changed.json()["model"] == "different-model"
        assert changed.json()["archived"] is True
        assert (await client.delete(f"/api/sessions/{bot['session_id']}", headers=_auth("alice"))).status_code == 409

        # Restart the persistence layer against the same isolated SQLite file.
        close_pool()
        init_db()
        recovered = (await client.get(f"/api/bots/{bot['id']}", headers=_auth("alice"))).json()
        assert recovered["model"] == "different-model"
        assert recovered["last_message"] == "mensagem guardada"
        assert (await client.delete(f"/api/bots/{bot['id']}", headers=_auth("alice"))).status_code == 204
        assert (await client.get("/api/bots", headers=_auth("alice"))).json() == {"bots": []}
        assert get_messages(bot["session_id"])[0]["content"] == "mensagem guardada"
        assert (await client.post("/api/chat", headers=_auth("alice"), json={
            "session_id": bot["session_id"], "message": "Olá",
        })).status_code == 404


@pytest.mark.asyncio
async def test_bot_chat_pins_profile_and_keeps_mutating_tools_denied(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from backend.core import conversation_log
    from backend.orchestrator import advanced_modes
    from backend.orchestrator.context_manager import ContextStore
    from backend.orchestrator.routes import chat_primary

    class ScriptedProvider:
        """A controlled test double, never evidence of real-model inference."""

        provider_name = "lmstudio"
        last_finish_reason = "stop"
        last_usage: dict[str, int] = {}
        calls: list[dict[str, Any]] = []
        attack = False

        async def chat_stream(self, model: str, messages: list[dict], **kwargs: Any):
            self.calls.append({"model": model, "messages": messages, **kwargs})
            if self.attack:
                self.attack = False
                yield '```tool\n{"name":"write_file","arguments":{"path":"probe.txt","content":"oops"}}\n```'
                return
            yield "Resposta "
            yield "do teste."

    class NoModes:
        def build_active_execution_profile(self) -> dict:
            return {}

    provider = ScriptedProvider()
    monkeypatch.setenv("NEXUS_PRIMARY_ENABLED", "1")
    monkeypatch.setenv("NEXUS_EXPERIENCE_OFF", "1")
    monkeypatch.setenv("NEXUS_ADVISOR_ENABLED", "0")
    monkeypatch.setattr(chat_primary, "run_integration_enabled", lambda: False)
    monkeypatch.setattr(chat_primary, "_tool_policy_context", lambda *_a, **_kw: {"_allowed_tools": ("write_file",)})
    monkeypatch.setattr(advanced_modes, "get_orchestrator", lambda: NoModes())
    monkeypatch.setattr(conversation_log, "_DEFAULT_LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(app.state, "llm_client", provider, raising=False)
    monkeypatch.setattr(app.state, "context", ContextStore(), raising=False)
    monkeypatch.setattr(app.state, "event_bus", None, raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://nexus.local", headers=_auth("alice")) as client:
        bot = (await client.post("/api/bots", json={"name": "Pixel", "instructions": "Responde com precisão", "provider": "lmstudio", "model": "model-pixel"})).json()
        response = await client.post("/api/chat", json={
            "session_id": bot["session_id"], "message": "Olá!", "mode": "autonomous",
            "autonomous": True, "provider": "openai", "model": "wrong-model",
            "swarm_agents": ["CODER"],
        })
        assert response.status_code == 200, response.text
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert not [frame for frame in frames if frame["type"] == "error"], frames
        assert "".join(frame.get("content", "") for frame in frames if frame["type"] == "token") == "Resposta do teste."
        assert any(frame["type"] == "done" for frame in frames)
        assert provider.calls and all(call["model"] == "model-pixel" for call in provider.calls)
        advertised = provider.calls[0].get("options", {}).get("tools") or []
        advertised_names = {tool.get("function", {}).get("name") for tool in advertised}
        assert "write_file" not in advertised_names
        assert "execute_shell" not in advertised_names
        assert "Responde com precisão" in provider.calls[0]["messages"][0]["content"]
        assert [row["role"] for row in get_messages(bot["session_id"])] == ["user", "assistant"]

        # A model can emit a tool call even when none was advertised. The
        # execution layer must refuse it, not merely hide it from the prompt.
        from backend.agents import base as agent_base

        executions: list[str] = []

        async def record_execution(name: str, *_args: Any, **_kwargs: Any) -> dict:
            executions.append(name)
            return {"ok": True}

        monkeypatch.setattr(agent_base, "execute_tool", record_execution)
        provider.attack = True
        denied = await client.post("/api/chat", json={
            "session_id": bot["session_id"], "message": "Tenta usar uma ferramenta.",
        })
        denied_frames = [json.loads(line[6:]) for line in denied.text.splitlines() if line.startswith("data: ")]
        assert any(frame["type"] == "tool_error" for frame in denied_frames), denied_frames
        assert executions == []
        assert not (tmp_path / "probe.txt").exists()


@pytest.mark.asyncio
async def test_isolated_bot_does_not_touch_shared_agent_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.agents.base import AgentBase, AgentRequest
    from backend.core import agent_state

    def forbidden_store() -> None:
        raise AssertionError("a bot must not access the shared agent brain")

    class Agent(AgentBase):
        name = "NEXUS"
        model_key = "coder"
        prompt_file = "nexus_primary"
        supported_actions = set()

        async def _execute(self, _request: AgentRequest):
            yield "ok"

    monkeypatch.setattr(agent_state, "AgentStateStore", forbidden_store)
    request = AgentRequest(session_id="isolated-bot", query="hello", client=object(),
                           context={"_isolated_bot_conversation": True})
    assert [token async for token in Agent().run(request)] == ["ok"]


@pytest.mark.asyncio
async def test_bot_tools_remain_denied_when_advanced_policy_fails(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from backend.agents import base as agent_base
    from backend.core import conversation_log
    from backend.orchestrator import advanced_modes
    from backend.orchestrator.context_manager import ContextStore
    from backend.orchestrator.routes import chat_primary

    executions: list[str] = []

    class Provider:
        provider_name = "lmstudio"
        last_finish_reason = "stop"
        last_usage: dict[str, int] = {}

        async def chat_stream(self, model: str, messages: list[dict], **kwargs: Any):
            yield '```tool\n{"name":"recall_context","arguments":{"query":"test"}}\n```'

    async def record_execution(name: str, *_args: Any, **_kwargs: Any) -> dict:
        executions.append(name)
        return {"ok": True}

    def unavailable():
        raise RuntimeError("policy unavailable")

    monkeypatch.setenv("NEXUS_PRIMARY_ENABLED", "1")
    monkeypatch.setenv("NEXUS_EXPERIENCE_OFF", "1")
    monkeypatch.setenv("NEXUS_ADVISOR_ENABLED", "0")
    monkeypatch.setattr(chat_primary, "run_integration_enabled", lambda: False)
    monkeypatch.setattr(advanced_modes, "get_orchestrator", unavailable)
    monkeypatch.setattr(agent_base, "execute_tool", record_execution)
    monkeypatch.setattr(conversation_log, "_DEFAULT_LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(app.state, "llm_client", Provider(), raising=False)
    monkeypatch.setattr(app.state, "context", ContextStore(), raising=False)
    monkeypatch.setattr(app.state, "event_bus", None, raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=_auth("policy-user")) as client:
        bot = (await client.post("/api/bots", json={"name": "B", "provider": "lmstudio", "model": "m"})).json()
        response = await client.post("/api/chat", json={"session_id": bot["session_id"], "message": "Recorda o contexto"})
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert any(frame["type"] == "tool_error" for frame in frames), frames
        assert executions == []


@pytest.mark.asyncio
async def test_bot_conversation_receives_selected_project_memory(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from backend.core import conversation_log
    from backend.knowledge import project_continuity, project_memory
    from backend.orchestrator import advanced_modes
    from backend.orchestrator.context_manager import ContextStore
    from backend.orchestrator.routes import chat_primary, files

    messages_seen: list[list[dict]] = []
    owners: list[str] = []

    class Provider:
        provider_name = "lmstudio"
        last_finish_reason = "stop"
        last_usage: dict[str, int] = {}

        async def chat_stream(self, model: str, messages: list[dict], **kwargs: Any):
            messages_seen.append(messages)
            yield "Olá"

    class NoModes:
        def build_active_execution_profile(self) -> dict:
            return {}

    def load_continuity(*_args: Any, **kwargs: Any):
        owners.append(kwargs["owner_id"])
        return None, ""

    monkeypatch.setenv("NEXUS_PRIMARY_ENABLED", "1")
    monkeypatch.setenv("NEXUS_EXPERIENCE_OFF", "1")
    monkeypatch.setenv("NEXUS_ADVISOR_ENABLED", "0")
    monkeypatch.setattr(chat_primary, "run_integration_enabled", lambda: False)
    monkeypatch.setattr(advanced_modes, "get_orchestrator", lambda: NoModes())
    monkeypatch.setattr(files, "_resolve_project_root", lambda *_args: tmp_path)
    monkeypatch.setattr(project_continuity, "load_project_continuity", load_continuity)
    monkeypatch.setattr(project_continuity, "ProjectContinuityStore", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(project_continuity, "combine_project_context", lambda memory, _continuity: memory)
    monkeypatch.setattr(project_memory, "read_project_memory", lambda _path: "PROJECT_MEMORY_SENTINEL")
    monkeypatch.setattr(conversation_log, "_DEFAULT_LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(app.state, "llm_client", Provider(), raising=False)
    monkeypatch.setattr(app.state, "context", ContextStore(), raising=False)
    monkeypatch.setattr(app.state, "event_bus", None, raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=_auth("memory-user")) as client:
        bot = (await client.post("/api/bots", json={"name": "B", "provider": "lmstudio", "model": "m"})).json()
        response = await client.post("/api/chat", json={"session_id": bot["session_id"], "message": "Olá", "project_path": "registered-project"})
        assert response.status_code == 200
        assert owners == ["memory-user"]
        assert any("PROJECT_MEMORY_SENTINEL" in str(message.get("content")) for call in messages_seen for message in call)


@pytest.mark.asyncio
async def test_cancellation_interrupts_the_bot_pipeline_pump(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.models.api import ChatRequest
    from backend.orchestrator.cancellation import CancellationRegistry
    from backend.orchestrator.routes import chat, chat_primary

    registry = CancellationRegistry()
    request_id = await registry.register("bot-cancel-request")
    request = SimpleNamespace(headers={}, state=SimpleNamespace(
        nexus_request_id=request_id, nexus_bot_profile={"name": "Pixel"},
    ))
    entered = asyncio.Event()
    interrupted = asyncio.Event()

    async def blocked_primary(*_args: Any, **_kwargs: Any):
        yield 'data: {"type":"routing"}\n\n'
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            interrupted.set()
            raise

    monkeypatch.setattr(chat, "get_cancellation_registry", lambda: registry)
    monkeypatch.setattr(chat_primary, "is_primary_enabled", lambda: True)
    monkeypatch.setattr(chat_primary, "run_primary_chat", blocked_primary)
    req = ChatRequest(message="Olá", session_id="bot-session")

    async def consume() -> None:
        async for _frame in chat._select_pipeline(req, None, None, None, request=request, user_id="alice"):
            pass

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert await registry.cancel(request_id)
        # Match the middleware cleanup race seen in the live browser.
        await registry.unregister(request_id)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert interrupted.is_set()
    finally:
        await registry.shutdown()
