"""Agent State Store — persistent brain for NEXUS IDE agents.

Provides short-term, medium-term, and long-term memory for each agent,
enabling context retention across cycles and sessions.

State is persisted to the main SQLite database (``data/nexus.db``) using
the connection pool from :mod:`backend.persistence.db`.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.persistence.db import get_db

logger = logging.getLogger(__name__)

MemoryTier = Literal["short_term", "medium_term", "long_term"]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class AgentState(BaseModel):
    """A single memory entry for an agent.

    Attributes:
        agent_name: Identifier used in routing and metrics.
        session_id: The active session this memory belongs to.
        project_path: The project directory associated with this memory.
        memory_tier: One of ``short_term``, ``medium_term``, ``long_term``.
        key: The memory lookup key.
        value: Arbitrary JSON-serialisable data.
        created_at: When the memory was first created.
        updated_at: When the memory was last modified.
        access_count: How many times this memory has been read.
        importance_score: Normalised importance (0.0–1.0).
    """

    model_config = ConfigDict(extra="forbid")

    agent_name: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    project_path: str = Field(default="", max_length=2000)
    memory_tier: MemoryTier = "short_term"
    key: str = Field(min_length=1, max_length=512)
    value: Any = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    access_count: int = Field(default=0, ge=0)
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("agent_name", "session_id", "key")
    @classmethod
    def _strip_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("importance_score")
    @classmethod
    def _clamp_importance(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


class AgentBrain(BaseModel):
    """Aggregated view of every memory tier for an agent."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str
    short_term: list[AgentState] = Field(default_factory=list)
    medium_term: list[AgentState] = Field(default_factory=list)
    long_term: list[AgentState] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _to_json(value: Any) -> str:
    return json.dumps(value, default=str)


