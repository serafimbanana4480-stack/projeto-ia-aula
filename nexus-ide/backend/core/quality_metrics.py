from __future__ import annotations

import ast
import hashlib
import importlib.util
import logging
import math
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class QualityMetrics:
    coverage_percent: float = 0.0
    cyclomatic_complexity: float = 0.0
    maintainability_index: float = 100.0
    lint_score: float = 100.0
    security_issues_count: int = 0
    duplication_ratio: float = 0.0
    technical_debt_ratio: float = 0.0


def _run_cmd(cmd: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return -1, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -1, "", "command timed out"
    except Exception as exc:
        return -1, "", str(exc)


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _collect_python_files(project_path: str) -> list[Path]:
    root = Path(project_path)
    if not root.exists():
        return []
    return [
        p
        for p in root.rglob("*.py")
        if p.is_file()
        and ".venv" not in str(p)
        and "venv" not in str(p)
        and "__pycache__" not in str(p)
    ]


async def _measure_coverage(project_path: str) -> float:
    xml_path = Path(project_path) / "coverage.xml"
    if xml_path.exists():
        try:
            import xml.etree.ElementTree as ET

            tree = ET.parse(str(xml_path))
            root = tree.getroot()
            line_rate = root.attrib.get("line-rate")
            if line_rate is not None:
                return round(float(line_rate) * 100, 2)
        except Exception as exc:
            logger.debug("Failed to parse coverage.xml: %s", exc)

    if _has_module("pytest") or _has_module("coverage"):
        returncode, stdout, stderr = _run_cmd(
            ["python", "-m", "pytest", "--cov", "--cov-report=term-missing", "--tb=no", "-q"],
            cwd=project_path,
        )
        if returncode == 0 or returncode == 1:
            for line in stdout.splitlines():
                line = line.strip()
                if line.startswith("TOTAL "):
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            return float(parts[3].rstrip("%"))
                        except ValueError:
                            pass
    logger.warning("Coverage unavailable, using fallback 0.0")
    return 0.0


def _compute_ast_complexity(source: str) -> float:
    try:
        tree = ast.parse(source)
        visitor = _ComplexityVisitor()
        visitor.visit(tree)
        return float(visitor.complexity)
    except Exception:
        return 1.0


class _ComplexityVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.complexity = 1.0

    def visit_If(self, node: ast.AST) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.AST) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AST) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.AST) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_Try(self, node: ast.AST) -> None:  # pragma: no cover - defensive
        self.complexity += 1
        self.generic_visit(node)

    def visit_With(self, node: ast.AST) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.AST) -> None:
        self.complexity += len(getattr(node, "values", [])) - 1
        self.generic_visit(node)

    def visit_ListComp(self, node: ast.AST) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_SetComp(self, node: ast.AST) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_DictComp(self, node: ast.AST) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_GeneratorExp(self, node: ast.AST) -> None:
        self.complexity += 1
        self.generic_visit(node)


async def _measure_complexity(project_path: str) -> float:
    files = _collect_python_files(project_path)
    if not files:
        return 0.0
    total = 0.0
    for filepath in files:
        try:
            source = filepath.read_text(encoding="utf-8", errors="ignore")
            total += _compute_ast_complexity(source)
        except Exception as exc:
            logger.debug("Failed to read %s: %s", filepath, exc)
    return round(total / len(files), 2)


async def _measure_maintainability(cyclomatic_complexity: float, duplication_ratio: float) -> float:
    try:
        cc = cyclomatic_complexity if cyclomatic_complexity > 0 else 1.0
        raw = 171 - 5.2 * math.log(cc) - 0.23 * cc - 16.2 * math.log(cc) - 50 * duplication_ratio
        return round(max(0.0, min(100.0, raw)), 2)
    except Exception:
        return 100.0


def _normalize_score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


async def _measure_lint(project_path: str) -> float:
    files = _collect_python_files(project_path)
    if not files:
        return 100.0
    if _has_module("ruff"):
        file_args = [str(f) for f in files]
        returncode, stdout, stderr = _run_cmd(
            ["ruff", "check", "--output-format=concise"] + file_args,
            cwd=project_path,
        )
        if returncode != -1:
            issues = len(
                [
                    line
                    for line in stdout.splitlines()
                    if line.strip() and not line.strip().startswith("All")
                ]
            )
            score = 100.0 - (issues * 5.0)
            return _normalize_score(score)
    logger.warning("ruff not available, using heuristic lint score")
    issue_indicators = 0
    max_check = min(len(files), 50)
    for filepath in files[:max_check]:
        try:
            source = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        lines = source.splitlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("print(") and not stripped.startswith("#"):
                issue_indicators += 1
            if "import *" in stripped:
                issue_indicators += 1
            if stripped == "except:":
                issue_indicators += 1
    issue_indicators += sum(
        1
        for _ in files[:max_check]
        if len(_.read_text(encoding="utf-8", errors="ignore").splitlines()) > 500
    )
    score = 100.0 - (issue_indicators * 2.0)
    return _normalize_score(score)


