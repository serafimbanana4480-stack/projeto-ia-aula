"""DebateVisualizer — real-time debate state tracking and visualization data."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Stance(str, Enum):
    FOR = "for"
    AGAINST = "against"
    NEUTRAL = "neutral"
    PENDING = "pending"


@dataclass
class DebateArgument:
    """A single argument in a debate."""

    argument_id: str
    agent_id: str
    stance: Stance
    content: str
    timestamp: float = field(default_factory=time.time)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.5


@dataclass
class DebateRound:
    """A round in a multi-turn debate."""

    round_number: int
    arguments: list[DebateArgument] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def add_argument(self, argument: DebateArgument) -> None:
        self.arguments.append(argument)

    def complete(self) -> None:
        self.completed_at = time.time()


@dataclass
class DebateSession:
    """A complete debate session."""

    session_id: str
    topic: str
    rounds: list[DebateRound] = field(default_factory=list)
    participants: list[str] = field(default_factory=list)
    status: str = "active"  # active, completed, cancelled
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def add_round(self) -> DebateRound:
        round_obj = DebateRound(round_number=len(self.rounds) + 1)
        self.rounds.append(round_obj)
        return round_obj

    def complete(self) -> None:
        self.status = "completed"
        self.completed_at = time.time()

    def get_summary(self) -> dict[str, Any]:
        total_args = sum(len(r.arguments) for r in self.rounds)
        stances = {}
        for r in self.rounds:
            for a in r.arguments:
                stances[a.stance.value] = stances.get(a.stance.value, 0) + 1
        return {
            "session_id": self.session_id,
            "topic": self.topic,
            "status": self.status,
            "rounds": len(self.rounds),
            "total_arguments": total_args,
            "participants": self.participants,
            "stance_distribution": stances,
            "duration_seconds": (self.completed_at or time.time()) - self.started_at,
        }


class DebateVisualizer:
    """Tracks and visualizes agent debates in real-time."""

    def __init__(self) -> None:
        self._sessions: dict[str, DebateSession] = {}

    def create_session(self, session_id: str, topic: str, participants: list[str]) -> DebateSession:
        session = DebateSession(session_id=session_id, topic=topic, participants=participants)
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> DebateSession | None:
        return self._sessions.get(session_id)

    def add_argument(
        self,
        session_id: str,
        agent_id: str,
        stance: Stance,
        content: str,
        confidence: float = 0.5,
        evidence: list[dict[str, Any]] | None = None,
    ) -> DebateArgument | None:
        session = self._sessions.get(session_id)
        if not session:
            return None
        if not session.rounds or session.rounds[-1].completed_at:
            session.add_round()

        arg = DebateArgument(
            argument_id=f"arg-{len(session.rounds)}-{len(session.rounds[-1].arguments)}",
            agent_id=agent_id,
            stance=stance,
            content=content,
            confidence=confidence,
            evidence=evidence or [],
        )
        session.rounds[-1].add_argument(arg)
        return arg

    def complete_round(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if not session or not session.rounds:
            return False
        session.rounds[-1].complete()
        return True

    def complete_session(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        session.complete()
        return True

    def get_live_state(self, session_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        if not session:
            return None
        current_round = session.rounds[-1] if session.rounds else None
        return {
            "session_id": session.session_id,
            "topic": session.topic,
            "status": session.status,
            "current_round": current_round.round_number if current_round else 0,
            "arguments_in_current_round": len(current_round.arguments) if current_round else 0,
            "total_rounds": len(session.rounds),
            "participants": session.participants,
        }

    def list_sessions(self, status: str | None = None) -> list[DebateSession]:
        sessions = list(self._sessions.values())
        if status:
            sessions = [s for s in sessions if s.status == status]
        return sessions
