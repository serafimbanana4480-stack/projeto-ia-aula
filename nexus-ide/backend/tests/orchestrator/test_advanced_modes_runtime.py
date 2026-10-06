from __future__ import annotations

import json

from backend.orchestrator import advanced_modes as modes


def test_legacy_goal_node_enum_is_restored_and_serialised_as_value(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(modes, "ADVANCED_MODES_STATE_DIR", tmp_path)
    legacy = {
        "mode_id": "vibe-infinity",
        "session_id": "legacy",
        "state": "active",
        "goal_tree": {
            "G-1": {
                "id": "G-1",
                "title": "Legacy goal",
                "description": "Legacy goal",
                "state": "GoalNodeState.IN_PROGRESS",
                "parent_id": None,
                "children": [],
                "assigned_agent": None,
                "evidence": [],
                "rejection_reason": None,
                "quality_score": None,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        },
    }
    (tmp_path / "vibe-infinity__legacy.json").write_text(
        json.dumps(legacy), encoding="utf-8"
    )

    manager = modes.ModeStateManager()
    session = manager.get_session("vibe-infinity", "legacy")

    assert session is not None
    assert session.goal_tree["G-1"].state is modes.GoalNodeState.IN_PROGRESS

    manager.update_session(session)
    saved = json.loads((tmp_path / "vibe-infinity__legacy.json").read_text(encoding="utf-8"))
    assert saved["goal_tree"]["G-1"]["state"] == "in_progress"


def test_mode_status_separates_active_sessions_from_history(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(modes, "ADVANCED_MODES_STATE_DIR", tmp_path)
    manager = modes.ModeStateManager()
    active = manager.create_session("forge")
    historical = manager.create_session("forge")
    historical.state = modes.ModeState.COMPLETED
    manager.update_session(historical)

    sessions = manager.list_sessions("forge")
    assert len(sessions) == 2
    assert sum(1 for item in sessions if item["active"]) == 1
    assert active.session_id in {item["session_id"] for item in sessions}


def test_active_profile_composes_composite_without_claiming_workers(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(modes, "ADVANCED_MODES_STATE_DIR", tmp_path)
    manager = modes.ModeStateManager()
    manager.create_session("autonomous")
    manager.create_session("advisor-infinity")

    orchestrator = modes.AdvancedModeOrchestrator()
    orchestrator.state_manager = manager
    profile = orchestrator.build_active_execution_profile("ship the feature")

    assert profile["primary_mode"] == "autonomous"
    assert profile["force_autonomous"] is True
    assert profile["applied_mode_ids"] == ["autonomous"]
    assert set(profile["policy_mode_ids"]) == set(modes.MODE_PRIORITY)
    assert "does not prove that a specialist has run" in profile["addon"]


def test_preparing_active_profile_persists_goal_checkpoint_and_trajectory(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(modes, "ADVANCED_MODES_STATE_DIR", tmp_path)
    monkeypatch.setattr(modes, "CHECKPOINT_DIR", tmp_path / "checkpoints")
    monkeypatch.setattr(modes, "TRAJECTORY_DIR", tmp_path / "trajectories")
    modes.CHECKPOINT_DIR.mkdir()
    modes.TRAJECTORY_DIR.mkdir()
    manager = modes.ModeStateManager()
    manager.create_session("forge")

    orchestrator = modes.AdvancedModeOrchestrator()
    orchestrator.state_manager = manager
    profile = orchestrator.prepare_active_execution_profile("implement the feature")
    session = manager.get_session("forge", profile["session_id"])

    assert session is not None
    assert profile["goal_id"] in session.goal_tree
    assert profile["checkpoint_id"] in session.checkpoints
    assert any(item["type"] == "active_profile_applied" for item in session.trajectory)


def test_execution_outcome_closes_goal_without_promoting_response_to_verified(
    tmp_path, monkeypatch
) -> None:
    state_dir = tmp_path / "state"
    checkpoints = tmp_path / "checkpoints"
    trajectories = tmp_path / "trajectories"
    for folder in (state_dir, checkpoints, trajectories):
        folder.mkdir()
    monkeypatch.setattr(modes, "ADVANCED_MODES_STATE_DIR", state_dir)
    monkeypatch.setattr(modes, "CHECKPOINT_DIR", checkpoints)
    monkeypatch.setattr(modes, "TRAJECTORY_DIR", trajectories)

    manager = modes.ModeStateManager()
    manager.create_session("forge")
    orchestrator = modes.AdvancedModeOrchestrator()
    orchestrator.state_manager = manager
    profile = orchestrator.prepare_active_execution_profile("implement the feature")

    recorded = orchestrator.record_execution_outcome(
        mode_id="forge",
        session_id=profile["session_id"],
        goal_id=profile["goal_id"],
        run_id="run-success",
        outcome="completed",
        verification={"ran": True, "ok": True, "summary": "4 tests passed"},
    )
    session = manager.get_session("forge", profile["session_id"])
    assert recorded is True
    assert session is not None
    assert session.goal_tree[profile["goal_id"]].state is modes.GoalNodeState.IN_REVIEW
    assert orchestrator.record_execution_outcome(
        mode_id="forge",
        session_id=profile["session_id"],
        goal_id=profile["goal_id"],
        run_id="run-success",
        outcome="failed",
    ) is False
    assert session.goal_tree[profile["goal_id"]].state is modes.GoalNodeState.IN_REVIEW
    saved = json.loads((state_dir / f"forge__{profile['session_id']}.json").read_text())
    assert saved["goal_tree"][profile["goal_id"]]["state"] == "in_review"
    assert saved["metrics"]["execution_outcomes"]["run-success"]["verification"]["ok"] is True


def test_measured_failed_verification_rejects_goal_but_success_does_not_verify_it(
    tmp_path, monkeypatch
) -> None:
    state_dir = tmp_path / "state"
    checkpoints = tmp_path / "checkpoints"
    trajectories = tmp_path / "trajectories"
    for folder in (state_dir, checkpoints, trajectories):
        folder.mkdir()
    monkeypatch.setattr(modes, "ADVANCED_MODES_STATE_DIR", state_dir)
    monkeypatch.setattr(modes, "CHECKPOINT_DIR", checkpoints)
    monkeypatch.setattr(modes, "TRAJECTORY_DIR", trajectories)

    manager = modes.ModeStateManager()
    manager.create_session("forge")
    orchestrator = modes.AdvancedModeOrchestrator()
    orchestrator.state_manager = manager
    profile = orchestrator.prepare_active_execution_profile("implement the feature")

    assert orchestrator.record_execution_outcome(
        mode_id="forge",
        session_id=profile["session_id"],
        goal_id=profile["goal_id"],
        run_id="run-failed-check",
        outcome="completed",
        verification={"ran": True, "ok": False, "summary": "2 tests failed"},
    ) is True
    session = manager.get_session("forge", profile["session_id"])
    assert session is not None
    node = session.goal_tree[profile["goal_id"]]
    assert node.state is modes.GoalNodeState.REJECTED
    assert node.rejection_reason == "2 tests failed"


def test_high_confidence_evidence_stays_unproven_until_an_independent_gate(
    tmp_path, monkeypatch
) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    monkeypatch.setattr(modes, "EVIDENCE_DIR", evidence_dir)
    session = modes.ModeSession(mode_id="proof", session_id="proof-session")

    evidence_id = modes.add_evidence(
        session,
        requirement="The endpoint rejects invalid input",
        implementation_files=["api.py"],
        test_files=["test_api.py"],
        evidence_paths=["test-run-123"],
        confidence=0.99,
    )

    assert session.evidence_book[evidence_id]["status"] == modes.EvidenceStatus.UNPROVEN.value


def test_mode_prompt_renders_catalog_values_without_formatting_literal_json() -> None:
    mode_def = modes.get_advanced_mode("advisor-infinity")
    assert mode_def is not None

    rendered = modes.AdvancedModeOrchestrator._render_mode_prompt(mode_def)

    assert "{max_debate_rounds}" not in rendered
    assert "6" in rendered


def test_explicit_commands_have_a_concrete_execution_target(monkeypatch) -> None:
    orchestrator = modes.AdvancedModeOrchestrator()

    monkeypatch.setenv("NEXUS_VIBE_LANE", "1")
    assert orchestrator.get_execution_target("autonomous") == {
        "kind": "autonomous",
        "agent": None,
    }
    assert orchestrator.get_execution_target("vibe-infinity") == {
        "kind": "vibe",
        "agent": "CODER",
    }
    monkeypatch.setenv("NEXUS_VIBE_LANE", "0")
    assert orchestrator.get_execution_target("vibe-infinity") == {
        "kind": "autonomous",
        "agent": None,
    }
    assert orchestrator.get_execution_target("swarm-foundry") == {
        "kind": "swarm",
        "agent": "SWARM",
    }

    expected_agents = {
        "advisor-infinity": "ADVISOR",
        "forge": "CODER",
        "multiverse": "ARCHITECT",
        "proof": "ADVISOR",
        "reality-lab": "TEST_RUNNER_E2E",
        "archaeologist": "ANALYZER",
        "evolve": "ANALYZER",
        "sentinel": "NEXUS",
    }
    for mode_id, agent in expected_agents.items():
        assert orchestrator.get_execution_target(mode_id) == {
            "kind": "agent",
            "agent": agent,
        }

    assert orchestrator.get_execution_target("does-not-exist")["kind"] == "unknown"
