"""CoverageAnalyzer — identify untested code and generate targeted tests.

Parses coverage reports, identifies gaps, and generates edge cases
to improve branch and line coverage.
"""
from __future__ import annotations

import ast
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CoverageGap:
    """A section of code missing test coverage."""

    file_path: str
    line_start: int
    line_end: int
    gap_type: str  # line, branch, function
    function_name: str = ""
    risk_level: str = "medium"  # low, medium, high, critical


@dataclass
class EdgeCase:
    """An edge case to test."""

    parameter_name: str
    parameter_type: str
    values: list[Any]
    rationale: str = ""


class CoverageAnalyzer:
    """Analyze coverage reports and identify gaps."""

    def parse_coverage(self, coverage_xml_path: str) -> list[CoverageGap]:
        """Parse coverage XML and return gaps.

        Args:
            coverage_xml_path: Path to coverage XML report.

        Returns:
            List of CoverageGap objects.
        """
        gaps: list[CoverageGap] = []

        try:
            tree = ET.parse(coverage_xml_path)
            root = tree.getroot()

            for package in root.iter("package"):
                for cls in package.iter("class"):
                    filename = cls.get("filename", "")
                    for line in cls.iter("line"):
                        hits = int(line.get("hits", "0"))
                        number = int(line.get("number", 0))

                        if hits == 0:
                            gaps.append(CoverageGap(
                                file_path=filename,
                                line_start=number,
                                line_end=number,
                                gap_type="line",
                                risk_level=self._assess_risk(filename, number),
                            ))

                    # Check branch coverage
                    for line in cls.iter("line"):
                        branch = line.get("branch")
                        if branch == "true":
                            cond_cov = line.get("condition-coverage", "")
                            if cond_cov and not cond_cov.endswith("(1/1)"):
                                number = int(line.get("number", 0))
                                gaps.append(CoverageGap(
                                    file_path=filename,
                                    line_start=number,
                                    line_end=number,
                                    gap_type="branch",
                                    risk_level="high",
                                ))

        except ET.ParseError as exc:
            logger.error("Failed to parse coverage XML: %s", exc)

        return gaps

    def _assess_risk(self, filename: str, line_number: int) -> str:
        """Assess risk level of uncovered code."""
        filename_lower = filename.lower()
        if "test" in filename_lower:
            return "low"
        if "api" in filename_lower or "route" in filename_lower:
            return "critical"
        if any(x in filename_lower for x in ["auth", "security", "payment"]):
            return "critical"
        if "service" in filename_lower or "handler" in filename_lower:
            return "high"
        return "medium"

    def prioritize_gaps(self, gaps: list[CoverageGap]) -> list[CoverageGap]:
        """Sort gaps by risk level and gap type."""
        risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        type_order = {"branch": 0, "function": 1, "line": 2}
        return sorted(
            gaps,
            key=lambda g: (risk_order.get(g.risk_level, 99), type_order.get(g.gap_type, 99)),
        )

    def get_public_functions_missing_tests(self, source_path: str) -> list[str]:
        """Find public functions in source file without tests."""
        try:
            with open(source_path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
        except (SyntaxError, FileNotFoundError):
            return []

        public_functions: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    public_functions.append(node.name)

        # Check which have test functions
        test_file = Path(source_path).parent / "tests" / f"test_{Path(source_path).stem}.py"
        tested_functions: set[str] = set()

        if test_file.exists():
            try:
                with open(test_file, encoding="utf-8") as f:
                    test_tree = ast.parse(f.read())
                for node in ast.walk(test_tree):
                    if isinstance(node, ast.FunctionDef):
                        for func in public_functions:
                            if func in node.name:
                                tested_functions.add(func)
            except SyntaxError:
                pass

        return [f for f in public_functions if f not in tested_functions]


class EdgeCaseGenerator:
    """Generate edge cases for common Python types."""

    TYPE_EDGE_CASES: dict[str, list[Any]] = {
        "str": ["", "a" * 10000, "\n\t\r", "special!@#$%", "unicode: 你好世界 🌍"],
        "int": [0, -1, 1, 2147483647, -2147483648],
        "float": [0.0, -0.0, float("inf"), float("-inf"), 1e-10, 1e10],
        "bool": [True, False],
        "list": [[], [1], list(range(1000)), [None], [1, "mixed", True]],
        "dict": [{}, {"key": "value"}, {f"k{i}": i for i in range(100)}, {None: None}],
    }

    def generate(self, param_name: str, param_type: str) -> EdgeCase:
        """Generate edge cases for a parameter.

        Args:
            param_name: Parameter name.
            param_type: Python type annotation string.

        Returns:
            EdgeCase with values to test.
        """
        # Normalize type string
        type_key = param_type.lower().replace("optional[", "").replace("]", "").replace("|", "").replace("none", "").strip()

        values = self.TYPE_EDGE_CASES.get(type_key, [None])

        return EdgeCase(
            parameter_name=param_name,
            parameter_type=param_type,
            values=values,
            rationale=f"Edge cases for {param_type} parameter '{param_name}'",
        )

    def generate_for_function(self, source_code: str, func_name: str) -> list[EdgeCase]:
        """Generate edge cases for all parameters of a function."""
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return []

        cases: list[EdgeCase] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                for arg in node.args.args:
                    arg_name = arg.arg
                    # Try to get type annotation
                    arg_type = "Any"
                    if arg.annotation:
                        if isinstance(arg.annotation, ast.Name):
                            arg_type = arg.annotation.id
                        elif isinstance(arg.annotation, ast.Constant):
                            arg_type = str(arg.annotation.value)

                    cases.append(self.generate(arg_name, arg_type))

        return cases
