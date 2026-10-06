"""Trace Lake — persistent, searchable storage for ExperienceBus traces.

FASE 3 — Armazenamento persistente e pesquisável para:
  tasks, prompts, respostas, decisões, tool calls, terminal output, errors,
  stack traces, tests, resultados, rewards, user feedback, memory usage,
  retrieval, latency, token usage, model/agent/prompt/workflow/skill version.

Support queries like:
  * "Why do React tasks fail?"  → filter task_type + result.success
  * "Which tool produces most errors?"  → aggregate trajectory entries
  * "Which planner version performs best?"  → group by component_version
  * "Which model performs best per domain?"  → group by model + category
  * "Which prompts increased task success?"  → compare experiment_id groups
  * "Where are tokens being wasted?"  → group by task_type, order by tokens
  * "Which skill causes regressions?"  → group by version, filter regressions
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.experience.models import (
    ComponentKind,
    ExperienceTrace,
    TaskCategory,
)

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "trace_lake.db"
)


def _connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with WAL + row factory."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


# ── Schema ───────────────────────────────────────────────────────────────────

SCHEMA_VERSION = 2

_SCHEMA_SQL = """
-- Main traces table: one row per task execution
CREATE TABLE IF NOT EXISTS traces (
    task_id            TEXT PRIMARY KEY,
    timestamp          TEXT NOT NULL,
    prompt             TEXT NOT NULL,
    task_type          TEXT NOT NULL,
    difficulty         REAL DEFAULT 0.5,
    category           TEXT,
    session_id         TEXT,

    model_name         TEXT,
    model_version      TEXT,
    temperature        REAL DEFAULT 0,
    context_size       INTEGER DEFAULT 0,
    tier               TEXT,

    agents_json        TEXT,
    trajectory_json    TEXT,
    memory_retrieved_json TEXT,
    files_modified_json TEXT,
    commands_executed_json TEXT,
    tests_executed_json TEXT,

    result_success     INTEGER,
    result_score       REAL DEFAULT 0,
    result_error       TEXT,
    result_output      TEXT,

    latency_ms         INTEGER DEFAULT 0,
    tokens_input       INTEGER DEFAULT 0,
    tokens_output      INTEGER DEFAULT 0,
    tool_calls         INTEGER DEFAULT 0,
    retries            INTEGER DEFAULT 0,
    cost_usd           REAL DEFAULT 0,
    eval_correctness   REAL DEFAULT 0,
    eval_efficiency    REAL DEFAULT 0,
    eval_quality       REAL DEFAULT 0,
    eval_regression    INTEGER DEFAULT 0,

    parent_trace_id    TEXT,
    experiment_id      TEXT,
    component_kind     TEXT,
    component_version  TEXT,
    workflow_version   TEXT,
    version_tags_json  TEXT,
    tags_json          TEXT,
    content_hash       TEXT,
    raw_json           TEXT
);

-- FTS5 full-text index on prompt for semantic-style text search
CREATE VIRTUAL TABLE IF NOT EXISTS traces_fts USING fts5(
    prompt, content='traces', content_rowid='rowid'
);

-- Trajectory entries for granular tool/error analysis
CREATE TABLE IF NOT EXISTS trajectory_entries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    agent        TEXT,
    action       TEXT,
    tool         TEXT,
    observation  TEXT,
    duration_ms  INTEGER DEFAULT 0,
    tokens_used  INTEGER DEFAULT 0,
    success      INTEGER DEFAULT 1,
    error        TEXT,
    FOREIGN KEY (task_id) REFERENCES traces(task_id) ON DELETE CASCADE
);

-- Failure classification index (one row per failed task)
CREATE TABLE IF NOT EXISTS failure_categories (
    task_id          TEXT PRIMARY KEY,
    failure_category TEXT NOT NULL,
    classified_at    TEXT NOT NULL
);

