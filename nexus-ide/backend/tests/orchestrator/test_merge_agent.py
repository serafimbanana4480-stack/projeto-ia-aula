"""Tests for MergeAgent."""
from backend.orchestrator.merge_agent import MergeAgent, MergeStrategy


class TestMergeAgent:
    def test_no_conflict(self) -> None:
        agent = MergeAgent()
        result = agent.merge_files("base", "same", "same")
        assert result["conflicts"] == 0
        assert result["content"] == "same"

    def test_ours_equals_base(self) -> None:
        agent = MergeAgent()
        result = agent.merge_files("base", "base", "theirs")
        assert result["conflicts"] == 0
        assert result["strategy"] == MergeStrategy.THEIRS
        assert result["content"] == "theirs"

    def test_theirs_equals_base(self) -> None:
        agent = MergeAgent()
        result = agent.merge_files("base", "ours", "base")
        assert result["conflicts"] == 0
        assert result["strategy"] == MergeStrategy.OURS
        assert result["content"] == "ours"

    def test_strategy_ours(self) -> None:
        agent = MergeAgent(strategy=MergeStrategy.OURS)
        result = agent.merge_files("base", "ours-content", "theirs-content")
        assert result["conflicts"] == 1
        assert result["strategy"] == MergeStrategy.OURS
        assert result["content"] == "ours-content"

    def test_strategy_theirs(self) -> None:
        agent = MergeAgent(strategy=MergeStrategy.THEIRS)
        result = agent.merge_files("base", "ours-content", "theirs-content")
        assert result["conflicts"] == 1
        assert result["strategy"] == MergeStrategy.THEIRS
        assert result["content"] == "theirs-content"

    def test_strategy_manual(self) -> None:
        agent = MergeAgent(strategy=MergeStrategy.MANUAL)
        result = agent.merge_files("base", "ours", "theirs")
        assert result["conflicts"] == 1
        assert result["strategy"] == MergeStrategy.MANUAL
        assert "<<<<<<<" in result["content"]

    def test_validate_imports_sorted(self) -> None:
        agent = MergeAgent()
        content = "import zebra\nimport alpha\n"
        violations = agent.validate_conventions(content, "fastapi")
        assert any(v["rule"] == "imports_sorted" for v in violations)

    def test_validate_no_wildcard(self) -> None:
        agent = MergeAgent()
        content = "from os import *\n"
        violations = agent.validate_conventions(content, "fastapi")
        assert any(v["rule"] == "no_wildcard_imports" for v in violations)

    def test_validate_clean(self) -> None:
        agent = MergeAgent()
        content = "import alpha\nimport zebra\n"
        violations = agent.validate_conventions(content, "fastapi")
        assert len(violations) == 0
