"""Opt-in real-model probe; it never contacts a non-loopback provider.

This is intentionally not part of the ordinary mocked test suite. It uses a
copy of a NEXUS module and an isolated test database/project/journal.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest


@pytest.mark.asyncio
async def test_local_model_agentic_acceptance(tmp_path: Path, monkeypatch) -> None:
    endpoint = os.environ.get("NEXUS_LOCAL_ACCEPTANCE_URL", "")
    if not endpoint:
        pytest.skip("real local model acceptance is opt-in")
    assert urlparse(endpoint).hostname in {"127.0.0.1", "localhost", "::1"}
    artifact_dir = Path(os.environ["NEXUS_LOCAL_ACCEPTANCE_ARTIFACTS"])
    assert artifact_dir.is_dir()

    from backend.core import conversation_log
    from backend.knowledge.memory import EmbeddingService
    from backend.llm.lmstudio_provider import LMStudioProvider
    from backend.models.api import ChatRequest
    from backend.orchestrator import advanced_modes
    from backend.orchestrator.context_manager import ContextStore
    from backend.orchestrator.registry import get_registry
    from backend.orchestrator.routes import chat_primary
    from backend.runtime import events as runtime_events

    root = Path(__file__).resolve().parents[2]
    project = tmp_path / "nexus-module-copy"
    project.mkdir()
    source_path = Path(os.environ.get("NEXUS_LOCAL_ACCEPTANCE_SOURCE") or
                       root / "runtime" / "activity_redaction.py")
    source = source_path.read_text(encoding="utf-8")
    module = project / "redaction.py"
    module.write_text(source, encoding="utf-8")
    tests = project / "tests"
    tests.mkdir()
    (tests / "test_redaction.py").write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(root.parent)!r})\n"
        "from redaction import is_sensitive_file_request\n\n"
        "def test_git_credentials_is_sensitive():\n"
        "    assert is_sensitive_file_request({'path': '.git-credentials'})\n",
        encoding="utf-8",
    )
    (project / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")

    monkeypatch.setenv("NEXUS_EVENT_JOURNAL", "1")
    monkeypatch.setenv("NEXUS_ADVISOR_ENABLED", "0")
    monkeypatch.setenv("NEXUS_EXPERIENCE_OFF", "1")
    monkeypatch.setenv("NEXUS_REASONING_VISIBILITY", "off")
    monkeypatch.setenv("NEXUS_PRIMARY_MAX_CYCLES", "2")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setattr(runtime_events, "run_event_journal_path", lambda run_id: artifact_dir / f"{run_id}.jsonl")
    monkeypatch.setattr(conversation_log, "_DEFAULT_LOG_DIR", tmp_path / "conversation-logs")
    monkeypatch.setattr(chat_primary, "run_integration_enabled", lambda: False)
    allowed = ("read_file", "read_multiple_files", "list_dir", "search_in_files",
               "write_file", "run_tests", "spawn_task")
    monkeypatch.setattr(chat_primary, "_tool_policy_context", lambda *_args, **_kwargs: {"_allowed_tools": allowed})

    async def local_embedding(self, text):
        return self._fallback_embed(text)

    monkeypatch.setattr(EmbeddingService, "embed", local_embedding)

    class NoActiveModes:
        def build_active_execution_profile(self):
            return {}

        def prepare_active_execution_profile(self, _message):
            return {}

    monkeypatch.setattr(advanced_modes, "get_orchestrator", lambda: NoActiveModes())
    model = os.environ.get("NEXUS_LOCAL_ACCEPTANCE_MODEL", "nexus-local-validation")
    provider = LMStudioProvider(base_url=endpoint, api_key=os.environ.get("NEXUS_LOCAL_ACCEPTANCE_API_KEY", ""),
                                default_model=model, fast_model=model, coder_model=model)
    message = (
        "Analisa o módulo redaction.py, copiado do NEXUS. O teste em tests/test_redaction.py "
        "reproduz um problema: .git-credentials deve ser tratado como ficheiro sensível. "
        "Lê o módulo, pesquisa o código, delega a análise e revisão a dois subagentes, "
        "corrige o ficheiro e executa os testes. Comunica os resultados reais e limitações. "
        "Trabalha apenas neste projeto temporário e não uses serviços externos. "
        "Usa os caminhos relativos redaction.py e tests/test_redaction.py, sem os tornar absolutos."
    )
    request = ChatRequest(message=message, session_id="local-acceptance", mode="assisted",
                          project_path=str(project), provider="lmstudio", model=model,
                          model_is_concrete=True, autonomous=True)
    decision = chat_primary.plan_turn(message, "assisted", str(project))
    frames: list[dict] = []
    started = time.monotonic()
    timed_out = False
    try:
        async with asyncio.timeout(180):
            async for raw in chat_primary.run_primary_chat(
                request, provider, get_registry(), ContextStore(), decision=decision,
                owner_id="local-acceptance",
            ):
                if raw.startswith("data: "):
                    frames.append(json.loads(raw[6:].strip()))
    except TimeoutError:
        timed_out = True
    finally:
        await provider.aclose()
        (artifact_dir / "frames.json").write_text(json.dumps(frames, ensure_ascii=False, indent=2), encoding="utf-8")
        after = module.read_text(encoding="utf-8")
        (artifact_dir / "module.diff").write_text(
            "".join(difflib.unified_diff(source.splitlines(keepends=True), after.splitlines(keepends=True),
                                         fromfile="before/redaction.py", tofile="after/redaction.py")),
            encoding="utf-8",
        )
        calls = [item.get("tool_name") for item in frames if item.get("type") == "tool_call"]
        children = [item for item in frames if item.get("type") == "agent_started"
                    and item.get("data", {}).get("kind") == "subagent_started"]
        summary = {"model": model, "duration_seconds": round(time.monotonic() - started, 1),
                   "timed_out": timed_out, "calls": calls, "children_started": len(children),
                   "text_frames": sum(item.get("type") == "token" for item in frames),
                   "terminal_errors": [item.get("content") for item in frames if item.get("type") == "error"],
                   "module_changed": source != after,
                   "project_copy": str(project), "model_server": endpoint}
        (artifact_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.copy2(module, artifact_dir / "redaction-after.py")
        shutil.copy2(tests / "test_redaction.py", artifact_dir / "test_redaction.py")

    assert not timed_out, "The real local-model probe exceeded 180 seconds"
    assert "read_file" in calls, f"The model did not read the module: {calls}"
    assert len(children) >= 2, f"Fewer than two real subagents started: {len(children)}"
    assert source != after, "The model did not modify the temporary module"
    assert "run_tests" in calls, f"The model did not invoke the test tool: {calls}"


@pytest.mark.asyncio
async def test_local_model_http_chat_and_recovery(tmp_path: Path, monkeypatch) -> None:
    """Exercise the HTTP app and durable replay with a real loopback model.

    ASGITransport buffers the response, so this checks the SSE payload and
    replay but does not establish timing or live browser streaming.
    """
    endpoint = os.environ.get("NEXUS_LOCAL_ACCEPTANCE_URL", "")
    if not endpoint:
        pytest.skip("real local model acceptance is opt-in")
    assert urlparse(endpoint).hostname in {"127.0.0.1", "localhost", "::1"}
    artifact_dir = Path(os.environ["NEXUS_LOCAL_ACCEPTANCE_ARTIFACTS"])
    assert artifact_dir.is_dir()

    import httpx

    from backend.core import conversation_log
    from backend.knowledge.memory import EmbeddingService
    from backend.llm.lmstudio_provider import LMStudioProvider
    from backend.middleware.auth import create_access_token
    from backend.orchestrator import main as main_module
    from backend.orchestrator.context_manager import ContextStore
    from backend.orchestrator.routes import chat_primary
    from backend.persistence.db import get_messages, get_session_run
    from backend.runtime import events as runtime_events

    monkeypatch.setenv("NEXUS_EVENT_JOURNAL", "1")
    monkeypatch.setenv("NEXUS_PRIMARY_ENABLED", "1")
    monkeypatch.setenv("NEXUS_ADVISOR_ENABLED", "0")
    monkeypatch.setenv("NEXUS_EXPERIENCE_OFF", "1")
    monkeypatch.setenv("NEXUS_REASONING_VISIBILITY", "off")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setattr(runtime_events, "run_event_journal_path", lambda run_id: artifact_dir / f"{run_id}.jsonl")
    monkeypatch.setattr(conversation_log, "_DEFAULT_LOG_DIR", tmp_path / "conversation-logs")
    monkeypatch.setattr(chat_primary, "run_integration_enabled", lambda: False)
    monkeypatch.setattr(chat_primary, "_tool_policy_context", lambda *_args, **_kwargs: {"_allowed_tools": ()})

    async def local_embedding(self, text):
        return self._fallback_embed(text)

    monkeypatch.setattr(EmbeddingService, "embed", local_embedding)
    model = os.environ.get("NEXUS_LOCAL_ACCEPTANCE_MODEL", "nexus-local-validation")
    provider = LMStudioProvider(base_url=endpoint, api_key=os.environ.get("NEXUS_LOCAL_ACCEPTANCE_API_KEY", ""),
                                default_model=model, fast_model=model, coder_model=model)
    app = main_module.app
    monkeypatch.setattr(app.state, "llm_client", provider, raising=False)
    monkeypatch.setattr(app.state, "context", ContextStore(), raising=False)
    monkeypatch.setattr(app.state, "event_bus", None, raising=False)
    token = create_access_token({"sub": "local-acceptance", "email": "local@example.test"})
    session_id = "local-http-acceptance"
    frames: list[dict] = []
    replay: list[dict] = []
    history: dict = {}

    def parse_events(body: str) -> list[dict]:
        return [json.loads(line[6:].strip()) for line in body.splitlines() if line.startswith("data: ")]

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://nexus.local",
                                     headers={"Authorization": f"Bearer {token}"}) as client:
            async with asyncio.timeout(120):
                response = await client.post("/api/chat", json={
                    "message": "Olá! Responde de forma curta em português.",
                    "session_id": session_id, "mode": "ask", "autonomous": False,
                    "provider": "lmstudio", "model": model, "model_is_concrete": True,
                })
            assert response.status_code == 200
            frames = parse_events(response.text)
            run_id = next((str(frame.get("run_id") or frame.get("data", {}).get("run_id") or "")
                           for frame in frames if frame.get("run_id") or frame.get("data", {}).get("run_id")), "")
            assert run_id, "No run ID was returned by the real-model chat"
            assert any(frame.get("type") == "token" and frame.get("content") for frame in frames)
            live_answer = "".join(str(frame.get("content") or "") for frame in frames
                                  if frame.get("type") == "token")
            assert not any(frame.get("type") == "error" for frame in frames)
            assert any(frame.get("type") == "done" for frame in frames)
            run = get_session_run(run_id)
            assert run and run["status"] == "completed"
            assert any(message.get("role") == "assistant" and message.get("run_id") == run_id
                       for message in get_messages(session_id))

            monkeypatch.setattr(app.state, "context", ContextStore(), raising=False)
            history_response = await client.get(f"/api/sessions/{session_id}/history")
            assert history_response.status_code == 200
            history = history_response.json()
            recovered_answers = [message.get("content") for message in history["messages"]
                                 if message.get("role") == "assistant" and message.get("run_id") == run_id]
            assert recovered_answers == [live_answer]
            replay_response = await client.get(f"/api/sessions/{session_id}/events", params={"run_id": run_id})
            assert replay_response.status_code == 200
            replay = parse_events(replay_response.text)
            assert any(frame.get("type") == "token" and frame.get("content") for frame in replay)
            replayed_answer = "".join(str(frame.get("content") or "") for frame in replay
                                      if frame.get("type") == "token")
            assert replayed_answer == live_answer
            assert any(frame.get("type") == "done" for frame in replay)
    finally:
        await provider.aclose()
        (artifact_dir / "http-frames.json").write_text(json.dumps(frames, ensure_ascii=False, indent=2), encoding="utf-8")
        (artifact_dir / "http-replay.json").write_text(json.dumps(replay, ensure_ascii=False, indent=2), encoding="utf-8")
        (artifact_dir / "http-history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
