"""Self-Evolution Engine — NEXUS IDE auto-improves itself.

FASE 4 — evolution/ module:
    engine, traces, evaluator, candidate_generator,
    prompt_evolver, skill_evolver, workflow_evolver, tool_evolver,
    memory_evolver, code_evolver, model_evolver,
    arena, champion_registry, regression_guard, rollback

The engine reads structured traces from the TraceLake, analyzes failures,
generates candidate mutations, runs champion-vs-challenger arenas, and
promotes improvements that pass regression gates.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from backend.experience.lake import TraceLake, get_trace_lake

logger = logging.getLogger(__name__)

__all__ = [
    "ALLOWED_STATUS_TRANSITIONS",
    "DEFAULT_DB_PATH",
    "ChampionRegistry",
    "ComponentStatus",
    "ComponentVersion",
    "EvolutionResult",
    "Experiment",
    "ExperimentStatus",
    "FailureCategory",
    "FailurePriority",
    "bump_semantic_version",
    "parse_semantic_version",
    "semantic_bump_for_outcome",
    "validate_transition",
]

DEFAULT_DB_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "evolution.db"
)


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_json(value: str | None) -> dict[str, Any]:
    """Safely parse a JSON string, returning {} on failure."""
    if not value:
        return {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}

# ── Enums ────────────────────────────────────────────────────────────────────

class ComponentStatus(StrEnum):
    """Lifecycle status for versioned components."""

    CHAMPION = "champion"
    CHALLENGER = "challenger"
    EXPERIMENTAL = "experimental"
    ARCHIVED = "archived"
    RETIRED = "retired"
    REJECTED = "rejected"


class ExperimentStatus(StrEnum):
    """Status of a champion-vs-challenger arena experiment."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    REGRESSION = "regression"


class FailureCategory(StrEnum):
    """Classification of task failures (FASE 7)."""

    BAD_PLANNING = "bad_planning"
    INCORRECT_CODE = "incorrect_code"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    TOO_MANY_CALLS = "too_many_calls"
    TOOL_SELECTION_ERROR = "tool_selection_error"
    MEMORY_RETRIEVAL_ERROR = "memory_retrieval_error"
    HALLUCINATED_API = "hallucinated_api"
    TEST_MISUNDERSTANDING = "test_misunderstanding"
    DEPENDENCY_PROBLEM = "dependency_problem"
    TIMEOUT = "timeout"
    INFINITE_LOOP = "infinite_loop"
    REGRESSION = "regression"
    INTERNAL_PLANNING = "internal_planning"
    MODEL_LIMITATION = "model_limitation"
    UNKNOWN = "unknown"


# ── Status transitions ───────────────────────────────────────────────────────

ALLOWED_STATUS_TRANSITIONS: dict[ComponentStatus, frozenset[ComponentStatus]] = {
    ComponentStatus.EXPERIMENTAL: frozenset({
        ComponentStatus.CHALLENGER,
        ComponentStatus.CHAMPION,
        ComponentStatus.ARCHIVED,
        ComponentStatus.REJECTED,
    }),
    ComponentStatus.CHALLENGER: frozenset({
        ComponentStatus.CHAMPION,
        ComponentStatus.ARCHIVED,
        ComponentStatus.REJECTED,
    }),
    # A champion may be re-affirmed (idempotent promote), demoted, or retired.
    ComponentStatus.CHAMPION: frozenset({
        ComponentStatus.CHAMPION,
        ComponentStatus.ARCHIVED,
        ComponentStatus.RETIRED,
    }),
    # Demoted champions can be restored (e.g. rollback), but not rejected.
    ComponentStatus.ARCHIVED: frozenset({ComponentStatus.CHAMPION}),
    # Terminal states: re-entry requires a fresh challenger derived from the
    # retired/rejected lineage that wins a new experiment ("re-promotion").
    ComponentStatus.RETIRED: frozenset(),
    ComponentStatus.REJECTED: frozenset(),
}


def validate_transition(current: ComponentStatus | str, target: ComponentStatus | str) -> None:
    """Validate a lifecycle transition, raising ValueError on illegal moves."""
    cur = ComponentStatus(current)
    tgt = ComponentStatus(target)
    if tgt not in ALLOWED_STATUS_TRANSITIONS[cur]:
        allowed = ", ".join(sorted(s.value for s in ALLOWED_STATUS_TRANSITIONS[cur]))
        raise ValueError(
            f"Illegal status transition {cur.value!r} -> {tgt.value!r} "
            f"(allowed: {allowed or 'none'})"
        )


