"""Per-session scratchpad and history management.

See ARCHITECTURE.md §5.4 (Gestão de Contexto entre Iterações).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.tools.ollama_client import ChatMessage

logger = logging.getLogger(__name__)


@dataclass
class AgentScratchpad:
    """Per-session, per-agent working memory for ReAct loops.

    Currently populated only by future ReAct-capable agents (Tier 3+). For
    Tier 1 it is instantiated but left mostly empty.
    """

    session_id: str
    agent_id: str

    observations: list[str] = field(default_factory=list)
    failed_approaches: list[str] = field(default_factory=list)
    confirmed_facts: list[str] = field(default_factory=list)
    pending_questions: list[str] = field(default_factory=list)

    iteration: int = 0
    max_iterations: int = 7
    current_plan: str = ""

    tokens_used: int = 0
    web_searches: int = 0
    agent_consultations: int = 0
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))


class ContextStore:
    """Process-local, async-safe session store.

    Used for two things:

    1. **Conversation history** — ``list[ChatMessage]`` per session, fed back
       to agents so they remember prior turns.
    2. **Scratchpads** — per ``(session, agent)`` ReAct state (Tier 3+).

    Swap for a Redis-backed implementation by subclassing and overriding the
    three coroutines. The interface is intentionally small.
    """

    def __init__(self, *, max_history: int = 20) -> None:
        self._history: dict[str, list[ChatMessage]] = {}
        self._scratchpads: dict[tuple[str, str], AgentScratchpad] = {}
        self._lock = asyncio.Lock()
        self._max_history = max_history

    async def active_session_count(self) -> int:
        """Return the number of sessions currently tracked in memory."""
        async with self._lock:
            return len(self._history)

    async def append_message(self, session_id: str, message: ChatMessage) -> None:
        async with self._lock:
            bucket = self._history.setdefault(session_id, [])
            bucket.append(message)
            # Bound memory per session (sliding window).
            if len(bucket) > self._max_history:
                del bucket[0 : len(bucket) - self._max_history]

    async def get_scratchpad(self, session_id: str, agent_id: str) -> AgentScratchpad:
        key = (session_id, agent_id)
        async with self._lock:
            if key not in self._scratchpads:
                self._scratchpads[key] = AgentScratchpad(session_id, agent_id)
            return self._scratchpads[key]

    async def clear_session(self, session_id: str) -> None:
        async with self._lock:
            self._history.pop(session_id, None)
            for key in [k for k in self._scratchpads if k[0] == session_id]:
                self._scratchpads.pop(key, None)

    async def reload_from_db(self, session_id: str) -> int:
        """Reload conversation history from SQLite for a session.

        This is called on startup or when a session is accessed that isn't
        in memory yet. Returns the number of messages loaded.

        Args:
            session_id: The session to reload history for.

        Returns:
            Number of messages loaded from the database.
        """
        try:
            from backend.persistence.db import get_messages
        except ImportError:
            logger.warning("Cannot reload from DB: persistence module unavailable")
            return 0

        async with self._lock:
            # Don't reload if we already have history in memory
            if session_id in self._history and self._history[session_id]:
                return 0

            try:
                db_messages = get_messages(session_id, limit=self._max_history)
            except Exception as exc:
                logger.warning("Failed to load messages from DB for session %s: %s", session_id, exc)
                return 0

            if not db_messages:
                return 0

            messages: list[ChatMessage] = []
            for row in db_messages:
                role = row.get("role", "user")
                content = row.get("content", "")
                timestamp = row.get("created_at", "")
                messages.append(
                    ChatMessage(role=role, content=content, timestamp=timestamp)
                )

            self._history[session_id] = messages
            logger.info(
                "Reloaded %d messages from DB for session %s",
                len(messages), session_id,
            )
            return len(messages)

    async def get_history(self, session_id: str) -> list[ChatMessage]:
        """Get conversation history, reloading from DB if not in memory."""
        async with self._lock:
            if session_id not in self._history or not self._history[session_id]:
                # Release lock before DB access to avoid deadlock
                pass
            else:
                return list(self._history[session_id])

        # Try to reload from DB (outside the lock to avoid holding it during I/O)
        await self.reload_from_db(session_id)

        async with self._lock:
            return list(self._history.get(session_id, []))
