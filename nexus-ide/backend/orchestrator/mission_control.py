"""NEXUS IDE — Mission Control.

Why this module exists
──────────────────────
Before it, the chat pipeline went straight from a user prompt to
``engine.execute_autonomous()``, which internally created a plan, auto-approved
it, and started agents. The plan *existed* but the only thing that ever reached
the user was ``ORCHESTRATOR_STARTED {plan_id, steps: 7}`` — a count. From the
outside the product looked like a spawner: activity with no legible intent.

Seven questions were unanswerable from the UI:

    1. What did the system understand from my request?
    2. What is the real state of the project right now?
    3. Why were *these* agents chosen?
    4. What is the plan?
    5. What is each agent touching?
    6. Were the changes actually tested?
    7. What is still missing?

Mission Control answers all seven as first-class, observable objects:

    MissionBrief    → (1) (2) — interpreted objective + measured initial state
    ExecutionPlan   → (4)     — five ordered phases, declared before any spawn
    AgentContract   → (3) (5) — justification, inputs, outputs, completion criteria
    Wave            → (3)     — bounded concurrency, dependency-ordered
    DecisionLog     → (3)     — choice + reason + alternatives considered
    Verification    → (6)     — commands run and their real exit codes
    MissionReport   → (7)     — markdown artefact written to ``reports/``

Design constraints
──────────────────
* **Stdlib only.** No FastAPI, pydantic or LLM import at module scope, so the
  planner is unit-testable and usable from a script or a cron job.
* **Nothing is invented.** ``ProjectIntelligence`` reports what it measured and
  marks everything else ``unknown``. A brief that guesses is worse than no
  brief, because it is trusted.
* **Additive.** The existing engine is untouched; Mission Control wraps it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "reports"
MISSIONS_DIR = REPO_ROOT / ".nexus" / "missions"

# Directories that never carry signal and cost real seconds to walk.
SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".next", ".next-dev", ".venv", "venv",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build", ".turbo",
    "coverage", ".idea", ".vscode", "playwright-report", "test-results",
    ".nexus", ".kilo", ".agents", "site-packages", ".egg-info",
})

# A scan walking a monorepo unbounded is a hang, not a scan. These caps make the
# worst case predictable; ``truncated`` tells the reader when one was hit.
MAX_SCAN_FILES = 20_000
MAX_SCAN_SECONDS = 12.0

# Concurrency band. Below 3 the wall-clock cost of a mission balloons; above 6
# agents start colliding on the same files and burning context re-reading each
# other's half-written edits.
MIN_CONCURRENT_AGENTS = 3
MAX_CONCURRENT_AGENTS = 6


# ═══════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════

class MissionPhase(StrEnum):
    """The five phases every mission passes through, in order."""

    DIAGNOSIS = "diagnosis"
    STABILISATION = "stabilisation"
    IMPROVEMENT = "improvement"
    VERIFICATION = "verification"
    DELIVERY = "delivery"

    @property
    def label(self) -> str:
        return {
            "diagnosis": "Fase 1 — Diagnóstico",
            "stabilisation": "Fase 2 — Estabilização",
            "improvement": "Fase 3 — Melhorias",
            "verification": "Fase 4 — Verificação",
            "delivery": "Fase 5 — Entrega",
        }[self.value]


class MissionState(StrEnum):
    ANALYSING = "analysing"      # reading the project, no agent exists yet
    PLANNED = "planned"          # plan published, awaiting first wave
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContractState(StrEnum):
    PROPOSED = "proposed"        # visible in the UI, deliberately not started
    READY = "ready"              # dependencies satisfied
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# ═══════════════════════════════════════════════════════════════════════════
# Project intelligence — measured, never guessed
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Finding:
    """One measured fact about the project.

    ``evidence`` is the raw string the finding was derived from. Without it a
    finding is an assertion; with it the reader can check the work.
    """

    id: str
    title: str
    severity: Severity = Severity.INFO
    category: str = "general"
    detail: str = ""
    evidence: str = ""
    paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class ProjectSnapshot:
    """What the project actually looked like when the mission started.

    Every field is either measured or explicitly ``None``/``unknown``. There is
    no field here whose value was inferred from a filename convention alone.
    """

    root: str = ""
    scanned_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    file_count: int = 0
    truncated: bool = False
    scan_seconds: float = 0.0
    languages: dict[str, int] = field(default_factory=dict)
    frameworks: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    test_files: int = 0
    test_frameworks: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)
    doc_files: int = 0
    todo_count: int = 0
    todo_samples: list[str] = field(default_factory=list)
    git_branch: str | None = None
    git_dirty_files: int | None = None
    git_last_commit: str | None = None
    dependency_manifests: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["findings"] = [f.to_dict() for f in self.findings]
        return d

    def summary_lines(self) -> list[str]:
        """Human-readable initial state — the body of the Mission Brief."""
        out: list[str] = []
        if self.languages:
            top = sorted(self.languages.items(), key=lambda kv: -kv[1])[:4]
            out.append("Linguagens: " + ", ".join(f"{k} ({v})" for k, v in top))
        if self.frameworks:
            out.append("Frameworks: " + ", ".join(self.frameworks))
        out.append(
            f"Ficheiros analisados: {self.file_count}"
            + (" (limite atingido — análise parcial)" if self.truncated else "")
        )
        if self.test_files:
            fw = f" ({', '.join(self.test_frameworks)})" if self.test_frameworks else ""
            out.append(f"Ficheiros de teste: {self.test_files}{fw}")
        else:
            out.append("Ficheiros de teste: nenhum encontrado")
        if self.todo_count:
            out.append(f"Marcadores TODO/FIXME/HACK: {self.todo_count}")
        if self.git_branch:
            dirty = (
                f", {self.git_dirty_files} ficheiros por commitar"
                if self.git_dirty_files
                else ", árvore limpa"
            )
            out.append(f"Git: {self.git_branch}{dirty}")
        if self.dependency_manifests:
            out.append("Manifestos: " + ", ".join(self.dependency_manifests[:5]))
        return out


class ProjectIntelligence:
    """Reads a project and reports measurements. It never modifies anything.

    This is the "Project Intelligence Agent" of the design, implemented as a
    deterministic scanner rather than an LLM call: the initial state of a
    repository is a fact, and paying a model to hallucinate facts that ``os.walk``
    can measure is both slower and less trustworthy.
    """

    LANG_BY_EXT = {
        ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript React",
        ".js": "JavaScript", ".jsx": "JavaScript React", ".go": "Go",
        ".rs": "Rust", ".java": "Java", ".rb": "Ruby", ".php": "PHP",
        ".cs": "C#", ".cpp": "C++", ".c": "C", ".sh": "Shell",
        ".sql": "SQL", ".css": "CSS", ".scss": "SCSS", ".md": "Markdown",
        ".yaml": "YAML", ".yml": "YAML", ".json": "JSON",
    }

    FRAMEWORK_MARKERS = {
        "next.config.mjs": "Next.js", "next.config.js": "Next.js",
        "next.config.ts": "Next.js", "vite.config.ts": "Vite",
        "nuxt.config.ts": "Nuxt", "angular.json": "Angular",
        "svelte.config.js": "Svelte", "tailwind.config.ts": "Tailwind CSS",
        "tailwind.config.js": "Tailwind CSS", "alembic.ini": "Alembic",
        "docker-compose.yml": "Docker Compose", "Dockerfile": "Docker",
        "playwright.config.ts": "Playwright", "vitest.config.ts": "Vitest",
        "jest.config.js": "Jest", "pyproject.toml": "Python packaging",
        "Cargo.toml": "Cargo", "go.mod": "Go modules",
    }

    MANIFESTS = frozenset({
        "package.json", "pyproject.toml", "requirements.txt", "Pipfile",
        "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "Gemfile",
        "composer.json", "pnpm-lock.yaml", "poetry.lock",
    })

    TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX|BUG)\b[: ]", re.IGNORECASE)

    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).resolve()

    # ── public ────────────────────────────────────────────────────────────
    def scan(self, *, deep: bool = True) -> ProjectSnapshot:
        started = time.monotonic()
        snap = ProjectSnapshot(root=str(self.root))

        if not self.root.is_dir():
            snap.notes.append(f"Caminho inexistente ou não é diretório: {self.root}")
            snap.findings.append(
                Finding(
                    id="scan-root-missing",
                    title="Raiz do projeto inacessível",
                    severity=Severity.CRITICAL,
                    category="scan",
                    detail=f"{self.root} não existe ou não é um diretório.",
                    evidence=str(self.root),
                )
            )
            return snap

        self._walk(snap, deep=deep, started=started)
        self._read_git(snap)
        self._derive_findings(snap)
        snap.scan_seconds = round(time.monotonic() - started, 3)
        return snap

    # ── internals ─────────────────────────────────────────────────────────
    def _walk(self, snap: ProjectSnapshot, *, deep: bool, started: float) -> None:
        todo_samples: list[str] = []

        for dirpath, dirnames, filenames in os.walk(self.root):
            # Prune in place — os.walk honours mutation of ``dirnames``.
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS and not d.startswith(".pytest")
            ]

            if snap.file_count >= MAX_SCAN_FILES or (time.monotonic() - started) > MAX_SCAN_SECONDS:
                snap.truncated = True
                break

            rel_dir = Path(dirpath).relative_to(self.root)

            for name in filenames:
                snap.file_count += 1
                if snap.file_count >= MAX_SCAN_FILES:
                    snap.truncated = True
                    break

                ext = Path(name).suffix.lower()
                lang = self.LANG_BY_EXT.get(ext)
                if lang:
                    snap.languages[lang] = snap.languages.get(lang, 0) + 1

                if name in self.FRAMEWORK_MARKERS:
                    fw = self.FRAMEWORK_MARKERS[name]
                    if fw not in snap.frameworks:
                        snap.frameworks.append(fw)

                if name in self.MANIFESTS:
                    rel = str(rel_dir / name) if str(rel_dir) != "." else name
                    if rel not in snap.dependency_manifests:
                        snap.dependency_manifests.append(rel)

                if ext == ".md":
                    snap.doc_files += 1

                if self._is_test_file(name):
                    snap.test_files += 1

                if name in ("main.py", "app.py", "index.ts", "server.ts", "main.go", "main.rs"):
                    rel = str(rel_dir / name) if str(rel_dir) != "." else name
                    if len(snap.entrypoints) < 12:
                        snap.entrypoints.append(rel)

                if deep and ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"):
                    hits = self._scan_todos(Path(dirpath) / name)
                    snap.todo_count += hits
                    if hits and len(todo_samples) < 10:
                        rel = str(rel_dir / name) if str(rel_dir) != "." else name
                        todo_samples.append(f"{rel} ({hits})")

        snap.todo_samples = todo_samples
        self._detect_test_frameworks(snap)

    #: Extensions a test file can actually have. Without this, the name-only
    #: heuristic counted any artifact called ``test_*`` — a SQLite fixture
    #: (``test_nexus.db``) and its ``-wal``/``-shm`` siblings each scored as a
    #: test, inflating "Ficheiros de teste" in every mission brief.
    _TEST_FILE_EXTENSIONS: frozenset[str] = frozenset(
        {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".rb"}
    )

    @classmethod
    def _is_test_file(cls, name: str) -> bool:
        low = name.lower()
        stem, ext = os.path.splitext(low)
        if ext not in cls._TEST_FILE_EXTENSIONS:
            return False
        return (
            low.startswith("test_")
            # ``_test`` is the Go and Rust convention too — the previous rule
            # hard-coded ``_test.py`` and silently missed ``foo_test.go``.
            or stem.endswith("_test")
            or ".test." in low
            or ".spec." in low
        )

    def _scan_todos(self, path: Path) -> int:
        """Count TODO-family markers. Silent on unreadable files by design —
        a permissions error in one file must not abort the whole scan."""
        try:
            if path.stat().st_size > 512_000:
                return 0
            with path.open("r", encoding="utf-8", errors="ignore") as fh:
                return sum(1 for line in fh if self.TODO_RE.search(line))
        except (OSError, ValueError):
            return 0

    def _detect_test_frameworks(self, snap: ProjectSnapshot) -> None:
        checks = {
            "pytest": ["pyproject.toml", "pytest.ini", "setup.cfg"],
            "vitest": ["vitest.config.ts", "vitest.config.js"],
            "playwright": ["playwright.config.ts", "playwright.config.js"],
            "jest": ["jest.config.js", "jest.config.ts"],
        }
        for fw, files in checks.items():
            for f in files:
                p = self.root / f
                if not p.exists():
                    continue
                if fw == "pytest":
                    try:
                        if "pytest" not in p.read_text(encoding="utf-8", errors="ignore"):
                            continue
                    except OSError:
                        continue
                if fw not in snap.test_frameworks:
                    snap.test_frameworks.append(fw)
                break

    def _read_git(self, snap: ProjectSnapshot) -> None:
        """Best-effort git state. A repo without git is normal, not an error."""
        def run(args: Sequence[str]) -> str | None:
            try:
                out = subprocess.run(
                    ["git", *args],
                    cwd=self.root,
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
                return out.stdout.strip() if out.returncode == 0 else None
            except (OSError, subprocess.SubprocessError):
                return None

        if not (self.root / ".git").exists():
            snap.notes.append("Sem repositório git — histórico e diff indisponíveis.")
            return

        snap.git_branch = run(["rev-parse", "--abbrev-ref", "HEAD"])
        snap.git_last_commit = run(["log", "-1", "--pretty=%h %s"])
        status = run(["status", "--porcelain"])
        if status is not None:
            snap.git_dirty_files = len([ln for ln in status.splitlines() if ln.strip()])

    def _derive_findings(self, snap: ProjectSnapshot) -> None:
        """Turn measurements into ranked findings. Each carries its evidence."""
        if snap.test_files == 0:
            snap.findings.append(Finding(
                id="no-tests",
                title="Nenhum ficheiro de teste encontrado",
                severity=Severity.HIGH,
                category="testing",
                detail="Alterações não podem ser validadas automaticamente.",
                evidence="test_files=0",
            ))
        elif snap.test_frameworks == []:
            snap.findings.append(Finding(
                id="tests-no-runner",
                title="Testes existem mas nenhum runner foi detetado",
                severity=Severity.MEDIUM,
                category="testing",
                detail="Ficheiros de teste presentes sem configuração de runner reconhecida.",
                evidence=f"test_files={snap.test_files}, test_frameworks=[]",
            ))

        if snap.todo_count > 50:
            snap.findings.append(Finding(
                id="high-todo",
                title=f"{snap.todo_count} marcadores TODO/FIXME por resolver",
                severity=Severity.MEDIUM,
                category="tech-debt",
                detail="Volume elevado de trabalho declarado como incompleto no código.",
                evidence="; ".join(snap.todo_samples[:5]),
                paths=[s.split(" (")[0] for s in snap.todo_samples[:5]],
            ))

        if snap.git_dirty_files and snap.git_dirty_files > 25:
            snap.findings.append(Finding(
                id="dirty-tree",
                title=f"{snap.git_dirty_files} ficheiros não commitados",
                severity=Severity.MEDIUM,
                category="vcs",
                detail="Uma árvore suja torna o rollback de alterações desta missão ambíguo.",
                evidence=f"git status --porcelain → {snap.git_dirty_files} linhas",
            ))

        if snap.doc_files == 0:
            snap.findings.append(Finding(
                id="no-docs",
                title="Sem documentação markdown",
                severity=Severity.LOW,
                category="docs",
                detail="Nenhum ficheiro .md encontrado no projeto.",
                evidence="doc_files=0",
            ))

        if snap.truncated:
            snap.findings.append(Finding(
                id="scan-truncated",
                title="Análise parcial — limite de varrimento atingido",
                severity=Severity.INFO,
                category="scan",
                detail=(
                    f"O varrimento parou em {snap.file_count} ficheiros ou "
                    f"{MAX_SCAN_SECONDS}s. Conclusões sobre cobertura são incompletas."
                ),
                evidence=f"file_count={snap.file_count}, truncated=True",
            ))


# ═══════════════════════════════════════════════════════════════════════════
# Mission brief
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class MissionBrief:
    """What the system understood, before it does anything.

    Published as an event *before* the first agent contract is created. If the
    interpretation is wrong the user finds out in seconds instead of after a
    dozen agents have edited files.
    """

    objective_raw: str
    objective_interpreted: str
    snapshot: ProjectSnapshot
    priorities: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective_raw": self.objective_raw,
            "objective_interpreted": self.objective_interpreted,
            "initial_state": self.snapshot.summary_lines(),
            "snapshot": self.snapshot.to_dict(),
            "priorities": self.priorities,
            "assumptions": self.assumptions,
            "out_of_scope": self.out_of_scope,
        }

    def render(self) -> str:
        lines = [
            "MISSION BRIEF",
            "",
            "Objetivo interpretado:",
            f"  {self.objective_interpreted}",
            "",
            "Estado inicial:",
        ]
        lines += [f"  - {ln}" for ln in self.snapshot.summary_lines()]
        if self.snapshot.findings:
            lines += ["", "Problemas detetados:"]
            for f in self.snapshot.findings[:8]:
                lines.append(f"  - [{f.severity.value}] {f.title}")
        if self.priorities:
            lines += ["", "Prioridades propostas:"]
            lines += [f"  {i}. {p}" for i, p in enumerate(self.priorities, 1)]
        if self.assumptions:
            lines += ["", "Pressupostos:"]
            lines += [f"  - {a}" for a in self.assumptions]
        lines += ["", "Nenhum agente foi criado nesta fase."]
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# Agent contracts and waves
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class AgentContract:
    """The terms an agent is spawned under.

    An agent without a contract is unaccountable: there is no statement of what
    it was supposed to achieve, so "done" is whatever it says it is.
    ``completion_criteria`` is what turns a claim into a checkable assertion.
    """

    name: str
    objective: str
    justification: str
    phase: MissionPhase = MissionPhase.DIAGNOSIS
    inputs: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    completion_criteria: list[str] = field(default_factory=list)

    # ── live state ──
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    state: ContractState = ContractState.PROPOSED
    activity: str = ""
    discoveries: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    confidence: float | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["phase"] = self.phase.value
        d["state"] = self.state.value
        return d

    def render_card(self) -> str:
        lines = [
            f"{self.name.upper()}",
            "",
            f"Estado: {self.state.value}",
            f"Objetivo: {self.objective}",
            f"Motivo: {self.justification}",
        ]
        if self.dependencies:
            lines.append(f"Dependências: {', '.join(self.dependencies)}")
        if self.activity:
            lines += ["", "Atividade atual:", f"  {self.activity}"]
        if self.discoveries:
            lines += ["", "Descobertas:"]
            lines += [f"  - {d}" for d in self.discoveries]
        if self.files_changed:
            lines += ["", "Alterações:"]
            lines += [f"  - {f}" for f in self.files_changed]
        if self.confidence is not None:
            lines += ["", f"Confiança atual: {self.confidence:.0%}"]
        return "\n".join(lines)


@dataclass
class Wave:
    """A bounded, dependency-ordered group of contracts.

    Waves are the mechanism that stops the orchestrator from creating twenty
    agents at once. Wave N+1 is only *composed* after wave N reports, so later
    agents get to read what earlier ones found rather than duplicating it.
    """

    index: int
    name: str
    phase: MissionPhase
    contracts: list[AgentContract] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None

    @property
    def state(self) -> str:
        if not self.contracts:
            return "empty"
        states = {c.state for c in self.contracts}
        if states == {ContractState.PROPOSED}:
            return "proposed"
        if ContractState.RUNNING in states:
            return "running"
        if ContractState.FAILED in states:
            return "failed"
        if states <= {ContractState.COMPLETED, ContractState.SKIPPED}:
            return "completed"
        return "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "phase": self.phase.value,
            "state": self.state,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "contracts": [c.to_dict() for c in self.contracts],
        }


# ═══════════════════════════════════════════════════════════════════════════
# Decision log
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Decision:
    """A choice, its reason, and the options that lost.

    Deliberately *not* raw chain-of-thought. Streaming a model's internal
    monologue is noise; a decision the reader can disagree with is signal.
    """

    number: int
    choice: str
    reason: str
    alternatives: list[str] = field(default_factory=list)
    outcome: str = ""
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        lines = [f"Decisão #{self.number}", "", "Escolha:", f"  {self.choice}", "", "Razão:", f"  {self.reason}"]
        if self.alternatives:
            lines += ["", "Alternativas consideradas:"]
            lines += [f"  - {a}" for a in self.alternatives]
        if self.outcome:
            lines += ["", f"Decisão final: {self.outcome}"]
        return "\n".join(lines)


@dataclass
class TimelineEntry:
    at: str
    label: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationResult:
    """A command that was actually executed, with its real exit code.

    ``passed`` is derived from ``exit_code``, never set by a caller — that is
    the whole point. A verification that can be asserted is not a verification.
    """

    command: str
    exit_code: int | None = None
    summary: str = ""
    duration_s: float = 0.0
    skipped_reason: str | None = None

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["passed"] = self.passed
        return d


# ═══════════════════════════════════════════════════════════════════════════
# Execution plan
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PhasePlan:
    phase: MissionPhase
    steps: list[str] = field(default_factory=list)
    rationale: str = ""
    skipped: bool = False
    skip_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "label": self.phase.label,
            "steps": self.steps,
            "rationale": self.rationale,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
        }


@dataclass
class MissionPlan:
    phases: list[PhasePlan] = field(default_factory=list)
    concurrency_limit: int = 4

    def to_dict(self) -> dict[str, Any]:
        return {
            "phases": [p.to_dict() for p in self.phases],
            "concurrency_limit": self.concurrency_limit,
        }

    def render(self) -> str:
        lines = ["PLANO DE EXECUÇÃO", ""]
        for p in self.phases:
            lines.append(p.phase.label + (" — ignorada" if p.skipped else ""))
            if p.skipped:
                lines.append(f"  ({p.skip_reason})")
            else:
                lines += [f"  - {s}" for s in p.steps]
            lines.append("")
        lines.append(f"Limite de agentes concorrentes: {self.concurrency_limit}")
        return "\n".join(lines).rstrip()


# ═══════════════════════════════════════════════════════════════════════════
# The mission itself
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Mission:
    """Live, serialisable state of one run. This is what the UI renders."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    session_id: str = ""
    title: str = ""
    state: MissionState = MissionState.ANALYSING
    phase: MissionPhase = MissionPhase.DIAGNOSIS
    brief: MissionBrief | None = None
    plan: MissionPlan | None = None
    waves: list[Wave] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    timeline: list[TimelineEntry] = field(default_factory=list)
    verifications: list[VerificationResult] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None

    # ── derived ───────────────────────────────────────────────────────────
    @property
    def contracts(self) -> list[AgentContract]:
        return [c for w in self.waves for c in w.contracts]

    @property
    def active_agents(self) -> int:
        return sum(1 for c in self.contracts if c.state == ContractState.RUNNING)

    @property
    def files_changed(self) -> list[str]:
        seen: list[str] = []
        for c in self.contracts:
            for f in c.files_changed:
                if f not in seen:
                    seen.append(f)
        return seen

    @property
    def progress(self) -> float:
        cs = self.contracts
        if not cs:
            return 0.0
        done = sum(1 for c in cs if c.state in (ContractState.COMPLETED, ContractState.SKIPPED))
        return round(done / len(cs), 4)

    @property
    def tests_passed(self) -> int:
        return sum(1 for v in self.verifications if v.passed)

    @property
    def tests_failed(self) -> int:
        return sum(1 for v in self.verifications if v.exit_code not in (0, None))

    def to_dict(self) -> dict[str, Any]:
        cs = self.contracts
        return {
            "id": self.id,
            "session_id": self.session_id,
            "title": self.title,
            "state": self.state.value,
            "phase": self.phase.value,
            "phase_label": self.phase.label,
            "progress": self.progress,
            "active_agents": self.active_agents,
            "tasks_total": len(cs),
            "tasks_done": sum(
                1 for c in cs if c.state in (ContractState.COMPLETED, ContractState.SKIPPED)
            ),
            "files_changed": self.files_changed,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "risks": self.risks,
            "unresolved": self.unresolved,
            "suggestions": self.suggestions,
            "brief": self.brief.to_dict() if self.brief else None,
            "plan": self.plan.to_dict() if self.plan else None,
            "waves": [w.to_dict() for w in self.waves],
            "decisions": [d.to_dict() for d in self.decisions],
            "timeline": [t.to_dict() for t in self.timeline],
            "verifications": [v.to_dict() for v in self.verifications],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Planner — turns a snapshot into a plan and waves
# ═══════════════════════════════════════════════════════════════════════════

# Wave composition. The order encodes a rule the previous orchestrator did not
# have: nothing writes before something has read. Wave 1 is read-only.
WAVE_BLUEPRINT: list[dict[str, Any]] = [
    {
        "name": "Onda 1 — Compreensão",
        "phase": MissionPhase.DIAGNOSIS,
        "agents": [
            ("Project Intelligence Agent", "Mapear estrutura, linguagens, dependências e estado git",
             ["file_read", "terminal"], ["mapa técnico do projeto"]),
            ("Architecture Agent", "Identificar limites de módulos, acoplamentos e pontos de falha",
             ["file_read"], ["relatório de arquitetura"]),
            ("Test Discovery Agent", "Localizar testes, runners e cobertura declarada",
             ["file_read", "terminal"], ["inventário de testes"]),
            ("Documentation Analyzer", "Comparar documentação com o código real",
             ["file_read"], ["divergências doc-vs-código"]),
        ],
    },
    {
        "name": "Onda 2 — Implementação",
        "phase": MissionPhase.STABILISATION,
        "agents": [
            ("Backend Agent", "Corrigir e validar o backend",
             ["file_read", "code_editor", "terminal", "test_runner"], ["diagnóstico", "alterações", "testes"]),
            ("Frontend Agent", "Corrigir e validar o frontend",
             ["file_read", "code_editor", "terminal"], ["diagnóstico", "alterações"]),
            ("Integration Agent", "Validar contratos entre camadas e integrações externas",
             ["file_read", "code_editor", "terminal"], ["contratos validados"]),
        ],
    },
    {
        "name": "Onda 3 — Validação",
        "phase": MissionPhase.VERIFICATION,
        "agents": [
            ("Test Agent", "Executar a suite de testes e reportar resultados reais",
             ["terminal", "test_runner"], ["resultados de testes"]),
            ("Security Reviewer", "Rever superfícies de risco introduzidas ou existentes",
             ["file_read"], ["achados de segurança"]),
            ("Regression Agent", "Confirmar que nada que funcionava deixou de funcionar",
             ["terminal", "test_runner"], ["comparação antes/depois"]),
        ],
    },
    {
        "name": "Onda 4 — Integração",
        "phase": MissionPhase.DELIVERY,
        "agents": [
            ("Critic Agent", "Contestar as alegações de conclusão com base na evidência",
             ["file_read"], ["contestações"]),
            ("Verifier Agent", "Confirmar critérios de conclusão de cada contrato",
             ["file_read", "terminal"], ["veredicto por contrato"]),
            ("Documentation Agent", "Atualizar documentação afetada e gerar o relatório",
             ["file_read", "code_editor"], ["docs atualizados", "relatório"]),
        ],
    },
]


class MissionPlanner:
    """Builds a brief, a plan and waves from a measured snapshot.

    Everything here is derived from the snapshot, so the plan reacts to the
    project instead of being a fixed template: phases whose preconditions are
    absent are marked ``skipped`` with a reason rather than silently executed.
    """

    def __init__(self, snapshot: ProjectSnapshot) -> None:
        self.snapshot = snapshot

    # ── brief ─────────────────────────────────────────────────────────────
    def build_brief(self, objective: str, interpreted: str | None = None) -> MissionBrief:
        snap = self.snapshot
        priorities: list[str] = []

        crit = [f for f in snap.findings if f.severity in (Severity.CRITICAL, Severity.HIGH)]
        if crit:
            priorities.append(f"Corrigir falhas críticas ({len(crit)} detetadas)")
        priorities.append("Validar arquitetura e limites de módulos")
        if snap.test_files == 0:
            priorities.append("Criar cobertura de testes mínima (não existe nenhuma)")
        else:
            priorities.append(f"Executar e estabilizar os {snap.test_files} ficheiros de teste")
        priorities.append("Melhorar observabilidade da execução")
        if snap.todo_count:
            priorities.append(f"Completar funcionalidades incompletas ({snap.todo_count} marcadores)")
        priorities.append("Executar testes de regressão antes da entrega")

        assumptions: list[str] = []
        if snap.truncated:
            assumptions.append(
                "A análise foi truncada — conclusões sobre cobertura total são parciais."
            )
        if snap.git_branch is None:
            assumptions.append("Sem git: não é possível gerar instruções de reversão por commit.")
        if not snap.test_frameworks:
            assumptions.append("Nenhum runner de testes reconhecido — verificação será limitada.")

        return MissionBrief(
            objective_raw=objective,
            objective_interpreted=interpreted or self._interpret(objective),
            snapshot=snap,
            priorities=priorities,
            assumptions=assumptions,
            out_of_scope=[
                "Alterações em produção",
                "Migrações de base de dados destrutivas",
                "Instalação de dependências não declaradas nos manifestos",
            ],
        )

    @staticmethod
    def _interpret(objective: str) -> str:
        """Restate the request in terms of intent.

        Keyword-based on purpose: this runs before any model call so the user
        sees an interpretation immediately, and a wrong keyword match is
        obvious to spot and cheap to correct.
        """
        low = objective.lower()
        intents: list[str] = []
        table = [
            (("corrig", "fix", "bug", "erro", "falha"), "corrigir defeitos existentes"),
            (("test", "teste"), "validar comportamento através de testes"),
            (("refactor", "refatora", "limpar", "clean"), "reestruturar código sem alterar comportamento"),
            (("segur", "secur", "vulnerab"), "reduzir superfície de risco de segurança"),
            (("perform", "otimiz", "optimi", "lento", "rápid"), "melhorar desempenho"),
            (("document", "docs", "readme"), "atualizar documentação"),
            (("autonom", "orquestr", "agente", "agent"), "melhorar autonomia e orquestração"),
            (("observab", "log", "métric", "metric", "dashboard", "painel"), "melhorar observabilidade"),
            (("adicion", "criar", "implementa", "add", "build", "nova"), "implementar funcionalidade nova"),
            (("analis", "analys", "audit", "revi"), "produzir uma análise do estado atual"),
        ]
        for keys, label in table:
            if any(k in low for k in keys):
                intents.append(label)
        if not intents:
            return f"Executar o pedido tal como formulado: {objective.strip()[:200]}"
        # Not ``.capitalize()`` — that also lowercases the tail, which would
        # mangle any proper noun a future intent label introduces.
        joined = "; ".join(dict.fromkeys(intents))
        return joined[:1].upper() + joined[1:] + "."

    # ── plan ──────────────────────────────────────────────────────────────
    def build_plan(self, brief: MissionBrief) -> MissionPlan:
        snap = self.snapshot
        phases: list[PhasePlan] = []

        phases.append(PhasePlan(
            phase=MissionPhase.DIAGNOSIS,
            steps=[
                "Mapear arquitetura e dependências",
                "Inventariar testes existentes",
                "Identificar componentes incompletos",
            ],
            rationale="Nenhuma alteração é aplicada antes do mapa técnico estar completo.",
        ))

        crit = [f for f in snap.findings if f.severity in (Severity.CRITICAL, Severity.HIGH)]
        phases.append(PhasePlan(
            phase=MissionPhase.STABILISATION,
            steps=[
                f"Corrigir {len(crit)} problemas de severidade alta ou crítica" if crit
                else "Confirmar que não existem falhas críticas por corrigir",
                "Resolver dependências quebradas",
                "Validar configuração e variáveis de ambiente",
            ],
            rationale="Estabilizar antes de melhorar: melhorias sobre uma base instável não são mensuráveis.",
        ))

        phases.append(PhasePlan(
            phase=MissionPhase.IMPROVEMENT,
            steps=[
                "Melhorar o sistema de agentes e a sua observabilidade",
                "Otimizar caminhos com custo desproporcional",
                "Completar funcionalidades declaradas como incompletas",
            ],
            rationale="Trabalho opcional — só avança se a fase de estabilização terminar limpa.",
        ))

        can_verify = bool(snap.test_frameworks)
        phases.append(PhasePlan(
            phase=MissionPhase.VERIFICATION,
            steps=[
                "Executar testes unitários",
                "Executar testes de integração",
                "Testar fluxos principais end-to-end",
            ] if can_verify else [],
            rationale="A verificação usa comandos reais e reporta o código de saída obtido.",
            skipped=not can_verify,
            skip_reason=(
                "" if can_verify
                else "Nenhum runner de testes detetado — a verificação automática não pode ser executada."
            ),
        ))

        phases.append(PhasePlan(
            phase=MissionPhase.DELIVERY,
            steps=[
                "Rever o diff completo das alterações",
                "Atualizar documentação afetada",
                "Gerar relatório final em reports/",
            ],
            rationale="Uma missão sem relatório é indistinguível de uma missão que não aconteceu.",
        ))

        return MissionPlan(phases=phases, concurrency_limit=self._concurrency())

    def _concurrency(self) -> int:
        """Scale with project size, clamped to the 3–6 band."""
        n = self.snapshot.file_count
        if n < 200:
            return MIN_CONCURRENT_AGENTS
        if n < 2_000:
            return 4
        if n < 10_000:
            return 5
        return MAX_CONCURRENT_AGENTS

    # ── waves ─────────────────────────────────────────────────────────────
    def build_waves(self, brief: MissionBrief) -> list[Wave]:
        """Compose waves, dropping agents whose preconditions are absent.

        Spawning a Frontend Agent against a repository with no frontend is the
        exact failure mode this replaces: an agent existing because it was
        available rather than because it was needed.
        """
        snap = self.snapshot
        langs = set(snap.languages)
        has_frontend = bool(
            langs & {"TypeScript", "TypeScript React", "JavaScript", "JavaScript React"}
        )
        has_backend = bool(langs & {"Python", "Go", "Rust", "Java", "C#", "Ruby", "PHP"})
        has_tests = snap.test_files > 0
        has_docs = snap.doc_files > 0

        skip_rules: dict[str, tuple[bool, str]] = {
            "Frontend Agent": (has_frontend, "Nenhuma linguagem de frontend detetada."),
            "Backend Agent": (has_backend, "Nenhuma linguagem de backend detetada."),
            "Test Agent": (has_tests, "Não existem ficheiros de teste para executar."),
            "Regression Agent": (has_tests, "Sem testes, não há linha de base para comparar."),
            "Test Discovery Agent": (has_tests, "Não existem ficheiros de teste para inventariar."),
            "Documentation Analyzer": (has_docs, "Não existe documentação markdown para comparar."),
        }

        waves: list[Wave] = []
        previous_names: list[str] = []

        for i, blueprint in enumerate(WAVE_BLUEPRINT, start=1):
            wave = Wave(index=i, name=blueprint["name"], phase=blueprint["phase"])
            for name, objective, tools, outputs in blueprint["agents"]:
                needed, reason = skip_rules.get(name, (True, ""))
                contract = AgentContract(
                    name=name,
                    objective=objective,
                    justification=self._justify(name, needed, reason),
                    phase=blueprint["phase"],
                    inputs=self._inputs_for(name),
                    expected_outputs=list(outputs),
                    dependencies=previous_names[:] if i > 1 else [],
                    tools=list(tools),
                    completion_criteria=self._criteria_for(name),
                    state=ContractState.PROPOSED if needed else ContractState.SKIPPED,
                )
                if not needed:
                    contract.error = reason
                wave.contracts.append(contract)
            waves.append(wave)
            previous_names = [
                c.name for c in wave.contracts if c.state != ContractState.SKIPPED
            ]

        return waves

    def _justify(self, name: str, needed: bool, skip_reason: str) -> str:
        if not needed:
            return f"Não necessário nesta missão: {skip_reason}"
        snap = self.snapshot
        table = {
            "Project Intelligence Agent": (
                f"O projeto tem {snap.file_count} ficheiros e nenhum mapa técnico existe ainda."
            ),
            "Architecture Agent": (
                f"Foram detetadas {len(snap.frameworks)} frameworks — os limites entre elas precisam de ser explícitos."
                if snap.frameworks else "É preciso estabelecer os limites de módulos antes de alterar código."
            ),
            "Test Discovery Agent": f"Existem {snap.test_files} ficheiros de teste por inventariar.",
            "Documentation Analyzer": f"Existem {snap.doc_files} documentos a comparar com o código.",
            "Backend Agent": "Existe código de backend que precisa de diagnóstico e correção.",
            "Frontend Agent": "Existe código de frontend que precisa de diagnóstico e correção.",
            "Integration Agent": "Os contratos entre camadas ainda não foram validados nesta missão.",
            "Test Agent": f"Existem {snap.test_files} ficheiros de teste cujo resultado real é desconhecido.",
            "Security Reviewer": "Alterações de código exigem uma revisão de superfície de risco.",
            "Regression Agent": "É preciso provar que nada que funcionava deixou de funcionar.",
            "Critic Agent": "As alegações de conclusão precisam de ser contestadas antes de aceites.",
            "Verifier Agent": "Cada contrato declara critérios de conclusão que têm de ser confirmados.",
            "Documentation Agent": "A missão só termina com documentação atualizada e relatório escrito.",
        }
        return table.get(name, "Necessário para completar a fase.")

    @staticmethod
    def _inputs_for(name: str) -> list[str]:
        return {
            "Backend Agent": ["backend/", "logs/", "tests/"],
            "Frontend Agent": ["frontend/", "components/", "app/"],
            "Test Agent": ["tests/", "pyproject.toml", "package.json"],
            "Security Reviewer": ["backend/", "config/", ".env.example"],
            "Documentation Agent": ["docs/", "README.md"],
            "Documentation Analyzer": ["docs/", "README.md"],
        }.get(name, ["."])

    @staticmethod
    def _criteria_for(name: str) -> list[str]:
        base = ["nenhuma regressão detetada"]
        return {
            "Backend Agent": ["o backend importa sem erros", "testes relevantes passam", *base],
            "Frontend Agent": ["o build de tipos passa", "nenhum import quebrado", *base],
            "Test Agent": ["a suite foi executada", "o resultado real foi registado com o exit code"],
            "Security Reviewer": ["todas as superfícies de risco foram enumeradas"],
            "Verifier Agent": ["cada contrato tem um veredicto explícito"],
            "Critic Agent": ["cada alegação de conclusão tem evidência ou é contestada"],
            "Documentation Agent": ["relatório escrito em reports/", "documentação afetada atualizada"],
        }.get(name, ["o objetivo declarado foi cumprido", *base])


# ═══════════════════════════════════════════════════════════════════════════
# Runtime tracker
# ═══════════════════════════════════════════════════════════════════════════

class MissionTracker:
    """Owns one live mission and notifies a sink on every change.

    ``sink`` receives ``(event_name, payload)`` and is expected to be cheap and
    non-throwing — an observability layer that can break the run it observes is
    worse than no observability. Exceptions from the sink are swallowed and
    logged for exactly that reason.
    """

    def __init__(
        self,
        mission: Mission,
        sink: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.mission = mission
        self._sink = sink
        self._decision_seq = 0

    # ── emission ──────────────────────────────────────────────────────────
    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self._sink is None:
            return
        try:
            self._sink(event, payload)
        except Exception:  # pragma: no cover - observability must not break work
            logger.debug("mission sink raised on %s", event, exc_info=True)

    def _mark(self, label: str, detail: str = "") -> None:
        entry = TimelineEntry(
            at=datetime.now(UTC).isoformat(), label=label, detail=detail
        )
        self.mission.timeline.append(entry)
        self._emit("mission_timeline", entry.to_dict())

    # ── lifecycle ─────────────────────────────────────────────────────────
    def publish_brief(self, brief: MissionBrief) -> None:
        self.mission.brief = brief
        self.mission.title = brief.objective_interpreted[:120]
        self._mark("Análise inicial concluída", f"{brief.snapshot.file_count} ficheiros")
        self._emit("mission_brief", brief.to_dict())

    def publish_plan(self, plan: MissionPlan) -> None:
        self.mission.plan = plan
        self.mission.state = MissionState.PLANNED
        self._mark("Plano de execução criado", f"{len(plan.phases)} fases")
        self._emit("mission_plan", plan.to_dict())

    def publish_waves(self, waves: list[Wave]) -> None:
        self.mission.waves = waves
        proposed = sum(
            1 for w in waves for c in w.contracts if c.state == ContractState.PROPOSED
        )
        skipped = sum(
            1 for w in waves for c in w.contracts if c.state == ContractState.SKIPPED
        )
        self._mark("Agentes propostos", f"{proposed} propostos, {skipped} dispensados")
        self._emit("mission_waves", {"waves": [w.to_dict() for w in waves]})

    def start_wave(self, index: int) -> Wave | None:
        wave = self.get_wave(index)
        if wave is None:
            return None
        wave.started_at = datetime.now(UTC).isoformat()
        self.mission.state = MissionState.EXECUTING
        self.mission.phase = wave.phase
        for c in wave.contracts:
            if c.state == ContractState.PROPOSED:
                c.state = ContractState.READY
        self._mark(f"{wave.name} iniciada")
        self._emit("mission_wave_started", wave.to_dict())
        return wave

    def finish_wave(self, index: int) -> Wave | None:
        wave = self.get_wave(index)
        if wave is None:
            return None
        wave.finished_at = datetime.now(UTC).isoformat()
        self._mark(f"{wave.name} concluída", f"estado: {wave.state}")
        self._emit("mission_wave_finished", wave.to_dict())
        return wave

    def get_wave(self, index: int) -> Wave | None:
        for w in self.mission.waves:
            if w.index == index:
                return w
        return None

    def find_contract(self, agent_id_or_name: str) -> AgentContract | None:
        for c in self.mission.contracts:
            if c.id == agent_id_or_name or c.name == agent_id_or_name:
                return c
        return None

    # ── agent state ───────────────────────────────────────────────────────
    def start_agent(self, name: str) -> AgentContract | None:
        c = self.find_contract(name)
        if c is None or c.state == ContractState.SKIPPED:
            return c
        c.state = ContractState.RUNNING
        c.started_at = datetime.now(UTC).isoformat()
        self._mark(f"{name} iniciado", c.justification)
        self._emit("mission_agent", c.to_dict())
        return c

    def update_agent(
        self,
        name: str,
        *,
        activity: str | None = None,
        discovery: str | None = None,
        file_changed: str | None = None,
        command: str | None = None,
        confidence: float | None = None,
    ) -> AgentContract | None:
        c = self.find_contract(name)
        if c is None:
            return None
        if activity is not None:
            c.activity = activity
        if discovery and discovery not in c.discoveries:
            c.discoveries.append(discovery)
        if file_changed and file_changed not in c.files_changed:
            c.files_changed.append(file_changed)
        if command and command not in c.commands_run:
            c.commands_run.append(command)
        if confidence is not None:
            c.confidence = max(0.0, min(1.0, confidence))
        self._emit("mission_agent", c.to_dict())
        return c

    def finish_agent(
        self, name: str, *, success: bool = True, error: str | None = None
    ) -> AgentContract | None:
        c = self.find_contract(name)
        if c is None:
            return None
        c.state = ContractState.COMPLETED if success else ContractState.FAILED
        c.finished_at = datetime.now(UTC).isoformat()
        c.activity = ""
        if error:
            c.error = error
        self._mark(
            f"{name} terminou",
            "sucesso" if success else f"falhou: {error or 'motivo não registado'}",
        )
        self._emit("mission_agent", c.to_dict())
        return c

    # ── decisions / verification ──────────────────────────────────────────
    def record_decision(
        self,
        choice: str,
        reason: str,
        alternatives: Iterable[str] | None = None,
        outcome: str = "",
    ) -> Decision:
        self._decision_seq += 1
        d = Decision(
            number=self._decision_seq,
            choice=choice,
            reason=reason,
            alternatives=list(alternatives or []),
            outcome=outcome,
        )
        self.mission.decisions.append(d)
        self._emit("mission_decision", d.to_dict())
        return d

    def record_verification(self, result: VerificationResult) -> VerificationResult:
        self.mission.verifications.append(result)
        self.mission.state = MissionState.VERIFYING
        self._mark(
            f"Verificação: {result.command}",
            "passou" if result.passed else f"exit {result.exit_code}",
        )
        self._emit("mission_verification", result.to_dict())
        return result

    def run_verification(
        self, command: Sequence[str], *, cwd: str | None = None, timeout: int = 600
    ) -> VerificationResult:
        """Execute a command and record its *real* exit code.

        Nothing here can report success without a process having exited 0.
        """
        joined = " ".join(command)
        started = time.monotonic()
        try:
            proc = subprocess.run(
                list(command),
                cwd=cwd or self.mission.brief.snapshot.root if self.mission.brief else None,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            tail = (proc.stdout or proc.stderr or "").strip().splitlines()
            result = VerificationResult(
                command=joined,
                exit_code=proc.returncode,
                summary="\n".join(tail[-12:]),
                duration_s=round(time.monotonic() - started, 2),
            )
        except subprocess.TimeoutExpired:
            result = VerificationResult(
                command=joined,
                exit_code=None,
                summary=f"Timeout após {timeout}s",
                duration_s=round(time.monotonic() - started, 2),
                skipped_reason="timeout",
            )
        except (OSError, ValueError) as exc:
            result = VerificationResult(
                command=joined,
                exit_code=None,
                summary=str(exc),
                duration_s=round(time.monotonic() - started, 2),
                skipped_reason="not-executable",
            )
        return self.record_verification(result)

    # ── completion ────────────────────────────────────────────────────────
    def complete(
        self,
        *,
        state: MissionState = MissionState.COMPLETED,
        unresolved: Iterable[str] | None = None,
        risks: Iterable[str] | None = None,
        suggestions: Iterable[str] | None = None,
    ) -> Mission:
        self.mission.state = state
        self.mission.finished_at = datetime.now(UTC).isoformat()
        if unresolved:
            self.mission.unresolved.extend(unresolved)
        if risks:
            self.mission.risks.extend(risks)
        if suggestions:
            self.mission.suggestions.extend(suggestions)
        self._mark("Missão terminada", state.value)
        self._emit("mission_completed", self.mission.to_dict())
        return self.mission

    # ── persistence ───────────────────────────────────────────────────────
    def persist(self) -> Path | None:
        try:
            MISSIONS_DIR.mkdir(parents=True, exist_ok=True)
            path = MISSIONS_DIR / f"{self.mission.id}.json"
            path.write_text(
                json.dumps(self.mission.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return path
        except OSError:
            logger.warning("could not persist mission %s", self.mission.id, exc_info=True)
            return None


# ═══════════════════════════════════════════════════════════════════════════
# Report
# ═══════════════════════════════════════════════════════════════════════════

class MissionReport:
    """Renders a mission to the mandatory end-of-run markdown artefact."""

    def __init__(self, mission: Mission) -> None:
        self.m = mission

    def path(self) -> Path:
        started = self.m.started_at.replace(":", "").replace("-", "")
        stamp = started[:13] if len(started) >= 13 else datetime.now(UTC).strftime("%Y%m%dT%H%M")
        try:
            dt = datetime.fromisoformat(self.m.started_at.replace("Z", "+00:00"))
            stamp = dt.strftime("%Y-%m-%d-%H%M")
        except (ValueError, AttributeError):
            pass
        return REPORTS_DIR / f"nexus-run-{stamp}.md"

    def write(self) -> Path | None:
        try:
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            p = self.path()
            p.write_text(self.render(), encoding="utf-8")
            return p
        except OSError:
            logger.warning("could not write mission report", exc_info=True)
            return None

    # ── rendering ─────────────────────────────────────────────────────────
    def render(self) -> str:
        m = self.m
        b = m.brief
        snap = b.snapshot if b else None
        L: list[str] = []

        L += ["# Relatório de execução — NEXUS IDE", ""]
        L += [
            f"- **Missão:** `{m.id}`",
            f"- **Sessão:** `{m.session_id or '—'}`",
            f"- **Início:** {m.started_at}",
            f"- **Fim:** {m.finished_at or '— (em curso)'}",
            f"- **Estado:** `{m.state.value}`",
            f"- **Confiança global:** {self._confidence()}",
            "",
        ]

        L += ["## Resumo executivo", "", self._executive_summary(), ""]

        L += ["## 1. Pedido original", "", "```", (b.objective_raw if b else "—"), "```", ""]
        L += ["## 2. Interpretação do objetivo", "", (b.objective_interpreted if b else "—"), ""]

        L += ["## 3. Estado inicial do projeto", ""]
        if snap:
            L += [f"- {ln}" for ln in snap.summary_lines()]
            if snap.git_last_commit:
                L.append(f"- Último commit: `{snap.git_last_commit}`")
            L.append(f"- Duração da análise: {snap.scan_seconds}s")
        else:
            L.append("_Sem snapshot registado._")
        L.append("")

        L += ["## 4. Problemas encontrados", ""]
        findings = snap.findings if snap else []
        if findings:
            L += ["| Severidade | Problema | Evidência |", "| --- | --- | --- |"]
            for f in findings:
                L.append(f"| `{f.severity.value}` | {f.title} | `{self._cell(f.evidence)}` |")
        else:
            L.append("_Nenhum problema detetado pela análise automática._")
        L.append("")

        L += ["## 5. Plano executado", ""]
        if m.plan:
            for ph in m.plan.phases:
                L.append(f"### {ph.phase.label}" + (" — ignorada" if ph.skipped else ""))
                if ph.skipped:
                    L += [f"> {ph.skip_reason}", ""]
                else:
                    L += [f"- {s}" for s in ph.steps]
                    if ph.rationale:
                        L += ["", f"_{ph.rationale}_"]
                    L.append("")
        else:
            L += ["_Nenhum plano foi publicado._", ""]

        L += ["## 6. Agentes criados e justificação", ""]
        for w in m.waves:
            L.append(f"### {w.name} — `{w.state}`")
            L.append("")
            L += ["| Agente | Estado | Justificação | Critérios de conclusão |", "| --- | --- | --- | --- |"]
            for c in w.contracts:
                L.append(
                    f"| **{c.name}** | `{c.state.value}` | {self._cell(c.justification)} | "
                    f"{self._cell('; '.join(c.completion_criteria))} |"
                )
            L.append("")

        L += ["## 7. Alterações realizadas", ""]
        changed = m.files_changed
        if changed:
            L += [f"{len(changed)} ficheiros modificados:", ""]
            L += [f"- `{f}`" for f in changed]
        else:
            L.append("_Nenhum ficheiro foi modificado nesta missão._")
        L.append("")

        L += ["## 8. Comandos executados", ""]
        cmds = [cmd for c in m.contracts for cmd in c.commands_run]
        if cmds:
            L += ["```bash"] + cmds + ["```"]
        else:
            L.append("_Nenhum comando registado._")
        L.append("")

        L += ["## 9. Testes e resultados", ""]
        if m.verifications:
            L += ["| Comando | Exit code | Resultado | Duração |", "| --- | --- | --- | --- |"]
            for v in m.verifications:
                verdict = "✅ passou" if v.passed else (
                    f"⚠️ {v.skipped_reason}" if v.skipped_reason else "❌ falhou"
                )
                L.append(f"| `{v.command}` | `{v.exit_code}` | {verdict} | {v.duration_s}s |")
            L += ["", f"**{m.tests_passed} passaram, {m.tests_failed} falharam.**"]
        else:
            L.append(
                "_Nenhuma verificação foi executada. As alterações desta missão **não estão testadas**._"
            )
        L.append("")

        L += ["## 10. Registo de decisões", ""]
        if m.decisions:
            for d in m.decisions:
                L += [f"### Decisão #{d.number} — {d.choice}", "", f"**Razão:** {d.reason}", ""]
                if d.alternatives:
                    L += ["**Alternativas consideradas:**"] + [f"- {a}" for a in d.alternatives] + [""]
                if d.outcome:
                    L += [f"**Decisão final:** {d.outcome}", ""]
        else:
            L += ["_Nenhuma decisão registada._", ""]

        L += ["## 11. Problemas corrigidos", ""]
        fixed = [c for c in m.contracts if c.state == ContractState.COMPLETED and c.files_changed]
        if fixed:
            for c in fixed:
                L.append(f"- **{c.name}** — {c.objective} ({len(c.files_changed)} ficheiros)")
        else:
            L.append("_Nenhuma correção com alteração de ficheiros foi concluída._")
        L.append("")

        L += ["## 12. Problemas não resolvidos", ""]
        failed = [c for c in m.contracts if c.state == ContractState.FAILED]
        if m.unresolved or failed:
            L += [f"- {u}" for u in m.unresolved]
            L += [f"- **{c.name}** falhou: {c.error or 'motivo não registado'}" for c in failed]
        else:
            L.append("_Nada por resolver foi registado._")
        L.append("")

        L += ["## 13. Riscos técnicos", ""]
        L += ([f"- {r}" for r in m.risks] if m.risks else ["_Nenhum risco registado._"])
        L.append("")

        L += ["## 14. Melhorias sugeridas e dívida técnica", ""]
        L += ([f"- {s}" for s in m.suggestions] if m.suggestions
              else ["_Nenhuma sugestão registada._"])
        L.append("")

        L += ["## 15. Próximas ações por prioridade", ""]
        nxt = self._next_actions()
        L += [f"{i}. {a}" for i, a in enumerate(nxt, 1)] if nxt else ["_Nada em fila._"]
        L.append("")

        L += ["## 16. Como reverter estas alterações", ""]
        L += self._rollback_instructions()
        L.append("")

        L += ["## 17. Cronologia", ""]
        if m.timeline:
            for t in m.timeline:
                clock = t.at[11:19] if len(t.at) > 19 else t.at
                L.append(f"- `{clock}` — {t.label}" + (f" ({t.detail})" if t.detail else ""))
        else:
            L.append("_Sem eventos registados._")
        L += ["", "---", "", f"_Gerado por NEXUS Mission Control em {datetime.now(UTC).isoformat()}._"]

        return "\n".join(L) + "\n"

    # ── helpers ───────────────────────────────────────────────────────────
    @staticmethod
    def _cell(text: str) -> str:
        """Markdown tables break on pipes and newlines."""
        return (text or "—").replace("|", "\\|").replace("\n", " ")[:220]

    def _confidence(self) -> str:
        """Confidence is earned by verification, not asserted.

        A run that changed files but ran no tests is capped low on purpose —
        the alternative is a number that reads like assurance and is not.
        """
        m = self.m
        if m.state == MissionState.FAILED:
            return "baixa — a missão falhou"
        if not m.verifications:
            if m.files_changed:
                return "baixa — houve alterações mas nenhuma verificação foi executada"
            return "n/a — nenhuma alteração e nenhuma verificação"
        if m.tests_failed:
            return f"média — {m.tests_failed} verificações falharam"
        failed_agents = sum(1 for c in m.contracts if c.state == ContractState.FAILED)
        if failed_agents:
            return f"média — {failed_agents} agentes falharam apesar das verificações passarem"
        return "alta — todas as verificações executadas passaram"

    def _executive_summary(self) -> str:
        m = self.m
        cs = m.contracts
        ran = sum(1 for c in cs if c.state in (ContractState.COMPLETED, ContractState.FAILED))
        skipped = sum(1 for c in cs if c.state == ContractState.SKIPPED)
        parts = [
            f"A missão passou por {len([p for p in (m.plan.phases if m.plan else []) if not p.skipped])} "
            f"fases e {len(m.waves)} ondas de agentes.",
            f"{ran} agentes executaram, {skipped} foram dispensados por não serem necessários.",
            f"{len(m.files_changed)} ficheiros foram modificados.",
        ]
        if m.verifications:
            parts.append(f"{m.tests_passed} verificações passaram e {m.tests_failed} falharam.")
        else:
            parts.append("Nenhuma verificação automática foi executada.")
        if m.unresolved:
            parts.append(f"{len(m.unresolved)} pontos ficaram por resolver.")
        return " ".join(parts)

    def _next_actions(self) -> list[str]:
        m = self.m
        out: list[str] = []
        if m.tests_failed:
            out.append(f"Corrigir as {m.tests_failed} verificações que falharam (bloqueante).")
        for c in m.contracts:
            if c.state == ContractState.FAILED:
                out.append(f"Reexecutar **{c.name}** — falhou com: {c.error or 'motivo desconhecido'}.")
        if m.files_changed and not m.verifications:
            out.append("Executar a suite de testes — houve alterações não validadas.")
        out.extend(m.unresolved)
        out.extend(m.suggestions)
        snap = m.brief.snapshot if m.brief else None
        if snap:
            for f in snap.findings:
                if f.severity in (Severity.CRITICAL, Severity.HIGH):
                    out.append(f"Resolver: {f.title}")
        return list(dict.fromkeys(out))[:15]

    def _rollback_instructions(self) -> list[str]:
        m = self.m
        snap = m.brief.snapshot if m.brief else None
        if not m.files_changed:
            return ["_Nenhuma alteração foi feita — não há nada para reverter._"]
        if snap and snap.git_branch:
            lines = [
                "Esta missão começou em:",
                "",
                "```",
                f"branch: {snap.git_branch}",
                f"commit: {snap.git_last_commit or 'desconhecido'}",
                "```",
                "",
                "Reverter apenas os ficheiros tocados:",
                "",
                "```bash",
            ]
            lines += [f"git checkout -- {f}" for f in m.files_changed[:40]]
            lines += ["```"]
            if snap.git_dirty_files:
                lines += [
                    "",
                    f"> ⚠️ A árvore já tinha {snap.git_dirty_files} ficheiros não commitados "
                    "quando a missão começou. `git checkout --` nesses ficheiros também descarta "
                    "trabalho anterior a esta missão.",
                ]
            return lines
        return [
            "> ⚠️ Sem repositório git: não é possível gerar comandos de reversão. "
            "Ficheiros alterados nesta missão:",
            "",
            *[f"- `{f}`" for f in m.files_changed],
        ]


# ═══════════════════════════════════════════════════════════════════════════
# Facade
# ═══════════════════════════════════════════════════════════════════════════

def start_mission(
    objective: str,
    *,
    session_id: str = "",
    project_path: str = ".",
    sink: Callable[[str, dict[str, Any]], None] | None = None,
    deep_scan: bool = True,
) -> MissionTracker:
    """Analyse → brief → plan → waves. Returns a tracker with **no agent started**.

    The separation is the point: the caller decides when to start wave 1, and
    by then the user has already seen what the system understood and why each
    proposed agent exists.
    """
    mission = Mission(session_id=session_id, title=objective[:120])
    tracker = MissionTracker(mission, sink=sink)
    tracker._mark("Pedido recebido", objective[:160])

    snapshot = ProjectIntelligence(project_path).scan(deep=deep_scan)
    planner = MissionPlanner(snapshot)

    brief = planner.build_brief(objective)
    tracker.publish_brief(brief)

    plan = planner.build_plan(brief)
    tracker.publish_plan(plan)

    tracker.record_decision(
        choice=f"Executar em {len(WAVE_BLUEPRINT)} ondas com no máximo {plan.concurrency_limit} agentes concorrentes",
        reason=(
            f"O projeto tem {snapshot.file_count} ficheiros. Ondas sequenciais evitam que "
            "agentes editem os mesmos ficheiros em paralelo e permitem que cada onda leia o "
            "que a anterior descobriu."
        ),
        alternatives=[
            "Criar todos os agentes de uma vez (rápido, mas com conflitos de ficheiros)",
            "Um único agente sequencial (sem conflitos, mas lento e sem especialização)",
        ],
        outcome=f"Ondas com limite de {plan.concurrency_limit} agentes concorrentes",
    )

    tracker.publish_waves(planner.build_waves(brief))
    return tracker


__all__ = [
    "AgentContract", "ContractState", "Decision", "Finding", "Mission",
    "MissionBrief", "MissionPhase", "MissionPlan", "MissionPlanner",
    "MissionReport", "MissionState", "MissionTracker", "PhasePlan",
    "ProjectIntelligence", "ProjectSnapshot", "Severity", "TimelineEntry",
    "VerificationResult", "Wave", "start_mission",
]
