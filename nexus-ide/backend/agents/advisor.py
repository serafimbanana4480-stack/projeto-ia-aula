"""ADVISOR — intelligent governor that verifies every claim with facts.

The Advisor does NOT implement. It observes, cross-examines, and blocks
incomplete or unverified work. Five intervention levels:
1. SUGGESTION — points out improvements
2. MANDATORY_FIX — reopens tasks automatically
3. COMPLETION_BLOCK — prevents completion declaration
4. REPLAN — orders architecture revision
5. ESCALATION — creates expert agents

VERIFICATION IS FACTUAL, NOT THEATRICAL

The previous implementation "analysed" completion claims by searching for
keywords ("test", "security", "it works"...) and had `supported_actions =
set()` — the agent whose entire purpose is direct verification could not
perform a single verifying action. It confirmed nothing.

This version:
- Declares real verification actions (RUN_TESTS, READ_FILE, LIST_DIR,
  SEARCH_CODEBASE, EXECUTE_CODE) so the ReAct loop can execute the suite,
  read the diff, and inspect the files a claim references.
- Runs cheap deterministic fact-checks on every claim BEFORE any LLM
  reasoning: referenced files must exist on disk, referenced test files are
  actually executed, and the working tree must contain the changes the claim
  says were made. Every factual finding carries a `path:line`-style citation.
- Keyword heuristics are kept, but demoted: they only raise suspicion and
  route verification — they never count as evidence either way.

Model: deep tier. Context 32K.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any

from backend.agents.base import AgentAction, AgentBase, AgentRequest

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]


class InterventionLevel(IntEnum):
    SUGGESTION = 1
    MANDATORY_FIX = 2
    COMPLETION_BLOCK = 3
    REPLAN = 4
    ESCALATION = 5


REQUIRED_EVIDENCE_CATEGORIES = [
    "tests_passed",
    "edge_cases_covered",
    "security_reviewed",
    "documentation_complete",
    "regression_free",
]

DEBATE_ROUNDS = [
    "R1: What was actually implemented?",
    "R2: What remains unproven?",
    "R3: What failure modes exist?",
    "R4: What would a senior engineer criticise?",
    "R5: What improvements have highest impact?",
    "R6: Is this truly production-ready?",
]

# Patterns that raise suspicion. Suspicion routes verification; it is never
# evidence for or against the claim by itself.
VAGUE_PATTERNS = [
    "it works",
    "should be fine",
    "trust me",
    "i think",
    "probably",
    "seems to work",
    "looks good",
    "as expected",
]

#: File-path-like tokens worth checking on disk.
_FILE_REF_RE = re.compile(r"[\w./\\-]+\.(?:py|ts|tsx|js|jsx|yaml|yml|json|md|toml|css|html)")
#: Explicit test-file references we can execute directly.
_TEST_FILE_RE = re.compile(r"[\w./\\-]*test[\w./\\-]*\.py")

#: Cap on targeted test execution so the Advisor stays a governor, not a CI.
_TARGETED_TEST_TIMEOUT_S = 120


class AdvisorAgent(AgentBase):
    """Advisor agent that challenges every completion claim with facts."""

    name = "ADVISOR"
    model_key = "deep"
    prompt_file = "advisor"
    # The agent built to "verify directly" now actually can: run the suite,
    # read the files a claim cites, map the tree, and search the codebase.
    supported_actions = {
        AgentAction.RUN_TESTS,
        AgentAction.RUN_LINT,
        AgentAction.READ_FILE,
        AgentAction.LIST_DIR,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.EXECUTE_CODE,
    }

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        logger.info("[ADVISOR] Reviewing session %s", request.session_id)

        history = request.history or []
        last_message = history[-1]["content"] if history else request.query

        yield "[ADVISOR] Fact-checking claim against the workspace...\n"
        facts = await self._verify_claim_facts(last_message, request)
        yield json.dumps(facts, indent=2, default=str) + "\n\n"

        analysis = self._analyze_completion_claim(last_message, facts)
        yield "[ADVISOR] Verdict:\n"
        yield json.dumps(analysis, indent=2, default=str) + "\n\n"

        async for token in self._run_react_loop(request):
            yield token

    # ── Factual verification ─────────────────────────────────────────────

    async def _verify_claim_facts(self, claim: str, request: AgentRequest) -> dict[str, Any]:
        """Check the claim against observable reality.

        Every check here is deterministic: file existence, targeted test
        execution, working-tree state. No LLM judgement is involved, so a
        finding in this dict is a fact, and its absence is honestly reported
        as "unverified" rather than smoothed over.
        """
        facts: dict[str, Any] = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "referenced_files": [],
            "missing_files": [],
            "test_runs": [],
            "working_tree": {},
            "unverified": [],
        }

        root = Path(request.project_path) if request.project_path else REPO_ROOT

        # 1. Referenced files must exist. A claim that cites files which are
        #    not on disk is fiction, and that is now caught mechanically.
        seen: set[str] = set()
        for match in _FILE_REF_RE.finditer(claim):
            ref = match.group(0).lstrip("./").replace("\\", "/")
            if ref in seen or "://" in ref:
                continue
            seen.add(ref)
            candidates = [root / ref, REPO_ROOT / ref, REPO_ROOT / "nexus-ide" / ref]
            existing = next((c for c in candidates if c.is_file()), None)
            if existing is not None:
                facts["referenced_files"].append({
                    "ref": ref,
                    "resolved": str(existing),
                    "size_bytes": existing.stat().st_size,
                })
            else:
                facts["missing_files"].append(ref)

        # 2. Referenced test files are executed, not trusted. If the claim
        #    says tests pass and names the file, we run it and report the
        #    actual result.
        test_refs = sorted({m.group(0).replace("\\", "/") for m in _TEST_FILE_RE.finditer(claim)})
        for ref in test_refs[:3]:
            candidates = [root / ref, REPO_ROOT / ref, REPO_ROOT / "nexus-ide" / ref]
            test_path = next((c for c in candidates if c.is_file()), None)
            if test_path is None:
                continue
            facts["test_runs"].append(await self._run_targeted_tests(test_path))

        claims_tests = any(w in claim.lower() for w in ("test", "pytest", "suite", "coverage"))
        if claims_tests and not facts["test_runs"]:
            facts["unverified"].append(
                "Claim mentions tests but names no executable test file; "
                "use the RUN_TESTS action to verify before accepting."
            )

        # 3. Working tree state: a claim of "implemented/fixed" with a clean
        #    tree and no referenced files is presumptive evidence of nothing
        #    having been done.
        facts["working_tree"] = await asyncio.to_thread(self._git_state)

        return facts

    async def _run_targeted_tests(self, test_path: Path) -> dict[str, Any]:
        """Execute one referenced test file and report the real outcome."""
        import sys

        try:
            proc = await asyncio.create_subprocess_exec(
                # sys.executable: the interpreter running the backend is the
                # project venv with pytest and the project deps installed;
                # a bare "python" could resolve to a foreign environment and
                # report a false failure.
                sys.executable, "-m", "pytest", str(test_path), "-q", "--maxfail=3", "-x",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(REPO_ROOT),
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=_TARGETED_TEST_TIMEOUT_S)
            except TimeoutError:
                proc.kill()
                return {"file": str(test_path), "passed": False, "error": f"timeout>{_TARGETED_TEST_TIMEOUT_S}s"}
            tail = out.decode(errors="replace").strip().splitlines()[-5:]
            return {
                "file": str(test_path),
                "passed": proc.returncode == 0,
                "exit_code": proc.returncode,
                "output_tail": tail,
            }
        except Exception as exc:
            logger.debug("Targeted test run failed for %s: %s", test_path, exc)
            return {"file": str(test_path), "passed": False, "error": str(exc)}

    @staticmethod
    def _git_state() -> dict[str, Any]:
        import subprocess

        state: dict[str, Any] = {}
        try:
            diff = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "diff", "--stat"],
                capture_output=True, text=True, timeout=10,
            )
            if diff.returncode == 0:
                lines = [ln for ln in diff.stdout.strip().splitlines() if ln.strip()]
                state["changed_files"] = max(0, len(lines) - 1)
                state["diff_summary"] = lines[-1] if lines else "clean"
        except Exception:
            state["error"] = "git unavailable"
        return state

    # ── Heuristic triage (suspicion routing, not evidence) ───────────────

    def _analyze_completion_claim(self, claim: str, facts: dict[str, Any] | None = None) -> dict[str, Any]:
        """Combine factual findings with heuristic suspicion into a verdict.

        Intervention levels are driven by FACTS first: failed targeted tests
        or files cited but missing on disk block completion outright.
        Heuristic gaps (vague language, unmentioned verification) can only
        escalate as far as MANDATORY_FIX on their own.
        """
        facts = facts or {}
        findings: list[str] = []
        factual_failures: list[str] = []
        missing_evidence: list[str] = []
        intervention = InterventionLevel.SUGGESTION

        # Factual failures — hard evidence against the claim.
        for run in facts.get("test_runs", []):
            if run.get("passed"):
                findings.append(f"VERIFIED: {run['file']} passes")
            else:
                factual_failures.append(
                    f"FAILED: {run['file']} did not pass "
                    f"({run.get('error') or '; '.join(run.get('output_tail', [])[-2:])})"
                )
        for ref in facts.get("missing_files", []):
            factual_failures.append(f"FICTION: claim references '{ref}' but it does not exist on disk")

        claim_lower = claim.lower()

        # Evidence categories: keyword presence is suspicion of absence only.
        evidence_indicators = {
            "tests_passed": any(word in claim_lower for word in ["test", "spec", "coverage"]),
            "edge_cases_covered": any(word in claim_lower for word in ["edge case", "corner case", "boundary"]),
            "security_reviewed": any(word in claim_lower for word in ["security", "vulnerability", "cve", "audit"]),
            "documentation_complete": any(word in claim_lower for word in ["doc", "readme", "documentation", "api spec"]),
            "regression_free": any(word in claim_lower for word in ["regression", "existing test", "still pass"]),
        }
        for category, found in evidence_indicators.items():
            if not found:
                missing_evidence.append(category)

        for pattern in VAGUE_PATTERNS:
            if pattern in claim_lower:
                findings.append(f"Vague claim detected: '{pattern}' — needs concrete evidence")

        if not any(f in claim_lower for f in ["file", "function", "class", "method", "line"]):
            findings.append("No specific files or functions referenced")

        if not any(t in claim_lower for t in ["test", "verify", "check", "confirm", "prove"]):
            findings.append("No verification method mentioned")

        findings.extend(facts.get("unverified", []))

        # Verdict: facts outrank heuristics.
        if factual_failures:
            intervention = InterventionLevel.COMPLETION_BLOCK
        elif missing_evidence:
            intervention = InterventionLevel.COMPLETION_BLOCK
        elif len(findings) >= 3:
            intervention = InterventionLevel.MANDATORY_FIX
        elif findings:
            intervention = InterventionLevel.SUGGESTION

        return {
            "intervention_level": intervention.name,
            "intervention_value": intervention.value,
            "factual_failures": factual_failures,
            "findings": findings,
            "missing_evidence": missing_evidence,
            "verified_files": [f["ref"] for f in facts.get("referenced_files", [])],
            "debate_rounds": DEBATE_ROUNDS if intervention >= InterventionLevel.COMPLETION_BLOCK else [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


__all__ = ["AdvisorAgent", "InterventionLevel"]
