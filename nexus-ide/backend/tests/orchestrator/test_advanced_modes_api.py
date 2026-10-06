"""Infinity contracts use isolated state; no providers or background workers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.middleware.auth import require_auth
from backend.orchestrator import advanced_modes as modes
from backend.orchestrator.routes import advanced_modes as routes


@pytest.fixture
def orchestrator(tmp_path, monkeypatch):
    for constant, name in (
        ("ADVANCED_MODES_STATE_DIR", "sessions"),
        ("CHECKPOINT_DIR", "checkpoints"),
        ("TRAJECTORY_DIR", "trajectories"),
        ("EVIDENCE_DIR", "evidence"),
    ):
        directory = tmp_path / name
        directory.mkdir()
        monkeypatch.setattr(modes, constant, directory)
    manager = modes.ModeStateManager()
    monkeypatch.setattr(modes, "_state_manager", manager)
    orch = modes.AdvancedModeOrchestrator()
    monkeypatch.setattr(modes, "_orchestrator", orch)
    monkeypatch.setattr(routes, "_get_orch", lambda: orch)
    return orch


@pytest.fixture
def client(orchestrator):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[require_auth] = lambda: {"sub": "isolated-infinity-test"}
    with TestClient(app) as test_client:
        yield test_client


def test_all_eleven_modes_activate_resolve_prepare_reload_and_deactivate(client, orchestrator):
    catalog = modes.get_advanced_modes()
    assert len(catalog) == 11
    for mode_id in catalog:
        endpoint = f"/api/advanced-modes/{mode_id}"
        first = client.post(f"{endpoint}/activate").json()
        second = client.post(f"{endpoint}/activate").json()
        assert first["success"] is True
        assert second["session_id"] == first["session_id"]
        status = client.get(endpoint).json()
        assert status["active_session_count"] == 1
        assert status["execution_target"]["kind"] != "unknown"
        assert status["activity_evidence_status"] == "NOT_MEASURED"
        assert status["limitations"]
        resolved = client.get("/api/commands/resolve", params={"command": f"/{mode_id}"})
        assert resolved.status_code == 200
        assert resolved.json()["resolved_to"] == mode_id
        prepared = client.post(f"{endpoint}/context", json={"request": "Validate the isolated feature"})
        assert prepared.status_code == 200
        payload = prepared.json()
        session = client.get(f"{endpoint}/sessions/{payload['session_id']}").json()
        assert payload["goal_id"] in session["goal_tree"]
        assert session["checkpoint_count"] == 1
        assert session["trajectory_count"] == 2  # activation + request
        reloaded = modes.ModeStateManager().get_session(mode_id, first["session_id"])
        assert reloaded is not None and payload["goal_id"] in reloaded.goal_tree
        assert client.post(f"{endpoint}/deactivate").json()["success"] is True
        assert client.get(endpoint).json()["active"] is False
    assert orchestrator.state_manager.list_active_modes() == []


def test_health_read_is_non_mutating_and_does_not_claim_runtime_execution(client, orchestrator):
    before = list(modes.ADVANCED_MODES_STATE_DIR.iterdir())
    data = client.get("/api/advanced-modes/health").json()
    assert data["healthy"] is True
    assert data["activity_evidence_status"] == "NOT_MEASURED"
    assert data["catalog_evidence_scope"] == "configuration_and_persisted_sessions"
    assert "disk_guard" in data
    assert data["execution_profile"]["primary_mode"] is None
    assert list(modes.ADVANCED_MODES_STATE_DIR.iterdir()) == before

    summaries = data["modes"]
    assert "/spawn" in summaries["vibe-infinity"]["runtime_summary"]
    assert "persist locally per chat" in summaries["vibe-infinity"]["runtime_summary"]
    assert "never rerun automatically" in summaries["vibe-infinity"]["runtime_summary"]
    assert "NEXUS_VIBE_STATE_ROOT" in summaries["vibe-infinity"]["limitations"]
    assert "/advisor-infinity review" in summaries["advisor-infinity"]["runtime_summary"]
    assert "/multiverse rank" in summaries["multiverse"]["runtime_summary"]
    assert "/sentinel gate" in summaries["sentinel"]["runtime_summary"]


@pytest.mark.parametrize("path", ["missing", "missing/sessions", "missing/sessions/session"])
def test_unknown_mode_is_not_an_empty_success(client, path):
    assert client.get(f"/api/advanced-modes/{path}").status_code == 404


def test_context_rejects_unknown_mode_and_blank_request(client):
    assert client.post("/api/advanced-modes/missing/context", json={"request": "do work"}).status_code == 404
    assert client.post("/api/advanced-modes/forge/context", json={"request": " "}).status_code == 400


def test_active_mode_with_missing_config_fails_closed(orchestrator, monkeypatch):
    monkeypatch.setattr(
        orchestrator.state_manager,
        "list_active_modes",
        lambda: ["removed-but-still-armed"],
    )

    with pytest.raises(RuntimeError, match="configuration is unavailable"):
        orchestrator.build_active_execution_profile()


def test_deactivation_preserves_completed_and_failed_history(orchestrator):
    active = orchestrator.state_manager.create_session("forge")
    completed = orchestrator.state_manager.create_session("forge")
    completed.state = modes.ModeState.COMPLETED
    orchestrator.state_manager.update_session(completed)
    assert orchestrator.state_manager.is_mode_active("forge")  # another session remains armed
    failed = orchestrator.state_manager.create_session("forge")
    failed.state = modes.ModeState.FAILED
    orchestrator.state_manager.update_session(failed)
    before = modes.ADVANCED_MODES_STATE_DIR.joinpath(f"forge__{completed.session_id}.json").read_bytes()
    orchestrator.deactivate_mode("forge")
    assert active.state is modes.ModeState.INACTIVE
    assert completed.state is modes.ModeState.COMPLETED
    assert failed.state is modes.ModeState.FAILED
    assert modes.ADVANCED_MODES_STATE_DIR.joinpath(f"forge__{completed.session_id}.json").read_bytes() == before


def test_advisor_rejects_missing_session_keywords_and_false_evidence(client):
    body = {"session_id": "missing", "claim": "tests security documentation regression edge cases all pass"}
    assert client.post("/api/advanced-modes/advisor-infinity/review", json=body).status_code == 404
    activated = client.post("/api/advanced-modes/advisor-infinity/activate").json()
    body["session_id"] = activated["session_id"]
    body["evidence"] = {"tests_passed": "false", "security_reviewed": {"status": ["PASS"]}, "irrelevant": True}
    result = client.post("/api/advanced-modes/advisor-infinity/review", json=body).json()
    assert result["blocked"] is True
    assert len(result["missing"]) == 5
    assert result["evidence_status"] == "UNVERIFIED"
    assert result["confidence"] is None


@pytest.mark.parametrize("risk", [-1, 5, True, "2"])
def test_sentinel_rejects_invalid_risk(client, risk):
    assert client.post("/api/advanced-modes/sentinel/check", json={"action": "read file", "risk_level": risk}).status_code == 422


def test_sentinel_install_requires_approval_and_windows_delete_is_detected(client):
    review = client.post("/api/advanced-modes/sentinel/check", json={"action": "Install a package", "risk_level": 2}).json()
    assert review["gate_passed"] is False and review["requires_approval"] is True
    dangerous = client.post("/api/advanced-modes/sentinel/check", json={"action": "Remove-Item -Recurse C:/project", "risk_level": 0}).json()
    assert dangerous["gate_passed"] is False
    safe = client.post("/api/advanced-modes/sentinel/check", json={"action": "Read src/main.py", "risk_level": 0}).json()
    assert safe["gate_passed"] is True
    assert safe["check_kind"] == "static_risk_check"
    assert client.post("/api/advanced-modes/sentinel/check", json={"action": " "}).status_code == 422


def test_multiverse_validates_scores_weights_and_does_not_invent_winners(client):
    endpoint = "/api/advanced-modes/multiverse/evaluate"
    entries = [{"id": "a", "name": "A", "scores": {"security": 80}}, {"id": "b", "name": "B", "scores": {"security": 40}}]
    result = client.post(endpoint, json={"entries": entries, "weights": {"security": 7}}).json()
    assert result["winner"] == "a" and result["winner_score"] == 80
    assert result["entries"][1]["scores"]["security"] == 40  # no relative inflation
    assert result["execution_evidence_status"] == "NOT_MEASURED"
    entries[1]["scores"]["security"] = 80
    tied = client.post(endpoint, json={"entries": entries, "weights": {"security": 1}}).json()
    assert tied["winner"] is None and tied["status"] == "TIE"
    entries[1]["scores"] = {}
    assert client.post(endpoint, json={"entries": entries, "weights": {"security": 1}}).status_code == 422
    entries[1]["scores"] = {"security": 101}
    assert client.post(endpoint, json={"entries": entries, "weights": {"security": 1}}).status_code == 422
    assert client.post(endpoint, json={"entries": [], "weights": {"security": -1}}).status_code == 422
    entries[1]["scores"] = {"security": 40}
    large_weights = client.post(
        endpoint, json={"entries": entries, "weights": {"security": 1e308}}
    ).json()
    assert large_weights["winner_score"] == 80  # finite input cannot overflow into Infinity


@pytest.mark.asyncio
@pytest.mark.parametrize("command", [f"/{mid}" for mid in modes.get_advanced_modes()])
async def test_explicit_advanced_command_reaches_its_adapter(monkeypatch, orchestrator, command):
    from backend.orchestrator.routes import chat

    seen = []
    async def legacy(*args):
        seen.append(args[0].message)
        yield "legacy-mode-adapter"
    monkeypatch.setattr(chat, "_run_pipeline", legacy)
    req = SimpleNamespace(message=f"{command} inspect main.py", session_id="isolated-command", mode="auto", project_path="")
    frames = [frame async for frame in chat._select_pipeline(req, None, None, None)]
    assert frames == ["legacy-mode-adapter"]
    assert seen == [req.message]


@pytest.mark.asyncio
async def test_armed_composite_routes_project_work_but_keeps_questions_primary(monkeypatch, orchestrator):
    from backend.orchestrator.routes import chat, chat_primary

    orchestrator.activate_mode("autonomous")
    async def legacy(*_args):
        yield "plan-execute-verify"
    async def primary(*_args, **_kwargs):
        yield "primary-question"
    monkeypatch.setattr(chat, "_run_pipeline", legacy)
    monkeypatch.setattr(chat_primary, "run_primary_chat", primary)
    monkeypatch.setattr(chat_primary, "is_primary_enabled", lambda: True)
    req = SimpleNamespace(message="Implement the selected feature across this project with the required changes and validation", session_id="isolated-routing", mode="auto", project_path="C:/project")
    assert [frame async for frame in chat._select_pipeline(req, None, None, None)] == ["plan-execute-verify"]
    req.message = "Como funciona esta função?"
    assert [frame async for frame in chat._select_pipeline(req, None, None, None)] == ["primary-question"]
    req.message = "proof of concept: como funciona esta função?"
    assert [frame async for frame in chat._select_pipeline(req, None, None, None)] == ["primary-question"]


@pytest.mark.asyncio
async def test_primary_agent_receives_armed_policies_without_creating_question_goals(monkeypatch, orchestrator):
    from backend.orchestrator import registry
    from backend.orchestrator.routes import chat_primary

    orchestrator.activate_mode("evolve")
    captured = {}
    async def provider(_req, client):
        return client, None
    async def history(_session):
        return []
    def capture(**kwargs):
        captured.update(kwargs["agent_context"])
        raise RuntimeError("context inspected before any provider call")
    monkeypatch.setattr(registry, "resolve", lambda *_args: object())
    monkeypatch.setattr(chat_primary, "_request_provider_client", provider)
    monkeypatch.setattr(chat_primary, "make_signal_stream", capture)
    req = SimpleNamespace(message="Como funciona esta função?", session_id="isolated-policy", project_path="")
    decision = chat_primary.plan_turn(req.message, "auto", "")
    before = len(orchestrator.state_manager.get_session("evolve").goal_tree)
    with pytest.raises(RuntimeError, match="context inspected"):
        _ = [frame async for frame in chat_primary.run_primary_chat(req, object(), object(), SimpleNamespace(get_history=history), decision=decision)]
    assert "evolve" in captured["_system_addon"]
    assert captured["_advanced_profile"]["primary_mode"] == "evolve"
    assert captured["_allowed_tools"] == ()  # a policy does not widen tool access
    assert len(orchestrator.state_manager.get_session("evolve").goal_tree) == before


@pytest.mark.asyncio
async def test_primary_project_turn_receives_selected_mode_tool_contract(
    monkeypatch, orchestrator, tmp_path
):
    from backend.orchestrator import registry
    from backend.orchestrator.routes import chat_primary

    orchestrator.activate_mode("evolve")
    project = tmp_path / "project"
    project.mkdir()
    captured = {}

    async def provider(_req, client):
        return client, None

    async def history(_session):
        return []

    def capture(**kwargs):
        captured.update(kwargs["agent_context"])
        raise RuntimeError("context inspected before any provider call")

    monkeypatch.setattr(registry, "resolve", lambda *_args: object())
    monkeypatch.setattr(chat_primary, "_request_provider_client", provider)
    monkeypatch.setattr(chat_primary, "make_signal_stream", capture)
    req = SimpleNamespace(
        message="Implement a focused project change and verify it",
        session_id="isolated-mode-tools",
        project_path=str(project),
        model="",
    )
    decision = chat_primary.plan_turn(req.message, "auto", req.project_path)

    with pytest.raises(RuntimeError, match="context inspected"):
        _ = [
            frame
            async for frame in chat_primary.run_primary_chat(
                req,
                object(),
                object(),
                SimpleNamespace(get_history=history),
                decision=decision,
            )
        ]

    assert captured["_advanced_profile"]["primary_mode"] == "evolve"
    assert captured["_allowed_tools"] == modes.get_advanced_mode_tool_allowlist("evolve")


@pytest.mark.asyncio
async def test_primary_mode_policy_load_failure_disables_all_tools(monkeypatch, tmp_path):
    from backend.orchestrator import registry
    from backend.orchestrator.routes import chat_primary

    project = tmp_path / "project"
    project.mkdir()
    captured = {}

    async def provider(_req, client):
        return client, None

    async def history(_session):
        return []

    def capture(**kwargs):
        captured.update(kwargs["agent_context"])
        raise RuntimeError("context inspected before any provider call")

    def fail_policy_load():
        raise RuntimeError("mode state unavailable")

    monkeypatch.setattr(modes, "get_orchestrator", fail_policy_load)
    monkeypatch.setattr(registry, "resolve", lambda *_args: object())
    monkeypatch.setattr(chat_primary, "_request_provider_client", provider)
    monkeypatch.setattr(chat_primary, "make_signal_stream", capture)
    req = SimpleNamespace(
        message="Implement and verify this project change",
        session_id="isolated-policy-failure",
        project_path=str(project),
        model="",
    )
    decision = chat_primary.plan_turn(req.message, "auto", req.project_path)

    with pytest.raises(RuntimeError, match="context inspected"):
        _ = [
            frame
            async for frame in chat_primary.run_primary_chat(
                req,
                object(),
                object(),
                SimpleNamespace(get_history=history),
                decision=decision,
            )
        ]

    assert captured["_allowed_tools"] == ()
    assert captured["_advanced_policy_unavailable"] is True
    assert "não pôde ser carregada" in captured["_system_addon"]


@pytest.mark.asyncio
async def test_primary_applies_the_configured_mode_iteration_ceiling(
    monkeypatch, orchestrator, tmp_path
):
    from backend.orchestrator import registry
    from backend.orchestrator.routes import chat_primary
    from backend.runtime.triage import RequestClass

    orchestrator.activate_mode("advisor-infinity")
    monkeypatch.setenv("NEXUS_PRIMARY_MAX_ITERATIONS", "40")
    project = tmp_path / "project"
    project.mkdir()
    captured = {}

    async def provider(_req, client):
        return client, None

    async def history(_session):
        return []

    def capture(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stream setup inspected before provider call")

    monkeypatch.setattr(registry, "resolve", lambda *_args: object())
    monkeypatch.setattr(chat_primary, "_request_provider_client", provider)
    monkeypatch.setattr(chat_primary, "make_signal_stream", capture)
    req = SimpleNamespace(
        message="Review this project and provide evidence",
        session_id="isolated-mode-iteration-cap",
        project_path=str(project),
        model="",
    )
    decision = SimpleNamespace(
        request_class=RequestClass.DIRECT,
        reason="direct test task",
        signals=(),
        max_iterations=0,
        force_verification=False,
        needs_clarification=False,
        uses_tools=True,
    )

    with pytest.raises(RuntimeError, match="stream setup inspected"):
        _ = [
            frame
            async for frame in chat_primary.run_primary_chat(
                req,
                object(),
                object(),
                SimpleNamespace(get_history=history),
                decision=decision,
            )
        ]

    assert captured["max_iterations"] == 15
    assert captured["agent_context"]["_advanced_profile"]["primary_mode"] == "advisor-infinity"
    assert captured["agent_context"]["_allowed_tools"] == modes.get_advanced_mode_tool_allowlist(
        "advisor-infinity"
    )
