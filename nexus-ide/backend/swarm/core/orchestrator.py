"""SWARM Orchestrator — the central executor.

Connects the Coordinator, agents, message bus, memory layers, RAG retriever,
quality gate, and safe workflow into a single runnable pipeline.

Key responsibilities
--------------------
- Validate the run (mode, agents, objective)
- Detect / confirm the operational mode
- Build evidence via RAG (when enabled by the mode)
- Run external research (when enabled by the mode)
- Spawn agent tasks per the mode's strategy
- Aggregate agent results
- Run the Reviewer on any Proposal
- Compute and store QualityScores
- Return a :class:`SwarmResult`
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from backend.swarm.communication.message_bus import MessageBus
from backend.swarm.core.agents import AGENT_BINDINGS, get_definition
from backend.swarm.core.coordinator import Coordinator
from backend.swarm.core.types import (
    AgentMessage,
    AgentRole,
    Decision,
    MessageType,
    OperationalMode,
    Proposal,
    QualityScores,
    ReviewReport,
    SwarmResult,
    SwarmStrategy,
    WorkflowState,
)
from backend.swarm.memory.memory_layers import MemoryStore
from backend.swarm.modes.mode_registry import get_mode
from backend.swarm.quality.quality_gate import (
    gate_failure_reason,
    merge_scores,
    passes_gate,
    score_proposal,
)
from backend.swarm.rag.retriever import (
    RetrievalHit,
    SwarmRetriever,
)
from backend.swarm.research.researcher import ResearcherAgent
from backend.swarm.review.reviewer import ReviewerAgent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class SwarmRunRequest:
    """Input to :meth:`SwarmOrchestrator.run`."""

    objective: str
    session_id: str = "default"
    mode: OperationalMode | None = None
    strategy: SwarmStrategy | None = None
    agents: list[AgentRole] | None = None
    project_path: str = ""
    auto_approve: bool = False
    autonomous: bool = True
    max_iterations: int = 1000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _RunContext:
    """Per-run collaboration substrate.

    Each ``run()`` gets its own bus, coordinator, researcher and reviewer so
    two concurrent runs cannot clear each other's history or share the
    anti-loop counters. It is published through a :class:`~contextvars.ContextVar`
    so the existing ``self.message_bus`` / ``self.coordinator`` call sites keep
    working unchanged.
    """

    message_bus: MessageBus
    coordinator: Coordinator
    researcher: ResearcherAgent
    reviewer: ReviewerAgent


_current_run: contextvars.ContextVar[_RunContext | None] = contextvars.ContextVar(
    "swarm_run_context", default=None
)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class SwarmOrchestrator:
    """Top-level SWARM orchestrator.

    Constructed once per process. ``run()`` may be called concurrently from
    different sessions: each run allocates its own :class:`_RunContext`, while
    the memory store and RAG retriever stay shared (they are additive and
    run-tagged).
    """

    def __init__(
        self,
        llm_client: Any = None,
        registry: dict[str, Any] | None = None,
        event_bus: Any = None,
        message_bus: MessageBus | None = None,
        memory: MemoryStore | None = None,
        retriever: SwarmRetriever | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.registry = registry or {}
        self.events = event_bus  # legacy NEXUS EventBus (for SSE / dashboard)
        self.memory = memory or MemoryStore()
        self.retriever = retriever or SwarmRetriever()
        # Fallback substrate used outside of a run (and by callers that
        # injected their own bus).
        self._default_ctx = _RunContext(
            message_bus=message_bus or MessageBus(),
            coordinator=Coordinator(message_bus),
            researcher=ResearcherAgent(message_bus),
            reviewer=ReviewerAgent(message_bus),
        )
        if message_bus is None:
            bus = self._default_ctx.message_bus
            self._default_ctx.coordinator = Coordinator(bus)
            self._default_ctx.researcher = ResearcherAgent(bus)
            self._default_ctx.reviewer = ReviewerAgent(bus)

    # -- per-run substrate ------------------------------------------------

    @property
    def _ctx(self) -> _RunContext:
        return _current_run.get() or self._default_ctx

    @property
    def message_bus(self) -> MessageBus:
        return self._ctx.message_bus

    @property
    def coordinator(self) -> Coordinator:
        return self._ctx.coordinator

    @property
    def researcher(self) -> ResearcherAgent:
        return self._ctx.researcher

    @property
    def reviewer(self) -> ReviewerAgent:
        return self._ctx.reviewer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, req: SwarmRunRequest) -> SwarmResult:
        """Run a full SWARM cycle for ``req`` and return the result."""
        run_id = uuid.uuid4().hex[:12]
        started = time.time()
        result = SwarmResult(
            run_id=run_id,
            mode=req.mode or OperationalMode.INVESTIGATION,
            strategy=req.strategy or SwarmStrategy.ADAPTIVE,
            objective=req.objective,
        )
        bus = MessageBus()
        token = _current_run.set(
            _RunContext(
                message_bus=bus,
                coordinator=Coordinator(bus),
                researcher=ResearcherAgent(bus),
                reviewer=ReviewerAgent(bus),
            )
        )
        try:
            return await self._run_inner(req, result, run_id, started)
        finally:
            _current_run.reset(token)

    async def _run_inner(
        self,
        req: SwarmRunRequest,
        result: SwarmResult,
        run_id: str,
        started: float,
    ) -> SwarmResult:
        """Body of :meth:`run`, executed inside an active :class:`_RunContext`."""
        try:
            # 1. Coordinator decides mode + strategy
            decision = self.coordinator.decide(req.objective, explicit_mode=req.mode)
            result.mode = decision.mode
            result.strategy = req.strategy or decision.strategy
            spec = get_mode(result.mode)
            # Report the team that will actually run, not the mode default —
            # otherwise an explicit ``agents`` selection never showed up in
            # the result and the UI displayed the wrong roster.
            result.agents_involved = [
                a.value for a in self._resolve_agents(spec.agents, req.agents)
            ]
            await self._publish_status(
                f"🧭 Coordinator chose mode={result.mode.value} strategy={result.strategy.value} "
                f"(confidence={decision.confidence:.2f})",
                {"stage": "decide", "decision": decision.rationale},
            )
            self.memory.add(
                "short_term",
                f"Run {run_id} mode={result.mode.value} objective={req.objective[:200]}",
                tags=[result.mode.value, "decision"],
                importance=0.7,
                run_id=run_id,
                session_id=req.session_id,
                project_id=req.project_path,
            )

            # 2. Pull RAG evidence (if the mode needs it)
            evidence: list[RetrievalHit] = []
            if spec.uses_rag and self.retriever.stats()["chunks"] > 0:
                evidence = self.retriever.retrieve(
                    req.objective,
                    top_k=6,
                    project_path=req.project_path or None,
                )
                result.evidence_used = [h.to_dict() for h in evidence]
                await self._publish_status(
                    f"📚 RAG retrieved {len(evidence)} evidence chunks",
                    {"stage": "rag", "count": len(evidence)},
                )

            # 3. External research (if the mode needs it)
            research_payload: dict[str, Any] = {}
            if spec.uses_research:
                try:
                    report = await self.researcher.research(req.objective)
                    research_payload = report.to_dict()
                    result.research_used = [report.to_dict()]
                    await self._publish_status(
                        f"🌐 Research gathered {len(report.findings)} sources "
                        f"(confidence={report.confidence:.2f})",
                        {"stage": "research"},
                    )
                except Exception as exc:
                    await self._publish_status(
                        f"⚠️ Research failed: {exc}", {"stage": "research", "error": str(exc)}
                    )

            # 4. Run the per-mode pipeline
            plan_text, proposals, decisions, reviews = await self._run_pipeline(
                req=req, spec=spec, evidence=evidence, research=research_payload
            )
            result.proposals = proposals
            result.decisions = decisions
            result.reviews = reviews
            result.messages = self.message_bus.all_history()
            result.final_answer = plan_text

            # 5. Compute final quality scores
            if reviews:
                result.scores = merge_scores(*(r.scores for r in reviews))
            elif proposals:
                result.scores = merge_scores(*(score_proposal(p) for p in proposals))
            else:
                result.scores = QualityScores(quality=0.5, confidence=0.5, risk=0.3, complexity=0.3)

            # 6. Decide final workflow state
            if not proposals:
                result.state = WorkflowState.COMPLETED
            elif any(r.passed for r in reviews) and passes_gate(result.scores):
                result.state = (
                    WorkflowState.APPROVED if req.auto_approve else WorkflowState.VALIDATED
                )
            else:
                result.state = WorkflowState.FAILED

            # 7. Persist into long-term memory (best-effort)
            self._store_long_term(result, req)

            result.duration_ms = int((time.time() - started) * 1000)
            result.finished_at = time.time()
            await self._publish_status(
                f"✅ Swarm run complete | state={result.state.value} | "
                f"scores={result.scores.to_dict()}",
                {"stage": "done", "scores": result.scores.to_dict()},
            )
            return result
        except Exception as exc:
            logger.exception("Swarm run failed")
            result.error = str(exc)
            result.state = WorkflowState.FAILED
            result.duration_ms = int((time.time() - started) * 1000)
            result.finished_at = time.time()
            return result

    async def run_blocking(self, req: SwarmRunRequest) -> SwarmResult:
        """Run synchronously (caller does not await)."""
        return await self.run(req)

    # ------------------------------------------------------------------
    # Pipelines
    # ------------------------------------------------------------------

    async def _run_pipeline(
        self,
        req: SwarmRunRequest,
        spec: Any,
        evidence: list[RetrievalHit],
        research: dict[str, Any],
    ) -> tuple[str, list[Proposal], list[Decision], list[ReviewReport]]:
        """Dispatch agents per the mode + strategy and return the plan text."""
        # Map SWARM roles to NEXUS agents actually present in the registry
        selected_agents = self._resolve_agents(spec.agents, req.agents)

        # Collect evidence context
        evidence_blob = self._format_evidence(evidence)
        research_blob = self._format_research(research)

        # Specialised pipelines per strategy
        if spec.mode == OperationalMode.PLANNING:
            return await self._pipeline_planning(req, selected_agents, evidence_blob, research_blob)
        if spec.mode == OperationalMode.IMPLEMENTATION:
            return await self._pipeline_implementation(
                req, selected_agents, evidence_blob, research_blob
            )
        if spec.mode == OperationalMode.BUGFIX:
            return await self._pipeline_bugfix(req, selected_agents, evidence_blob, research_blob)
        if spec.mode == OperationalMode.REVIEW:
            return await self._pipeline_review(req, selected_agents, evidence_blob, research_blob)
        if spec.mode == OperationalMode.RESEARCH:
            return await self._pipeline_research(req, selected_agents, evidence_blob, research_blob)
        # Architecture / Investigation / default → investigation
        return await self._pipeline_investigation(
            req, selected_agents, evidence_blob, research_blob
        )

    # ---- Per-mode pipelines -------------------------------------------

    async def _pipeline_investigation(
        self,
        req: SwarmRunRequest,
        agents: list[AgentRole],
        evidence: str,
        research: str,
    ) -> tuple[str, list[Proposal], list[Decision], list[ReviewReport]]:
        await self._publish_status(
            "🔍 Running INVESTIGATION pipeline", {"pipeline": "investigation"}
        )
        prompt = self._build_investigation_prompt(req, evidence, research)
        decision = self._make_decision(
            AgentRole.COORDINATOR,
            title="Investigation report",
            rationale="Coordinator triggered investigation of the requested area.",
        )
        outputs = await self._gather_agent_outputs(
            agents, prompt, req, exclude={AgentRole.COORDINATOR}
        )
        body = self._join_outputs(outputs, header="Investigation report")
        return body, [], [decision], []

    async def _pipeline_planning(
        self,
        req: SwarmRunRequest,
        agents: list[AgentRole],
        evidence: str,
        research: str,
    ) -> tuple[str, list[Proposal], list[Decision], list[ReviewReport]]:
        await self._publish_status("🗺️ Running PLANNING pipeline", {"pipeline": "planning"})
        prompt = self._build_planning_prompt(req, evidence, research)
        outputs = await self._gather_agent_outputs(
            agents, prompt, req, exclude={AgentRole.COORDINATOR}
        )
        body = self._join_outputs(outputs, header="Execution plan")
        decision = self._make_decision(
            AgentRole.ARCHITECT,
            title="Execution plan",
            rationale="Architect produced a structured plan.",
        )
        return body, [], [decision], []

    async def _pipeline_review(
        self,
        req: SwarmRunRequest,
        agents: list[AgentRole],
        evidence: str,
        research: str,
    ) -> tuple[str, list[Proposal], list[Decision], list[ReviewReport]]:
        await self._publish_status("🧪 Running REVIEW pipeline", {"pipeline": "review"})
        # Build a synthetic proposal from the objective so the reviewer has
        # something concrete to score.
        proposal = Proposal(
            title=req.objective[:120],
            description=req.objective,
            rationale="Review pipeline: scoring the user's text against the 8 review axes.",
            files_to_change=[],
        )
        review = self.reviewer.review_proposal(proposal)
        body = (
            f"# Review\n\n{review.summary}\n\n"
            f"**Scores:** {review.scores.to_dict()}\n"
            f"**Verdict:** {'PASS' if review.passed else 'FAIL'}"
        )
        if not review.passed:
            body += f"\n\n**Reason:** {gate_failure_reason(review.scores)}"
        return body, [proposal], [], [review]

    async def _pipeline_research(
        self,
        req: SwarmRunRequest,
        agents: list[AgentRole],
        evidence: str,
        research: str,
    ) -> tuple[str, list[Proposal], list[Decision], list[ReviewReport]]:
        await self._publish_status("🌐 Running RESEARCH pipeline", {"pipeline": "research"})
        if not research:
            report = await self.researcher.research(req.objective)
            research = report.to_dict()
        body = (
            "# External research\n\n"
            f"**Query:** {req.objective}\n\n"
            f"**Summary:**\n{research.get('summary', '')}\n\n"
            f"**Confidence:** {research.get('confidence', 0):.2f}\n"
        )
        decision = self._make_decision(
            AgentRole.RESEARCHER,
            title="Research briefing",
            rationale="Researcher agent gathered external sources.",
        )
        return body, [], [decision], []

    async def _pipeline_bugfix(
        self,
        req: SwarmRunRequest,
        agents: list[AgentRole],
        evidence: str,
        research: str,
    ) -> tuple[str, list[Proposal], list[Decision], list[ReviewReport]]:
        await self._publish_status("🛠 Running BUGFIX pipeline", {"pipeline": "bugfix"})
        prompt = self._build_implementation_prompt(req, evidence, research, label="bugfix")
        # Investigator + Implementer + Reviewer
        outputs = await self._gather_agent_outputs(
            [AgentRole.INVESTIGATOR, AgentRole.IMPLEMENTER], prompt, req
        )
        body = self._join_outputs(outputs, header="Bugfix investigation & plan")
        proposal = self._make_proposal_from_outputs(req, outputs, prefix="Fix:")
        review = self.reviewer.review_proposal(proposal)
        decision = self._make_decision(
            AgentRole.IMPLEMENTER,
            title="Bugfix proposal",
            rationale="Implementer proposed a minimal patch.",
        )
        return body, [proposal], [decision], [review]

    async def _pipeline_implementation(
        self,
        req: SwarmRunRequest,
        agents: list[AgentRole],
        evidence: str,
        research: str,
    ) -> tuple[str, list[Proposal], list[Decision], list[ReviewReport]]:
        await self._publish_status(
            "🏗 Running IMPLEMENTATION pipeline", {"pipeline": "implementation"}
        )
        prompt = self._build_implementation_prompt(req, evidence, research, label="implementation")
        outputs = await self._gather_agent_outputs(
            [AgentRole.ARCHITECT, AgentRole.IMPLEMENTER], prompt, req
        )
        body = self._join_outputs(outputs, header="Implementation plan")
        proposal = self._make_proposal_from_outputs(req, outputs, prefix="Implement:")
        review = self.reviewer.review_proposal(proposal)
        decision = self._make_decision(
            AgentRole.ARCHITECT,
            title="Implementation plan",
            rationale="Architect + Implementer produced a code-change plan.",
        )
        return body, [proposal], [decision], [review]

    # ------------------------------------------------------------------
    # Agent execution
    # ------------------------------------------------------------------

    def _resolve_agents(
        self,
        spec_agents: list[AgentRole],
        requested: list[AgentRole] | None,
    ) -> list[AgentRole]:
        """Pick the roles to run, preferring the caller's explicit selection.

        Falls back to the mode's default team when the request is empty or
        filters down to nothing — previously an all-unknown selection produced
        an empty list and the run silently returned no output at all.
        """
        if requested:
            picked = [a for a in requested if a in AGENT_BINDINGS]
            # De-duplicate while preserving order.
            seen: set[AgentRole] = set()
            picked = [a for a in picked if not (a in seen or seen.add(a))]
            if picked:
                return picked
            logger.warning(
                "Requested agents %s resolved to nothing — falling back to the "
                "mode default team %s",
                [getattr(a, "value", a) for a in requested],
                [a.value for a in spec_agents],
            )
        return list(spec_agents)

    async def _gather_agent_outputs(
        self,
        roles: list[AgentRole],
        prompt: str,
        req: SwarmRunRequest,
        exclude: set[AgentRole] | None = None,
    ) -> dict[AgentRole, str]:
        """Run the agents (concurrently when possible) and collect outputs."""
        results: dict[AgentRole, str] = {}
        coros: list[tuple[AgentRole, Any]] = []
        exclude = exclude or set()

        for role in roles:
            if role in exclude:
                continue
            nexus_agent_name = AGENT_BINDINGS.get(role)
            if not nexus_agent_name:
                continue
            agent = self.registry.get(nexus_agent_name) if self.registry else None
            if agent is None:
                results[role] = f"_(agent {nexus_agent_name} not available)_"
                # Anti-loop accounting so missing agents don't count as silent
                await self._record_message(
                    sender=role.value,
                    recipient=AgentRole.COORDINATOR.value,
                    content=results[role],
                    type=MessageType.ERROR,
                )
                continue
            coros.append((role, self._run_nexus_agent(agent, prompt, req)))

        if not coros:
            return results

        # Concurrent execution
        outputs = await asyncio.gather(*(c for _, c in coros), return_exceptions=True)
        for (role, _), out in zip(coros, outputs, strict=True):
            if isinstance(out, Exception):
                results[role] = f"_(error: {out})_"
                await self._record_message(
                    sender=role.value,
                    recipient=AgentRole.COORDINATOR.value,
                    content=results[role],
                    type=MessageType.ERROR,
                )
            else:
                results[role] = out
        return results

    async def _run_nexus_agent(self, agent: Any, prompt: str, req: SwarmRunRequest) -> str:
        """Stream tokens from a NEXUS agent and return the concatenated text."""
        from backend.agents.base import AgentRequest

        agent_req = AgentRequest(
            session_id=f"{req.session_id}:swarm:{uuid.uuid4().hex[:6]}",
            query=prompt,
            client=self.llm_client,
            project_path=req.project_path or ".",
            max_iterations=req.max_iterations,
            enable_thinking=False,
            autonomous=req.autonomous,
        )
        parts: list[str] = []
        try:
            async for token in agent.run(agent_req):
                parts.append(token)
        except Exception as exc:
            logger.debug("agent %s raised: %s", getattr(agent, "name", "?"), exc)
            return f"_(agent error: {exc})_"
        return "".join(parts).strip() or "_(no output)_"

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    def _build_investigation_prompt(
        self, req: SwarmRunRequest, evidence: str, research: str
    ) -> str:
        return (
            f"# SWARM — Investigation\n\n"
            f"**Objective:** {req.objective}\n\n"
            f"{self._ctx_block(evidence, research)}\n\n"
            "Read the evidence carefully and produce a cited investigation report:\n"
            "- List the relevant files (with line ranges) you read.\n"
            "- Summarise the current behaviour.\n"
            "- Surface constraints, conventions, and integration points.\n"
            "- Do not propose code changes here — just facts."
        )

    def _build_planning_prompt(self, req: SwarmRunRequest, evidence: str, research: str) -> str:
        return (
            f"# SWARM — Planning\n\n"
            f"**Objective:** {req.objective}\n\n"
            f"{self._ctx_block(evidence, research)}\n\n"
            "Produce a structured execution plan:\n"
            "1. **Steps** — numbered, each with an agent (ARCHITECT, CODER, REVIEWER, …).\n"
            "2. **Dependencies** — which steps depend on which.\n"
            "3. **Deliverables** — concrete output per step.\n"
            "4. **Risks** — what could go wrong.\n"
            "Do not write code."
        )

    def _build_implementation_prompt(
        self, req: SwarmRunRequest, evidence: str, research: str, label: str
    ) -> str:
        return (
            f"# SWARM — Implementation ({label})\n\n"
            f"**Objective:** {req.objective}\n\n"
            f"{self._ctx_block(evidence, research)}\n\n"
            "Produce an implementation plan that another engineer could execute:\n"
            "- List the **files to change** with the rationale per file.\n"
            "- Cite evidence (file path + line range) and the architectural decisions that justify the change.\n"
            "- Provide before/after sketches for the key edits.\n"
            "- Flag any risk, security concern, or test gap.\n"
            "You do NOT have permission to write files. Just emit the plan."
        )

    @staticmethod
    def _ctx_block(evidence: str, research: str) -> str:
        parts: list[str] = []
        if evidence:
            parts.append("## RAG Evidence\n" + evidence)
        if research:
            parts.append("## External Research\n" + research)
        return "\n\n".join(parts) if parts else ""

    @staticmethod
    def _format_evidence(hits: list[RetrievalHit]) -> str:
        if not hits:
            return ""
        out = []
        for h in hits:
            snippet = h.text.replace("\n", " ")[:300]
            out.append(
                f"- `{h.source_path}:{h.start_line}-{h.end_line}` (score={h.score:.2f}) — {snippet}"
            )
        return "\n".join(out)

    @staticmethod
    def _format_research(research: dict[str, Any] | str) -> str:
        if not research:
            return ""
        if isinstance(research, str):
            return research
        return research.get("summary", "") or json.dumps(research, indent=2)[:2000]

    @staticmethod
    def _join_outputs(outputs: dict[AgentRole, str], header: str) -> str:
        if not outputs:
            return f"# {header}\n\n_(no agents returned output)_"
        lines: list[str] = [f"# {header}", ""]
        for role, text in outputs.items():
            label = get_definition(role).label
            lines.append(f"## {label}")
            lines.append("")
            lines.append(text or "_(empty)_")
            lines.append("")
        return "\n".join(lines).rstrip()

    def _make_decision(self, decided_by: AgentRole, title: str, rationale: str) -> Decision:
        d = Decision(
            title=title,
            rationale=rationale,
            decided_by=decided_by.value,
            confidence=0.7,
        )
        self.memory.add(
            "decision",
            f"{title}: {rationale}",
            tags=[decided_by.value, "decision"],
            importance=0.6,
        )
        return d

    def _make_proposal_from_outputs(
        self,
        req: SwarmRunRequest,
        outputs: dict[AgentRole, str],
        prefix: str = "Implement:",
    ) -> Proposal:
        """Convert agent outputs into a Proposal with cited files where possible."""
        files_to_change: list[dict[str, Any]] = []
        evidence_refs: list[str] = []
        # Try to extract file references like `path/to/file.py:10-20` from the outputs
        for _role, text in outputs.items():
            for match in re.finditer(r"`?([\w./\-]+\.[A-Za-z]{1,5}):(\d+)(?:-(\d+))?`?", text):
                path = match.group(1)
                start = int(match.group(2))
                end = int(match.group(3) or match.group(2))
                evidence_refs.append(f"{path}:{start}-{end}")
        # Deduplicate
        evidence_refs = list(dict.fromkeys(evidence_refs))

        # Build a single Proposal referencing the cited files
        if evidence_refs:
            for ref in evidence_refs[:10]:
                path, _, rng = ref.partition(":")
                files_to_change.append(
                    {
                        "path": path,
                        "change": "see proposal body",
                        "rationale": f"Referenced by {prefix} {req.objective[:80]}",
                        "lines": rng,
                    }
                )

        proposal = Proposal(
            title=f"{prefix} {req.objective[:80]}",
            description=req.objective,
            rationale="Proposal produced by the SWARM implementation pipeline.",
            files_to_change=files_to_change,
            evidence_refs=evidence_refs,
            state=WorkflowState.PROPOSED,
            scores=score_proposal(
                Proposal(
                    title=req.objective[:80],
                    description=req.objective,
                    files_to_change=files_to_change,
                )
            ),
        )
        return proposal

    # ------------------------------------------------------------------
    # Memory & status
    # ------------------------------------------------------------------

    def _store_long_term(self, result: SwarmResult, req: SwarmRunRequest) -> None:
        # Persist a digest into long_term + decision + architecture
        digest = (
            f"SWARM run {result.run_id} ({result.mode.value}, {result.strategy.value}): "
            f"{req.objective[:200]} → state={result.state.value}, "
            f"scores={result.scores.to_dict()}"
        )
        self.memory.add(
            "long_term",
            digest,
            tags=[result.mode.value, "run", "swarm"],
            importance=0.6,
            run_id=result.run_id,
            session_id=req.session_id,
            project_id=req.project_path,
        )
        # Best-effort push to NEXUS memory store
        try:
            self.memory.persist_to_nexus("long_term", run_id=result.run_id)
        except Exception as exc:
            logger.debug("persist_to_nexus failed: %s", exc)

    async def _publish_status(self, content: str, payload: dict[str, Any] | None = None) -> None:
        await self.coordinator.publish_status(content, payload)
        # Also publish to legacy NEXUS EventBus if available, so the dashboard sees it
        if self.events is not None:
            try:
                from backend.orchestrator.events import EventType, OrchestratorEvent

                self.events.publish(
                    OrchestratorEvent(
                        event_type=EventType.AGENT_STARTED,
                        source="SWARM",
                        data={"swarm_status": content, **(payload or {})},
                    )
                )
            except Exception:
                pass

    async def _record_message(
        self,
        sender: str,
        recipient: str,
        content: str,
        type: MessageType = MessageType.RESPONSE,
    ) -> None:
        with contextlib.suppress(Exception):
            await self.message_bus.publish(
                AgentMessage(
                    sender=sender,
                    recipient=recipient,
                    type=type,
                    content=content,
                )
            )


__all__ = [
    "SwarmOrchestrator",
    "SwarmRunRequest",
]