def _from_json(value: str | None, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        logger.warning("Failed to decode JSON: %s", value[:200])
        return default


def _row_to_agent_state(row: Any) -> AgentState:
    return AgentState(
        agent_name=row["agent_name"],
        session_id=row["session_id"],
        project_path=row["project_path"] or "",
        memory_tier=row["memory_tier"],
        key=row["key"],
        value=_from_json(row["value"], {}),
        created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
        updated_at=datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00")),
        access_count=row["access_count"],
        importance_score=row["importance_score"],
    )


# ---------------------------------------------------------------------------
# Store manager
# ---------------------------------------------------------------------------


class AgentStateStore:
    """Manager for persisting and retrieving agent memory entries.

    Usage::

        store = AgentStateStore()
        store.save_state("CODER", "sess_abc", "/proj", "short_term", "last_query", {"q": "hello"}, 0.7)
        mem = store.load_state("CODER", "sess_abc", "/proj", "short_term", "last_query")
        brain = store.get_agent_brain("CODER")
    """

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def save_state(
        self,
        agent_name: str,
        session_id: str,
        project_path: str,
        tier: MemoryTier,
        key: str,
        value: Any,
        importance: float = 0.5,
    ) -> AgentState:
        """Persist a memory entry.

        Inserts a new row or updates the existing one matched by
        ``(agent_name, session_id, project_path, memory_tier, key)``.
        """
        importance = max(0.0, min(1.0, importance))
        value_json = _to_json(value)
        now = _now_iso()

        with get_db() as conn:
            conn.execute(
                """INSERT INTO agent_states
                   (agent_name, session_id, project_path, memory_tier, key, value,
                    created_at, updated_at, access_count, importance_score)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(agent_name, session_id, project_path, memory_tier, key)
                   DO UPDATE SET
                       value = excluded.value,
                       updated_at = excluded.updated_at,
                       importance_score = excluded.importance_score""",
                (agent_name, session_id, project_path, tier, key, value_json,
                 now, now, 0, importance),
            )

        logger.debug("Saved state %s/%s/%s/%s", agent_name, session_id, tier, key)
        return self.load_state(agent_name, session_id, project_path, tier, key)

    def load_state(
        self,
        agent_name: str,
        session_id: str,
        project_path: str,
        tier: MemoryTier,
        key: str,
    ) -> AgentState | None:
        """Load a single memory entry and bump its access metrics."""
        with get_db() as conn:
            row = conn.execute(
                """SELECT * FROM agent_states
                   WHERE agent_name = ? AND session_id = ? AND project_path = ?
                     AND memory_tier = ? AND key = ?""",
                (agent_name, session_id, project_path, tier, key),
            ).fetchone()

            if row is None:
                return None

            # Bump access count and importance on read
            new_access = row["access_count"] + 1
            new_importance = min(1.0, row["importance_score"] + 0.02)
            conn.execute(
                """UPDATE agent_states
                   SET access_count = ?, importance_score = ?
                   WHERE agent_name = ? AND session_id = ? AND project_path = ?
                     AND memory_tier = ? AND key = ?""",
                (new_access, new_importance, agent_name, session_id,
                 project_path, tier, key),
            )

        mem = _row_to_agent_state(row)
        mem.access_count = new_access
        mem.importance_score = new_importance
        logger.debug("Loaded state %s/%s/%s/%s (access=%d)", agent_name, session_id, tier, key, new_access)
        return mem

    def forget(
        self,
        agent_name: str,
        session_id: str,
        project_path: str,
        tier: MemoryTier,
        key: str,
    ) -> bool:
        """Delete a single memory entry.

        Returns ``True`` if a row was deleted.
        """
        with get_db() as conn:
            cursor = conn.execute(
                """DELETE FROM agent_states
                   WHERE agent_name = ? AND session_id = ? AND project_path = ?
                     AND memory_tier = ? AND key = ?""",
                (agent_name, session_id, project_path, tier, key),
            )
        deleted = cursor.rowcount > 0
        if deleted:
            logger.debug("Forgot state %s/%s/%s/%s", agent_name, session_id, tier, key)
        return deleted

    # ------------------------------------------------------------------
    # Search / recall
    # ------------------------------------------------------------------

    def recall(
        self,
        agent_name: str,
        query: str,
        tier: MemoryTier | None = None,
        project_path: str | None = None,
        limit: int = 10,
    ) -> list[AgentState]:
        """Semantic search using simple text matching.

        Searches ``key`` and the JSON-serialised ``value`` for the query
        substring. Results are ranked by a composite score that blends
        importance and access frequency.
        """
        query_lower = query.lower()
        conditions = ["agent_name = ?"]
        params: list[Any] = [agent_name]

        if tier is not None:
            conditions.append("memory_tier = ?")
            params.append(tier)
        if project_path is not None:
            conditions.append("project_path = ?")
            params.append(project_path)

        where_clause = " AND ".join(conditions)

        with get_db() as conn:
            rows = conn.execute(
                f"""SELECT * FROM agent_states
                    WHERE {where_clause}
                    ORDER BY updated_at DESC""",
                tuple(params),
            ).fetchall()

        results: list[tuple[float, AgentState]] = []
        for row in rows:
            key_text = (row["key"] or "").lower()
            value_text = (row["value"] or "").lower()
            if query_lower in key_text or query_lower in value_text:
                mem = _row_to_agent_state(row)
                # Composite ranking: importance * log(access+1)
                score = mem.importance_score * (1 + (mem.access_count / 10.0))
                results.append((score, mem))

        results.sort(key=lambda x: x[0], reverse=True)
        return [mem for _, mem in results[:limit]]

    def get_agent_brain(self, agent_name: str) -> AgentBrain:
        """Return every memory for an agent, grouped by tier."""
        with get_db() as conn:
            rows = conn.execute(
                """SELECT * FROM agent_states
                   WHERE agent_name = ?
                   ORDER BY memory_tier, updated_at DESC""",
                (agent_name,),
            ).fetchall()

        short_term: list[AgentState] = []
        medium_term: list[AgentState] = []
        long_term: list[AgentState] = []

        for row in rows:
            mem = _row_to_agent_state(row)
            if mem.memory_tier == "short_term":
                short_term.append(mem)
            elif mem.memory_tier == "medium_term":
                medium_term.append(mem)
            else:
                long_term.append(mem)

        return AgentBrain(
            agent_name=agent_name,
            short_term=short_term,
            medium_term=medium_term,
            long_term=long_term,
        )

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def decay_memories(
        self,
        agent_name: str | None = None,
        decay_factor: float = 0.95,
        min_importance: float = 0.05,
    ) -> int:
        """Reduce importance of old memories.

        Args:
            agent_name: If given, only decay this agent's memories.
            decay_factor: Multiplier applied to each importance score.
            min_importance: Floor below which memories are deleted.

        Returns:
            Number of rows deleted (those that fell below the floor).
        """
        decay_factor = max(0.0, min(1.0, decay_factor))

        with get_db() as conn:
            # Apply decay
            if agent_name:
                conn.execute(
                    """UPDATE agent_states
                       SET importance_score = MAX(?, importance_score * ?)
                       WHERE agent_name = ?""",
                    (min_importance, decay_factor, agent_name),
                )
            else:
                conn.execute(
                    """UPDATE agent_states
                       SET importance_score = MAX(?, importance_score * ?)""",
                    (min_importance, decay_factor),
                )

            # Purge fallen-below-floor
            if agent_name:
                cursor = conn.execute(
                    """DELETE FROM agent_states
                       WHERE agent_name = ? AND importance_score <= ?""",
                    (agent_name, min_importance),
                )
            else:
                cursor = conn.execute(
                    """DELETE FROM agent_states
                       WHERE importance_score <= ?""",
                    (min_importance,),
                )

            deleted = cursor.rowcount

        logger.info("Decayed memories for %s, deleted %d below floor",
                    agent_name or "all agents", deleted)
        return deleted

    def clear_tier(
        self,
        agent_name: str,
        tier: MemoryTier,
        session_id: str | None = None,
        project_path: str | None = None,
    ) -> int:
        """Delete all memories for an agent in a given tier.

        Optionally filter by ``session_id`` and/or ``project_path``.

        Returns:
            Number of rows deleted.
        """
        conditions = ["agent_name = ?", "memory_tier = ?"]
        params: list[Any] = [agent_name, tier]

        if session_id is not None:
            conditions.append("session_id = ?")
            params.append(session_id)
        if project_path is not None:
            conditions.append("project_path = ?")
            params.append(project_path)

        where_clause = " AND ".join(conditions)

        with get_db() as conn:
            cursor = conn.execute(
                f"DELETE FROM agent_states WHERE {where_clause}",
                tuple(params),
            )

        logger.debug("Cleared %d %s memories for %s", cursor.rowcount, tier, agent_name)
        return cursor.rowcount
