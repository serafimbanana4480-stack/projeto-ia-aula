"""Debate Transcriber for Enhanced Agent Parliament.

Transcribes debates and stores them in the Knowledge Graph for
context preservation and future reference.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from nexus_ide.backend.orchestrator.knowledge_graph import (
    Entity,
    EntityType,
    KnowledgeGraph,
    Relationship,
    RelationType,
)

from .logical_judge import JudgeReasoning
from .voting_system import DecisionType, Vote, VoteResult

logger = logging.getLogger(__name__)


class DebateStatus(str, Enum):
    """Status of a debate."""
    INITIATED = "initiated"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ARCHIVED = "archived"


@dataclass
class DebateTranscript:
    """Complete transcript of a debate."""
    debate_id: str = field(default_factory=lambda: f"debate-{uuid.uuid4().hex[:12]}")
    topic: str = ""
    decision_type: str = "default"
    
    # Participants
    participants: list[str] = field(default_factory=list)
    
    # Arguments
    arguments: list[dict[str, Any]] = field(default_factory=list)
    
    # Voting
    votes: list[Vote] = field(default_factory=list)
    vote_result: VoteResult | None = None
    
    # Adjudication
    judge_reasoning: JudgeReasoning | None = None
    
    # Final decision
    final_decision: str = ""
    
    # Status and metadata
    status: DebateStatus = DebateStatus.INITIATED
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    
    # Outcome (filled after implementation)
    outcome: dict[str, Any] | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert transcript to dictionary."""
        return {
            "debate_id": self.debate_id,
            "topic": self.topic,
            "decision_type": self.decision_type,
            "participants": self.participants,
            "arguments": self.arguments,
            "votes": [v.to_dict() for v in self.votes],
            "vote_result": self.vote_result.to_dict() if self.vote_result else None,
            "judge_reasoning": self.judge_reasoning.to_dict() if self.judge_reasoning else None,
            "final_decision": self.final_decision,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "outcome": self.outcome,
        }