-- Cold archive: TTL-purged traces keep the exact live schema plus the
-- archive stamp columns, so archived records remain fully queryable.
CREATE TABLE IF NOT EXISTS traces_archive (
    task_id            TEXT PRIMARY KEY,
    timestamp          TEXT NOT NULL,
    prompt             TEXT NOT NULL,
    task_type          TEXT NOT NULL,
    difficulty         REAL DEFAULT 0.5,
    category           TEXT,
    session_id         TEXT,

    model_name         TEXT,
    model_version      TEXT,
    temperature        REAL DEFAULT 0,
    context_size       INTEGER DEFAULT 0,
    tier               TEXT,

    agents_json        TEXT,
    trajectory_json    TEXT,
    memory_retrieved_json TEXT,
    files_modified_json TEXT,
    commands_executed_json TEXT,
    tests_executed_json TEXT,

    result_success     INTEGER,
    result_score       REAL DEFAULT 0,
    result_error       TEXT,
    result_output      TEXT,

    latency_ms         INTEGER DEFAULT 0,
    tokens_input       INTEGER DEFAULT 0,
    tokens_output      INTEGER DEFAULT 0,
    tool_calls         INTEGER DEFAULT 0,
    retries            INTEGER DEFAULT 0,
    cost_usd           REAL DEFAULT 0,
    eval_correctness   REAL DEFAULT 0,
    eval_efficiency    REAL DEFAULT 0,
    eval_quality       REAL DEFAULT 0,
    eval_regression    INTEGER DEFAULT 0,

    parent_trace_id    TEXT,
    experiment_id      TEXT,
    component_kind     TEXT,
    component_version  TEXT,
    workflow_version   TEXT,
    version_tags_json  TEXT,
    tags_json          TEXT,
    content_hash       TEXT,
    raw_json           TEXT,

    archived_at        TEXT NOT NULL,
    ttl_days           INTEGER
);

CREATE TABLE IF NOT EXISTS trajectory_entries_archive (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    agent        TEXT,
    action       TEXT,
    tool         TEXT,
    observation  TEXT,
    duration_ms  INTEGER DEFAULT 0,
    tokens_used  INTEGER DEFAULT 0,
    success      INTEGER DEFAULT 1,
    error        TEXT,

    archived_at  TEXT NOT NULL,
    ttl_days     INTEGER
);

CREATE TABLE IF NOT EXISTS failure_categories_archive (
    task_id          TEXT PRIMARY KEY,
    failure_category TEXT NOT NULL,
    classified_at    TEXT NOT NULL,

    archived_at      TEXT NOT NULL,
    ttl_days         INTEGER
);

CREATE INDEX IF NOT EXISTS idx_traces_task_type ON traces(task_type);
CREATE INDEX IF NOT EXISTS idx_traces_success    ON traces(result_success);
CREATE INDEX IF NOT EXISTS idx_traces_success_ts ON traces(result_success, timestamp);
CREATE INDEX IF NOT EXISTS idx_traces_timestamp  ON traces(timestamp);
CREATE INDEX IF NOT EXISTS idx_traces_category   ON traces(category);
CREATE INDEX IF NOT EXISTS idx_traces_model      ON traces(model_name);
CREATE INDEX IF NOT EXISTS idx_traces_exp        ON traces(experiment_id);
CREATE INDEX IF NOT EXISTS idx_traces_component  ON traces(component_kind, component_version);
CREATE INDEX IF NOT EXISTS idx_traces_tags       ON traces(tags_json);
CREATE INDEX IF NOT EXISTS idx_traj_task         ON trajectory_entries(task_id);
CREATE INDEX IF NOT EXISTS idx_traj_tool         ON trajectory_entries(tool);
CREATE INDEX IF NOT EXISTS idx_traj_success      ON trajectory_entries(success);
CREATE INDEX IF NOT EXISTS idx_fc_cat            ON failure_categories(failure_category);
CREATE INDEX IF NOT EXISTS idx_fc_task           ON failure_categories(task_id);
CREATE INDEX IF NOT EXISTS idx_arch_traces_ts    ON traces_archive(timestamp);
CREATE INDEX IF NOT EXISTS idx_arch_traj_task    ON trajectory_entries_archive(task_id);

-- Metadata table
CREATE TABLE IF NOT EXISTS trace_lake_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# ── Failure classification ───────────────────────────────────────────────────

