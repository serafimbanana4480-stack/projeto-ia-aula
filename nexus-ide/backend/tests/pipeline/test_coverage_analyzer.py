"""Tests for coverage_analyzer.py components."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from backend.pipeline.coverage_analyzer import CoverageAnalyzer, CoverageGap, EdgeCaseGenerator
from backend.pipeline.coverage_analyzer import EdgeCase as EC


class TestCoverageAnalyzer:
    """Tests for CoverageAnalyzer."""

    @pytest.fixture
    def sample_coverage_xml(self, tmp_path: Path) -> str:
        """Create a sample coverage XML file."""
        xml_content = """<?xml version="1.0" ?>
<coverage version="4.5" timestamp="123456789">
  <packages>
    <package name="backend.pipeline">
      <classes>
        <class name="generator" filename="backend/pipeline/generator.py">
          <methods/>
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="0"/>
            <line number="3" hits="1"/>
            <line number="4" hits="0" branch="true" condition-coverage="50% (1/2)"/>
            <line number="5" hits="1"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>"""
        path = tmp_path / "coverage.xml"
        path.write_text(xml_content, encoding="utf-8")
        return str(path)

    def test_parse_coverage_finds_uncovered_lines(self, sample_coverage_xml: str) -> None:
        analyzer = CoverageAnalyzer()
        gaps = analyzer.parse_coverage(sample_coverage_xml)

        uncovered_lines = [g for g in gaps if g.gap_type == "line"]
        assert len(uncovered_lines) >= 2
        assert any(g.line_start == 2 for g in uncovered_lines)

    def test_parse_coverage_finds_branch_gaps(self, sample_coverage_xml: str) -> None:
        analyzer = CoverageAnalyzer()
        gaps = analyzer.parse_coverage(sample_coverage_xml)

        branch_gaps = [g for g in gaps if g.gap_type == "branch"]
        assert len(branch_gaps) == 1
        assert branch_gaps[0].line_start == 4
        assert branch_gaps[0].risk_level == "high"

    def test_risk_assessment_critical_for_api(self) -> None:
        analyzer = CoverageAnalyzer()
        assert analyzer._assess_risk("backend/api/routes.py", 1) == "critical"

    def test_risk_assessment_high_for_service(self) -> None:
        analyzer = CoverageAnalyzer()
        assert analyzer._assess_risk("backend/services/users.py", 1) == "high"

    def test_risk_assessment_critical_for_security(self) -> None:
        analyzer = CoverageAnalyzer()
        assert analyzer._assess_risk("backend/security/payments.py", 1) == "critical"

    def test_risk_assessment_low_for_test_file(self) -> None:
        analyzer = CoverageAnalyzer()
        assert analyzer._assess_risk("backend/tests/test_something.py", 1) == "low"

    def test_prioritize_gaps(self) -> None:
        analyzer = CoverageAnalyzer()
        gaps = [
            CoverageGap("f.py", 1, 1, "line", risk_level="low"),
            CoverageGap("f.py", 2, 2, "branch", risk_level="critical"),
            CoverageGap("f.py", 3, 3, "line", risk_level="medium"),
            CoverageGap("f.py", 4, 4, "function", risk_level="high"),
        ]

        sorted_gaps = analyzer.prioritize_gaps(gaps)
        assert sorted_gaps[0].risk_level == "critical"
        assert sorted_gaps[1].risk_level == "high"
        assert sorted_gaps[2].risk_level == "medium"
        assert sorted_gaps[2].gap_type == "line"
        assert sorted_gaps[3].risk_level == "low"

    def test_parse_coverage_invalid_xml(self, tmp_path: Path) -> None:
        bad_xml = tmp_path / "bad.xml"
        bad_xml.write_text("not xml", encoding="utf-8")
        analyzer = CoverageAnalyzer()
        gaps = analyzer.parse_coverage(str(bad_xml))
        assert gaps == []


class TestEdgeCaseGenerator:
    """Tests for EdgeCaseGenerator."""

    def test_generate_str_edge_cases(self) -> None:
        gen = EdgeCaseGenerator()
        case = gen.generate("name", "str")

        assert case.parameter_name == "name"
        assert case.parameter_type == "str"
        assert "" in case.values
        assert "a" * 10000 in case.values

    def test_generate_int_edge_cases(self) -> None:
        gen = EdgeCaseGenerator()
        case = gen.generate("count", "int")

        assert 0 in case.values
        assert -1 in case.values
        assert 2147483647 in case.values

    def test_generate_float_edge_cases(self) -> None:
        gen = EdgeCaseGenerator()
        case = gen.generate("ratio", "float")

        assert 0.0 in case.values
        assert float("inf") in case.values

    def test_generate_optional_type(self) -> None:
        gen = EdgeCaseGenerator()
        case = gen.generate("value", "Optional[int]")

        assert case.parameter_name == "value"
        assert 0 in case.values  # Should strip Optional wrapper

    def test_generate_unknown_type_defaults_to_none(self) -> None:
        gen = EdgeCaseGenerator()
        case = gen.generate("custom", "MyClass")
        assert case.values == [None]

    def test_generate_for_function(self) -> None:
        code = """
def add(a: int, b: int) -> int:
    return a + b
"""
        gen = EdgeCaseGenerator()
        cases = gen.generate_for_function(code, "add")

        assert len(cases) == 2
        param_names = {c.parameter_name for c in cases}
        assert "a" in param_names
        assert "b" in param_names

    def test_generate_for_function_not_found(self) -> None:
        gen = EdgeCaseGenerator()
        cases = gen.generate_for_function("def foo(): pass", "bar")
        assert cases == []

    def test_generate_for_function_bad_syntax(self) -> None:
        gen = EdgeCaseGenerator()
        cases = gen.generate_for_function("def foo(", "foo")
        assert cases == []
