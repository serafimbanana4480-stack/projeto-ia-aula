"""Per-subagent checkpoint store — persists individual subagent state.

Unlike CycleCheckpointStore (which tracks whole improvement cycles),
this store enables resuming individual subagents after a crash or restart.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SubagentCheckpoint:
    checkpoint_id: str
    subagent_id: str
    phase: str
    state: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed: bool = False


class SubagentCheckpointStore:
    """SQLite-backed checkpoint store for per-subagent recovery."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or (
            Path(__file__).resolve().parent.parent.parent / "data" / "subagent_checkpoints.db"
        )
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS subagent_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    subagent_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT,
                    completed INTEGER DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_subagent ON subagent_checkpoints(subagent_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_subagent_phase ON subagent_checkpoints(phase)"
            )
            conn.commit()

    def save(self, checkpoint: SubagentCheckpoint) -> None:
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO subagent_checkpoints
                    (checkpoint_id, subagent_id, phase, state, created_at, completed)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        checkpoint.checkpoint_id,
                        checkpoint.subagent_id,
                        checkpoint.phase,
                        json.dumps(checkpoint.state),
                        checkpoint.created_at.isoformat(),
                        1 if checkpoint.completed else 0,
                    ),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to save subagent checkpoint %s", checkpoint.checkpoint_id)

    def get_latest(self, subagent_id: str) -> SubagentCheckpoint | None:
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM subagent_checkpoints WHERE subagent_id = ? ORDER BY created_at DESC LIMIT 1",
                    (subagent_id,),
                ).fetchone()
                if not row:
                    return None
                return SubagentCheckpoint(
                    checkpoint_id=row["checkpoint_id"],
                    subagent_id=row["subagent_id"],
                    phase=row["phase"],
                    state=json.loads(row["state"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                    completed=bool(row["completed"]),
                )
        except Exception:
            logger.exception("Failed to load subagent checkpoint for %s", subagent_id)
            return None

    def get_by_phase(self, phase: str) -> list[SubagentCheckpoint]:
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM subagent_checkpoints WHERE phase = ? ORDER BY created_at DESC",
                    (phase,),
                ).fetchall()
                return [
                    SubagentCheckpoint(
                        checkpoint_id=row["checkpoint_id"],
                        subagent_id=row["subagent_id"],
                        phase=row["phase"],
                        state=json.loads(row["state"]),
                        created_at=datetime.fromisoformat(row["created_at"]),
                        completed=bool(row["completed"]),
                    )
                    for row in rows
                ]
        except Exception:
            logger.exception("Failed to list subagent checkpoints for phase %s", phase)
            return []

    def mark_completed(self, checkpoint_id: str) -> None:
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                conn.execute(
                    "UPDATE subagent_checkpoints SET completed = 1 WHERE checkpoint_id = ?",
                    (checkpoint_id,),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to mark subagent checkpoint %s as completed", checkpoint_id)

    def get_incomplete_subagents(self) -> list[str]:
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT subagent_id FROM subagent_checkpoints WHERE completed = 0"
                ).fetchall()
                return [row[0] for row in rows]
        except Exception:
            logger.exception("Failed to list incomplete subagents")
            return []
