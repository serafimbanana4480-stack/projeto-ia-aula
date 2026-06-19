"""Agent Bus Pub/Sub system — the nervous system for NEXUS IDE agents.

Allows agents to publish and subscribe to topics, enabling loosely-coupled,
async group collaboration.  Messages are persisted to SQLite for 24 hours
so agents can recover missed events after restarts.

Topics
------
Common topics used across the system::

    code.changes          — File modifications proposed by CODER / MICRO.
    test.results          — Test execution outcomes from TESTER / DEBUGGER.
    errors.found          — Bugs, lint errors, or runtime exceptions.
    architecture.proposals — Design docs or refactoring plans from ARCHITECT.
    review.completed      — Code-review verdicts from GUARDIAN / ANALYZER.
    agent.status          — Heart-beats, state changes, availability pings.
    mission.update        — High-level task progress from SUPERVISOR.

Any agent may publish or subscribe to any topic — there is no enforced ACL
inside the bus itself.  Guard-rails live in the agent logic layer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_TTL_SECONDS: int = 3_600  # 1 hour (requirement says default 3600)
DB_PATH: Path = Path(__file__).resolve().parent.parent.parent / "data" / "agent_bus.db"
_MAX_IN_MEMORY_PER_TOPIC: int = 1_000

# ──────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────────────────────────────────────


class BusMessage(BaseModel):
    """A single message travelling through the AgentBus.

    Attributes:
        message_id: UUIDv4 hex (16 chars) uniquely identifying the message.
        topic: Dot-namespaced channel, e.g. ``code.changes``.
        source_agent: Name of the publishing agent (e.g. ``CODER``).
        target_agents: List of specific agent names to target. Empty = broadcast.
        payload: Arbitrary JSON-serialisable dict.
        timestamp: ISO-8601 UTC timestamp when the message was created.
        priority: Message priority 1 (lowest) to 5 (highest).
        ttl_seconds: How long the message should be retained in persistence.
    """

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=128)
    topic: str = Field(default="", min_length=0, max_length=256)
    source_agent: str = Field(min_length=1, max_length=128)
    target_agents: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    priority: int = Field(default=3, ge=1, le=5)
    ttl_seconds: int = Field(default=DEFAULT_TTL_SECONDS, ge=1)

    @field_validator("topic")
    @classmethod
    def _topic_lowercase(cls, value: str) -> str:
        return value.lower().strip()

    def is_expired(self, now: datetime | None = None) -> bool:
        """Return ``True`` if the message TTL has elapsed."""
        now = now or datetime.now(UTC)
        return now > self.timestamp + timedelta(seconds=self.ttl_seconds)

    def is_targeted_at(self, agent_name: str) -> bool:
        """Return ``True`` if this message is a broadcast or targets *agent_name*."""
        return not self.target_agents or agent_name in self.target_agents


# ──────────────────────────────────────────────────────────────────────────────
# Subscription
# ──────────────────────────────────────────────────────────────────────────────

BusCallback = Callable[[BusMessage], Awaitable[Any]]


@dataclass
class Subscription:
    """Represents an active callback registration on a topic.

    Attributes:
        subscription_id: UUID hex identifying this subscription.
        topic: The topic string the callback is listening on.
        callback: Async callable invoked with the :class:`BusMessage`.
    """

    subscription_id: str
    topic: str
    callback: BusCallback


# ──────────────────────────────────────────────────────────────────────────────
# SQLite persistence helpers
# ──────────────────────────────────────────────────────────────────────────────


def _init_bus_db(db_path: Path) -> None:
    """Create the bus_messages table if it does not exist, and migrate schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path), check_same_thread=False) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bus_messages (
                message_id   TEXT PRIMARY KEY,
                topic        TEXT NOT NULL,
                source_agent TEXT NOT NULL,
                target_agents TEXT NOT NULL DEFAULT '[]',
                payload      TEXT NOT NULL,
                timestamp    TEXT NOT NULL,
                priority     INTEGER NOT NULL DEFAULT 3,
                ttl_seconds  INTEGER NOT NULL
            )
            """
        )
        # Migrate existing tables that may lack the new columns
        cursor = conn.execute("PRAGMA table_info(bus_messages)")
        columns = {row[1] for row in cursor.fetchall()}
        if "target_agents" not in columns:
            conn.execute(
                "ALTER TABLE bus_messages ADD COLUMN target_agents TEXT NOT NULL DEFAULT '[]'"
            )
        if "priority" not in columns:
            conn.execute("ALTER TABLE bus_messages ADD COLUMN priority INTEGER NOT NULL DEFAULT 3")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bus_messages_topic ON bus_messages(topic)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_bus_messages_timestamp ON bus_messages(timestamp)"
        )
        conn.commit()


def _row_to_message(row: sqlite3.Row) -> BusMessage:
    """Convert a sqlite3.Row into a :class:`BusMessage`."""
    return BusMessage(
        message_id=row["message_id"],
        topic=row["topic"],
        source_agent=row["source_agent"],
        target_agents=json.loads(row["target_agents"]),
        payload=json.loads(row["payload"]),
        timestamp=datetime.fromisoformat(row["timestamp"]),
        priority=row["priority"],
        ttl_seconds=row["ttl_seconds"],
    )


# ──────────────────────────────────────────────────────────────────────────────
# AgentBus — singleton pub/sub bus
# ──────────────────────────────────────────────────────────────────────────────


class AgentBus:
    """Singleton pub/sub message bus for inter-agent communication.

    Usage::

        bus = AgentBus()

        sub = await bus.subscribe("code.changes", on_code_change)
        await bus.publish("code.changes", BusMessage(...))
        await bus.unsubscribe(sub.subscription_id)

    Messages are broadcast **in-memory** to all active subscribers and
    simultaneously persisted to SQLite so that late-joiners or restarted
    agents can replay history via :meth:`get_history`.
    """

    _instance: AgentBus | None = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls, *, db_path: Path | None = None) -> AgentBus:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init(db_path=db_path or DB_PATH)
        return cls._instance

    def _init(self, db_path: Path) -> None:
        self._db_path = db_path
        _init_bus_db(self._db_path)

        # topic -> list[Subscription]
        self._subs: dict[str, list[Subscription]] = {}

        # topic -> list[BusMessage]  (in-memory ring buffer per topic)
        self._history: dict[str, list[BusMessage]] = {}

        self._lock = asyncio.Lock()

    # ── public API ──────────────────────────────────────────────────────────

    async def publish(self, topic: str, message: BusMessage) -> None:
        """Broadcast *message* to every subscriber of *topic* and persist it.

        Args:
            topic: Target topic (normalised to lower-case).
            message: The :class:`BusMessage` to send.

        If a subscriber callback raises an exception it is logged but **does
        not** block other subscribers from receiving the message.
        """
        topic = topic.lower().strip()
        message.topic = topic

        # Persist first so history is always consistent even if a callback crashes.
        await asyncio.to_thread(self._persist_message, message)

        async with self._lock:
            # Update in-memory history
            self._history.setdefault(topic, [])
            self._history[topic].append(message)
            if len(self._history[topic]) > _MAX_IN_MEMORY_PER_TOPIC:
                self._history[topic].pop(0)

            subs = list(self._subs.get(topic, []))

        # Broadcast outside the lock so slow callbacks don't stall the bus.
        if subs:
            logger.debug(
                "Bus publish | topic=%s | msg_id=%s | subscribers=%d",
                topic,
                message.message_id,
                len(subs),
            )
        for sub in subs:
            try:
                await sub.callback(message)
            except Exception:
                logger.exception(
                    "Subscriber %s crashed on topic %s (msg_id=%s)",
                    sub.subscription_id,
                    topic,
                    message.message_id,
                )

    async def subscribe(self, topic: str, callback: BusCallback) -> Subscription:
        """Register *callback* to receive messages on *topic*.

        Args:
            topic: Topic to listen on.
            callback: Async callable taking a single :class:`BusMessage` argument.

        Returns:
            The :class:`Subscription` handle, which can later be passed to
            :meth:`unsubscribe`.
        """
        topic = topic.lower().strip()
        sub = Subscription(
            subscription_id=uuid.uuid4().hex[:16],
            topic=topic,
            callback=callback,
        )
        async with self._lock:
            self._subs.setdefault(topic, []).append(sub)
        logger.info(
            "Bus subscribe | sub_id=%s | topic=%s | total_subs=%d",
            sub.subscription_id,
            topic,
            len(self._subs[topic]),
        )
        return sub

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Remove the subscription identified by *subscription_id*.

        Returns:
            ``True`` if the subscription existed and was removed.
        """
        async with self._lock:
            for topic, subs in self._subs.items():
                for idx, sub in enumerate(subs):
                    if sub.subscription_id == subscription_id:
                        subs.pop(idx)
                        logger.info(
                            "Bus unsubscribe | sub_id=%s | topic=%s",
                            subscription_id,
                            topic,
                        )
                        return True
        logger.warning("Bus unsubscribe | sub_id=%s not found", subscription_id)
        return False

    async def get_history(
        self,
        topic: str,
        *,
        limit: int = 100,
        include_expired: bool = False,
    ) -> list[BusMessage]:
        """Return recent messages for *topic*, newest first.

        By default expired messages (older than their ``ttl_seconds``) are
        filtered out.  If the in-memory buffer is smaller than *limit* the
        remaining rows are pulled from SQLite.

        Args:
            topic: Topic to query.
            limit: Maximum number of messages to return (default 100).
            include_expired: If ``True``, include messages past their TTL.

        Returns:
            List of :class:`BusMessage` instances ordered newest → oldest.
        """
        topic = topic.lower().strip()
        now = datetime.now(UTC)

        # 1. Try in-memory first (already sorted by insertion order)
        async with self._lock:
            mem = list(self._history.get(topic, []))

        if not include_expired:
            mem = [m for m in mem if not m.is_expired(now)]

        mem = mem[-limit:][::-1]  # newest first
        if len(mem) >= limit:
            return mem

        # 2. Back-fill from SQLite
        remaining = limit - len(mem)
        db_rows = await asyncio.to_thread(
            self._fetch_from_db, topic, remaining, include_expired, now
        )
        # Deduplicate by message_id — in-memory messages always win.
        seen = {m.message_id for m in mem}
        for row in db_rows:
            if row.message_id not in seen:
                mem.append(row)
        return mem[:limit]

    async def clear_history(self, topic: str) -> int:
        """Delete **all** persisted and in-memory messages for *topic*.

        Returns:
            Number of messages removed from the database.
        """
        topic = topic.lower().strip()
        async with self._lock:
            self._history.pop(topic, None)

        rows_deleted = await asyncio.to_thread(self._delete_topic_from_db, topic)
        logger.info("Bus clear_history | topic=%s | deleted=%d", topic, rows_deleted)
        return rows_deleted

    async def purge_expired(self) -> int:
        """Remove expired messages from SQLite and in-memory caches.

        Returns:
            Number of messages removed from the database.
        """
        now = datetime.now(UTC)
        async with self._lock:
            for topic in list(self._history.keys()):
                self._history[topic] = [m for m in self._history[topic] if not m.is_expired(now)]

        rows_deleted = await asyncio.to_thread(self._delete_expired_from_db, now)
        logger.info("Bus purge_expired | deleted=%d", rows_deleted)
        return rows_deleted

    def get_topics(self) -> list[str]:
        """Return all topics that currently have in-memory history or subscribers."""
        topics: set[str] = set()
        topics.update(self._history.keys())
        topics.update(self._subs.keys())
        return sorted(topics)

    # ── internal helpers ────────────────────────────────────────────────────

    def _persist_message(self, message: BusMessage) -> None:
        """Insert a message into SQLite (synchronous)."""
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                conn.execute(
                    """
                    INSERT INTO bus_messages
                    (message_id, topic, source_agent, target_agents, payload, timestamp, priority, ttl_seconds)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message.message_id,
                        message.topic,
                        message.source_agent,
                        json.dumps(message.target_agents),
                        json.dumps(message.payload, default=str),
                        message.timestamp.isoformat(),
                        message.priority,
                        message.ttl_seconds,
                    ),
                )
                conn.commit()
        except sqlite3.Error:
            logger.exception("Failed to persist bus message %s", message.message_id)

    def _fetch_from_db(
        self,
        topic: str,
        limit: int,
        include_expired: bool,
        now: datetime,
    ) -> list[BusMessage]:
        """Load recent messages from SQLite (synchronous)."""
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                conn.row_factory = sqlite3.Row
                if include_expired:
                    rows = conn.execute(
                        """
                        SELECT * FROM bus_messages
                        WHERE topic = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                        """,
                        (topic, limit),
                    ).fetchall()
                else:
                    cutoff = (now - timedelta(seconds=DEFAULT_TTL_SECONDS)).isoformat()
                    rows = conn.execute(
                        """
                        SELECT * FROM bus_messages
                        WHERE topic = ? AND timestamp > ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                        """,
                        (topic, cutoff, limit),
                    ).fetchall()
                return [_row_to_message(r) for r in rows]
        except sqlite3.Error:
            logger.exception("Failed to fetch history for topic %s", topic)
            return []

    def _delete_topic_from_db(self, topic: str) -> int:
        """Remove all rows for a topic (synchronous)."""
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                cur = conn.execute("DELETE FROM bus_messages WHERE topic = ?", (topic,))
                conn.commit()
                return cur.rowcount
        except sqlite3.Error:
            logger.exception("Failed to clear history for topic %s", topic)
            return 0

    def _delete_expired_from_db(self, now: datetime) -> int:
        """Remove expired rows (synchronous)."""
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                cur = conn.execute(
                    """
                    DELETE FROM bus_messages
                    WHERE datetime(timestamp, '+' || ttl_seconds || ' seconds') < ?
                    """,
                    (now.isoformat(),),
                )
                conn.commit()
                return cur.rowcount
        except sqlite3.Error:
            logger.exception("Failed to purge expired messages")
            return 0


# ──────────────────────────────────────────────────────────────────────────────
# Convenience accessor
# ──────────────────────────────────────────────────────────────────────────────


def get_agent_bus() -> AgentBus:
    """Return the singleton :class:`AgentBus` instance."""
    return AgentBus()


# ──────────────────────────────────────────────────────────────────────────────
# Example / self-test
# ──────────────────────────────────────────────────────────────────────────────


async def _example() -> None:
    """Demonstrate two agents communicating over the bus."""
    logging.basicConfig(level=logging.INFO)

    bus = get_agent_bus()

    received_by_reviewer: list[BusMessage] = []
    received_by_architect: list[BusMessage] = []

    async def reviewer_handler(msg: BusMessage) -> None:
        received_by_reviewer.append(msg)
        print(f"[REVIEWER] got {msg.topic} from {msg.source_agent}: {msg.payload}")

    async def architect_handler(msg: BusMessage) -> None:
        received_by_architect.append(msg)
        print(f"[ARCHITECT] got {msg.topic} from {msg.source_agent}: {msg.payload}")

    # Subscribe
    sub_reviewer = await bus.subscribe("code.changes", reviewer_handler)
    sub_architect = await bus.subscribe("architecture.proposals", architect_handler)
    # Subscribe architect to code.changes as well to show many-to-many
    sub_architect_code = await bus.subscribe("code.changes", architect_handler)

    # CODER publishes a code change
    await bus.publish(
        "code.changes",
        BusMessage(
            message_id=uuid.uuid4().hex[:16],
            source_agent="CODER",
            payload={"file": "api.py", "lines_added": 42, "lines_removed": 7},
        ),
    )

    # ARCHITECT publishes a proposal
    await bus.publish(
        "architecture.proposals",
        BusMessage(
            message_id=uuid.uuid4().hex[:16],
            source_agent="ARCHITECT",
            payload={"proposal": "Migrate to FastAPI routers", "impact": "high"},
        ),
    )

    # Small yield so callbacks finish before assertions
    await asyncio.sleep(0.05)

    assert len(received_by_reviewer) == 1, "Reviewer should see exactly 1 code.changes"
    assert len(received_by_architect) == 2, (
        "Architect should see 1 code.changes + 1 architecture.proposals"
    )

    # History replay
    history = await bus.get_history("code.changes", limit=10)
    print(f"History for code.changes: {len(history)} message(s)")
    assert history[0].source_agent == "CODER"

    # Cleanup
    await bus.unsubscribe(sub_reviewer.subscription_id)
    await bus.unsubscribe(sub_architect.subscription_id)
    await bus.unsubscribe(sub_architect_code.subscription_id)
    await bus.clear_history("code.changes")
    await bus.clear_history("architecture.proposals")

    print("AgentBus example completed successfully ✓")


if __name__ == "__main__":
    asyncio.run(_example())