# ── Semantic versioning helpers ──────────────────────────────────────────────

def parse_semantic_version(version: str) -> tuple[int, int, int]:
    """Parse 'X.Y.Z' or 'vX.Y.Z' into (major, minor, patch).

    Raises ValueError if the string is not a semantic version.
    """
    text = version.strip()
    prefix = "v" if text.startswith(("v", "V")) else ""
    parts = text[len(prefix):].split(".")
    if len(parts) != 3:
        raise ValueError(f"Not a semantic version: {version!r}")
    try:
        major, minor, patch = (int(p) for p in parts)
    except ValueError as exc:
        raise ValueError(f"Not a semantic version: {version!r}") from exc
    return major, minor, patch


def bump_semantic_version(version: str, part: str) -> str:
    """Bump the major/minor/patch component of a semantic version string.

    Preserves a leading 'v' prefix. Lower components reset to zero
    ('v1.2.3' + minor -> 'v1.3.0'). Raises ValueError for non-semantic
    versions or unknown parts.
    """
    if part not in ("major", "minor", "patch"):
        raise ValueError(f"Unknown bump part {part!r} (expected major|minor|patch)")
    major, minor, patch = parse_semantic_version(version)
    prefix = "v" if version.startswith(("v", "V")) else ""
    if part == "major":
        return f"{prefix}{major + 1}.0.0"
    if part == "minor":
        return f"{prefix}{major}.{minor + 1}.0"
    return f"{prefix}{major}.{minor}.{patch + 1}"


def semantic_bump_for_outcome(experiment: Experiment) -> str:
    """Map a completed experiment outcome to a semantic bump level.

    Rules:
        - challenger won / promoted -> "minor" (adopted behavior change);
        - regression detected       -> "patch" (hotfix over last good version);
        - champion kept or tie      -> "patch".

    Raises ValueError if the experiment is still pending/running.
    """
    if experiment.status in (ExperimentStatus.PENDING, ExperimentStatus.RUNNING):
        raise ValueError(f"Experiment {experiment.experiment_id} is not complete")
    if experiment.regression_detected or experiment.status == ExperimentStatus.REGRESSION:
        return "patch"
    if experiment.winner == "challenger":
        return "minor"
    return "patch"


# ── Core data models ─────────────────────────────────────────────────────────

@dataclass
class ComponentVersion:
    """A single version of an evolvable component."""

    component_kind: str
    version: str
    status: ComponentStatus = ComponentStatus.EXPERIMENTAL
    config: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utcnow_iso)
    promoted_at: str | None = None
    parent_version: str | None = None
    changelog: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.component_kind}:{self.version}"


@dataclass
class Experiment:
    """A champion-vs-challenger arena experiment."""

    experiment_id: str
    component_kind: str
    champion_version: str
    challenger_version: str
    status: ExperimentStatus = ExperimentStatus.PENDING
    started_at: str = field(default_factory=_utcnow_iso)
    completed_at: str | None = None
    winner: str | None = None  # "champion", "challenger", or "tie"
    regression_detected: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)
    log: str = ""

    @property
    def is_complete(self) -> bool:
        return self.status in (
            ExperimentStatus.COMPLETED,
            ExperimentStatus.PROMOTED,
            ExperimentStatus.REJECTED,
            ExperimentStatus.REGRESSION,
        )


@dataclass
class FailurePriority:
    """Scored failure for prioritization (FASE 7)."""

    category: FailureCategory
    frequency: float  # 0-1: fraction of tasks with this failure
    impact: float      # 0-1: how much failures of this type cost
    repairability: float  # 0-1: how easy to fix
    priority_score: float  # frequency × impact × repairability
    affected_tasks: list[str] = field(default_factory=list)
    evidence: str = ""


@dataclass
class EvolutionResult:
    """Result of a single evolution cycle."""

    cycle: int
    experiment_id: str | None
    candidates_generated: int
    experiments_run: int
    promoted: list[str]  # component ids promoted
    rejected: list[str]  # component ids rejected
    regressions: int
    success_rate_before: float
    success_rate_after: float
    delta: float
    explanation: str = ""
    timestamp: str = field(default_factory=_utcnow_iso)