class DebateTranscriber:
    """Transcribes debates and stores them in the Knowledge Graph.
    
    Features:
    - Complete debate transcription
    - Knowledge Graph storage with semantic search
    - Query of past debates
    - Context retrieval for similar topics
    - Linking debates to outcomes
    - Local storage fallback when KG unavailable
    """
    
    def __init__(
        self,
        knowledge_graph: KnowledgeGraph | None = None,
        db_path: str | None = None
    ):
        """Initialize debate transcriber.
        
        Args:
            knowledge_graph: Knowledge Graph instance for storage
            db_path: Path to SQLite database for persistence (optional)
        """
        self.kg = knowledge_graph
        
        # Local cache for transcripts (fallback)
        self._local_transcripts: dict[str, DebateTranscript] = {}
        
        # SQLite persistence
        self.db_path = db_path or "nexus_debates.db"
        self._conn = None
        self._init_db()
        
        if knowledge_graph:
            logger.info("DebateTranscriber initialized with Knowledge Graph and SQLite persistence")
        else:
            logger.info("DebateTranscriber initialized with SQLite persistence (no KG)")
    
    def _init_db(self) -> None:
        """Initialize SQLite database for debate persistence."""
        try:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            
            # Create tables
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS debates (
                    debate_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    decision_type TEXT NOT NULL,
                    participants TEXT,
                    arguments TEXT,
                    votes TEXT,
                    vote_result TEXT,
                    judge_reasoning TEXT,
                    final_decision TEXT,
                    status TEXT NOT NULL,
                    created_at REAL,
                    started_at REAL,
                    completed_at REAL,
                    outcome TEXT
                )
            """)
            
            self._conn.commit()
            logger.info(f"SQLite database initialized: {self.db_path}")
            
            # Load existing transcripts from SQLite
            self._load_from_sqlite()
            
        except Exception as e:
            logger.error(f"Failed to initialize SQLite database: {e}")
            self._conn = None
    
    def _load_from_sqlite(self) -> None:
        """Load transcripts from SQLite on initialization."""
        if not self._conn:
            return
        
        try:
            cursor = self._conn.execute(
                "SELECT * FROM debates ORDER BY completed_at DESC"
            )
            
            for row in cursor.fetchall():
                # Reconstruct transcript from database
                transcript = DebateTranscript(
                    debate_id=row["debate_id"],
                    topic=row["topic"],
                    decision_type=row["decision_type"],
                    participants=json.loads(row["participants"]) if row["participants"] else [],
                    arguments=json.loads(row["arguments"]) if row["arguments"] else [],
                    votes=json.loads(row["votes"]) if row["votes"] else [],
                    vote_result=json.loads(row["vote_result"]) if row["vote_result"] else None,
                    judge_reasoning=json.loads(row["judge_reasoning"]) if row["judge_reasoning"] else None,
                    final_decision=row["final_decision"],
                    status=DebateStatus(row["status"]),
                    created_at=row["created_at"],
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                    outcome=json.loads(row["outcome"]) if row["outcome"] else None,
                )
                
                self._local_transcripts[transcript.debate_id] = transcript
            
            logger.info(f"Loaded {len(self._local_transcripts)} transcripts from SQLite")
            
        except Exception as e:
            logger.error(f"Failed to load from SQLite: {e}")
    
    def _store_in_sqlite(self, transcript: DebateTranscript) -> None:
        """Store transcript in SQLite database."""
        if not self._conn:
            return
        
        try:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO debates 
                (debate_id, topic, decision_type, participants, arguments, votes, 
                 vote_result, judge_reasoning, final_decision, status, 
                 created_at, started_at, completed_at, outcome)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transcript.debate_id,
                    transcript.topic,
                    transcript.decision_type,
                    json.dumps(transcript.participants),
                    json.dumps(transcript.arguments),
                    json.dumps([v.to_dict() for v in transcript.votes]),
                    json.dumps(transcript.vote_result.to_dict()) if transcript.vote_result else None,
                    json.dumps(transcript.judge_reasoning.to_dict()) if transcript.judge_reasoning else None,
                    transcript.final_decision,
                    transcript.status.value,
                    transcript.created_at,
                    transcript.started_at,
                    transcript.completed_at,
                    json.dumps(transcript.outcome) if transcript.outcome else None,
                )
            )
            
            self._conn.commit()
            logger.debug(f"Stored transcript in SQLite: {transcript.debate_id}")
            
        except Exception as e:
            logger.error(f"Failed to store in SQLite: {e}")
    
    def _update_outcome_in_sqlite(self, debate_id: str, outcome: dict[str, Any]) -> None:
        """Update outcome in SQLite database."""
        if not self._conn:
            return
        
        try:
            self._conn.execute(
                """
                UPDATE debates 
                SET outcome = ?
                WHERE debate_id = ?
                """,
                (json.dumps(outcome), debate_id)
            )
            
            self._conn.commit()
            logger.debug(f"Updated outcome in SQLite for debate: {debate_id}")
            
        except Exception as e:
            logger.error(f"Failed to update outcome in SQLite: {e}")
    
    async def transcribe_debate(
        self,
        transcript: DebateTranscript
    ) -> str:
        """Transcribe debate and store in Knowledge Graph.
        
        Args:
            transcript: Debate transcript to store
            
        Returns:
            ID of the stored transcript
        """
        transcript.status = DebateStatus.COMPLETED
        transcript.completed_at = time.time()
        
        if self.kg:
            await self._store_in_knowledge_graph(transcript)
        else:
            self._store_locally(transcript)
        
        logger.info(
            f"Transcribed debate {transcript.debate_id}: "
            f"topic='{transcript.topic}', decision='{transcript.final_decision}'"
        )
        
        return transcript.debate_id
    
    async def _store_in_knowledge_graph(
        self,
        transcript: DebateTranscript
    ) -> None:
        """Store transcript in Knowledge Graph.
        
        Args:
            transcript: Debate transcript to store
        """
        try:
            # Create debate entity
            debate_entity = Entity(
                id=transcript.debate_id,
                name=transcript.topic,
                entity_type=EntityType.DEBATE,
                description=f"Debate about {transcript.topic}",
                properties={
                    "decision_type": transcript.decision_type,
                    "final_decision": transcript.final_decision,
                    "status": transcript.status.value,
                    "created_at": transcript.created_at,
                    "completed_at": transcript.completed_at,
                    "participants": transcript.participants,
                    "participant_count": len(transcript.participants),
                }
            )
            
            # Add debate entity to KG
            debate_entity_id = await self.kg._add_entity(debate_entity)
            logger.debug(f"Stored debate entity in KG: {debate_entity_id}")
            
            # Create agent entities and relationships
            for participant in transcript.participants:
                # Create or get agent entity
                agent_entity = Entity(
                    id=f"agent-{participant.lower()}",
                    name=participant,
                    entity_type=EntityType.AGENT,
                    description=f"AI Agent: {participant}",
                    properties={
                        "agent_type": "ai_agent",
                        "role": participant,
                    }
                )
                
                agent_entity_id = await self.kg._add_entity(agent_entity)
                
                # Create participation relationship
                participation_relationship = Relationship(
                    source_entity_id=agent_entity_id,
                    target_entity_id=debate_entity_id,
                    relation_type=RelationType.PARTICIPATED_IN,
                    properties={
                        "role": "participant",
                        "timestamp": transcript.started_at or transcript.created_at,
                    }
                )
                
                await self.kg._add_relationship(participation_relationship)
                
                logger.debug(
                    f"Created participation relationship: {agent_entity_id} "
                    f"-> {debate_entity_id}"
                )
            
            # Store vote information as relationships
            for vote in transcript.votes:
                agent_entity_id = f"agent-{vote.agent_id.lower()}"
                
                vote_relationship = Relationship(
                    source_entity_id=agent_entity_id,
                    target_entity_id=debate_entity_id,
                    relation_type=RelationType.VOTED_ON,
                    properties={
                        "vote_value": vote.value,
                        "vote_weighted": vote.value * self.kg.get_agent_weight(vote.agent_id, DecisionType(transcript.decision_type)) if hasattr(self.kg, 'get_agent_weight') else vote.value,
                        "reasoning": vote.reasoning,
                        "timestamp": vote.timestamp,
                    }
                )
                
                await self.kg._add_relationship(vote_relationship)
            
            # Store full transcript as document entity
            transcript_entity = Entity(
                id=f"transcript-{transcript.debate_id}",
                name=f"Transcript: {transcript.topic}",
                entity_type=EntityType.DOCUMENT,
                description=f"Full transcript of debate: {transcript.topic}",
                properties={
                    "debate_id": transcript.debate_id,
                    "transcript": transcript.to_dict(),
                    "created_at": transcript.created_at,
                }
            )
            
            transcript_entity_id = await self.kg._add_entity(transcript_entity)
            
            # Link transcript to debate
            transcript_link = Relationship(
                source_entity_id=transcript_entity_id,
                target_entity_id=debate_entity_id,
                relation_type=RelationType.RELATED_TO,
                properties={"relationship": "transcript_of"}
            )
            
            await self.kg._add_relationship(transcript_link)
            
            logger.info(f"Successfully stored debate in Knowledge Graph: {transcript.debate_id}")
            
        except Exception as e:
            logger.error(f"Failed to store in Knowledge Graph: {e}")
            # Fallback to local storage
            self._store_locally(transcript)
    
    def _store_locally(self, transcript: DebateTranscript) -> None:
        """Store transcript locally and in SQLite."""
        self._local_transcripts[transcript.debate_id] = transcript
        logger.debug(f"Stored transcript locally: {transcript.debate_id}")
        
        # Persist to SQLite if available
        if self._conn:
            self._store_in_sqlite(transcript)
    
    async def query_past_debates(
        self,
        topic: str,
        decision_type: str | None = None,
        limit: int = 10
    ) -> list[DebateTranscript]:
        """Query past debates on similar topics.
        
        Args:
            topic: Topic to search for
            decision_type: Optional decision type filter
            limit: Maximum number of results
            
        Returns:
            List of matching debate transcripts
        """
        if self.kg:
            return await self._query_from_knowledge_graph(topic, decision_type, limit)
        else:
            return self._query_locally(topic, decision_type, limit)
    
    async def _query_from_knowledge_graph(
        self,
        topic: str,
        decision_type: str | None,
        limit: int
    ) -> list[DebateTranscript]:
        """Query from Knowledge Graph using semantic search.
        
        Args:
            topic: Topic to search for
            decision_type: Optional decision type filter
            limit: Maximum number of results
            
        Returns:
            List of matching debate transcripts
        """
        try:
            # Build query for semantic search
            query = f"debate about {topic}"
            if decision_type:
                query += f" decision type {decision_type}"
            
            # Query for debate entities
            entity_types = [EntityType.DEBATE]
            related_entities = await self.kg.query_entities(
                query=query,
                entity_types=entity_types,
                limit=limit * 2  # Get more to filter
            )
            
            # Convert entities to transcripts
            transcripts = []
            for entity in related_entities:
                # Filter by decision type if specified
                if decision_type:
                    entity_decision_type = entity.properties.get("decision_type")
                    if entity_decision_type != decision_type:
                        continue
                
                # Reconstruct transcript from entity properties
                transcript = DebateTranscript(
                    debate_id=entity.id,
                    topic=entity.name,
                    decision_type=entity.properties.get("decision_type", "default"),
                    participants=entity.properties.get("participants", []),
                    final_decision=entity.properties.get("final_decision", ""),
                    status=DebateStatus(entity.properties.get("status", "completed")),
                    created_at=entity.properties.get("created_at", time.time()),
                    completed_at=entity.properties.get("completed_at"),
                )
                
                transcripts.append(transcript)
                
                if len(transcripts) >= limit:
                    break
            
            logger.info(
                f"Query from KG returned {len(transcripts)} debates for topic: {topic}"
            )
            
            return transcripts
            
        except Exception as e:
            logger.error(f"Failed to query Knowledge Graph: {e}")
            # Fallback to local storage
            return self._query_locally(topic, decision_type, limit)
    
    def _query_locally(
        self,
        topic: str,
        decision_type: str | None,
        limit: int
    ) -> list[DebateTranscript]:
        """Query from local storage (including SQLite)."""
        results = []
        
        # Query from local cache first
        for transcript in self._local_transcripts.values():
            # Simple topic matching (case-insensitive)
            if topic.lower() in transcript.topic.lower():
                if decision_type is None or transcript.decision_type == decision_type:
                    results.append(transcript)
                    if len(results) >= limit:
                        break
        
        return results
    
    async def get_debate_context(
        self,
        debate_id: str
    ) -> dict[str, Any] | None:
        """Get context for a specific debate.
        
        Args:
            debate_id: ID of the debate
            
        Returns:
            Debate context or None if not found
        """
        if self.kg:
            return await self._get_context_from_kg(debate_id)
        else:
            return self._get_context_locally(debate_id)
    
    async def _get_context_from_kg(
        self,
        debate_id: str
    ) -> dict[str, Any] | None:
        """Get context from Knowledge Graph.
        
        Args:
            debate_id: ID of the debate
            
        Returns:
            Debate context or None if not found
        """
        try:
            # Get debate entity
            debate_entity = await self.kg.get_entity(debate_id)
            if not debate_entity:
                return None
            
            # Get related entities (participants, votes, etc.)
            related_entities = await self.kg.get_related_entities(
                debate_id,
                relation_types=[
                    RelationType.PARTICIPATED_IN,
                    RelationType.VOTED_ON,
                ],
                max_depth=1
            )
            
            # Build context
            context = {
                "debate": debate_entity.to_dict(),
                "participants": [],
                "votes": [],
            }
            
            # Add participant information
            for entity in related_entities:
                if entity.entity_type == EntityType.AGENT:
                    context["participants"].append(entity.to_dict())
            
            # Add vote information from relationships
            relationships = await self.kg.get_related_entities(
                debate_id,
                relation_types=[RelationType.VOTED_ON],
                max_depth=1
            )
            
            for entity in relationships:
                if entity.relation_type == RelationType.VOTED_ON:
                    context["votes"].append({
                        "agent_id": entity.source_entity_id,
                        "vote_value": entity.properties.get("vote_value"),
                        "reasoning": entity.properties.get("reasoning"),
                    })
            
            logger.debug(f"Retrieved context from KG for debate: {debate_id}")
            
            return context
            
        except Exception as e:
            logger.error(f"Failed to get context from KG: {e}")
            # Fallback to local storage
            return self._get_context_locally(debate_id)
    
    def _get_context_locally(
        self,
        debate_id: str
    ) -> dict[str, Any] | None:
        """Get context from local storage (including SQLite)."""
        transcript = self._local_transcripts.get(debate_id)
        if transcript:
            return transcript.to_dict()
        
        # Try loading from SQLite if not in cache
        if self._conn:
            try:
                cursor = self._conn.execute(
                    "SELECT * FROM debates WHERE debate_id = ?",
                    (debate_id,)
                )
                row = cursor.fetchone()
                if row:
                    transcript = DebateTranscript(
                        debate_id=row["debate_id"],
                        topic=row["topic"],
                        decision_type=row["decision_type"],
                        participants=json.loads(row["participants"]) if row["participants"] else [],
                        arguments=json.loads(row["arguments"]) if row["arguments"] else [],
                        votes=json.loads(row["votes"]) if row["votes"] else [],
                        vote_result=json.loads(row["vote_result"]) if row["vote_result"] else None,
                        judge_reasoning=json.loads(row["judge_reasoning"]) if row["judge_reasoning"] else None,
                        final_decision=row["final_decision"],
                        status=DebateStatus(row["status"]),
                        created_at=row["created_at"],
                        started_at=row["started_at"],
                        completed_at=row["completed_at"],
                        outcome=json.loads(row["outcome"]) if row["outcome"] else None,
                    )
                    # Add to cache
                    self._local_transcripts[debate_id] = transcript
                    return transcript.to_dict()
            except Exception as e:
                logger.error(f"Failed to load from SQLite: {e}")
        
        return None
    
    async def update_outcome(
        self,
        debate_id: str,
        outcome: dict[str, Any]
    ) -> None:
        """Update outcome of a debate after implementation.
        
        Args:
            debate_id: ID of the debate
            outcome: Outcome data (success, metrics, etc.)
        """
        if self.kg:
            await self._update_outcome_in_kg(debate_id, outcome)
        else:
            self._update_outcome_locally(debate_id, outcome)
        
        logger.info(f"Updated outcome for debate {debate_id}")
    
    async def _update_outcome_in_kg(
        self,
        debate_id: str,
        outcome: dict[str, Any]
    ) -> None:
        """Update outcome in Knowledge Graph.
        
        Args:
            debate_id: ID of the debate
            outcome: Outcome data (success, metrics, etc.)
        """
        try:
            # Get debate entity
            debate_entity = await self.kg.get_entity(debate_id)
            if not debate_entity:
                logger.warning(f"Debate {debate_id} not found in KG")
                return
            
            # Update debate entity with outcome
            debate_entity.properties["outcome"] = outcome
            debate_entity.properties["outcome_updated_at"] = time.time()
            
            # Update entity in KG
            await self.kg._update_entity(debate_entity)
            
            # Create outcome entity if decision was successful
            if outcome.get("success", False):
                outcome_entity = Entity(
                    id=f"outcome-{debate_id}",
                    name=f"Outcome: {debate_entity.name}",
                    entity_type=EntityType.DECISION,
                    description=f"Outcome of debate: {debate_entity.name}",
                    properties={
                        "debate_id": debate_id,
                        "success": outcome.get("success"),
                        "score": outcome.get("score"),
                        "metrics": outcome.get("metrics", {}),
                        "updated_at": time.time(),
                    }
                )
                
                outcome_entity_id = await self.kg._add_entity(outcome_entity)
                
                # Link outcome to debate
                outcome_link = Relationship(
                    source_entity_id=outcome_entity_id,
                    target_entity_id=debate_id,
                    relation_type=RelationType.LED_TO,
                    properties={"relationship": "outcome_of"}
                )
                
                await self.kg._add_relationship(outcome_link)
                
                logger.debug(f"Created outcome entity: {outcome_entity_id}")
            
            logger.info(f"Updated outcome in KG for debate: {debate_id}")
            
        except Exception as e:
            logger.error(f"Failed to update outcome in KG: {e}")
            # Fallback to local storage
            self._update_outcome_locally(debate_id, outcome)
    
    def _update_outcome_locally(
        self,
        debate_id: str,
        outcome: dict[str, Any]
    ) -> None:
        """Update outcome locally and in SQLite."""
        if debate_id in self._local_transcripts:
            self._local_transcripts[debate_id].outcome = outcome
            logger.debug(f"Updated outcome locally for debate: {debate_id}")
        
        # Persist to SQLite if available
        if self._conn:
            self._update_outcome_in_sqlite(debate_id, outcome)
    
    async def get_debate_statistics(self) -> dict[str, Any]:
        """Get statistics about debates.
        
        Returns:
            Dictionary with debate statistics
        """
        if self.kg:
            return await self._get_statistics_from_kg()
        else:
            return self._get_statistics_locally()
    
    async def _get_statistics_from_kg(self) -> dict[str, Any]:
        """Get statistics from Knowledge Graph.
        
        Returns:
            Dictionary with debate statistics
        """
        try:
            # Query for debate entities
            debate_entities = await self.kg.query_entities(
                query="debate",
                entity_types=[EntityType.DEBATE],
                limit=10000  # Get all debates
            )
            
            total = len(debate_entities)
            
            # Count by decision type
            by_decision_type: dict[str, int] = {}
            by_status: dict[str, int] = {}
            total_duration = 0.0
            duration_count = 0
            
            for entity in debate_entities:
                # Count by decision type
                dt = entity.properties.get("decision_type", "default")
                by_decision_type[dt] = by_decision_type.get(dt, 0) + 1
                
                # Count by status
                status = entity.properties.get("status", "unknown")
                by_status[status] = by_status.get(status, 0) + 1
                
                # Calculate duration
                created_at = entity.properties.get("created_at", 0)
                completed_at = entity.properties.get("completed_at", 0)
                if completed_at and created_at:
                    duration = completed_at - created_at
                    total_duration += duration
                    duration_count += 1
            
            avg_duration = total_duration / duration_count if duration_count > 0 else 0
            
            logger.debug(f"Retrieved statistics from KG: {total} debates")
            
            return {
                "total_debates": total,
                "by_decision_type": by_decision_type,
                "by_status": by_status,
                "average_duration": avg_duration,
                "storage": "knowledge_graph",
            }
            
        except Exception as e:
            logger.error(f"Failed to get statistics from KG: {e}")
            # Fallback to local storage
            stats = self._get_statistics_locally()
            stats["storage"] = "local_fallback"
            return stats
    
    def _get_statistics_locally(self) -> dict[str, Any]:
        """Get statistics from local storage (including SQLite)."""
        # If SQLite is available, get total count from there
        if self._conn:
            try:
                cursor = self._conn.execute("SELECT COUNT(*) FROM debates")
                total = cursor.fetchone()[0]
            except Exception as e:
                logger.error(f"Failed to get count from SQLite: {e}")
                total = len(self._local_transcripts)
        else:
            total = len(self._local_transcripts)
        
        by_decision_type: dict[str, int] = {}
        by_status: dict[str, int] = {}
        total_duration = 0.0
        duration_count = 0
        
        for transcript in self._local_transcripts.values():
            # Count by decision type
            dt = transcript.decision_type
            by_decision_type[dt] = by_decision_type.get(dt, 0) + 1
            
            # Count by status
            status = transcript.status.value
            by_status[status] = by_status.get(status, 0) + 1
            
            # Calculate duration
            if transcript.started_at and transcript.completed_at:
                duration = transcript.completed_at - transcript.started_at
                total_duration += duration
                duration_count += 1
        
        avg_duration = total_duration / duration_count if duration_count > 0 else 0
        
        return {
            "total_debates": total,
            "by_decision_type": by_decision_type,
            "by_status": by_status,
            "average_duration": avg_duration,
        }
    
    def create_transcript(
        self,
        topic: str,
        decision_type: str,
        participants: list[str]
    ) -> DebateTranscript:
        """Create a new debate transcript.
        
        Args:
            topic: Topic of the debate
            decision_type: Type of decision
            participants: List of participant agent IDs
            
        Returns:
            New DebateTranscript
        """
        transcript = DebateTranscript(
            topic=topic,
            decision_type=decision_type,
            participants=participants,
            status=DebateStatus.INITIATED,
            started_at=time.time()
        )
        
        logger.debug(f"Created transcript {transcript.debate_id} for topic: {topic}")
        
        return transcript
