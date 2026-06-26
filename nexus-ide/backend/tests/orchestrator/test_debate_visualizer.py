import pytest
from backend.orchestrator.debate_visualizer import (
    DebateVisualizer,
    DebateSession,
    DebateRound,
    DebateArgument,
    Stance,
)


def test_create_session():
    viz = DebateVisualizer()
    session = viz.create_session("s1", "AI Safety", ["agent-a", "agent-b"])
    assert session.session_id == "s1"
    assert session.topic == "AI Safety"
    assert session.participants == ["agent-a", "agent-b"]
    assert session.status == "active"
    assert len(session.rounds) == 0


def test_add_argument_creates_round():
    viz = DebateVisualizer()
    viz.create_session("s1", "Topic", ["a", "b"])
    arg = viz.add_argument("s1", "a", Stance.FOR, "AI is safe", 0.8)
    assert arg is not None
    assert arg.agent_id == "a"
    assert arg.stance == Stance.FOR
    assert arg.confidence == 0.8

    session = viz.get_session("s1")
    assert len(session.rounds) == 1
    assert len(session.rounds[0].arguments) == 1


def test_add_argument_to_existing_round():
    viz = DebateVisualizer()
    viz.create_session("s1", "Topic", ["a", "b"])
    viz.add_argument("s1", "a", Stance.FOR, "For")
    viz.add_argument("s1", "b", Stance.AGAINST, "Against")
    session = viz.get_session("s1")
    assert len(session.rounds[0].arguments) == 2


def test_complete_round():
    viz = DebateVisualizer()
    viz.create_session("s1", "Topic", ["a", "b"])
    viz.add_argument("s1", "a", Stance.FOR, "For")
    assert viz.complete_round("s1") is True
    session = viz.get_session("s1")
    assert session.rounds[0].completed_at is not None


def test_complete_session():
    viz = DebateVisualizer()
    viz.create_session("s1", "Topic", ["a", "b"])
    assert viz.complete_session("s1") is True
    assert viz.get_session("s1").status == "completed"


def test_get_live_state():
    viz = DebateVisualizer()
    viz.create_session("s1", "Topic", ["a", "b"])
    viz.add_argument("s1", "a", Stance.FOR, "For")
    state = viz.get_live_state("s1")
    assert state["session_id"] == "s1"
    assert state["current_round"] == 1
    assert state["arguments_in_current_round"] == 1
    assert state["status"] == "active"


def test_get_summary():
    viz = DebateVisualizer()
    viz.create_session("s1", "Topic", ["a", "b"])
    viz.add_argument("s1", "a", Stance.FOR, "For")
    viz.add_argument("s1", "b", Stance.AGAINST, "Against")
    viz.complete_session("s1")
    summary = viz.get_session("s1").get_summary()
    assert summary["total_arguments"] == 2
    assert summary["stance_distribution"]["for"] == 1
    assert summary["stance_distribution"]["against"] == 1
    assert summary["status"] == "completed"


def test_list_sessions():
    viz = DebateVisualizer()
    viz.create_session("s1", "T1", ["a"])
    viz.create_session("s2", "T2", ["b"])
    viz.complete_session("s1")
    active = viz.list_sessions("active")
    completed = viz.list_sessions("completed")
    assert len(active) == 1
    assert active[0].session_id == "s2"
    assert len(completed) == 1
    assert completed[0].session_id == "s1"
