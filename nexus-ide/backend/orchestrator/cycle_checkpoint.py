"""Cycle Checkpoint — persists improvement cycle state for crash recovery.

Checkpoints are stored in SQLite and allow resuming a cycle from the last
successful step instead of starting over.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CycleCheckpoint:
    checkpoint_id: str
    cycle_id: str
    step: str
    state: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed: bool = False


class CycleCheckpointStore:
    """SQLite-backed checkpoint store for cycle recovery."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or Path(__file__).resolve().parent.parent.parent / "data" / "cycle_checkpoints.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        import sqlite3
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cycle_checkpoints (
                        checkpoint_id TEXT PRIMARY KEY,
                        cycle_id TEXT NOT NULL,
                        step TEXT NOT NULL,
                        state TEXT NOT NULL,
                        created_at TEXT,
                        completed INTEGER DEFAULT 0
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cycle ON cycle_checkpoints(cycle_id)")
                conn.commit()
        except Exception:
            logger.exception("CycleCheckpointStore DB init failed")

    def save(self, checkpoint: CycleCheckpoint) -> None:
        import sqlite3
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO cycle_checkpoints
                    (checkpoint_id, cycle_id, step, state, created_at, completed)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        checkpoint.checkpoint_id,
                        checkpoint.cycle_id,
                        checkpoint.step,
                        json.dumps(checkpoint.state),
                        checkpoint.created_at.isoformat(),
                        1 if checkpoint.completed else 0,
                    ),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to save checkpoint %s", checkpoint.checkpoint_id)

    def get_latest(self, cycle_id: str) -> CycleCheckpoint | None:
        import sqlite3
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM cycle_checkpoints WHERE cycle_id = ? ORDER BY created_at DESC LIMIT 1",
                    (cycle_id,),
                ).fetchone()
                if not row:
                    return None
                return CycleCheckpoint(
                    checkpoint_id=row["checkpoint_id"],
                    cycle_id=row["cycle_id"],
                    step=row["step"],
                    state=json.loads(row["state"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                    completed=bool(row["completed"]),
                )
        except Exception:
            logger.exception("Failed to load checkpoint for %s", cycle_id)
            return None

    def mark_completed(self, checkpoint_id: str) -> None:
        import sqlite3
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                conn.execute(
                    "UPDATE cycle_checkpoints SET completed = 1 WHERE checkpoint_id = ?",
                    (checkpoint_id,),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to mark checkpoint %s as completed", checkpoint_id)

    def get_incomplete_cycles(self) -> list[str]:
        import sqlite3
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT cycle_id FROM cycle_checkpoints WHERE completed = 0"
                ).fetchall()
                return [row[0] for row in rows]
        except Exception:
            logger.exception("Failed to list incomplete cycles")
            return []