# ── Database ─────────────────────────────────────────────────────────────────

def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DEFAULT_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS evolution_versions (
            id              TEXT PRIMARY KEY,
            component_kind  TEXT NOT NULL,
            version         TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'experimental',
            config_json     TEXT NOT NULL DEFAULT '{}',
            created_at      TEXT NOT NULL,
            promoted_at     TEXT,
            parent_version  TEXT,
            changelog       TEXT,
            metrics_json    TEXT NOT NULL DEFAULT '{}',
            UNIQUE(component_kind, version)
        );

        CREATE TABLE IF NOT EXISTS evolution_experiments (
            id              TEXT PRIMARY KEY,
            component_kind  TEXT NOT NULL,
            champion_version TEXT NOT NULL,
            challenger_version TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            started_at      TEXT NOT NULL,
            completed_at    TEXT,
            winner          TEXT,
            regression_detected INTEGER DEFAULT 0,
            metrics_json    TEXT NOT NULL DEFAULT '{}',
            log             TEXT
        );

        CREATE TABLE IF NOT EXISTS evolution_log (
            id              TEXT PRIMARY KEY,
            experiment_id   TEXT,
            event_type      TEXT NOT NULL,
            component_kind  TEXT,
            version         TEXT,
            message         TEXT,
            metrics_json    TEXT,
            timestamp       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS failure_classification (
            id              TEXT PRIMARY KEY,
            category        TEXT NOT NULL,
            frequency       REAL,
            impact          REAL,
            repairability   REAL,
            priority_score  REAL,
            affected_tasks  TEXT,
            evidence        TEXT,
            last_seen       TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_ev_versions_kind ON evolution_versions(component_kind);
        CREATE INDEX IF NOT EXISTS idx_ev_versions_status ON evolution_versions(status);
        CREATE INDEX IF NOT EXISTS idx_ev_experiments_status ON evolution_experiments(status);
        CREATE INDEX IF NOT EXISTS idx_ev_experiments_comp ON evolution_experiments(component_kind);
        CREATE INDEX IF NOT EXISTS idx_ev_log_exp ON evolution_log(experiment_id);
        CREATE INDEX IF NOT EXISTS idx_ev_log_ts ON evolution_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_fail_cat ON failure_classification(category);
        """
    )
    conn.commit()


# ── Champion Registry ────────────────────────────────────────────────────────

class ChampionRegistry:
    """Manages versioned components with Champion/Challenger/Experimental lifecycle.

    FASE 6 — Every evolvable component has versions. Only one version is the
    Champion at any time; others are Challengers, Experimental, Archived, or
    Rejected.

    Mutations are serialized through an internal reentrant lock, so a single
    registry instance can be shared across threads safely.
    """

    def __init__(self, db_path: str | Path | None = None, lake: TraceLake | None = None) -> None:
        self.db_path = Path(db_path) if db_path else Path(DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lake = lake or get_trace_lake()
        self._lock = threading.RLock()
        self._init()

    def _init(self) -> None:
        with self._conn() as conn:
            _init_db(conn)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = _connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def register_champion(self, component_kind: str, version: str, config: dict[str, Any] | None = None,
                          changelog: str = "", parent_version: str | None = None) -> ComponentVersion:
        """Register the initial champion for a component kind.

        If a champion already exists, it is demoted to 'archived'.
        """
        now = _utcnow_iso()
        with self._lock, self._conn() as conn:
            # Demote existing champion
            conn.execute(
                "UPDATE evolution_versions SET status = 'archived' "
                "WHERE component_kind = ? AND status = 'champion'",
                (component_kind,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO evolution_versions "
                "(id, component_kind, version, status, config_json, created_at, promoted_at, "
                "parent_version, changelog, metrics_json) "
                "VALUES (?, ?, ?, 'champion', ?, ?, ?, ?, ?, '{}')",
                (
                    f"{component_kind}:{version}",
                    component_kind, version,
                    json.dumps(config or {}),
                    now, now,
                    parent_version,
                    changelog,
                ),
            )
        return ComponentVersion(
            component_kind=component_kind, version=version,
            status=ComponentStatus.CHAMPION, config=config or {},
            created_at=now, promoted_at=now,
            parent_version=parent_version, changelog=changelog,
        )

    def create_challenger(self, component_kind: str, version: str, config: dict[str, Any],
                          parent_version: str, changelog: str = "") -> ComponentVersion:
        """Register a new challenger version derived from a parent."""
        now = _utcnow_iso()
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO evolution_versions "
                "(id, component_kind, version, status, config_json, created_at, promoted_at, "
                "parent_version, changelog, metrics_json) "
                "VALUES (?, ?, ?, 'challenger', ?, ?, NULL, ?, ?, '{}')",
                (
                    f"{component_kind}:{version}",
                    component_kind, version,
                    json.dumps(config),
                    now,
                    parent_version,
                    changelog,
                ),
            )
        return ComponentVersion(
            component_kind=component_kind, version=version,
            status=ComponentStatus.CHALLENGER, config=config,
            created_at=now, parent_version=parent_version, changelog=changelog,
        )

    def promote(self, component_kind: str, version: str, changelog: str = "") -> ComponentVersion:
        """Promote a version to champion (demoting the current champion).

        The target's current status must allow a transition to 'champion'
        (challenger/experimental/archived). Retired or rejected versions must
        be re-promoted through a fresh challenger; unknown versions and
        illegal moves raise ValueError.
        """
        now = _utcnow_iso()
        with self._lock, self._conn() as conn:
            target = conn.execute(
                "SELECT status FROM evolution_versions WHERE component_kind = ? AND version = ?",
                (component_kind, version),
            ).fetchone()
            if target is None:
                raise ValueError(f"Unknown version {component_kind}:{version}")
            validate_transition(ComponentStatus(target["status"]), ComponentStatus.CHAMPION)
            # Demote current champion
            conn.execute(
                "UPDATE evolution_versions SET status = 'archived' "
                "WHERE component_kind = ? AND status = 'champion'",
                (component_kind,),
            )
            # Promote challenger
            conn.execute(
                "UPDATE evolution_versions SET status = 'champion', promoted_at = ? "
                "WHERE component_kind = ? AND version = ?",
                (now, component_kind, version),
            )
            if changelog:
                conn.execute(
                    "UPDATE evolution_versions SET changelog = changelog || ';' || ? "
                    "WHERE component_kind = ? AND version = ?",
                    (changelog, component_kind, version),
                )
        return self.get_version(component_kind, version)

    def reject(self, component_kind: str, version: str, reason: str = "") -> ComponentVersion:
        """Reject a challenger, validating the current status first."""
        with self._lock, self._conn() as conn:
            target = conn.execute(
                "SELECT status FROM evolution_versions WHERE component_kind = ? AND version = ?",
                (component_kind, version),
            ).fetchone()
            if target is None:
                raise ValueError(f"Unknown version {component_kind}:{version}")
            validate_transition(ComponentStatus(target["status"]), ComponentStatus.REJECTED)
            conn.execute(
                "UPDATE evolution_versions SET status = 'rejected', changelog = changelog || ';' || ? "
                "WHERE component_kind = ? AND version = ?",
                (reason, component_kind, version),
            )
        return self.get_version(component_kind, version)

    def archive(self, component_kind: str, version: str) -> ComponentVersion:
        """Archive a version (demoted champion or old challenger), validating first."""
        with self._lock, self._conn() as conn:
            target = conn.execute(
                "SELECT status FROM evolution_versions WHERE component_kind = ? AND version = ?",
                (component_kind, version),
            ).fetchone()
            if target is None:
                raise ValueError(f"Unknown version {component_kind}:{version}")
            validate_transition(ComponentStatus(target["status"]), ComponentStatus.ARCHIVED)
            conn.execute(
                "UPDATE evolution_versions SET status = 'archived' "
                "WHERE component_kind = ? AND version = ?",
                (component_kind, version),
            )
        return self.get_version(component_kind, version)

    def set_status(self, component_kind: str, version: str,
                   new_status: ComponentStatus | str) -> ComponentVersion:
        """Apply a validated lifecycle transition to a version.

        Generic escape hatch over ALLOWED_STATUS_TRANSITIONS. Raises
        ValueError for unknown versions or illegal transitions.
        """
        tgt = ComponentStatus(new_status)
        now = _utcnow_iso()
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT status FROM evolution_versions WHERE component_kind = ? AND version = ?",
                (component_kind, version),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown version {component_kind}:{version}")
            cur = ComponentStatus(row["status"])
            validate_transition(cur, tgt)
            if tgt is ComponentStatus.CHAMPION and cur is not ComponentStatus.CHAMPION:
                conn.execute(
                    "UPDATE evolution_versions SET status = 'archived' "
                    "WHERE component_kind = ? AND status = 'champion'",
                    (component_kind,),
                )
            if tgt is ComponentStatus.CHAMPION:
                conn.execute(
                    "UPDATE evolution_versions SET status = ?, promoted_at = COALESCE(promoted_at, ?) "
                    "WHERE component_kind = ? AND version = ?",
                    (tgt.value, now, component_kind, version),
                )
            else:
                conn.execute(
                    "UPDATE evolution_versions SET status = ? "
                    "WHERE component_kind = ? AND version = ?",
                    (tgt.value, component_kind, version),
                )
        return self.get_version(component_kind, version)

    def retire(self, component_kind: str, version: str, reason: str = "") -> ComponentVersion:
        """Retire a champion (terminal state).

        A retired version can only re-enter the lifecycle via re-promotion:
        derive a fresh challenger from it (create_challenger with
        parent_version=retired version) and promote that challenger.
        """
        with self._lock, self._conn() as conn:
            target = conn.execute(
                "SELECT status FROM evolution_versions WHERE component_kind = ? AND version = ?",
                (component_kind, version),
            ).fetchone()
            if target is None:
                raise ValueError(f"Unknown version {component_kind}:{version}")
            validate_transition(ComponentStatus(target["status"]), ComponentStatus.RETIRED)
            conn.execute(
                "UPDATE evolution_versions SET status = 'retired', changelog = changelog || ';' || ? "
                "WHERE component_kind = ? AND version = ?",
                (reason, component_kind, version),
            )
        return self.get_version(component_kind, version)

    def get_champion(self, component_kind: str) -> ComponentVersion | None:
        """Return the current champion for a component kind."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM evolution_versions WHERE component_kind = ? AND status = 'champion'",
                (component_kind,),
            ).fetchone()
        return self._row_to_version(row) if row else None

    def get_version(self, component_kind: str, version: str) -> ComponentVersion | None:
        """Get a specific version."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM evolution_versions WHERE component_kind = ? AND version = ?",
                (component_kind, version),
            ).fetchone()
        return self._row_to_version(row) if row else None

    def list_versions(self, component_kind: str, status: str | None = None) -> list[ComponentVersion]:
        """List all versions for a component kind, optionally filtered by status."""
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM evolution_versions WHERE component_kind = ? AND status = ? ORDER BY created_at DESC",
                    (component_kind, status),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM evolution_versions WHERE component_kind = ? ORDER BY created_at DESC",
                    (component_kind,),
                ).fetchall()
        return [self._row_to_version(r) for r in rows]

    def history(self, component_kind: str) -> list[ComponentVersion]:
        """List all versions for a component kind in chronological order.

        Unlike :meth:`list_versions` (which is newest-first), this returns
        the full lifecycle history oldest → newest, matching insertion order.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM evolution_versions WHERE component_kind = ? "
                "ORDER BY created_at ASC, rowid ASC",
                (component_kind,),
            ).fetchall()
        return [self._row_to_version(r) for r in rows]

    def list_all_kinds(self) -> list[str]:
        """Return all component kinds that have registered versions."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT component_kind FROM evolution_versions"
            ).fetchall()
        return [r["component_kind"] for r in rows]

    def history(self, component_kind: str) -> list[ComponentVersion]:
        """Chronological (oldest-first) list of all versions for a component kind."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM evolution_versions WHERE component_kind = ? "
                "ORDER BY created_at ASC, rowid ASC",
                (component_kind,),
            ).fetchall()
        return [self._row_to_version(r) for r in rows]

    def next_version(self, component_kind: str) -> str:
        """Generate the next version string (v1, v2, ...) for a component kind."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(CAST(SUBSTR(version, 2) AS INTEGER)) AS max_v FROM evolution_versions WHERE component_kind = ?",
                (component_kind,),
            ).fetchone()
        max_v = row["max_v"] if row and row["max_v"] else 0
        return f"v{max_v + 1}"

    def next_semantic_version(self, component_kind: str, part: str = "minor") -> str:
        """Next semantic version for a component, bumped from the current champion.

        Falls back to '0.0.0' when the champion has no semantic version.
        """
        champ = self.get_champion(component_kind)
        base = champ.version if champ else ""
        try:
            parse_semantic_version(base)
        except ValueError:
            base = "0.0.0"
        return bump_semantic_version(base, part)

    def update_metrics(self, component_kind: str, version: str, metrics: dict[str, Any]) -> None:
        """Update performance metrics for a version."""
        with self._lock, self._conn() as conn:
            # Merge with existing metrics
            row = conn.execute(
                "SELECT metrics_json FROM evolution_versions WHERE component_kind = ? AND version = ?",
                (component_kind, version),
            ).fetchone()
            if row:
                existing = {}
                try:
                    existing = json.loads(row["metrics_json"]) if row["metrics_json"] else {}
                except (json.JSONDecodeError, TypeError):
                    existing = {}
                existing.update(metrics)
                conn.execute(
                    "UPDATE evolution_versions SET metrics_json = ? WHERE component_kind = ? AND version = ?",
                    (json.dumps(existing), component_kind, version),
                )

    def export_versions(self, component_kind: str | None = None) -> str:
        """Export versions (all kinds, or one) as a JSON backup string."""
        query = "SELECT * FROM evolution_versions"
        params: tuple[str, ...] = ()
        if component_kind is not None:
            query += " WHERE component_kind = ?"
            params = (component_kind,)
        with self._conn() as conn:
            rows = conn.execute(query + " ORDER BY created_at ASC, rowid ASC", params).fetchall()
        payload = [
            {
                "component_kind": row["component_kind"],
                "version": row["version"],
                "status": row["status"],
                "config": _safe_json(row["config_json"]),
                "created_at": row["created_at"],
                "promoted_at": row["promoted_at"],
                "parent_version": row["parent_version"],
                "changelog": row["changelog"] or "",
                "metrics": _safe_json(row["metrics_json"]),
            }
            for row in rows
        ]
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def import_versions(self, data: str | bytes | list[dict[str, Any]]) -> int:
        """Import versions from export_versions() output; returns the count imported.

        Accepts a JSON string/bytes or an already-parsed list of version dicts.
        Uses INSERT OR REPLACE so re-importing a backup is idempotent. Raises
        ValueError on unknown status values.
        """
        items: list[dict[str, Any]] = (
            json.loads(data) if isinstance(data, (str, bytes)) else data
        )
        count = 0
        with self._lock, self._conn() as conn:
            for item in items:
                status = ComponentStatus(item["status"]).value
                conn.execute(
                    "INSERT OR REPLACE INTO evolution_versions "
                    "(id, component_kind, version, status, config_json, created_at, promoted_at, "
                    "parent_version, changelog, metrics_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"{item['component_kind']}:{item['version']}",
                        item["component_kind"],
                        item["version"],
                        status,
                        json.dumps(item.get("config", {})),
                        item["created_at"],
                        item.get("promoted_at"),
                        item.get("parent_version"),
                        item.get("changelog", ""),
                        json.dumps(item.get("metrics", {})),
                    ),
                )
                count += 1
        return count

    def get_version_tree(self) -> dict[str, Any]:
        """Return a tree of all component versions grouped by kind.

        Used for the dashboard evolution tree visualization.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM evolution_versions ORDER BY component_kind, created_at"
            ).fetchall()

        tree: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            kind = row["component_kind"]
            tree.setdefault(kind, []).append({
                "version": row["version"],
                "status": row["status"],
                "parent_version": row["parent_version"],
                "created_at": row["created_at"],
                "promoted_at": row["promoted_at"],
                "changelog": row["changelog"],
                "metrics": _safe_json(row["metrics_json"]),
            })
        return tree

    def _row_to_version(self, row: sqlite3.Row) -> ComponentVersion:
        config = _safe_json(row["config_json"])
        metrics = _safe_json(row["metrics_json"])
        return ComponentVersion(
            component_kind=row["component_kind"],
            version=row["version"],
            status=ComponentStatus(row["status"]),
            config=config,
            created_at=row["created_at"],
            promoted_at=row["promoted_at"],
            parent_version=row["parent_version"],
            changelog=row["changelog"] or "",
            metrics=metrics,
        )
