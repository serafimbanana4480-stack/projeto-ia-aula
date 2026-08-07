"""SWARM Skills — reusable, named workflow templates.

A skill is a named entry-point into the SWARM system that pre-fills:
- the operational mode
- the strategy
- the agent set
- a templated objective builder (so the user supplies variables)

The catalogue below is auto-loaded by the SWARM API so a frontend or
external client can list them with ``GET /api/swarm/skills`` and invoke
them with ``POST /api/swarm/skills/{id}/run`` providing the variables.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.swarm.core.types import AgentRole, OperationalMode, SwarmStrategy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skill definition
# ---------------------------------------------------------------------------


@dataclass
class SkillVariable:
    name: str
    label: str
    description: str
    required: bool = True
    default: str = ""
    multiline: bool = False


@dataclass
class Skill:
    id: str
    name: str
    description: str
    category: str  # e.g. "code-quality", "architecture", "security", "docs", "data"
    icon: str
    mode: OperationalMode
    strategy: SwarmStrategy
    agents: list[AgentRole]
    objective_template: str
    variables: list[SkillVariable] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    max_iterations: int = 1000
    estimated_seconds: int = 60

    def render_objective(self, values: dict[str, str]) -> str:
        """Render the objective template with the user's values."""
        try:
            return self.objective_template.format(**values)
        except KeyError as exc:
            raise ValueError(f"Skill {self.id!r} missing required variable: {exc.args[0]}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "mode": self.mode.value,
            "strategy": self.strategy.value,
            "agents": [a.value for a in self.agents],
            "variables": [
                {
                    "name": v.name,
                    "label": v.label,
                    "description": v.description,
                    "required": v.required,
                    "default": v.default,
                    "multiline": v.multiline,
                }
                for v in self.variables
            ],
            "tags": self.tags,
            "max_iterations": self.max_iterations,
            "estimated_seconds": self.estimated_seconds,
        }


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


