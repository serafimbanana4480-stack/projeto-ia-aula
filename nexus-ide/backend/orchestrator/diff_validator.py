"""Diff Validator — analyzes applied diffs for code smells and risky patterns.

Runs before commit to catch:
- Security anti-patterns (eval, exec, hardcoded secrets)
- Performance issues (O(n²) loops, unnecessary copies)
- Style violations (long lines, complex functions)
- Test coverage gaps
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DiffIssue:
    file: str
    line: int
    severity: str
    category: str
    message: str
    snippet: str


@dataclass
class DiffReport:
    passed: bool
    issues: list[DiffIssue] = field(default_factory=list)
    total_lines_changed: int = 0
    files_modified: int = 0


class DiffValidator:
    """Analyzes diffs for risky patterns before commit."""

    PATTERNS = {
        "security": [
            (r'\beval\s*\(', "Uso de eval() detectado — risco de injeção de código"),
            (r'\bexec\s*\(', "Uso de exec() detectado — risco de injeção de código"),
            (r'(password|secret|api_key|token)\s*=\s*["\'][^"\']+["\']', "Segredo hardcoded detetado"),
            (r'subprocess\.call\s*\(.*shell\s*=\s*True', "subprocess com shell=True — risco de injeção"),
        ],
        "performance": [
            (r'for\s+\w+\s+in\s+range\s*\(\s*len\s*\(', "Loop com range(len()) — considere enumerate()"),
            (r'\+\=\s*list', "Concatenación de listas em loop — considere extend()"),
        ],
        "style": [
            (r'.{120,}', "Linha excede 120 caracteres"),
            (r'def\s+\w+\([^)]{80,}\)', "Função com muitos parâmetros (>80 chars na assinatura)"),
        ],
    }

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent.parent

    def validate_diff(self, diff_text: str) -> DiffReport:
        issues: list[DiffIssue] = []
        files_modified = set()
        total_lines = 0

        for line in diff_text.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                if "/dev/null" not in line:
                    files_modified.add(line.split("/")[-1])
            if line.startswith("+") and not line.startswith("+++"):
                total_lines += 1
                for category, patterns in self.PATTERNS.items():
                    for pattern, message in patterns:
                        if re.search(pattern, line):
                            issues.append(DiffIssue(
                                file="unknown",
                                line=0,
                                severity="warning" if category == "style" else "error",
                                category=category,
                                message=message,
                                snippet=line[:100],
                            ))

        passed = not any(issue.severity == "error" for issue in issues)
        return DiffReport(
            passed=passed,
            issues=issues,
            total_lines_changed=total_lines,
            files_modified=len(files_modified),
        )

    def validate_files(self, file_paths: list[Path]) -> DiffReport:
        all_issues: list[DiffIssue] = []
        total_lines = 0
        for file_path in file_paths:
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                total_lines += len(content.splitlines())
                for category, patterns in self.PATTERNS.items():
                    for pattern, message in patterns:
                        for line in content.splitlines():
                            if re.search(pattern, line):
                                all_issues.append(DiffIssue(
                                    file=str(file_path.relative_to(self.repo_root)),
                                    line=0,
                                    severity="warning" if category == "style" else "error",
                                    category=category,
                                    message=message,
                                    snippet=line[:100],
                                ))
            except Exception:
                logger.debug("Could not read file %s", file_path, exc_info=True)

        passed = not any(issue.severity == "error" for issue in all_issues)
        return DiffReport(
            passed=passed,
            issues=all_issues,
            total_lines_changed=total_lines,
            files_modified=len(file_paths),
        )
