"""Tests for MetaAnalyzerAgent."""

from __future__ import annotations

import pytest

from backend.agents.base import AgentAction, AgentRequest
from backend.agents.meta_analyzer import (
    MetaAnalyzerAgent,
    QualityCriteria,
)


@pytest.fixture
def meta_agent(monkeypatch: pytest.MonkeyPatch, tmp_path) -> MetaAnalyzerAgent:
    """Return a MetaAnalyzerAgent with an isolated evolution log."""
    test_path = tmp_path / "evolution_log.md"
    monkeypatch.setattr("backend.agents.meta_analyzer.EVOLUTION_LOG_PATH", test_path)
    return MetaAnalyzerAgent()


class TestMetaAnalyzerAgent:
    def test_metadata(self) -> None:
        agent = MetaAnalyzerAgent()
        assert agent.name == "META_ANALYZER"
        assert agent.model_key == "reasoning"
        assert agent.prompt_file == "meta_analyzer"

    def test_supported_actions(self) -> None:
        agent = MetaAnalyzerAgent()
        expected = {
            AgentAction.READ_FILE,
            AgentAction.SEARCH_CODEBASE,
            AgentAction.CONSULT_AGENT,
            AgentAction.RECALL_CONTEXT,
            AgentAction.ANALYZE_DATA,
            AgentAction.GENERATE_REPORT,
        }
        assert agent.supported_actions == expected

    async def test_run_streams_tokens(self, ollama_client) -> None:
        agent = MetaAnalyzerAgent()
        req = AgentRequest(
            session_id="s1",
            query="analyze quality",
            client=ollama_client,
        )
        tokens = [t async for t in agent.run(req)]
        # Real LLM test: just verify the agent emits at least one token.
        # The exact content depends on the loaded model and is not stable
        # across model upgrades, so we only assert that the stream produced
        # non-empty content (previously this test hard-coded the MockTransport
        # token list which only worked with a stub LLM).
        joined = "".join(tokens)
        assert tokens, "MetaAnalyzerAgent produced no tokens"
        assert len(joined) > 0, "MetaAnalyzerAgent produced empty text"
        await ollama_client.aclose()

    def test_evaluate_quality_all_pass(self, meta_agent: MetaAnalyzerAgent) -> None:
        metrics = {
            "test_coverage_percent": 95,
            "test_failures": 0,
            "security_critical": 0,
            "security_high": 0,
            "performance_regression_percent": 5,
            "cyclomatic_max_function": 10,
            "cyclomatic_max_file": 40,
            "lint_errors": 0,
            "missing_docstrings": 0,
        }
        verdict = meta_agent.evaluate_quality(metrics)
        assert verdict["overall"] == "PASS"
        assert len(verdict["violations"]) == 0
        assert verdict["categories"]["tests"]["pass"] is True
        assert verdict["categories"]["security"]["pass"] is True
        assert verdict["categories"]["performance"]["pass"] is True
        assert verdict["categories"]["complexity"]["pass"] is True
        assert verdict["categories"]["style"]["pass"] is True
        assert verdict["categories"]["documentation"]["pass"] is True

    def test_evaluate_quality_fails(self, meta_agent: MetaAnalyzerAgent) -> None:
        metrics = {
            "test_coverage_percent": 80,
            "test_failures": 2,
            "security_critical": 1,
            "security_high": 3,
            "performance_regression_percent": 15,
            "cyclomatic_max_function": 20,
            "cyclomatic_max_file": 60,
            "lint_errors": 5,
            "missing_docstrings": 3,
        }
        verdict = meta_agent.evaluate_quality(metrics)
        assert verdict["overall"] == "FAIL"
        assert len(verdict["violations"]) == 9

    def test_detect_contradictions(self, meta_agent: MetaAnalyzerAgent) -> None:
        outputs = {
            "ARCHITECT": {
                "content": "We should use microservices for scalability",
                "estimated_complexity": 8,
            },
            "ANALYZER": {
                "content": "This is too complex for our team size",
                "estimated_complexity": 3,
            },
        }
        contradictions = meta_agent.detect_contradictions(outputs)
        assert len(contradictions) >= 1
        assert any(c["type"] == "complexity_mismatch" for c in contradictions)

    def test_detect_contradictions_complexity_mismatch(self, meta_agent: MetaAnalyzerAgent) -> None:
        outputs = {
            "ARCHITECT": {
                "content": "Build a distributed event bus",
                "estimated_complexity": 9,
            },
            "ANALYZER": {
                "content": "Simple wrapper around Redis",
                "estimated_complexity": 2,
            },
        }
        contradictions = meta_agent.detect_contradictions(outputs)
        assert any(c["type"] == "complexity_mismatch" for c in contradictions)

    def test_build_approval_report_pass(self, meta_agent: MetaAnalyzerAgent) -> None:
        verdict = {
            "overall": "PASS",
            "categories": {
                "tests": {"pass": True, "coverage": 95, "failures": 0},
            },
            "violations": [],
        }
        report = meta_agent.build_approval_report(verdict, [], ["Merge PR #42"])
        assert "APPROVED" in report
        assert "Merge PR #42" in report

    def test_build_approval_report_fail(self, meta_agent: MetaAnalyzerAgent) -> None:
        verdict = {
            "overall": "FAIL",
            "categories": {
                "tests": {"pass": False, "coverage": 80, "failures": 2},
            },
            "violations": ["Coverage too low"],
        }
        report = meta_agent.build_approval_report(verdict, [], ["Refactor module X"])
        assert "DENIED" in report
        assert "Coverage too low" in report
        assert "Refactor module X" in report

    def test_log_evolution_entry(self, meta_agent: MetaAnalyzerAgent, tmp_path) -> None:
        meta_agent.log_evolution_entry(
            decision="Test decision",
            rationale="Testing the log",
            agents_involved=["META_ANALYZER", "CODER"],
        )
        # The monkeypatched path was applied at fixture time.
        # Read via the module-level path which was monkeypatched.
        import backend.agents.meta_analyzer as ma

        assert ma.EVOLUTION_LOG_PATH.exists()
        content = ma.EVOLUTION_LOG_PATH.read_text(encoding="utf-8")
        assert "Test decision" in content
        assert "Testing the log" in content
        assert "META_ANALYZER" in content

    def test_quality_criteria_constants(self) -> None:
        assert QualityCriteria.TEST_COVERAGE_MIN == 90
        assert QualityCriteria.TEST_FAILURES_MAX == 0
        assert QualityCriteria.SECURITY_CRITICAL_MAX == 0
        assert QualityCriteria.PERFORMANCE_REGRESSION_PCT == 10
        assert QualityCriteria.CYCLOMATIC_MAX_FUNCTION == 15
        assert QualityCriteria.CYCLOMATIC_MAX_FILE == 50
        assert QualityCriteria.LINT_ERRORS_MAX == 0
        assert QualityCriteria.DOCSTRING_REQUIRED_PUBLIC is True
