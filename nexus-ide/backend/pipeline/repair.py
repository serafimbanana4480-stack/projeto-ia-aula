"""RepairAgent and RepairLoop — automatic failure classification and patching.

Ingests structured failure reports, generates patches via LLM,
re-submits to sandbox, and escalates on max attempts.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from backend.config.settings import get_settings
from backend.knowledge.memory import MemoryStore
from backend.tools.ollama_client import OllamaClient

from .test_generator import FailureType, TestRunner, TestSuiteReport

logger = logging.getLogger(__name__)


class RepairState(str, Enum):
    """State machine for repair attempts."""

    PENDING = "pending"
    ANALYZING = "analyzing"
    PATCHING = "patching"
    TESTING = "testing"
    RESOLVED = "resolved"
    FAILED = "failed"
    ESCALATED = "escalated"


@dataclass
class FailureReport:
    """Structured failure report for repair."""

    report_id: str = field(default_factory=lambda: f"fail-{uuid.uuid4().hex[:8]}")
    story_id: str = ""
    failure_type: FailureType = FailureType.UNKNOWN
    error_message: str = ""
    traceback: str = ""
    source_path: str = ""
    source_context: str = ""  # Relevant lines ±20
    test_name: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "story_id": self.story_id,
            "failure_type": self.failure_type.value,
            "error_message": self.error_message,
            "traceback": self.traceback,
            "source_path": self.source_path,
            "source_context": self.source_context,
            "test_name": self.test_name,
            "timestamp": self.timestamp,
        }


@dataclass
class RepairAttempt:
    """Record of a single repair attempt."""

    attempt_number: int
    state: RepairState
    patch: str = ""
    test_results: TestSuiteReport = field(default_factory=TestSuiteReport)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str = ""
    notes: str = ""


@dataclass
class RepairTicket:
    """Full lifecycle of a repair process."""

    ticket_id: str = field(default_factory=lambda: f"repair-{uuid.uuid4().hex[:8]}")
    story_id: str = ""
    state: RepairState = RepairState.PENDING
    failures: list[FailureReport] = field(default_factory=list)
    attempts: list[RepairAttempt] = field(default_factory=list)
    max_attempts: int = 5
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    resolved_at: str = ""
    escalation_reason: str = ""

    @property
    def current_attempt(self) -> int:
        return len(self.attempts)

    @property
    def can_retry(self) -> bool:
        return self.current_attempt < self.max_attempts and self.state not in (
            RepairState.RESOLVED,
            RepairState.ESCALATED,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "story_id": self.story_id,
            "state": self.state.value,
            "current_attempt": self.current_attempt,
            "max_attempts": self.max_attempts,
            "can_retry": self.can_retry,
            "failures": [f.to_dict() for f in self.failures],
            "attempts": [
                {
                    "attempt_number": a.attempt_number,
                    "state": a.state.value,
                    "started_at": a.started_at,
                    "completed_at": a.completed_at,
                    "notes": a.notes,
                }
                for a in self.attempts
            ],
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "escalation_reason": self.escalation_reason,
        }


class RepairAgent:
    """Generates code patches from failure reports using LLM."""

    SYSTEM_PROMPT = """You are NEXUS-DEBUGGER, an expert debugging AI.
Your task is to analyze test failures and generate minimal, correct patches.

RULES:
1. Generate ONLY a unified diff patch — no explanations, no markdown
2. Keep patches minimal: change the fewest lines possible
3. Preserve existing style and conventions
4. Fix the ROOT CAUSE, not just the symptom
5. If the error is a missing dependency, add the import or requirement
6. If the error is a logic bug, fix the implementation
7. If the error is a test expectation mismatch, check if the test is wrong

PATCH FORMAT:
```diff
--- a/path/to/file.py
+++ b/path/to/file.py
@@ -line,range +line,range @@
 context
-context_to_remove
+context_to_add
 context
```

Return ONLY the diff block. No other text."""

    def __init__(
        self,
        ollama_client: OllamaClient | None = None,
        memory_store: MemoryStore | None = None,
    ) -> None:
        self._client = ollama_client or OllamaClient(get_settings().ollama_host)
        self._memory = memory_store

    async def generate_patch(
        self,
        failure: FailureReport,
        source_code: str,
    ) -> str:
        """Generate a unified diff patch for the given failure.

        Args:
            failure: Structured failure report.
            source_code: Current source code of the failing file.

        Returns:
            Unified diff string or empty if no patch could be generated.
        """
        # Query memory for similar past repairs
        memory_context = ""
        if self._memory:
            try:
                similar = self._memory.search(
                    query=f"{failure.failure_type.value} {failure.error_message}",
                    limit=3,
                )
                if similar:
                    memory_context = "\n\nSimilar past failures:\n" + json.dumps(similar, indent=2)
            except Exception as exc:
                logger.warning("Memory query failed: %s", exc)

        prompt = f"""FAILURE TYPE: {failure.failure_type.value}
