"""Verification and autonomous self-improvement helpers for the orchestrator.

This module is the single source of truth for the Plan → Execute → Verify →
Fix cycle helpers.  ``backend.orchestrator.engine`` delegates to these
functions; do not fork the logic back into the engine.

Design notes (why this file looks the way it does)
--------------------------------------------------
The first implementation had three defects that made the autonomous loop
report ``completed`` without doing real work:

1. **Self-triggering issue detection.**  ``_extract_verification_issues``
   scanned DEBUGGER output for the raw substrings ``"error"``, ``"fix"``,
   ``"missing"``, ``"issue"`` ... but the verification prompt we send
   *literally contains* "Check for: bugs, syntax errors, missing imports,
   logic errors".  Any agent that echoed its instructions matched, so the
   predicate was effectively always true.  Substring matching also fired on
   ``pre-fix``/``suffix`` and on negations such as "no errors found".

2. **Task-name nesting.**  ``Fix: {name}`` wrapped ``Verify: {name}`` wrapped
   ``Fix: {name}`` ... producing the tell-tale
   ``Fix: Verify: Fix: Verify: Execute Objective``.  Names now carry a stable
   ``origin`` and prefixes are stripped before re-wrapping.

3. **Silent exhaustion.**  Running out of fix rounds was indistinguishable
   from passing verification.  ``VerificationOutcome`` makes that explicit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.orchestrator.dependency_graph import TaskNode, TaskPriority
from backend.orchestrator.types import OrchestrationResult


def a2a_message_expired(message: Any, now: datetime | None = None) -> bool:
    """Return whether an A2A message deadline/TTL has elapsed.

    Expiry is a timeout, never a successful verification result.  The helper
    accepts the Pydantic message as well as a plain mapping for transport
    adapters that deserialize A2A envelopes themselves.
    """
    now = now or datetime.now(UTC)
    get = message.get if isinstance(message, dict) else lambda key, default=None: getattr(message, key, default)
    deadline = get("deadline")
    created = get("created_at")
    ttl = get("ttl_seconds")
    if isinstance(deadline, str):
        deadline = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    if isinstance(created, str):
        created = datetime.fromisoformat(created.replace("Z", "+00:00"))
    if isinstance(deadline, datetime):
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        return now >= deadline
    if isinstance(created, datetime) and ttl is not None:
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        return now >= created + timedelta(seconds=max(0, int(ttl)))
    return False


is_a2a_expired = a2a_message_expired
__all__ = [
    "VerificationOutcome",
    "a2a_message_expired",
    "is_a2a_expired",
    "output_is_inconclusive",
    "output_reports_issues",
    "strip_cycle_prefixes",
    "_find_tasks_needing_verification",
    "_create_verification_tasks",
    "_extract_verification_issues",
    "_extract_inconclusive_verifications",
    "_create_fix_tasks",
    "_create_final_review_task",
]


# ---------------------------------------------------------------------------
# Task-name hygiene
# ---------------------------------------------------------------------------

#: Matches any number of leading ``Verify:`` / ``Fix:`` (and PT-BR variants)
#: prefixes so a name can be re-wrapped without nesting.
_CYCLE_PREFIX_RE = re.compile(
    r"^\s*(?:(?:re-?)?(?:verify|verificar|verificação|fix|corrigir|correção)\s*:\s*)+",
    re.IGNORECASE,
)


def strip_cycle_prefixes(name: str) -> str:
    """Return ``name`` without accumulated ``Verify:``/``Fix:`` prefixes.

    >>> strip_cycle_prefixes("Fix: Verify: Fix: Verify: Execute Objective")
    'Execute Objective'
    """
    cleaned = _CYCLE_PREFIX_RE.sub("", name or "").strip()
    return cleaned or (name or "").strip() or "Unknown"


# ---------------------------------------------------------------------------
# Issue detection
# ---------------------------------------------------------------------------

# An explicit machine-readable verdict always wins over heuristics.
_VERDICT_RE = re.compile(
    r"\b(?:verdict|resultado|veredito|status)\s*[:=]\s*"
    r"(?P<verdict>pass(?:ed)?|ok|approved?|aprovado|clean|"
    r"fail(?:ed)?|reject(?:ed)?|reprovado|error)\b",
    re.IGNORECASE,
)
_PASSING_VERDICTS = {"pass", "passed", "ok", "approve", "approved", "aprovado", "clean"}

# Word-boundary matches only. Note the absence of bare "fix"/"missing":
# those appear in our own prompt text and in benign prose far too often to
# be used as standalone evidence. They are still matched as verbs in a
# finding ("must be fixed", "is missing").
_ISSUE_PATTERNS = (
    r"\berrors?\b",
    r"\berros?\b",
    r"\bbugs?\b",
    r"\bexceptions?\b",
    r"\btracebacks?\b",
    r"\bfail(?:s|ed|ure|ures)?\b",
    r"\bfalh(?:a|as|ou)\b",
    r"\bbroken\b",
    r"\bquebrad[oa]s?\b",
    r"\bincorrect(?:ly)?\b",
    r"\bincorret[oa]s?\b",
    r"\bmust be fixed\b",
    r"\bneeds? (?:a )?fix(?:es|ing)?\b",
    r"\bshould be fixed\b",
    r"\bprecisa ser corrigid[oa]\b",
    r"\bis missing\b",
    r"\bare missing\b",
    r"\bmissing (?:import|imports|argument|arguments|dependency|dependencies|"
    r"return|handler|test|tests|module|modules)\b",
    r"\bnot defined\b",
    r"\bundefined\b",
    r"\bproblemas?\b",
    r"\bissues? found\b",
    r"\bfound \d+ (?:issues?|errors?|bugs?|problems?)\b",
    r"\bsyntax error\b",
    r"\bdoes not (?:work|compile|run|pass)\b",
    r"\bnão (?:funciona|compila|passa)\b",
)
_ISSUE_RE = re.compile("|".join(_ISSUE_PATTERNS), re.IGNORECASE)

# Phrases that explicitly assert the *absence* of problems. A sentence
# matching one of these is discarded even if it also matches _ISSUE_RE
# ("no errors found" contains "errors").
_NEGATION_PATTERNS = (
    r"\bno\s+(?:\w+\s+){0,2}?(?:errors?|bugs?|issues?|problems?|failures?)\b",
    r"\bnot?\s+(?:any\s+)?(?:errors?|bugs?|issues?|problems?)\b",
    r"\bnone\s+(?:were\s+)?found\b",
    r"\bwithout\s+(?:any\s+)?(?:errors?|issues?|problems?)\b",
    r"\bzero\s+(?:errors?|issues?|bugs?|problems?)\b",
    r"\bnenhum[ao]?s?\s+(?:\w+\s+){0,2}?(?:erros?|bugs?|problemas?|falhas?)\b",
    r"\bsem\s+(?:\w+\s+){0,2}?(?:erros?|problemas?|falhas?|bugs?)\b",
    r"\ball\s+tests?\s+pass(?:ed)?\b",
    r"\btodos\s+os\s+testes\s+pass(?:am|aram)\b",
    r"\blooks?\s+(?:good|fine|correct)\b",
    r"\bno\s+changes?\s+(?:are\s+)?(?:needed|required)\b",
    r"\bfree\s+of\s+(?:errors?|bugs?|issues?)\b",
)
_NEGATION_RE = re.compile("|".join(_NEGATION_PATTERNS), re.IGNORECASE)

# Boilerplate we inject into the verification prompt. If the agent parrots
# it back, it must not count as a finding.
_ECHOED_PROMPT_PATTERNS = (
    r"check for\s*:\s*bugs.*?edge cases\.?",
    r"verify the output of task\s*'.*?'\.?",
    r"run any tests if available\.?",
    r"original output\s*:",
    r"fix the issues found during verification of\s*'.*?'\.?",
    r"debugger findings\s*:",
    r"apply all necessary fixes and ensure the code works correctly\.?",
)
_ECHOED_PROMPT_RE = re.compile("|".join(_ECHOED_PROMPT_PATTERNS), re.IGNORECASE | re.DOTALL)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;\n])\s+")

# Failures of *our own* infrastructure — an approval gate, a rate limit, a
# dropped connection, a tool-call the parser refused. None of these is a defect
# in the code under verification, and treating them as findings is what
# produced the ``Fix: Verify: Fix: Verify: Execute Objective`` cascade:
#
#   08:19:06  [DEBUGGER] Tool error | tool=run_shell | error=Autonomous
#             execution stopped before 'run_shell': this operation requires an
#             explicit human approval ...
#   08:19:33  Autonomous: 1 issues found, creating fix tasks (round 1)
#
# The DEBUGGER never inspected anything; it reported that it had been blocked,
# and the orchestrator spawned a CODER "fix" for a permission prompt. Every
# subsequent round repeated the pattern with a longer name.
_INFRA_FAILURE_PATTERNS = (
    r"requires an explicit human approval",
    r"autonomous execution stopped before",
    r"\bautonomous_blocked\b",
    r"operation cancelled or confirmation expired",
    r"\brate.?limit(?:ed|s|ing)?\b",
    r"\b429\b",
    r"\b50[0234]\b",
    r"network connection lost",
    r"provider[_ ]unavailable",
    r"failed to parse tool_call",
    r"rejected unknown tool name",
    r"llm stream failed",
    r"context overflow",
    r"model .* (?:failed|unavailable) for agent",
    r"consultation with \w+ timed out",
    r"no tool calls detected",
    r"ollama (?:embed )?(?:is )?unavailable",
)
_INFRA_FAILURE_RE = re.compile("|".join(_INFRA_FAILURE_PATTERNS), re.IGNORECASE)

_OPENROUTER_FREE_TIER_DAILY_LIMIT_RE = re.compile(
    r"free-models-per-day-high-balance|free[_ ]tier.*daily|daily.*limit.*free",
    re.IGNORECASE,
)


def _denoise(output: str, task_name: str = "") -> str:
    """Remove echoed instructions and the task's own name from ``output``.

    Without this, a DEBUGGER task literally named ``Fix: Verify: ...`` makes
    every downstream scan match on the name alone.
    """
    text = output or ""
    text = _ECHOED_PROMPT_RE.sub(" ", text)
    if task_name:
        text = text.replace(task_name, " ")
        stripped = strip_cycle_prefixes(task_name)
        if stripped and stripped != task_name:
            text = text.replace(stripped, " ")
    return text


def _has_unnegated_issue(text: str) -> bool:
    """True when at least one sentence reports a problem and is not negated."""
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        chunk = sentence.strip()
        if not chunk:
            continue
        if _NEGATION_RE.search(chunk):
            continue
        if _ISSUE_RE.search(chunk):
            return True
    return False


def _strip_infra_failures(text: str) -> str:
    """Drop sentences that describe our own plumbing failing.

    Kept separate from :func:`_denoise` because the two answer different
    questions: ``_denoise`` removes text the agent echoed back, this removes
    text that is genuinely about the run rather than about the code.
    """
    kept = [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split(text)
        if sentence.strip() and not _INFRA_FAILURE_RE.search(sentence)
    ]
    return " ".join(kept)


def output_is_inconclusive(output: str, task_name: str = "") -> bool:
    """True when verification could not actually be performed.

    A blocked tool, a 429 or a dropped stream means the verifier learned
    nothing. That is neither a pass nor a finding — and it must not be
    laundered into either. Callers should surface it as "not verified" so a
    human sees that the check never ran.
    """
    if not output or not output.strip():
        return False
    cleaned = _denoise(output, task_name)
    if not _INFRA_FAILURE_RE.search(cleaned):
        return False
    # Infrastructure noise only counts as inconclusive when nothing else in the
    # output stands on its own: an agent that hit one 429, retried and then
    # reported a real defect has still verified something.
    remainder = _strip_infra_failures(cleaned).strip()
    if _VERDICT_RE.search(remainder):
        return False
    if _OPENROUTER_FREE_TIER_DAILY_LIMIT_RE.search(cleaned):
        return True
    return not _has_unnegated_issue(remainder)


def output_reports_issues(output: str, task_name: str = "") -> bool:
    """Decide whether a DEBUGGER verification output reports real issues.

    Precedence: infrastructure failure → explicit ``VERDICT:`` marker →
    negation-aware keyword scan. An empty or whitespace-only output is *not*
    treated as a finding; an agent that produced nothing has not found
    anything.

    Sentences describing our own plumbing failing are removed before the scan.
    Without that, "Autonomous execution stopped before 'run_shell'" matched
    ``\\bfail...\\b``-style patterns and spawned a fix task for a permission
    prompt — see :data:`_INFRA_FAILURE_PATTERNS`.
    """
    if not output or not output.strip():
        return False

    cleaned = _denoise(output, task_name)

    verdict_match = _VERDICT_RE.search(cleaned)
    if verdict_match:
        verdict = verdict_match.group("verdict").lower()
        return verdict not in _PASSING_VERDICTS

    return _has_unnegated_issue(_strip_infra_failures(cleaned))


# ---------------------------------------------------------------------------
# Cycle outcome
# ---------------------------------------------------------------------------


@dataclass
class VerificationOutcome:
    """Explicit result of the verify/fix loop.

    ``resolved`` distinguishes "verification passed" from "we ran out of
    rounds", which the previous implementation conflated into success.
    """

    resolved: bool = False
    rounds_run: int = 0
    max_rounds: int = 0
    outstanding_issues: list[dict[str, Any]] = field(default_factory=list)
    #: Verifications whose own tooling failed (approval gate, 429, dead
    #: stream). Recorded so the summary can say "not checked" instead of
    #: silently implying "checked and clean".
    inconclusive_verifications: list[dict[str, Any]] = field(default_factory=list)

    @property
    def exhausted(self) -> bool:
        return not self.resolved and self.rounds_run >= self.max_rounds > 0

    def summary(self) -> str:
        if self.inconclusive_verifications and not self.outstanding_issues:
            names = ", ".join(
                strip_cycle_prefixes(str(i.get("origin") or i.get("name", "?")))
                for i in self.inconclusive_verifications[:5]
            )
            return (
                f"Verification could NOT be performed for {len(self.inconclusive_verifications)} "
                f"task(s) — the tooling failed, the code was never inspected: {names or 'n/a'}. "
                "This is not a pass."
            )
        if self.resolved:
            return f"Verification passed after {self.rounds_run} round(s)."
        if self.exhausted:
            names = ", ".join(
                strip_cycle_prefixes(str(i.get("name", "?"))) for i in self.outstanding_issues[:5]
            )
            return (
                f"Verification exhausted {self.rounds_run}/{self.max_rounds} round(s) "
                f"with {len(self.outstanding_issues)} unresolved issue(s): {names or 'n/a'}"
            )
        return "Verification did not run."


# ---------------------------------------------------------------------------
# Task factories
# ---------------------------------------------------------------------------


def _find_tasks_needing_verification(result: OrchestrationResult) -> list[dict]:
    """Find completed CODER tasks that should be verified by DEBUGGER."""
    tasks_needing_verify: list[dict] = []
    for task_id, artifact in result.task_results.items():
        if not isinstance(artifact, dict):
            continue
        agent = artifact.get("agent", "")
        status = artifact.get("status", "")
        if agent != "CODER" or status != "completed":
            continue
        raw_name = artifact.get("name", "Unknown")
        tasks_needing_verify.append(
            {
                "task_id": task_id,
                # ``name`` is the display name; ``origin`` is the stable,
                # prefix-free identity used when wrapping the task.
                "name": raw_name,
                "origin": artifact.get("origin") or strip_cycle_prefixes(raw_name),
                "output": artifact.get("output", ""),
            }
        )
    return tasks_needing_verify


def _create_verification_tasks(
    tasks_to_verify: list[dict[str, Any]],
    result: OrchestrationResult,
    session_id: str,
) -> list[TaskNode]:
    """Create DEBUGGER verification tasks for completed CODER work."""
    verify_steps: list[TaskNode] = []
    for task_info in tasks_to_verify:
        origin = task_info.get("origin") or strip_cycle_prefixes(str(task_info.get("name", "")))
        verify_task = TaskNode(


            name=f"Verify: {origin}",
            description=(
                f"Verify the output of task '{origin}'. "
                f"Check for: bugs, syntax errors, missing imports, "
                f"logic errors, edge cases. "
                f"Run any tests if available.\n\n"
                f"Answer with a final line in exactly this format:\n"
                f"VERDICT: PASS   (if no problems were found)\n"
                f"VERDICT: FAIL   (if problems were found, then list them)\n\n"
                f"Original output:\n{str(task_info.get('output', ''))[:1000]}"
            ),
            agent="DEBUGGER",
            priority=TaskPriority.HIGH,
            context=str(task_info.get("output", ""))[:2000],
        )
        verify_task.input_data["origin"] = origin
        verify_steps.append(verify_task)
    return verify_steps


def _failed_verification_evidence(artifact: dict[str, Any]) -> str | None:
    """Return a concrete execution failure from typed verification evidence."""
    raw = artifact.get("evidence")
    evidence_items = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    for evidence in evidence_items:
        if not isinstance(evidence, dict):
            continue
        if evidence.get("timed_out"):
            return "verification command timed out"
        exit_code = evidence.get("exit_code")
        if exit_code not in (None, 0):
            return f"verification command exited with code {exit_code}"
        if evidence.get("ok") is False or evidence.get("verified") is False:
            return "verification command did not produce passing evidence"
    return None
def _extract_verification_issues(verify_result: OrchestrationResult) -> list[dict]:
    """Extract genuine issues reported by DEBUGGER verification tasks."""
    issues: list[dict] = []
    for task_id, artifact in verify_result.task_results.items():
        if not isinstance(artifact, dict):
            continue
        if artifact.get("agent", "") != "DEBUGGER":
            continue
        name = str(artifact.get("name", "Unknown verification"))
        output = str(artifact.get("output", ""))
        evidence_error = _failed_verification_evidence(artifact)
        # A failed/timeout tool proves that verification could not run; it is
        # not, by itself, evidence that the project contains a defect. Only an
        # explicit verifier finding enters the fix loop.
        if not output_reports_issues(output, name):
            continue
        issues.append(
            {
                "task_id": task_id,
                "name": name,
                "origin": artifact.get("origin") or strip_cycle_prefixes(name),
                "output": output,
                "agent": "DEBUGGER",
                "evidence_error": evidence_error,
            }
        )
    return issues


def _extract_inconclusive_verifications(verify_result: OrchestrationResult) -> list[dict]:
    """Return verifications that could not run — blocked tools, 429s, dead streams.

    These are deliberately *not* returned by
    :func:`_extract_verification_issues`: spawning a CODER "fix" for a
    permission prompt is what produced the nested-name cascade. They are still
    worth surfacing, because "we could not check" is a materially different
    report from "we checked and it was fine".
    """
    inconclusive: list[dict] = []
    for task_id, artifact in verify_result.task_results.items():
        if not isinstance(artifact, dict):
            continue
        if artifact.get("agent", "") != "DEBUGGER":
            continue
        name = str(artifact.get("name", "Unknown verification"))
        output = str(artifact.get("output", ""))
        evidence_error = _failed_verification_evidence(artifact)
        expired = bool(artifact.get("a2a_expired"))
        if artifact.get("a2a_message"):
            expired = expired or a2a_message_expired(artifact["a2a_message"])
        has_code_finding = output_reports_issues(output, name)
        if has_code_finding:
            continue
        if not evidence_error and not expired and not output_is_inconclusive(output, name):
            continue
        inconclusive.append(
            {
                "task_id": task_id,
                "name": name,
                "origin": artifact.get("origin") or strip_cycle_prefixes(name),
                "output": output,
                "reason": (
                    "A2A response expired before verification"
                    if expired
                    else evidence_error
                    or "verification tooling failed; the code was never inspected"
                ),
            }
        )
    return inconclusive


def _create_fix_tasks(
    issues: list[dict[str, Any]],
    verify_tasks: list[TaskNode],
    session_id: str,
) -> list[TaskNode]:
    """Create CODER fix tasks based on DEBUGGER findings."""
    fix_steps: list[TaskNode] = []
    for issue in issues:
        origin = issue.get("origin") or strip_cycle_prefixes(str(issue.get("name", "")))
        fix_task = TaskNode(
            name=f"Fix: {origin}",
            description=(
                f"Fix the issues found during verification of '{origin}'. "
                f"DEBUGGER findings:\n{str(issue.get('output', ''))[:2000]}\n\n"
                f"Apply all necessary fixes and ensure the code works correctly."
            ),
            agent="CODER",
            priority=TaskPriority.HIGH,
            context=str(issue.get("output", ""))[:2000],
        )
        fix_task.input_data["origin"] = origin
        fix_steps.append(fix_task)
    return fix_steps


def _create_final_review_task(
    objective: str,
    result: OrchestrationResult,
    session_id: str,
) -> TaskNode:
    """Create a final ANALYZER review task."""
    completed_summary = "\n".join(
        f"- {strip_cycle_prefixes(str(a.get('name', 'Unknown')))}: {a.get('status', '?')}"
        for a in result.task_results.values()
        if isinstance(a, dict)
    )
    return TaskNode(
        name="Final Quality Review",
        description=(
            f"Perform a comprehensive quality review of all work done for: {objective}\n\n"
            f"Completed tasks:\n{completed_summary}\n\n"
            f"Check for: consistency, completeness, code quality, "
            f"security issues, performance problems, missing documentation."
        ),
        agent="ANALYZER",
        priority=TaskPriority.MEDIUM,
    )