_FAILURE_CLASSIFIERS: tuple[tuple[str, str], ...] = (
    # (category, regex) — first match wins; order matters.
    ("timeout", r"\btime(?:d)?[- _]?out\b|\bdeadline\b|\btimed out\b"),
    (
        "dependency_problem",
        r"no module named|modulenotfounderror|importerror|import error|"
        r"missing dependency|version conflict|incompatible",
    ),
    (
        "incorrect_code",
        r"syntaxerror|typeerror|attributeerror|nameerror|valueerror|"
        r"indexerror|keyerror|indentationerror|zerodivisionerror|"
        r"assertionerror|runtime error|exception|traceback|"
        r"undefined variable|undefined name|invalid syntax",
    ),
)


def classify_failure_text(error: str | None) -> str:
    """Classify a raw failure message into a coarse category string.

    Categories used by the lake's ``failure_categories`` index:
    ``incorrect_code``, ``dependency_problem``, ``timeout`` and ``unknown``.
    """
    if not error:
        return "unknown"
    text = error.lower()
    for category, pattern in _FAILURE_CLASSIFIERS:
        if re.search(pattern, text):
            return category
    return "unknown"


class TraceLake:
    """Persistent, searchable store for :class:`ExperienceTrace` objects.

    Uses SQLite with FTS5 for full-text search and structured columns
    for efficient filtering and aggregation.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else Path(DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ── Internal ──

    @property
    def _conn(self) -> sqlite3.Connection:
        """Each call gets a fresh connection (SQLite is not thread-safe by default)."""
        return _connect(self.db_path)

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """Context-managed transaction."""
        conn = self._conn
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        """Create tables if they don't exist; migrate legacy DBs."""
        with self._tx() as conn:
            self._migrate_legacy_schema(conn)
            conn.executescript(_SCHEMA_SQL)
            # content-hash index lives outside _SCHEMA_SQL so the legacy
            # schema (which drops the column via regex in tests) stays valid.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_traces_content_hash ON traces(content_hash)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO trace_lake_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    @staticmethod
    def _migrate_legacy_schema(conn: sqlite3.Connection) -> None:
        """Add + backfill ``content_hash`` when opening a pre-dedup database."""
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='traces'"
        ).fetchone()
        if table is None:
            return
        columns = {row[1] for row in conn.execute("PRAGMA table_info(traces)")}
        if "content_hash" in columns:
            return
        conn.execute("ALTER TABLE traces ADD COLUMN content_hash TEXT")
        rows = conn.execute(
            "SELECT task_id, raw_json FROM traces WHERE raw_json IS NOT NULL"
        ).fetchall()
        backfilled = 0
        for row in rows:
            try:
                trace = ExperienceTrace.model_validate_json(row["raw_json"])
            except Exception:  # noqa: BLE001 - corrupt legacy rows are skipped
                continue
            conn.execute(
                "UPDATE traces SET content_hash = ? WHERE task_id = ?",
                (trace.compute_content_hash(), row["task_id"]),
            )
            backfilled += 1
        logger.info("Legacy trace lake migrated; %d hashes backfilled", backfilled)

    # ── Storage ──

    def store_trace(self, trace: ExperienceTrace, *, dedupe: bool = True) -> str:
        """Persist an :class:`ExperienceTrace` to the lake.

        With ``dedupe`` enabled (default) an identical replay of the same
        task (same content hash) is skipped instead of rewritten.

        Returns the ``task_id`` of the stored trace.
        """
        result = self.store_trace_with_stats(trace, dedupe=dedupe)
        return result["task_id"]

    def store_trace_with_stats(
        self, trace: ExperienceTrace, *, dedupe: bool = True
    ) -> dict[str, Any]:
        """Store a trace and report what happened.

        Returns ``{"task_id", "stored", "duplicate"}`` — ``duplicate`` marks
        writes skipped by content-hash dedup.
        """
        content_hash = trace.compute_content_hash()

        if dedupe:
            with self._tx() as conn:
                row = conn.execute(
                    "SELECT 1 FROM traces WHERE task_id = ? AND content_hash = ?",
                    (trace.task_id, content_hash),
                ).fetchone()
            if row:
                self._bump_ingest_stats(duplicates=1)
                logger.debug("Duplicate trace %s skipped", trace.task_id)
                return {"task_id": trace.task_id, "stored": False, "duplicate": True}

        d = trace.to_dict()
        traj = d.get("trajectory", [])

        with self._tx() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO traces (
                    task_id, timestamp, prompt, task_type, difficulty, category,
                    session_id, model_name, model_version, temperature, context_size, tier,
                    agents_json, trajectory_json, memory_retrieved_json,
                    files_modified_json, commands_executed_json, tests_executed_json,
                    result_success, result_score, result_error, result_output,
                    latency_ms, tokens_input, tokens_output, tool_calls, retries, cost_usd,
                    eval_correctness, eval_efficiency, eval_quality, eval_regression,
                    parent_trace_id, experiment_id, component_kind, component_version,
                    workflow_version, version_tags_json, tags_json, content_hash, raw_json
                ) VALUES (
                    :task_id, :timestamp, :prompt, :task_type, :difficulty, :category,
                    :session_id, :model_name, :model_version, :temperature, :context_size, :tier,
                    :agents_json, :trajectory_json, :memory_retrieved_json,
                    :files_modified_json, :commands_executed_json, :tests_executed_json,
                    :result_success, :result_score, :result_error, :result_output,
                    :latency_ms, :tokens_input, :tokens_output, :tool_calls, :retries, :cost_usd,
                    :eval_correctness, :eval_efficiency, :eval_quality, :eval_regression,
                    :parent_trace_id, :experiment_id, :component_kind, :component_version,
                    :workflow_version, :version_tags_json, :tags_json, :content_hash, :raw_json
                )
                """,
                {
                    "task_id": trace.task_id,
                    "timestamp": trace.timestamp,
                    "prompt": trace.prompt,
                    "task_type": trace.task_type,
                    "difficulty": trace.difficulty,
                    "category": trace.category.value if isinstance(trace.category, TaskCategory) else trace.category,
                    "session_id": trace.session_id,
                    "model_name": trace.model.name,
                    "model_version": trace.model.version,
                    "temperature": trace.model.temperature,
                    "context_size": trace.model.context_size,
                    "tier": trace.model.tier,
                    "agents_json": json.dumps(d.get("agents", [])),
                    "trajectory_json": json.dumps(traj),
                    "memory_retrieved_json": json.dumps(d.get("memory_retrieved", [])),
                    "files_modified_json": json.dumps(d.get("files_modified", [])),
                    "commands_executed_json": json.dumps(d.get("commands_executed", [])),
                    "tests_executed_json": json.dumps(d.get("tests_executed", [])),
                    "result_success": 1 if trace.result.success else 0,
                    "result_score": trace.result.score,
                    "result_error": trace.result.error,
                    "result_output": trace.result.output,
                    "latency_ms": trace.metrics.latency_ms,
                    "tokens_input": trace.metrics.tokens_input,
                    "tokens_output": trace.metrics.tokens_output,
                    "tool_calls": trace.metrics.tool_calls,
                    "retries": trace.metrics.retries,
                    "cost_usd": trace.metrics.cost_usd,
                    "eval_correctness": trace.evaluation.correctness,
                    "eval_efficiency": trace.evaluation.efficiency,
                    "eval_quality": trace.evaluation.quality,
                    "eval_regression": 1 if trace.evaluation.regression else 0,
                    "parent_trace_id": trace.parent_trace_id,
                    "experiment_id": trace.experiment_id,
                    "component_kind": trace.component_kind.value if isinstance(trace.component_kind, ComponentKind) else trace.component_kind,
                    "component_version": trace.component_version,
                    "workflow_version": trace.workflow_version,
                    "version_tags_json": json.dumps(trace.version_tags),
                    "tags_json": json.dumps(trace.tags),
                    "content_hash": content_hash,
                    "raw_json": json.dumps(d),
                },
            )

            # Store trajectory entries separately for granular analysis
            conn.execute(
                "DELETE FROM trajectory_entries WHERE task_id = ?",
                (trace.task_id,),
            )
            for seq, entry in enumerate(traj):
                conn.execute(
                    """
                    INSERT INTO trajectory_entries
                        (task_id, seq, agent, action, tool, observation,
                         duration_ms, tokens_used, success, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace.task_id, seq,
                        entry.get("agent", ""), entry.get("action", ""),
                        entry.get("tool"), entry.get("observation"),
                        entry.get("duration_ms", 0), entry.get("tokens_used", 0),
                        1 if entry.get("success", True) else 0, entry.get("error"),
                    ),
                )

            # Failure classification index (only for failed tasks)
            if not trace.result.success:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO failure_categories
                        (task_id, failure_category, classified_at)
                    VALUES (?, ?, ?)
                    """,
                    (
                        trace.task_id,
                        classify_failure_text(trace.result.error or trace.result.output),
                        _utcnow_iso(),
                    ),
                )

        # Update FTS index
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO traces_fts(rowid, prompt) VALUES ((SELECT rowid FROM traces WHERE task_id = ?), ?)",
                (trace.task_id, trace.prompt),
            )
            conn.execute("INSERT INTO traces_fts(traces_fts) VALUES('rebuild')")

        self._bump_ingest_stats(writes=1)
        logger.debug("Stored trace %s (%s) in trace lake", trace.task_id, trace.task_type)
        return {"task_id": trace.task_id, "stored": True, "duplicate": False}

    def _bump_ingest_stats(self, writes: int = 0, duplicates: int = 0) -> None:
        """Accumulate ingest counters in ``trace_lake_meta``."""
        if not writes and not duplicates:
            return
        with self._tx() as conn:
            for key, delta in (("writes_total", writes), ("duplicates_skipped", duplicates)):
                if not delta:
                    continue
                row = conn.execute(
                    "SELECT value FROM trace_lake_meta WHERE key = ?", (key,)
                ).fetchone()
                try:
                    current = int(row["value"]) if row and row["value"] else 0
                except (ValueError, TypeError):
                    current = 0
                conn.execute(
                    """
                    INSERT INTO trace_lake_meta(key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, str(current + delta)),
                )

    def get_ingest_stats(self) -> dict[str, Any]:
        """Return ingest counters (``writes_total`` / ``duplicates_skipped``)."""
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT key, value FROM trace_lake_meta "
                "WHERE key IN ('writes_total', 'duplicates_skipped')"
            ).fetchall()
        stats = {row["key"]: row["value"] for row in rows}
        try:
            writes = int(stats.get("writes_total") or 0)
        except (ValueError, TypeError):
            writes = 0
        try:
            duplicates = int(stats.get("duplicates_skipped") or 0)
        except (ValueError, TypeError):
            duplicates = 0
        return {"writes_total": writes, "duplicates_skipped": duplicates}

    def get_trace(self, task_id: str) -> ExperienceTrace | None:
        """Retrieve a single trace by task_id."""
        with self._tx() as conn:
            row = conn.execute(
                "SELECT raw_json FROM traces WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return ExperienceTrace.model_validate_json(row["raw_json"])

    # ── Querying ──

    def search_prompts(self, query: str, k: int = 20) -> list[dict[str, Any]]:
        """Full-text search over task prompts via FTS5."""
        with self._tx() as conn:
            rows = conn.execute(
                """
                SELECT t.task_id, t.timestamp, t.task_type, t.result_success,
                       t.result_score, t.latency_ms, t.tokens_input,
                       t.model_name, snippet(traces_fts, 0, '<b>', '</b>', '…', 100) AS snippet
                FROM traces t
                JOIN traces_fts ON t.rowid = traces_fts.rowid
                WHERE traces_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, k),
            ).fetchall()
        return [dict(r) for r in rows]

    def query_traces(
        self,
        *,
        task_type: str | None = None,
        category: str | None = None,
        success: bool | None = None,
        min_difficulty: float | None = None,
        max_difficulty: float | None = None,
        model_name: str | None = None,
        experiment_id: str | None = None,
        component_kind: str | None = None,
        component_version: str | None = None,
        tags: list[str] | None = None,
        session_id: str | None = None,
        after: str | None = None,
        before: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Filter traces by any combination of fields."""
        clauses: list[str] = []
        params: list[Any] = []

        if task_type:
            clauses.append("task_type = ?")
            params.append(task_type)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if success is not None:
            clauses.append(f"result_success = {1 if success else 0}")
        if min_difficulty is not None:
            clauses.append("difficulty >= ?")
            params.append(min_difficulty)
        if max_difficulty is not None:
            clauses.append("difficulty <= ?")
            params.append(max_difficulty)
        if model_name:
            clauses.append("model_name = ?")
            params.append(model_name)
        if experiment_id:
            clauses.append("experiment_id = ?")
            params.append(experiment_id)
        if component_kind:
            clauses.append("component_kind = ?")
            params.append(component_kind)
        if component_version:
            clauses.append("component_version = ?")
            params.append(component_version)
        if tags:
            clauses.append("tags_json LIKE '%' || ? || '%'")
            params.append(tags[0])  # simple single-tag filter
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if after:
            clauses.append("timestamp > ?")
            params.append(after)
        if before:
            clauses.append("timestamp < ?")
            params.append(before)

        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.extend([limit, offset])

        with self._tx() as conn:
            rows = conn.execute(
                f"""
                SELECT task_id, timestamp, task_type, category, difficulty,
                       model_name, model_version, result_success, result_score,
                       result_error, result_output,
                       latency_ms, tokens_input, tokens_output, tool_calls,
                       retries, cost_usd, eval_correctness, eval_efficiency,
                       eval_quality, eval_regression, component_kind, component_version,
                       trajectory_json,
                       experiment_id, tags_json, agents_json
                FROM traces
                {where}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Analytics queries ──

    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics over all traces."""
        with self._tx() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN result_success = 1 THEN 1 ELSE 0 END) AS successes,
                    SUM(CASE WHEN result_success = 0 THEN 1 ELSE 0 END) AS failures,
                    AVG(result_score) AS avg_score,
                    AVG(latency_ms) AS avg_latency_ms,
                    AVG(tokens_input + tokens_output) AS avg_tokens,
                    AVG(tool_calls) AS avg_tool_calls,
                    SUM(cost_usd) AS total_cost_usd,
                    SUM(CASE WHEN eval_regression = 1 THEN 1 ELSE 0 END) AS regressions
                FROM traces
                """
            ).fetchone()
        return dict(row) if row else {}

    def get_failure_analysis(self) -> list[dict[str, Any]]:
        """Return failure frequency by task_type.

        Answer: *“Which task types fail most?”*
        """
        with self._tx() as conn:
            rows = conn.execute(
                """
                SELECT task_type, COUNT(*) AS failure_count,
                       AVG(result_score) AS avg_score,
                       AVG(latency_ms) AS avg_latency_ms
                FROM traces
                WHERE result_success = 0
                GROUP BY task_type
                ORDER BY failure_count DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_tool_error_analysis(self) -> list[dict[str, Any]]:
        """Return error frequency by tool.

        Answer: *“Which tool produces most errors?”*
        """
        with self._tx() as conn:
            rows = conn.execute(
                """
                SELECT tool, COUNT(*) AS error_count,
                       AVG(duration_ms) AS avg_duration_ms
                FROM trajectory_entries
                WHERE success = 0 AND tool IS NOT NULL
                GROUP BY tool
                ORDER BY error_count DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_component_performance(
        self, component_kind: str, version_col: str = "component_version"
    ) -> list[dict[str, Any]]:
        """Return performance by component version.

        Answer: *“Which planner version performs best?”*
        """
        with self._tx() as conn:
            rows = conn.execute(
                f"""
                SELECT {version_col} AS version,
                       COUNT(*) AS total,
                       SUM(CASE WHEN result_success = 1 THEN 1 ELSE 0 END) AS successes,
                       AVG(result_score) AS avg_score,
                       AVG(latency_ms) AS avg_latency_ms,
                       AVG(tokens_input + tokens_output) AS avg_tokens,
                       SUM(CASE WHEN eval_regression = 1 THEN 1 ELSE 0 END) AS regressions
                FROM traces
                WHERE component_kind = ?
                GROUP BY {version_col}
                ORDER BY avg_score DESC NULLS LAST, total DESC
                """,
                (component_kind,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_model_performance(self) -> list[dict[str, Any]]:
        """Return performance grouped by model and category.

        Answer: *“Which model performs best per domain?”*
        """
        with self._tx() as conn:
            rows = conn.execute(
                """
                SELECT model_name, category,
                       COUNT(*) AS total,
                       SUM(CASE WHEN result_success = 1 THEN 1 ELSE 0 END) AS successes,
                       AVG(result_score) AS avg_score,
                       AVG(tokens_input + tokens_output) AS avg_tokens,
                       AVG(latency_ms) AS avg_latency_ms
                FROM traces
                WHERE model_name IS NOT NULL
                GROUP BY model_name, category
                ORDER BY avg_score DESC NULLS LAST
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_token_waste_analysis(self) -> list[dict[str, Any]]:
        """Return token usage by task type.

        Answer: *“Where are tokens being wasted?”*
        """
        with self._tx() as conn:
            rows = conn.execute(
                """
                SELECT task_type, COUNT(*) AS task_count,
                       AVG(tokens_input) AS avg_input_tokens,
                       AVG(tokens_output) AS avg_output_tokens,
                       AVG(tokens_input + tokens_output) AS avg_total_tokens,
                       AVG(CASE WHEN result_success = 1 THEN 1.0 ELSE 0.0 END) AS success_rate
                FROM traces
                GROUP BY task_type
                ORDER BY avg_total_tokens DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_regression_analysis(self) -> list[dict[str, Any]]:
        """Return regression sources.

        Answer: *“Which skill causes regressions?”*
        """
        with self._tx() as conn:
            rows = conn.execute(
                """
                SELECT component_version, COUNT(*) AS total,
                       SUM(CASE WHEN eval_regression = 1 THEN 1 ELSE 0 END) AS regressions,
                       AVG(result_score) AS avg_score
                FROM traces
                WHERE component_version IS NOT NULL
                GROUP BY component_version
                HAVING regressions > 0
                ORDER BY regressions DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_prompt_experiment_comparison(self) -> list[dict[str, Any]]:
        """Compare success rates across experiments.

        Answer: *“Which prompts increased task success?”*
        """
        with self._tx() as conn:
            rows = conn.execute(
                """
                SELECT experiment_id, COUNT(*) AS total,
                       SUM(CASE WHEN result_success = 1 THEN 1 ELSE 0 END) AS successes,
                       AVG(result_score) AS avg_score,
                       AVG(latency_ms) AS avg_latency_ms,
                       AVG(tokens_input + tokens_output) AS avg_tokens
                FROM traces
                WHERE experiment_id IS NOT NULL
                GROUP BY experiment_id
                ORDER BY avg_score DESC NULLS LAST
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def trace_count(self) -> int:
        """Return total number of stored traces."""
        with self._tx() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM traces").fetchone()
        return row["n"] if row else 0

    # ── Retention / TTL cold archive ────────────────────────────────────────────

    def purge_expired(self, ttl_days: int) -> dict[str, Any]:
        """Move traces older than ``ttl_days`` into the cold archive.

        Nothing is deleted: expired traces, their trajectory entries and
        their failure classifications are relocated to the ``*_archive``
        tables with an archive stamp, then removed from the live tables.
        """
        if ttl_days < 0:
            raise ValueError("ttl_days must be >= 0")

        cutoff = (datetime.now(UTC) - timedelta(days=ttl_days)).isoformat()
        archived_at = _utcnow_iso()
        report: dict[str, Any] = {
            "archived_traces": 0,
            "archived_trajectory_entries": 0,
            "archived_failure_classifications": 0,
            "ttl_days": ttl_days,
        }

        with self._tx() as conn:
            old_ids = [
                row["task_id"]
                for row in conn.execute(
                    "SELECT task_id FROM traces WHERE timestamp < ?", (cutoff,)
                )
            ]
            if not old_ids:
                return report
            placeholders = ",".join("?" for _ in old_ids)

            cur = conn.execute(
                f"INSERT INTO traces_archive SELECT *, ?, ? FROM traces "
                f"WHERE task_id IN ({placeholders})",
                [archived_at, ttl_days, *old_ids],
            )
            report["archived_traces"] = cur.rowcount

            cur = conn.execute(
                f"INSERT INTO trajectory_entries_archive SELECT *, ?, ? "
                f"FROM trajectory_entries WHERE task_id IN ({placeholders})",
                [archived_at, ttl_days, *old_ids],
            )
            report["archived_trajectory_entries"] = cur.rowcount

            cur = conn.execute(
                f"INSERT INTO failure_categories_archive SELECT *, ?, ? "
                f"FROM failure_categories WHERE task_id IN ({placeholders})",
                [archived_at, ttl_days, *old_ids],
            )
            report["archived_failure_classifications"] = cur.rowcount

            conn.execute(
                f"DELETE FROM trajectory_entries WHERE task_id IN ({placeholders})",
                old_ids,
            )
            conn.execute(
                f"DELETE FROM failure_categories WHERE task_id IN ({placeholders})",
                old_ids,
            )
            conn.execute(
                f"DELETE FROM traces WHERE task_id IN ({placeholders})", old_ids
            )
            conn.execute("INSERT INTO traces_fts(traces_fts) VALUES('rebuild')")

        logger.info(
            "Purged %d expired traces to archive (ttl_days=%d)",
            report["archived_traces"],
            ttl_days,
        )
        return report

    def archived_trace_count(self) -> int:
        """Return the number of traces currently in the cold archive."""
        with self._tx() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM traces_archive").fetchone()
        return row["n"] if row else 0

    def list_archived(self, limit: int = 1000) -> list[dict[str, Any]]:
        """List archived trace rows (oldest archive stamp first)."""
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT * FROM traces_archive ORDER BY archived_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Failure-category queries ────────────────────────────────────────────────

    def top_failures(self, limit: int = 10) -> list[dict[str, Any]]:
        """Aggregate failure categories by frequency (most frequent first)."""
        with self._tx() as conn:
            rows = conn.execute(
                """
                SELECT failure_category, COUNT(*) AS failure_count,
                       MAX(classified_at) AS last_seen
                FROM failure_categories
                GROUP BY failure_category
                ORDER BY failure_count DESC, failure_category ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                entry = dict(row)
                tasks = conn.execute(
                    "SELECT task_id FROM failure_categories WHERE failure_category = ? "
                    "ORDER BY classified_at ASC LIMIT 10",
                    (row["failure_category"],),
                ).fetchall()
                entry["sample_task_ids"] = [t["task_id"] for t in tasks]
                out.append(entry)
        return out

    def query_by_failure_category(
        self, category: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return failed traces indexed under a failure category."""
        with self._tx() as conn:
            rows = conn.execute(
                """
                SELECT t.task_id, t.timestamp, t.task_type, t.category,
                       t.result_success, t.result_score, t.result_error,
                       t.result_output, fc.failure_category, fc.classified_at
                FROM failure_categories fc
                JOIN traces t ON t.task_id = fc.task_id
                WHERE fc.failure_category = ?
                ORDER BY fc.classified_at ASC
                LIMIT ?
                """,
                (category, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def clear(self) -> int:
        """Delete all traces (for testing). Returns count deleted."""
        with self._tx() as conn:
            conn.execute("DELETE FROM traces")
            conn.execute("DELETE FROM trajectory_entries")
            conn.execute("DELETE FROM failure_categories")
            conn.execute("INSERT INTO traces_fts(traces_fts) VALUES('rebuild')")
            conn.execute("DELETE FROM trace_lake_meta WHERE key = 'schema_version'")
            conn.execute(
                "INSERT INTO trace_lake_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
        return 0


# ── Singleton ────────────────────────────────────────────────────────────────

_lake: TraceLake | None = None


def get_trace_lake() -> TraceLake:
    """Return the process-wide :class:`TraceLake` singleton."""
    global _lake
    if _lake is None:
        _lake = TraceLake()
    return _lake


# ── Convenience ──────────────────────────────────────────────────────────────

def record_trace(trace: ExperienceTrace, db_path: str | Path | None = None) -> str:
    """Store a trace in the default or specified trace lake."""
    if db_path:
        return TraceLake(db_path).store_trace(trace)
    return get_trace_lake().store_trace(trace)


def _init(db_path: str | Path | None = None) -> TraceLake:
    """Initialise the trace lake for testing."""
    global _lake
    _lake = TraceLake(db_path)
    return _lake