async def _measure_security(project_path: str) -> int:
    files = _collect_python_files(project_path)
    if not files:
        return 0
    if _has_module("bandit"):
        file_args = [str(f) for f in files]
        returncode, stdout, stderr = _run_cmd(
            ["bandit", "-q", "-f", "txt"] + file_args,
            cwd=project_path,
        )
        if returncode != -1:
            return sum(
                1
                for line in stdout.splitlines()
                if line.strip() and not line.strip().startswith(">>")
            )
    logger.warning("bandit not available, using heuristic security issues count")
    count = 0
    max_check = min(len(files), 100)
    for filepath in files[:max_check]:
        try:
            source = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "eval(" in source:
            count += source.count("eval(")
        if " exec(" in source:
            count += source.count(" exec(")
        if "os.system(" in source:
            count += source.count("os.system(")
        if "subprocess.call(" in source:
            count += source.count("subprocess.call(")
        if "__import__(" in source:
            count += source.count("__import__(")
        if "pickle.loads(" in source:
            count += source.count("pickle.loads(")
    return count


async def _measure_duplication(project_path: str) -> float:
    files = _collect_python_files(project_path)
    if len(files) < 2:
        return 0.0
    block_hashes: set[str] = set()
    total_blocks = 0
    duplicate_blocks = 0
    block_size = 6

    for filepath in files:
        try:
            source = filepath.read_text(encoding="utf-8", errors="ignore")
            lines = [line.strip() for line in source.splitlines() if line.strip()]
        except Exception:
            continue
        for i in range(0, max(1, len(lines) - block_size + 1)):
            block = tuple(lines[i : i + block_size])
            normalized = "\n".join(block)
            block_hash = hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()
            total_blocks += 1
            if block_hash in block_hashes:
                duplicate_blocks += 1
            else:
                block_hashes.add(block_hash)

    if total_blocks == 0:
        return 0.0
    ratio = duplicate_blocks / total_blocks
    return round(ratio * 100, 2)


async def _measure_technical_debt(
    cyclomatic_complexity: float,
    lint_score: float,
    security_issues_count: int,
    duplication_ratio: float,
) -> float:
    try:
        complexity_penalty = max(0.0, cyclomatic_complexity - 10.0) * 2.0
        lint_penalty = max(0.0, 100.0 - lint_score) * 1.5
        security_penalty = security_issues_count * 10.0
        duplication_penalty = duplication_ratio * 3.0
        total = complexity_penalty + lint_penalty + security_penalty + duplication_penalty
        return round(total / 10.0, 2)
    except Exception:
        return 0.0


async def measure(project_path: str) -> QualityMetrics:
    path = os.path.abspath(project_path)
    if not os.path.isdir(path):
        raise ValueError(f"Invalid project path: {path}")

    logger.info("Measuring quality metrics for %s", path)

    coverage_percent = await _measure_coverage(path)
    cyclomatic_complexity = await _measure_complexity(path)
    duplication_ratio = await _measure_duplication(path)
    maintainability_index = await _measure_maintainability(cyclomatic_complexity, duplication_ratio)
    lint_score = await _measure_lint(path)
    security_issues_count = await _measure_security(path)
    technical_debt_ratio = await _measure_technical_debt(
        cyclomatic_complexity=cyclomatic_complexity,
        lint_score=lint_score,
        security_issues_count=security_issues_count,
        duplication_ratio=duplication_ratio,
    )

    metrics = QualityMetrics(
        coverage_percent=coverage_percent,
        cyclomatic_complexity=cyclomatic_complexity,
        maintainability_index=maintainability_index,
        lint_score=lint_score,
        security_issues_count=security_issues_count,
        duplication_ratio=duplication_ratio,
        technical_debt_ratio=technical_debt_ratio,
    )

    logger.info("Quality metrics measured: %s", metrics)
    return metrics


_HIGHER_IS_BETTER = {"coverage_percent", "maintainability_index", "lint_score"}
_LOWER_IS_BETTER = {
    "cyclomatic_complexity",
    "security_issues_count",
    "duplication_ratio",
    "technical_debt_ratio",
}


def _compare_single(prev_value, new_value, metric_name: str) -> str:
    if metric_name in _HIGHER_IS_BETTER:
        if new_value > prev_value:
            return "improved"
        if new_value < prev_value:
            return "regressed"
    elif metric_name in _LOWER_IS_BETTER:
        if new_value < prev_value:
            return "improved"
        if new_value > prev_value:
            return "regressed"
    return "unchanged"


def compare(project_path: str, baseline: QualityMetrics | None = None) -> dict:
    import asyncio

    current = asyncio.get_event_loop().run_until_complete(measure(project_path))
    result = {
        metric_name: {
            "current": value,
            "previous": getattr(baseline, metric_name) if baseline else None,
            "status": _compare_single(
                getattr(baseline, metric_name) if baseline else value,
                value,
                metric_name,
            ),
        }
        for metric_name, value in current.__dict__.items()
    }
    if baseline is None:
        logger.info("Comparison generated without baseline (first run)")
    else:
        logger.info("Comparison against baseline: %s", result)
    return result


def should_reject_fix(prev: QualityMetrics, new: QualityMetrics) -> bool:
    critical_rejections = [
        new.coverage_percent < prev.coverage_percent,
        new.cyclomatic_complexity > prev.cyclomatic_complexity,
        new.security_issues_count > prev.security_issues_count,
        new.maintainability_index < prev.maintainability_index,
    ]
    rejected = any(critical_rejections)
    if rejected:
        logger.warning(
            "Fix rejected. Coverage: %.2f -> %.2f, Complexity: %.2f -> %.2f, "
            "Security issues: %d -> %d, Maintainability: %.2f -> %.2f",
            prev.coverage_percent,
            new.coverage_percent,
            prev.cyclomatic_complexity,
            new.cyclomatic_complexity,
            prev.security_issues_count,
            new.security_issues_count,
            prev.maintainability_index,
            new.maintainability_index,
        )
    return rejected