ERROR: {failure.error_message}

TRACEBACK:
{failure.traceback[:2000]}

SOURCE CODE ({failure.source_path}):
```python
{source_code[:6000]}
```
{memory_context}

Generate a unified diff patch to fix this failure."""

        try:
            response = await self._client.chat(
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model="llama3.2",
                temperature=0.2,
            )
            content = response.content if hasattr(response, "content") else str(response)
            patch = self._extract_diff(content)

            if patch:
                logger.info("Generated patch for %s", failure.source_path)
                return patch

            logger.warning("No diff found in LLM response")
            return ""

        except Exception as exc:
            logger.error("Patch generation failed: %s", exc)
            return ""

    def _extract_diff(self, content: str) -> str:
        """Extract diff block from LLM response."""
        # Look for ```diff blocks
        if "```diff" in content:
            return content.split("```diff")[1].split("```")[0].strip()
        # Look for raw diff
        if content.startswith("---"):
            return content.strip()
        return ""

    @staticmethod
    def apply_patch(patch: str, source_path: Path) -> bool:
        """Apply a unified diff patch to a file.

        Args:
            patch: Unified diff string.
            source_path: Path to the file to patch.

        Returns:
            True if patch applied successfully.
        """
        # Validate patch format
        if not patch.strip() or "---" not in patch or "+++" not in patch or "@@" not in patch:
            logger.warning("Invalid or empty patch format")
            return False

        try:
            # Simple line-based patch application for single-file patches
            lines = patch.split("\n")
            original_lines = source_path.read_text(encoding="utf-8").split("\n")
            patched_lines = original_lines.copy()

            # Track line offsets
            i = 0
            while i < len(lines):
                line = lines[i]
                if line.startswith("@@"):
                    # Parse hunk header: @@ -old_line,old_count +new_line,new_count @@
                    match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
                    if match:
                        old_start = int(match.group(1)) - 1  # 0-based
                        new_start = int(match.group(2)) - 1
                        new_start - old_start

                        # Collect hunk lines
                        hunk_remove: list[str] = []
                        hunk_add: list[str] = []
                        i += 1
                        while i < len(lines) and not lines[i].startswith("@@"):
                            if lines[i].startswith("-") and not lines[i].startswith("---"):
                                hunk_remove.append(lines[i][1:])
                            elif lines[i].startswith("+") and not lines[i].startswith("+++"):
                                hunk_add.append(lines[i][1:])
                            elif not lines[i].startswith("\\"):
                                # Context line
                                hunk_remove.append(lines[i])
                                hunk_add.append(lines[i])
                            i += 1

                        # Apply hunk
                        start_idx = old_start
                        end_idx = old_start + len(hunk_remove)
                        patched_lines[start_idx:end_idx] = hunk_add
                    else:
                        i += 1
                else:
                    i += 1

            source_path.write_text("\n".join(patched_lines), encoding="utf-8")
            logger.info("Applied patch to %s", source_path)
            return True

        except Exception as exc:
            logger.error("Patch application failed: %s", exc)
            return False


class RepairLoop:
    """Orchestrates the repair lifecycle: detect -> analyze -> patch -> test."""

    def __init__(
        self,
        repair_agent: RepairAgent,
        test_runner: TestRunner,
        max_attempts: int = 5,
        backoff_base: float = 2.0,
    ) -> None:
        self.repair_agent = repair_agent
        self.test_runner = test_runner
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base

    async def repair(
        self,
        project_path: Path,
        test_report: TestSuiteReport,
        story_id: str = "",
    ) -> RepairTicket:
        """Run the repair loop on failing tests.

        Args:
            project_path: Path to the project directory.
            test_report: Test report with failures.
            story_id: Optional story identifier.

        Returns:
            RepairTicket with full lifecycle record.
        """
        ticket = RepairTicket(
            story_id=story_id,
            max_attempts=self.max_attempts,
        )

        # Build failure reports
        for result in test_report.failures():
            failure = FailureReport(
                story_id=story_id,
                failure_type=result.failure_type,
                error_message=result.error_message,
                traceback=result.traceback,
                test_name=result.test_name,
            )
            ticket.failures.append(failure)

        if not ticket.failures:
            ticket.state = RepairState.RESOLVED
            ticket.resolved_at = datetime.now(UTC).isoformat()
            return ticket

        logger.info("Repair loop starting for %d failures", len(ticket.failures))

        while ticket.can_retry:
            attempt = RepairAttempt(attempt_number=ticket.current_attempt + 1, state=RepairState.ANALYZING)
            ticket.attempts.append(attempt)
            ticket.state = RepairState.ANALYZING

            # Process each failure
            for failure in ticket.failures:
                # Find source file
                source_path = self._locate_source_file(project_path, failure)
                if not source_path or not source_path.exists():
                    attempt.notes += f"Source not found for {failure.source_path}\n"
                    continue

                failure.source_path = str(source_path.relative_to(project_path))
                source_code = source_path.read_text(encoding="utf-8")
                failure.source_context = self._extract_context(source_code, failure.traceback)

                # Generate patch
                ticket.state = RepairState.PATCHING
                attempt.state = RepairState.PATCHING
                patch = await self.repair_agent.generate_patch(failure, source_code)

                if patch:
                    attempt.patch = patch
                    if not RepairAgent.apply_patch(patch, source_path):
                        attempt.notes += f"Failed to apply patch for {failure.source_path}\n"
                        continue

            # Re-run tests
            ticket.state = RepairState.TESTING
            attempt.state = RepairState.TESTING
            new_report = self.test_runner.run(project_path)
            attempt.test_results = new_report
            attempt.completed_at = datetime.now(UTC).isoformat()

            if not new_report.failures():
                ticket.state = RepairState.RESOLVED
                ticket.resolved_at = datetime.now(UTC).isoformat()
                attempt.notes += "All tests passing after repair.\n"
                logger.info("Repair loop resolved after %d attempts", ticket.current_attempt)
                return ticket

            # Exponential backoff
            if ticket.can_retry:
                import asyncio
                delay = self.backoff_base ** ticket.current_attempt
                attempt.notes += f"Waiting {delay}s before retry...\n"
                await asyncio.sleep(delay)

        # Max attempts exceeded
        ticket.state = RepairState.ESCALATED
        ticket.escalation_reason = f"Max attempts ({self.max_attempts}) exceeded. {len(ticket.failures)} failures remain."
        logger.warning("Repair loop escalated: %s", ticket.escalation_reason)

        # Log to memory if available
        if self.repair_agent._memory:
            try:
                self.repair_agent._memory.store(
                    content=json.dumps(ticket.to_dict()),
                    memory_type="repair_escalation",
                    tags=["repair", "escalation", story_id],
                )
            except Exception as exc:
                logger.warning("Failed to log escalation: %s", exc)

        return ticket

    @staticmethod
    def _locate_source_file(project_path: Path, failure: FailureReport) -> Path | None:
        """Try to locate the source file from traceback or test name."""
        # Extract file from traceback
        if failure.traceback:
            match = re.search(r'File "([^"]+)"', failure.traceback)
            if match:
                candidate = Path(match.group(1))
                if candidate.exists():
                    return candidate
                # Try relative to project
                rel = project_path / candidate.name
                if rel.exists():
                    return rel

        # Infer from test name (e.g., test_module_func -> module.py)
        if failure.test_name:
            parts = failure.test_name.replace("test_", "").split(".")
            for part in parts:
                candidate = project_path / f"{part}.py"
                if candidate.exists():
                    return candidate
                candidate = project_path / "app" / f"{part}.py"
                if candidate.exists():
                    return candidate

        return None

    @staticmethod
    def _extract_context(source_code: str, traceback: str, radius: int = 20) -> str:
        """Extract relevant source lines around the error."""
        lines = source_code.split("\n")
        target_line = 0

        # Find line number from traceback
        if traceback:
            matches = re.findall(r'line (\d+)', traceback)
            if matches:
                target_line = int(matches[-1]) - 1  # 0-based

        start = max(0, target_line - radius)
        end = min(len(lines), target_line + radius + 1)
        context_lines = lines[start:end]

        # Add line numbers
        numbered = [f"{start + i + 1:4d}: {line}" for i, line in enumerate(context_lines)]
        return "\n".join(numbered)
