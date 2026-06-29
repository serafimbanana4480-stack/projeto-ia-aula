"""REVIEWER — peer code review agent with security, quality, and style analysis.

Model: qwen2.5-coder:7b (CODER tier). Context 8K.
Prompt: config/prompts/reviewer.md
See ARCHITECTURE.md §3.4.

Supports autonomous execution via ReAct loop:
- Reads files to understand the codebase
- Reviews code for bugs, security issues, style violations, performance
- Suggests improvements with line numbers and severity levels
- Can execute tests to verify correctness
- Generates structured review reports
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from .base import AgentAction, AgentBase, AgentRequest

logger = logging.getLogger(__name__)


@dataclass
class ReviewIssue:
    """Single code review issue with structured metadata."""

    severity: str  # CRITICAL | HIGH | MEDIUM | LOW | INFO
    category: str  # BUG | SECURITY | PERFORMANCE | STYLE | MAINTAINABILITY | TESTING
    file_path: str
    line_start: int
    line_end: int = 0
    description: str = ""
    impact: str = ""
    fix_suggestion: str = ""
    references: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "category": self.category,
            "file": self.file_path,
            "lines": f"{self.line_start}"
            if self.line_end == 0 or self.line_end == self.line_start
            else f"{self.line_start}-{self.line_end}",
            "description": self.description,
            "impact": self.impact,
            "fix_suggestion": self.fix_suggestion,
            "references": self.references,
        }


@dataclass
class ReviewReport:
    """Structured code review report."""

    target: str = ""
    overall_score: int = 0  # 0-100
    verdict: str = "NEEDS_CHANGES"  # APPROVE | APPROVE_WITH_COMMENTS | NEEDS_CHANGES | REJECT
    issues: list[ReviewIssue] = field(default_factory=list)
    positive_findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    test_results: str = ""
    appendix: str = ""

    def summary(self) -> dict[str, Any]:
        severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
        category_counts = {
            "BUG": 0,
            "SECURITY": 0,
            "PERFORMANCE": 0,
            "STYLE": 0,
            "MAINTAINABILITY": 0,
            "TESTING": 0,
        }
        for issue in self.issues:
            severity_counts[issue.severity] = severity_counts.get(issue.severity, 0) + 1
            category_counts[issue.category] = category_counts.get(issue.category, 0) + 1
        return {
            "target": self.target,
            "overall_score": self.overall_score,
            "verdict": self.verdict,
            "total_issues": len(self.issues),
            "by_severity": severity_counts,
            "by_category": category_counts,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Code Review Report: {self.target}",
            "",
            "## Executive Summary",
            f"- **Overall Score**: {self.overall_score}/100",
            f"- **Verdict**: {self.verdict}",
            f"- **Total Issues**: {len(self.issues)}",
            "",
            "### Issues by Severity",
        ]
        severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
        for issue in self.issues:
            severity_counts[issue.severity] = severity_counts.get(issue.severity, 0) + 1
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            if severity_counts[sev] > 0:
                lines.append(f"- {sev}: {severity_counts[sev]}")
        lines.append("")

        if self.issues:
            lines.append("## Detailed Findings")
            lines.append("")
            for idx, issue in enumerate(self.issues, 1):
                lines.extend(
                    [
                        f"### Issue #{idx}",
                        f"- **Severity**: {issue.severity}",
                        f"- **Category**: {issue.category}",
                        f"- **File**: `{issue.file_path}`",
                        f"- **Line(s)**: {issue.line_start}"
                        if issue.line_end == 0 or issue.line_end == issue.line_start
                        else f"- **Line(s)**: {issue.line_start}-{issue.line_end}",
                        f"- **Description**: {issue.description}",
                    ]
                )
                if issue.impact:
                    lines.append(f"- **Impact**: {issue.impact}")
                if issue.fix_suggestion:
                    lines.append(f"- **Fix Suggestion**: {issue.fix_suggestion}")
                if issue.references:
                    lines.append(f"- **References**: {issue.references}")
                lines.append("")

        if self.positive_findings:
            lines.append("## Positive Findings")
            lines.append("")
            for finding in self.positive_findings:
                lines.append(f"- {finding}")
            lines.append("")

        if self.recommendations:
            lines.append("## Recommendations")
            lines.append("")
            for idx, rec in enumerate(self.recommendations, 1):
                lines.append(f"{idx}. {rec}")
            lines.append("")

        if self.test_results:
            lines.append("## Test Results")
            lines.append("")
            lines.append(f"```\n{self.test_results}\n```")
            lines.append("")

        if self.appendix:
            lines.append("## Appendix")
            lines.append("")
            lines.append(self.appendix)
            lines.append("")

        return "\n".join(lines)


class ReviewerAgent(AgentBase):
    """Code review agent with comprehensive analysis capabilities.

    Uses the ReAct loop from AgentBase to autonomously:
    1. Read files to understand the context
    2. Analyze code for bugs, security issues, style violations, performance
    3. Suggest improvements with line numbers and severity levels
    4. Execute tests to verify correctness
    5. Generate structured review reports

    Supports multiple languages: Python, JavaScript, TypeScript, C/C++, Java, Go, Rust, etc.
    """

    name = "REVIEWER"
    model_key = "coder"
    prompt_file = "reviewer"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.READ_FILE_ABSOLUTE,
        AgentAction.WRITE_FILE,
        AgentAction.WRITE_FILE_ABSOLUTE,
        AgentAction.LIST_DIR,
        AgentAction.LIST_DIR_ABSOLUTE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.SEARCH_SYMBOLS,
        AgentAction.INDEX_SYMBOLS,
        AgentAction.CONSULT_AGENT,
        AgentAction.EXECUTE_CODE,
        AgentAction.RECALL_CONTEXT,
        AgentAction.STORE_MEMORY,
        AgentAction.FETCH_URL,
        AgentAction.GENERATE_REPORT,
    }

    # Language-specific file extensions for quick identification
    LANGUAGE_EXTENSIONS = {
        ".py": "Python",
        ".js": "JavaScript",
        ".jsx": "JavaScript (React)",
        ".ts": "TypeScript",
        ".tsx": "TypeScript (React)",
        ".c": "C",
        ".cpp": "C++",
        ".cc": "C++",
        ".h": "C/C++ Header",
        ".hpp": "C++ Header",
        ".java": "Java",
        ".go": "Go",
        ".rs": "Rust",
        ".cs": "C#",
        ".rb": "Ruby",
        ".php": "PHP",
        ".swift": "Swift",
        ".kt": "Kotlin",
        ".sh": "Shell/Bash",
        ".sql": "SQL",
        ".html": "HTML",
        ".css": "CSS",
        ".scss": "SCSS",
        ".sass": "Sass",
    }

    def detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension."""
        from pathlib import Path

        ext = Path(file_path).suffix.lower()
        return self.LANGUAGE_EXTENSIONS.get(ext, "Unknown")

    def extract_issues_from_response(
        self, response_text: str, file_path: str = ""
    ) -> list[ReviewIssue]:
        """Parse structured issues from LLM response text.

        Attempts to extract issues marked with severity/category patterns.
        """
        issues: list[ReviewIssue] = []

        # Pattern: **Severity**: VALUE or - Severity: VALUE
        severity_pattern = r"(?:\*\*|\b)Severity\*?\*?\s*[:\-]\s*(CRITICAL|HIGH|MEDIUM|LOW|INFO)"
        category_pattern = r"(?:\*\*|\b)Category\*?\*?\s*[:\-]\s*(BUG|SECURITY|PERFORMANCE|STYLE|MAINTAINABILITY|TESTING)"
        line_pattern = r"(?:\*\*|\b)Line\(s\)\*?\*?\s*[:\-]\s*(\d+)(?:\s*-\s*(\d+))?"
        description_pattern = r"(?:\*\*|\b)Description\*?\*?\s*[:\-]\s*([^\n]+)"
        impact_pattern = r"(?:\*\*|\b)Impact\*?\*?\s*[:\-]\s*([^\n]+)"
        fix_pattern = r"(?:\*\*|\b)Fix\s*Suggestion\*?\*?\s*[:\-]\s*([^\n]+)"
        ref_pattern = r"(?:\*\*|\b)References?\*?\*?\s*[:\-]\s*([^\n]+)"

        import re

        # Split response into potential issue blocks (look for headers like ### Issue or numbered lists)
        blocks = re.split(
            r"(?:\n#{1,3}\s*Issue\s*#?\d+|\n\d+\.\s*\*\*.*\*\*|\n-?\s*\*\*Severity\*\*)",
            response_text,
        )

        for block in blocks:
            if not block.strip():
                continue

            sev_match = re.search(severity_pattern, block, re.IGNORECASE)
            cat_match = re.search(category_pattern, block, re.IGNORECASE)
            line_match = re.search(line_pattern, block)
            desc_match = re.search(description_pattern, block)
            impact_match = re.search(impact_pattern, block)
            fix_match = re.search(fix_pattern, block)
            ref_match = re.search(ref_pattern, block)

            if sev_match and cat_match and desc_match:
                line_start = int(line_match.group(1)) if line_match else 0
                line_end = (
                    int(line_match.group(2)) if line_match and line_match.group(2) else line_start
                )

                issue = ReviewIssue(
                    severity=sev_match.group(1).upper(),
                    category=cat_match.group(1).upper(),
                    file_path=file_path,
                    line_start=line_start,
                    line_end=line_end,
                    description=desc_match.group(1).strip(),
                    impact=impact_match.group(1).strip() if impact_match else "",
                    fix_suggestion=fix_match.group(1).strip() if fix_match else "",
                    references=ref_match.group(1).strip() if ref_match else "",
                )
                issues.append(issue)

        return issues

    def calculate_score(self, issues: list[ReviewIssue]) -> int:
        """Calculate overall quality score (0-100) based on issue severity."""
        severity_weights = {
            "CRITICAL": 25,
            "HIGH": 10,
            "MEDIUM": 4,
            "LOW": 1,
            "INFO": 0,
        }
        total_deduction = sum(severity_weights.get(issue.severity, 0) for issue in issues)
        # Cap at 100 points deduction
        return max(0, 100 - min(total_deduction, 100))

    def determine_verdict(self, score: int, critical_count: int) -> str:
        """Determine review verdict based on score and critical issues."""
        if critical_count > 0:
            return "REJECT"
        if score >= 90:
            return "APPROVE"
        if score >= 70:
            return "APPROVE_WITH_COMMENTS"
        if score >= 50:
            return "NEEDS_CHANGES"
        return "REJECT"

    def build_review_context(self, request: AgentRequest) -> str:
        """Build additional context for the review request."""
        context_parts = []

        # Language detection hint
        query = request.query.lower()
        if any(ext in query for ext in [".py", "python"]):
            context_parts.append("Language: Python")
        elif any(ext in query for ext in [".js", "javascript", "jsx"]):
            context_parts.append("Language: JavaScript")
        elif any(ext in query for ext in [".ts", "typescript", "tsx"]):
            context_parts.append("Language: TypeScript")
        elif any(ext in query for ext in [".c", ".cpp", ".h", "c++"]):
            context_parts.append("Language: C/C++")
        elif any(ext in query for ext in [".java", "java "]):
            context_parts.append("Language: Java")
        elif any(ext in query for ext in [".go", "golang"]):
            context_parts.append("Language: Go")
        elif any(ext in query for ext in [".rs", "rust"]):
            context_parts.append("Language: Rust")

        # Review scope hint
        if "security" in query:
            context_parts.append("Focus: Security-focused review")
        elif "performance" in query:
            context_parts.append("Focus: Performance-focused review")
        elif "style" in query or "lint" in query:
            context_parts.append("Focus: Style and maintainability review")
        elif "test" in query:
            context_parts.append("Focus: Test coverage review")
        else:
            context_parts.append(
                "Focus: Comprehensive review (quality, security, performance, style)"
            )

        # Project path context
        if request.project_path:
            context_parts.append(f"Project: {request.project_path}")

        return "\n".join(context_parts) if context_parts else ""

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        """Execute the reviewer agent with ReAct loop.

        Injects review-specific context (language, focus, project path) before
        running the standard ReAct loop.
        """
        # Build review context and inject into request
        review_context = self.build_review_context(request)
        if review_context:
            original_query = request.query
            request.query = f"{original_query}\n\n[Review Context]\n{review_context}"
            logger.info("[REVIEWER] Enhanced query with context | session=%s", request.session_id)

        logger.info(
            "[REVIEWER] Starting review | session=%s | query=%.80s | project=%s",
            request.session_id,
            request.query,
            request.project_path,
        )

        # Run the standard ReAct loop
        async for token in self._run_react_loop(request):
            yield token

        # After ReAct loop completes, attempt to store a structured review summary
        # This is best-effort; failures are logged but not propagated
        try:
            await self._store_review_summary(request)
        except Exception as exc:
            logger.debug("[REVIEWER] Failed to store review summary: %s", exc)

    async def _store_review_summary(self, request: AgentRequest) -> None:
        """Store a summary of the review in semantic memory for future reference."""
        if not self.enable_memory:
            return

        try:
            from backend.knowledge.memory import MemoryType, get_memory_store

            mem_store = get_memory_store()
            summary = f"Review session for query: {request.query[:200]}"
            await mem_store.store(
                content=summary,
                memory_type=MemoryType.PROJECT,
                session_id=request.session_id,
                project_id=request.project_path or "",
                source=self.name,
                tags=["review", "code_review", "auto_memory"],
                importance=0.6,
            )
        except Exception as exc:
            logger.debug("[REVIEWER] Memory store failed: %s", exc)
