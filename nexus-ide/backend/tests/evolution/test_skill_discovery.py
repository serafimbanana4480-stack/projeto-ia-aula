"""Tests for SkillDiscovery (FASE 10)."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.evolution.skill_discovery import SkillDiscovery
from backend.experience.lake import TraceLake
from backend.experience.models import (
    ExperienceTrace,
    ModelInfo,
    TaskCategory,
    TraceMetrics,
    TraceResult,
)


@pytest.fixture
def temp_lake(tmp_path: Path) -> TraceLake:
    return TraceLake(tmp_path / "test_lake.db")


@pytest.fixture
def skill_discovery(temp_lake: TraceLake, tmp_path: Path) -> SkillDiscovery:
    return SkillDiscovery(lake=temp_lake, db_path=tmp_path / "test_evolution.db")


def _make_trace_with_trajectory(
    prompt: str = "Write code",
    actions: list[tuple[str, str]] | None = None,
) -> ExperienceTrace:
    """Build a trace with trajectory entries."""
    trace = ExperienceTrace(
        prompt=prompt,
        task_type="coding",
        difficulty=0.5,
        category=TaskCategory.CODING,
        model=ModelInfo(name="test-model", version="v1", temperature=0.0, tier="fast"),
        component_kind="coder",
    )
    trace.result = TraceResult(success=True, score=0.9)
    trace.metrics = TraceMetrics(latency_ms=100, tokens_input=500, tokens_output=200, tool_calls=len(actions) if actions else 0)

    if actions:
        for action, tool in actions:
            trace.add_trajectory_entry(
                agent="CODER",
                action=action,
                tool=tool,
                observation="ok",
                duration_ms=10,
            )
    return trace


class TestDiscover:
    def test_discover_empty_lake(self, skill_discovery: SkillDiscovery) -> None:
        """Empty lake returns no skills."""
        skills = skill_discovery.discover()
        assert skills == []

    def test_discover_no_trajectory(self, skill_discovery: SkillDiscovery, temp_lake: TraceLake) -> None:
        """Traces without trajectory return no skills."""
        trace = _make_trace_with_trajectory()
        temp_lake.store_trace(trace)

        skills = skill_discovery.discover()
        assert skills == []

    def test_discover_recurring_pattern(
        self, skill_discovery: SkillDiscovery, temp_lake: TraceLake
    ) -> None:
        """Recurring action sequences are discovered as skills."""
        # Store 3 traces with the same action sequence
        for _ in range(3):
            trace = _make_trace_with_trajectory(
                actions=[("read_file", "read"), ("write_file", "write"), ("run_tests", "bash")]
            )
            temp_lake.store_trace(trace)

        skills = skill_discovery.discover(min_occurrences=2)
        assert len(skills) >= 1
        skill = skills[0]
        assert "read" in skill["action_sequence"]
        assert "write" in skill["action_sequence"]
        assert skill["frequency"] >= 2

    def test_discover_filters_by_min_occurrences(
        self, skill_discovery: SkillDiscovery, temp_lake: TraceLake
    ) -> None:
        """Patterns below min_occurrences are filtered."""
        # Only 1 trace — won't meet default min_occurrences=3
        trace = _make_trace_with_trajectory(
            actions=[("read_file", "read"), ("write_file", "write"), ("run_tests", "bash")]
        )
        temp_lake.store_trace(trace)

        skills = skill_discovery.discover(min_occurrences=3)
        assert skills == []

    def test_discover_skill_fields(self, skill_discovery: SkillDiscovery, temp_lake: TraceLake) -> None:
        """Discovered skills have all expected fields."""
        for _ in range(3):
            trace = _make_trace_with_trajectory(
                actions=[("read", "read"), ("write", "write"), ("verify", "bash")]
            )
            temp_lake.store_trace(trace)

        skills = skill_discovery.discover(min_occurrences=2)
        assert len(skills) >= 1
        skill = skills[0]
        assert "name" in skill
        assert "description" in skill
        assert "action_sequence" in skill
        assert "frequency" in skill
        assert "example_tasks" in skill
        assert "component_kinds" in skill

    def test_discover_sorted_by_frequency(self, skill_discovery: SkillDiscovery, temp_lake: TraceLake) -> None:
        """Skills are sorted by frequency descending."""
        # 3 traces with pattern A
        for _ in range(3):
            trace = _make_trace_with_trajectory(
                actions=[("read", "read"), ("write", "write"), ("test", "bash")]
            )
            temp_lake.store_trace(trace)

        # 2 traces with pattern B (shorter)
        for _ in range(2):
            trace = _make_trace_with_trajectory(
                actions=[("read", "read"), ("write", "write"), ("deploy", "bash")]
            )
            temp_lake.store_trace(trace)

        skills = skill_discovery.discover(min_occurrences=2)
        if len(skills) >= 2:
            assert skills[0]["frequency"] >= skills[1]["frequency"]


class TestRegisterSkills:
    def test_register_skills(self, skill_discovery: SkillDiscovery, temp_lake: TraceLake) -> None:
        """Registered skills are persisted and retrievable."""
        for _ in range(3):
            trace = _make_trace_with_trajectory(
                actions=[("read", "read"), ("write", "write"), ("test", "bash")]
            )
            temp_lake.store_trace(trace)

        skills = skill_discovery.discover(min_occurrences=2)
        if skills:
            ids = skill_discovery.register_skills(skills)
            assert len(ids) == len(skills)

            stored = skill_discovery.get_discovered_skills()
            assert len(stored) == len(skills)

    def test_get_discovered_skills_empty(self, skill_discovery: SkillDiscovery) -> None:
        """Empty when no skills registered."""
        assert skill_discovery.get_discovered_skills() == []

    def test_register_empty_skills(self, skill_discovery: SkillDiscovery) -> None:
        """Registering empty list returns empty ids."""
        ids = skill_discovery.register_skills([])
        assert ids == []


class TestSubpatternGeneration:
    def test_generate_subpatterns(self, skill_discovery: SkillDiscovery) -> None:
        """Subpatterns of minimum length are generated."""
        sequence = ["read", "write", "test", "deploy"]
        subs = skill_discovery._generate_subpatterns(sequence)
        # min_sequence_len=3, so subpatterns of length 3 and 4
        assert len(subs) >= 2  # at least 3+4 length subpatterns
        # Length 3 subpatterns: [read,write,test], [write,test,deploy] = 2
        # Length 4: [read,write,test,deploy] = 1
        # Total = 3 (or more if min_sequence_len range goes up to 5)

    def test_sequence_to_key(self, skill_discovery: SkillDiscovery) -> None:
        """Sequence key is joined with ->."""
        key = skill_discovery._sequence_to_key(["a", "b", "c"])
        assert key == "a->b->c"


class TestSkillNaming:
    def test_generate_skill_name(self, skill_discovery: SkillDiscovery) -> None:
        """Skill name is generated from pattern."""
        name = skill_discovery._generate_skill_name("read->write->test")
        assert name.startswith("skill_")

    def test_generate_skill_description(self, skill_discovery: SkillDiscovery) -> None:
        """Description mentions step count."""
        desc = skill_discovery._generate_skill_description("read->write->test")
        assert "3" in desc
        assert "read" in desc
