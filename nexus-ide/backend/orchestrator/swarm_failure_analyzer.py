"""Swarm Failure Analyzer — diagnoses WHY swarm/auto-swarm executions fail.

Produces structured root-cause reports with remediation.
Uses structured hash + normalized fuzzy match for signature lookup.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FailureSignature:
    signature_hash: str
    project_id: str
    normalized_error: str
    error_type: str
    file_path: str = ""
    function_name: str = ""
    stack_frames: list[str] = field(default_factory=list)
    root_cause: str = ""
    remediation_skill_id: str | None = None
    occurrence_count: int = 1
    first_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_count: int = 0


@dataclass
class CausalLink:
    cause: str
    effect: str
    confidence: float


@dataclass
class FailureDiagnosis:
    diagnosis_id: str
    swarm_result: Any
    objective: str
    session_id: str
    failure_category: str
    root_cause: str
    causal_chain: list[CausalLink]
    matched_signature: str | None
    remediation_skill_id: str | None
    proposed_remediation: str
    confidence: float
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class SwarmFailureAnalyzer:
    """Diagnoses WHY swarm/auto-swarm executions fail."""

    FAILURE_CATEGORIES = {
        "agent_timeout": "Agent exceeded time budget",
        "tool_execution_failed": "Tool returned error",
        "context_overflow": "Token budget exceeded",
        "contradiction_detected": "Agents produced conflicting outputs",
        "synthesis_failed": "LLM merge failed",
        "quality_gate_failed": "Post-execution tests failed",
        "resource_exhaustion": "Global limits hit",
        "cascading_failure": "One agent failure blocked others",
    }

    def __init__(self) -> None:
        self._knowledge_base: Any | None = None
        try:
            from backend.core.knowledge_base import KnowledgeBase
            self._knowledge_base = KnowledgeBase.get_instance()
        except Exception:
            logger.debug("KnowledgeBase not available for SwarmFailureAnalyzer")

    def _compute_signature(self, error_output: str, agent_name: str = "") -> FailureSignature:
        error_type = self._classify_error(error_output)
        file_path, function_name = self._extract_location(error_output)
        stack_frames = self._extract_stack_frames(error_output, top_n=3)
        normalized = self._normalize_error(error_output)
        hash_input = f"{error_type}|{file_path}|{function_name}|{'|'.join(stack_frames)}"
        signature_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
        return FailureSignature(
            signature_hash=signature_hash,
            project_id="*",
            normalized_error=normalized,
            error_type=error_type,
            file_path=file_path,
            function_name=function_name,
            stack_frames=stack_frames,
        )

    def _classify_error(self, error_output: str) -> str:
        text = error_output.lower()
        if "timeout" in text or "timed out" in text:
            return "agent_timeout"
        if "context" in text and ("overflow" in text or "limit" in text or "budget" in text):
            return "context_overflow"
        if "contradiction" in text or "conflict" in text:
            return "contradiction_detected"
        if "synthesis" in text or "merge" in text and "fail" in text:
            return "synthesis_failed"
        if "quality gate" in text or "test" in text and "fail" in text:
            return "quality_gate_failed"
        if "resource" in text or "exhaustion" in text or "limit" in text:
            return "resource_exhaustion"
        if "tool" in text and ("error" in text or "fail" in text):
            return "tool_execution_failed"
        return "unknown"

    def _extract_location(self, error_output: str) -> tuple[str, str]:
        file_match = re.search(r'File "([^"]+)"', error_output)
        func_match = re.search(r'in ([A-Za-z_][A-Za-z0-9_]*)\b', error_output)
        file_path = file_match.group(1) if file_match else ""
        function_name = func_match.group(1) if func_match else ""
        return file_path, function_name

    def _extract_stack_frames(self, error_output: str, top_n: int = 3) -> list[str]:
        frames: list[str] = []
        for line in error_output.splitlines():
            line = line.strip()
            if line.startswith("File "):
                frames.append(line)
            if len(frames) >= top_n:
                break
        return frames

    def _normalize_error(self, error_output: str) -> str:
        normalized = error_output
        normalized = re.sub(r'File "[^"]+"', 'File "<PATH>"', normalized)
        normalized = re.sub(r'line \d+', 'line <N>', normalized)
        normalized = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '<IP>', normalized)
        normalized = re.sub(r'0x[0-9a-fA-F]+', '<HEX>', normalized)
        return normalized.strip()

    def _fuzzy_match(self, a: str, b: str, threshold: float) -> bool:
        if not a or not b:
            return a == b
        a_words = set(a.lower().split())
        b_words = set(b.lower().split())
        if not a_words or not b_words:
            return False
        overlap = len(a_words & b_words) / max(1, len(a_words | b_words))
        return overlap >= threshold

    async def analyze_failure(self, swarm_result: Any, objective: str, session_id: str, project_id: str = "*") -> FailureDiagnosis:
        error_output = getattr(swarm_result, "final_answer", "") or ""
        agent_results = getattr(swarm_result, "agent_results", []) or []
        if not error_output and agent_results:
            failed = [r for r in agent_results if not getattr(r, "success", False)]
            if failed:
                error_output = f"Agent {getattr(failed[0], 'agent', 'unknown')} failed: {getattr(failed[0], 'error', 'unknown')}"
            else:
                error_output = "Swarm completed but no final answer was produced"
        if not error_output:
            error_output = "Unknown swarm failure"

        signature = self._compute_signature(error_output)
        category = signature.error_type
        root_cause = self.FAILURE_CATEGORIES.get(category, "Unknown failure cause")

        matched_signature = None
        remediation_skill_id = None
        if self._knowledge_base:
            try:
                existing = self._knowledge_base.find_matching_signature(project_id, signature.normalized_error, category)
                if existing:
                    matched_signature = existing.signature_hash
                    remediation_skill_id = existing.remediation_skill_id
                    existing.occurrence_count += 1
                    existing.last_seen = datetime.now(UTC)
            except Exception:
                logger.debug("KnowledgeBase lookup failed", exc_info=True)

        if not matched_signature:
            sig_hash = f"{project_id}:{signature.signature_hash}"
            signature.project_id = project_id
            self._knowledge_base.record_signature(
                signature_hash=signature.signature_hash,
                project_id=project_id,
                normalized_error=signature.normalized_error,
                error_type=category,
                file_path=signature.file_path,
                function_name=signature.function_name,
                stack_frames=signature.stack_frames,
                root_cause=root_cause,
            )
            matched_signature = signature.signature_hash

        causal_chain = [CausalLink(cause=category, effect=root_cause, confidence=0.8)]
        proposed_remediation = self._propose_remediation(category, swarm_result)

        diagnosis = FailureDiagnosis(
            diagnosis_id=f"diag-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{signature.signature_hash[:8]}",
            swarm_result=swarm_result,
            objective=objective,
            session_id=session_id,
            failure_category=category,
            root_cause=root_cause,
            causal_chain=causal_chain,
            matched_signature=matched_signature,
            remediation_skill_id=remediation_skill_id,
            proposed_remediation=proposed_remediation,
            confidence=0.7 if matched_signature else 0.4,
        )
        return diagnosis

    def _propose_remediation(self, category: str, swarm_result: Any) -> str:
        remediations = {
            "agent_timeout": "Retry with larger token/time budget or split into smaller subtasks",
            "tool_execution_failed": "Retry with debugger agent or fallback to alternative tool",
            "context_overflow": "Enable context compression and reduce subtask scope",
            "contradiction_detected": "Run debate strategy with moderator agent",
            "synthesis_failed": "Retry synthesis with structured output or fallback to concatenation",
            "quality_gate_failed": "Run fix cycle and re-verify, or rollback and escalate",
            "resource_exhaustion": "Isolate failing agent, retry with ensemble for redundancy",
            "cascading_failure": "Isolate failing agent, fallback to single-agent mode",
        }
        return remediations.get(category, "Escalate to META_ANALYZER for manual review")
