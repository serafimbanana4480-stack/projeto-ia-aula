"""Unit tests for SWARM coordinator, modes, and reviewer."""

from __future__ import annotations

from backend.swarm.core.coordinator import AntiLoopGuard, detect_mode
from backend.swarm.core.types import (
    AgentMessage,
    MessageType,
    OperationalMode,
    Proposal,
)
from backend.swarm.modes.mode_registry import OPERATIONAL_MODES, get_mode
from backend.swarm.review.reviewer import ReviewerAgent


def test_detect_mode_architecture() -> None:
    d = detect_mode("Design the architecture for the new service")
    assert d.mode == OperationalMode.ARCHITECTURE


def test_detect_mode_bugfix() -> None:
    d = detect_mode("There's a bug in the login flow, please fix it")
    assert d.mode == OperationalMode.BUGFIX


def test_detect_mode_research() -> None:
    d = detect_mode("Research best practices for Rust vs Go")
    assert d.mode == OperationalMode.RESEARCH


def test_detect_mode_fallback() -> None:
    d = detect_mode("zzzz")
    assert d.mode in (OperationalMode.INVESTIGATION, OperationalMode.PLANNING)


def test_anti_loop_guard_triggers() -> None:
    g = AntiLoopGuard(threshold=3)
    ok1, _ = g.check(AgentMessage(sender="X", type=MessageType.REQUEST))
    ok2, _ = g.check(AgentMessage(sender="X", type=MessageType.REQUEST))
    ok3, _ = g.check(AgentMessage(sender="X", type=MessageType.REQUEST))
    ok4, _ = g.check(AgentMessage(sender="X", type=MessageType.REQUEST))
    assert ok1 and ok2 and ok3
    assert not ok4


def test_modes_catalogue_complete() -> None:
    expected = {
        OperationalMode.ARCHITECTURE,
        OperationalMode.INVESTIGATION,
        OperationalMode.IMPLEMENTATION,
        OperationalMode.REVIEW,
        OperationalMode.BUGFIX,
        OperationalMode.PLANNING,
        OperationalMode.RESEARCH,
    }
    assert set(OPERATIONAL_MODES.keys()) == expected
    for mode in expected:
        spec = get_mode(mode)
        assert spec.agents
        assert spec.objective
        assert spec.workflow


def test_reviewer_flags_eval_and_secrets() -> None:
    p = Proposal(
        title="Add script runner",
        description="Run user input as Python via eval()",
        rationale="api_key=ABCDEF",
        files_to_change=[{"path": "tools/run.py", "change": "eval(user_input)"}],
    )
    report = ReviewerAgent().review_proposal(p)
    cats = {f["category"] for f in report.findings}
    assert "security" in cats
    assert any("eval" in (f.get("message") or "").lower() for f in report.findings)


def test_reviewer_passes_clean_proposal() -> None:
    p = Proposal(
        title="Add unit tests",
        description=(
            "## Plan\n\n"
            "Cover the helper with tests.\n\n"
            "## Files\n\n"
            "- `tests/test_helper.py:1-30` — add test_foo function\n\n"
            "```python\n"
            "def test_foo() -> bool:\n    assert True\n"
            "```\n"
        ),
        rationale=(
            "## Rationale\n\n- tests cover the change\n- doc added\n- validate via pytest\n"
        ),
        files_to_change=[
            {
                "path": "tests/test_helper.py",
                "change": "def test_foo() -> bool:\n    assert True",
                "rationale": "increase test coverage",
            }
        ],
        evidence_refs=["helper.py:1-10"],
        decision_refs=["d1"],
    )
    report = ReviewerAgent().review_proposal(p)
    assert report.passed, f"review should pass but failed: {report.summary}"