SKILL_CATALOGUE: list[Skill] = [
    # ------------------ CODE QUALITY ------------------
    Skill(
        id="security-audit",
        name="Security Audit",
        description="Deep 8-axis security review of a file or module. Flags injection, secrets, CORS, auth issues.",
        category="code-quality",
        icon="shield",
        mode=OperationalMode.REVIEW,
        strategy=SwarmStrategy.ENSEMBLE,
        agents=[AgentRole.INVESTIGATOR, AgentRole.REVIEWER, AgentRole.ARCHITECT],
        objective_template=(
            "## Security audit\n\n"
            "Target file(s): `{file_path}`\n"
            "Project root: `{project_path}`\n\n"
            "Perform a deep security review:\n"
            "1. Read every line of the target file via the RAG retriever.\n"
            "2. Look for: SQL injection, command injection, path traversal, SSRF, "
            "open redirects, XSS, hard-coded secrets, weak crypto, missing auth, "
            "missing rate limits, wildcard CORS, insecure deserialization.\n"
            "3. For each finding produce: severity (critical/high/medium/low), "
            "line range, evidence, and a concrete fix.\n"
            "4. End with a Security Verdict: PASS or FAIL.\n"
        ),
        variables=[
            SkillVariable(
                "file_path",
                "Target file",
                "Path (relative to the project) of the file to audit",
                multiline=False,
            ),
            SkillVariable(
                "project_path",
                "Project root",
                "Absolute path to the project root",
                default=".",
                multiline=False,
            ),
        ],
        tags=["security", "review", "owasp"],
        max_iterations=4,
        estimated_seconds=45,
    ),
    Skill(
        id="refactor-clean",
        name="Refactor (clean)",
        description="Produce a refactor proposal: rename, dedupe, split functions, improve naming.",
        category="code-quality",
        icon="scissors",
        mode=OperationalMode.IMPLEMENTATION,
        strategy=SwarmStrategy.PIPELINE,
        agents=[AgentRole.INVESTIGATOR, AgentRole.IMPLEMENTER, AgentRole.REVIEWER],
        objective_template=(
            "## Refactor proposal\n\n"
            "Target: `{file_path}`\n"
            "Focus: `{focus}`\n"
            "Project root: `{project_path}`\n\n"
            "Steps:\n"
            "1. INVESTIGATOR reads the file via RAG and lists smells (long functions, "
            "duplication, magic numbers, weak naming, missing type hints, swallowed exceptions).\n"
            "2. IMPLEMENTER drafts a Proposal with the file-level changes. No code "
            "is written — only the plan is emitted.\n"
            "3. REVIEWER validates that the proposal keeps tests green and respects "
            "the existing API.\n"
        ),
        variables=[
            SkillVariable("file_path", "Target file", "File to refactor", multiline=False),
            SkillVariable(
                "focus",
                "Focus area",
                "What to focus on (naming / splitting / dedupe / types / etc.)",
                default="naming + structure",
                multiline=False,
            ),
            SkillVariable(
                "project_path",
                "Project root",
                "Absolute path to the project root",
                default=".",
                multiline=False,
            ),
        ],
        tags=["refactor", "clean-code"],
        max_iterations=4,
        estimated_seconds=60,
    ),
    Skill(
        id="test-suite",
        name="Generate test suite",
        description="Plan and propose a unit-test suite for a module, with stubs and edge cases.",
        category="code-quality",
        icon="flask",
        mode=OperationalMode.IMPLEMENTATION,
        strategy=SwarmStrategy.PIPELINE,
        agents=[AgentRole.INVESTIGATOR, AgentRole.IMPLEMENTER, AgentRole.REVIEWER],
        objective_template=(
            "## Test suite generation\n\n"
            "Target: `{file_path}`\n"
            "Test framework: `{framework}`\n"
            "Project root: `{project_path}`\n\n"
            "Steps:\n"
            "1. INVESTIGATOR reads the module and lists every public function / class / branch.\n"
            "2. IMPLEMENTER drafts a Proposal with: file path for the new test file, "
            "list of test functions, fixtures, parametrize cases, and edge cases (None, empty, "
            "max-int, unicode, concurrent).\n"
            "3. REVIEWER verifies the tests actually assert behaviour, not just call the function.\n"
        ),
        variables=[
            SkillVariable("file_path", "Target file", "Module to test", multiline=False),
            SkillVariable(
                "framework",
                "Test framework",
                "pytest / unittest / vitest / jest",
                default="pytest",
                multiline=False,
            ),
            SkillVariable(
                "project_path",
                "Project root",
                "Absolute path to the project root",
                default=".",
                multiline=False,
            ),
        ],
        tags=["tests", "qa", "coverage"],
        max_iterations=4,
        estimated_seconds=60,
    ),
    Skill(
        id="pr-review",
        name="PR review",
        description="Review a pull request diff. Surfaces blockers, must-fixes, and nits.",
        category="code-quality",
        icon="git-pull-request",
        mode=OperationalMode.REVIEW,
        strategy=SwarmStrategy.ENSEMBLE,
        agents=[AgentRole.INVESTIGATOR, AgentRole.REVIEWER],
        objective_template=(
            "## PR review\n\n"
            "Diff or branch: `{diff_or_branch}`\n"
            "Project root: `{project_path}`\n\n"
            "Steps:\n"
            "1. INVESTIGATOR reads the diff via RAG (path -> line range).\n"
            "2. REVIEWER produces a structured review with: blockers (must-fix), "
            "should-fixes, nits, and an overall verdict (APPROVE / REQUEST CHANGES / COMMENT).\n"
        ),
        variables=[
            SkillVariable(
                "diff_or_branch",
                "Diff or branch",
                "Paste a diff or a branch name like `feature/foo`",
                multiline=True,
            ),
            SkillVariable(
                "project_path",
                "Project root",
                "Absolute path to the project root",
                default=".",
                multiline=False,
            ),
        ],
        tags=["pr", "review", "git"],
        max_iterations=3,
        estimated_seconds=45,
    ),
    # ------------------ ARCHITECTURE ------------------
    Skill(
        id="api-design",
        name="API design",
        description="Design a new REST/GraphQL API: endpoints, payloads, errors, auth, versioning.",
        category="architecture",
        icon="rss",
        mode=OperationalMode.ARCHITECTURE,
        strategy=SwarmStrategy.DEBATE,
        agents=[AgentRole.INVESTIGATOR, AgentRole.ARCHITECT, AgentRole.REVIEWER],
        objective_template=(
            "## API design\n\n"
            "Use case: `{use_case}`\n"
            "Style: `{style}`\n"
            "Auth: `{auth}`\n\n"
            "Produce:\n"
            "1. Resource list and the operations on each.\n"
            "2. Endpoint table (method, path, request, response, errors).\n"
            "3. Pagination, filtering, sorting, idempotency strategy.\n"
            "4. Auth model (OAuth2 / JWT / API key) and rate-limit policy.\n"
            "5. Versioning strategy.\n"
            "6. 2-3 alternative designs with trade-offs and a clear Decision.\n"
        ),
        variables=[
            SkillVariable(
                "use_case", "Use case", "Short description of the use case", multiline=True
            ),
            SkillVariable(
                "style",
                "API style",
                "REST / GraphQL / gRPC / tRPC",
                default="REST",
                multiline=False,
            ),
            SkillVariable(
                "auth",
                "Auth",
                "Authentication / authorization scheme",
                default="JWT",
                multiline=False,
            ),
        ],
        tags=["api", "design", "rest", "graphql"],
        max_iterations=1000,
        estimated_seconds=90,
    ),
    Skill(
        id="data-model",
        name="Data model design",
        description="Design a relational or document data model. Tables, columns, indexes, constraints.",
        category="architecture",
        icon="database",
        mode=OperationalMode.ARCHITECTURE,
        strategy=SwarmStrategy.DEBATE,
        agents=[AgentRole.INVESTIGATOR, AgentRole.ARCHITECT, AgentRole.REVIEWER],
        objective_template=(
            "## Data model\n\n"
            "Domain: `{domain}`\n"
            "Engine: `{engine}`\n\n"
            "Produce:\n"
            "1. Entities and their attributes (PK, FK, NOT NULL, UNIQUE, default).\n"
            "2. Relationships (1:1, 1:N, N:M).\n"
            "3. Indexes (B-tree, partial, GIN for JSONB).\n"
            "4. Migrations strategy (online / zero-downtime).\n"
            "5. 2-3 alternative designs with trade-offs and a clear Decision.\n"
        ),
        variables=[
            SkillVariable("domain", "Domain", "Short description of the domain", multiline=True),
            SkillVariable(
                "engine",
                "DB engine",
                "PostgreSQL / MySQL / SQLite / MongoDB / DynamoDB",
                default="PostgreSQL",
                multiline=False,
            ),
        ],
        tags=["data", "db", "schema"],
        max_iterations=1000,
        estimated_seconds=90,
    ),
    Skill(
        id="architecture-diagram",
        name="Architecture diagram (mermaid)",
        description="Emit a Mermaid `graph` diagram for the system under design.",
        category="architecture",
        icon="git-branch",
        mode=OperationalMode.ARCHITECTURE,
        strategy=SwarmStrategy.DEBATE,
        agents=[AgentRole.INVESTIGATOR, AgentRole.ARCHITECT],
        objective_template=(
            "## Architecture diagram\n\n"
            "System: `{system}`\n\n"
            "Produce a Mermaid `graph TD` diagram with:\n"
            "- External clients (top)\n"
            "- Edge / API layer\n"
            "- Services / workers\n"
            "- Datastores (bottom)\n"
            "- Arrows labelled with the protocol (HTTPS, gRPC, pub/sub, queue).\n"
            "Also produce a one-paragraph caption explaining the diagram.\n"
        ),
        variables=[
            SkillVariable(
                "system", "System", "Short description of the system to diagram", multiline=True
            ),
        ],
        tags=["diagram", "mermaid", "c4"],
        max_iterations=3,
        estimated_seconds=45,
    ),
    Skill(
        id="migration-plan",
        name="Migration plan",
        description="Plan a database, framework, or service migration with phases and rollback.",
        category="architecture",
        icon="arrow-right",
        mode=OperationalMode.PLANNING,
        strategy=SwarmStrategy.DIVIDE,
        agents=[AgentRole.INVESTIGATOR, AgentRole.ARCHITECT],
        objective_template=(
            "## Migration plan\n\n"
            "From: `{from_state}`\n"
            "To: `{to_state}`\n\n"
            "Produce a plan with phases: pre-flight checks, dual-write, cutover, "
            "verification, cleanup. Each phase lists deliverables, owner-role, "
            "estimated effort, and rollback steps. End with a risk table.\n"
        ),
        variables=[
            SkillVariable(
                "from_state", "Current state", "Description of the current system", multiline=True
            ),
            SkillVariable(
                "to_state", "Target state", "Description of the target system", multiline=True
            ),
        ],
        tags=["migration", "plan", "rollout"],
        max_iterations=4,
        estimated_seconds=75,
    ),
    # ------------------ DOCS ------------------
    Skill(
        id="doc-generator",
        name="Generate documentation",
        description="Produce a README, a module docstring, or an OpenAPI summary for a file or set of files.",
        category="docs",
        icon="book",
        mode=OperationalMode.INVESTIGATION,
        strategy=SwarmStrategy.ENSEMBLE,
        agents=[AgentRole.INVESTIGATOR, AgentRole.ARCHITECT],
        objective_template=(
            "## Documentation generation\n\n"
            "Target: `{target}`\n"
            "Doc type: `{doc_type}`\n"
            "Project root: `{project_path}`\n\n"
            "Read the target via RAG and produce the requested doc type. "
            "Cite every file:line range you used.\n"
        ),
        variables=[
            SkillVariable("target", "Target", "File or directory to document", multiline=False),
            SkillVariable(
                "doc_type",
                "Doc type",
                "README / module-docstring / OpenAPI / runbook",
                default="README",
                multiline=False,
            ),
            SkillVariable(
                "project_path",
                "Project root",
                "Absolute path to the project root",
                default=".",
                multiline=False,
            ),
        ],
        tags=["docs", "readme"],
        max_iterations=3,
        estimated_seconds=45,
    ),
    Skill(
        id="incident-postmortem",
        name="Incident postmortem",
        description="Walk through an incident description and produce a blameless postmortem.",
        category="docs",
        icon="alert-triangle",
        mode=OperationalMode.INVESTIGATION,
        strategy=SwarmStrategy.ENSEMBLE,
        agents=[AgentRole.INVESTIGATOR, AgentRole.ARCHITECT],
        objective_template=(
            "## Incident postmortem\n\n"
            "Incident: `{incident}`\n\n"
            "Produce a blameless postmortem with: timeline, root cause analysis "
            "(5 Whys), contributing factors, what went well, what didn't, "
            "action items with owners and deadlines.\n"
        ),
        variables=[
            SkillVariable(
                "incident",
                "Incident description",
                "Free-form description of what happened",
                multiline=True,
            ),
        ],
        tags=["postmortem", "incident", "sre"],
        max_iterations=3,
        estimated_seconds=60,
    ),
    # ------------------ DATA / RESEARCH ------------------
    Skill(
        id="library-comparison",
        name="Library comparison",
        description="Compare 2-4 libraries for a given need. Trade-offs, benchmarks, recommendation.",
        category="research",
        icon="library",
        mode=OperationalMode.RESEARCH,
        strategy=SwarmStrategy.ENSEMBLE,
        agents=[AgentRole.RESEARCHER, AgentRole.ARCHITECT],
        objective_template=(
            "## Library comparison\n\n"
            "Need: `{need}`\n"
            "Candidates: `{candidates}`\n\n"
            "Use external research (multi-source). For each candidate produce:\n"
            "- One-paragraph summary\n"
            "- Pros / cons\n"
            "- When to use / when to avoid\n"
            "End with a clear recommendation + confidence.\n"
        ),
        variables=[
            SkillVariable("need", "Need", "What you're trying to solve", multiline=True),
            SkillVariable(
                "candidates",
                "Candidates",
                "Comma-separated list of libraries to compare",
                default="(let the researcher pick)",
                multiline=False,
            ),
        ],
        tags=["research", "comparison"],
        max_iterations=4,
        estimated_seconds=90,
    ),
    Skill(
        id="best-practices",
        name="Best practices research",
        description="Gather best practices for a topic from multiple official sources.",
        category="research",
        icon="lightbulb",
        mode=OperationalMode.RESEARCH,
        strategy=SwarmStrategy.ENSEMBLE,
        agents=[AgentRole.RESEARCHER, AgentRole.ARCHITECT],
        objective_template=(
            "## Best practices: `{topic}`\n\n"
            "Use external research. Cite ≥3 independent sources. Prefer official docs.\n"
        ),
        variables=[
            SkillVariable("topic", "Topic", "Topic to research", multiline=False),
        ],
        tags=["research", "best-practices"],
        max_iterations=3,
        estimated_seconds=60,
    ),
    # ------------------ DEBUG / BUGFIX ------------------
    Skill(
        id="bugfix-investigation",
        name="Bugfix investigation",
        description="Investigate a bug, surface the root cause, and propose a minimal fix.",
        category="debug",
        icon="bug",
        mode=OperationalMode.BUGFIX,
        strategy=SwarmStrategy.PIPELINE,
        agents=[AgentRole.INVESTIGATOR, AgentRole.IMPLEMENTER, AgentRole.REVIEWER],
        objective_template=(
            "## Bugfix investigation\n\n"
            "Symptom: `{symptom}`\n"
            "Repro: `{repro}`\n"
            "Project root: `{project_path}`\n\n"
            "1. INVESTIGATOR: gather the relevant code via RAG, list suspects, "
            "and run a 5-Whys root cause analysis.\n"
            "2. IMPLEMENTER: emit a minimal-fix Proposal with file:line evidence.\n"
            "3. REVIEWER: validate the fix doesn't introduce regressions.\n"
        ),
        variables=[
            SkillVariable("symptom", "Symptom", "What the user sees", multiline=True),
            SkillVariable("repro", "Repro", "Steps to reproduce", multiline=True),
            SkillVariable(
                "project_path",
                "Project root",
                "Absolute path to the project root",
                default=".",
                multiline=False,
            ),
        ],
        tags=["bug", "fix", "debug"],
        max_iterations=1000,
        estimated_seconds=75,
    ),
]


# ---------------------------------------------------------------------------
# Catalogue accessors
# ---------------------------------------------------------------------------


def get_skill(skill_id: str) -> Skill | None:
    for s in SKILL_CATALOGUE:
        if s.id == skill_id:
            return s
    return None


def all_skills() -> list[Skill]:
    return list(SKILL_CATALOGUE)


def by_category() -> dict[str, list[Skill]]:
    out: dict[str, list[Skill]] = {}
    for s in SKILL_CATALOGUE:
        out.setdefault(s.category, []).append(s)
    return out


def to_dict() -> list[dict[str, Any]]:
    return [s.to_dict() for s in SKILL_CATALOGUE]


__all__ = [
    "Skill",
    "SkillVariable",
    "SKILL_CATALOGUE",
    "get_skill",
    "all_skills",
    "by_category",
    "to_dict",
]
