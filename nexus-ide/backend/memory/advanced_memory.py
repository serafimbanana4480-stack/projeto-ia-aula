"""Advanced Memory Systems with Episodic, Procedural, and Graph Memory.

Implements multi-layered memory architecture with consolidation,
retrieval, forgetting, and memory management.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union, Tuple
from datetime import datetime, timedelta
import hashlib

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class MemoryType(str, Enum):
    """Types of memory systems."""
    EPISODIC = "episodic"  # Personal experiences and events
    SEMANTIC = "semantic"   # Facts and general knowledge
    PROCEDURAL = "procedural"  # Skills and procedures
    WORKING = "working"     # Short-term active memory
    LONG_TERM = "long_term"  # Persistent long-term memory
    GRAPH = "graph"         # Knowledge graph relationships


class MemoryStatus(str, Enum):
    """Memory status tracking."""
    ACTIVE = "active"
    CONSOLIDATING = "consolidating"
    CONSOLIDATED = "consolidated"
    DECAYING = "decaying"
    FORGOTTEN = "forgotten"
    ARCHIVED = "archived"


class MemoryPriority(str, Enum):
    """Memory priority levels."""
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass
class MemoryFragment:
    """Individual memory fragment."""
    fragment_id: str = field(default_factory=lambda: f"frag-{uuid.uuid4().hex[:12]}")
    memory_type: MemoryType = MemoryType.EPISODIC
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Temporal information
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    
    # Memory properties
    importance: float = 0.5  # 0.0-1.0
    emotional_intensity: float = 0.0  # 0.0-1.0
    rehearsal_count: int = 0
    consolidation_strength: float = 0.0  # 0.0-1.0
    
    # Relationships
    related_fragments: Set[str] = field(default_factory=set)
    parent_fragment_id: Optional[str] = None
    child_fragment_ids: Set[str] = field(default_factory=set)
    
    # Status and priority
    status: MemoryStatus = MemoryStatus.ACTIVE
    priority: MemoryPriority = MemoryPriority.NORMAL
    
    # Expiration and decay
    expires_at: Optional[float] = None
    decay_rate: float = 0.01  # Decay per day
    
    # Tags and categories
    tags: Set[str] = field(default_factory=set)
    categories: Set[str] = field(default_factory=set)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "fragment_id": self.fragment_id,
            "memory_type": self.memory_type.value,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "importance": self.importance,
            "emotional_intensity": self.emotional_intensity,
            "rehearsal_count": self.rehearsal_count,
            "consolidation_strength": self.consolidation_strength,
            "related_fragments": list(self.related_fragments),
            "parent_fragment_id": self.parent_fragment_id,
            "child_fragment_ids": list(self.child_fragment_ids),
            "status": self.status.value,
            "priority": self.priority.value,
            "expires_at": self.expires_at,
            "decay_rate": self.decay_rate,
            "tags": list(self.tags),
            "categories": list(self.categories),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryFragment":
        """Create from dictionary."""
        fragment = cls(
            fragment_id=data["fragment_id"],
            memory_type=MemoryType(data["memory_type"]),
            content=data["content"],
            metadata=data["metadata"],
            created_at=data["created_at"],
            last_accessed=data["last_accessed"],
            access_count=data["access_count"],
            importance=data["importance"],
            emotional_intensity=data["emotional_intensity"],
            rehearsal_count=data["rehearsal_count"],
            consolidation_strength=data["consolidation_strength"],
            related_fragments=set(data.get("related_fragments", [])),
            parent_fragment_id=data.get("parent_fragment_id"),
            child_fragment_ids=set(data.get("child_fragment_ids", [])),
            status=MemoryStatus(data["status"]),
            priority=MemoryPriority(data["priority"]),
            expires_at=data.get("expires_at"),
            decay_rate=data["decay_rate"],
            tags=set(data.get("tags", [])),
            categories=set(data.get("categories", [])),
        )
        return fragment
    
    def is_expired(self) -> bool:
        """Check if memory fragment has expired."""
        if self.expires_at:
            return time.time() > self.expires_at
        return False
    
    def calculate_activation(self) -> float:
        """Calculate activation level based on recency and frequency."""
        # Recency component
        time_since_access = time.time() - self.last_accessed
        recency_factor = 1.0 / (1.0 + time_since_access / 86400)  # Days
        
        # Frequency component
        frequency_factor = min(1.0, self.access_count / 10.0)
        
        # Importance component
        importance_factor = self.importance
        
        # Consolidation strength
        consolidation_factor = self.consolidation_strength
        
        # Combined activation
        activation = (
            recency_factor * 0.3 +
            frequency_factor * 0.2 +
            importance_factor * 0.3 +
            consolidation_factor * 0.2
        )
        
        return activation
    
    def should_consolidate(self) -> bool:
        """Check if memory should be consolidated."""
        return (
            self.access_count >= 3 and
            self.importance >= 0.6 and
            self.consolidation_strength < 0.8
        )


@dataclass
class MemoryEpisode:
    """Episodic memory representing a complete experience."""
    episode_id: str = field(default_factory=lambda: f"epi-{uuid.uuid4().hex[:12]}")
    title: str = ""
    description: str = ""
    
    # Temporal context
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration: Optional[float] = None
    
    # Spatial and contextual information
    location: Optional[str] = None
    participants: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    
    # Memory fragments
    fragment_ids: List[str] = field(default_factory=list)
    
    # Episode properties
    emotional_valence: float = 0.0  # -1.0 to 1.0
    emotional_arousal: float = 0.0  # 0.0 to 1.0
    importance: float = 0.5  # 0.0 to 1.0
    
    # Relationships
    related_episodes: Set[str] = field(default_factory=set)
    parent_episode_id: Optional[str] = None
    sub_episode_ids: Set[str] = field(default_factory=set)
    
    # Status
    status: MemoryStatus = MemoryStatus.ACTIVE
    tags: Set[str] = field(default_factory=set)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "title": self.title,
            "description": self.description,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "location": self.location,
            "participants": self.participants,
            "context": self.context,
            "fragment_ids": self.fragment_ids,
            "emotional_valence": self.emotional_valence,
            "emotional_arousal": self.emotional_arousal,
            "importance": self.importance,
            "related_episodes": list(self.related_episodes),
            "parent_episode_id": self.parent_episode_id,
            "sub_episode_ids": list(self.sub_episode_ids),
            "status": self.status.value,
            "tags": list(self.tags),
        }


@dataclass
class MemoryGraphNode:
    """Node in memory knowledge graph."""
    node_id: str = field(default_factory=lambda: f"node-{uuid.uuid4().hex[:12]}")
    concept: str = ""
    concept_type: str = "entity"  # entity, relation, attribute, event
    
    # Node properties
    properties: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5  # 0.0-1.0
    
    # Graph relationships
    outgoing_edges: Dict[str, List[str]] = field(default_factory=dict)  # relation_type -> [target_node_ids]
    incoming_edges: Dict[str, List[str]] = field(default_factory=dict)  # relation_type -> [source_node_ids]
    
    # Temporal information
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    
    # Activation and importance
    activation: float = 0.0
    importance: float = 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "concept": self.concept,
            "concept_type": self.concept_type,
            "properties": self.properties,
            "confidence": self.confidence,
            "outgoing_edges": self.outgoing_edges,
            "incoming_edges": self.incoming_edges,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "activation": self.activation,
            "importance": self.importance,
        }


@dataclass
class MemoryGraphEdge:
    """Edge in memory knowledge graph."""
    edge_id: str = field(default_factory=lambda: f"edge-{uuid.uuid4().hex[:12]}")
    source_node_id: str = ""
    target_node_id: str = ""
    relation_type: str = ""
    
    # Edge properties
    properties: Dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    confidence: float = 0.5
    
    # Temporal information
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "relation_type": self.relation_type,
            "properties": self.properties,
            "weight": self.weight,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
        }


class EpisodicMemory:
    """Episodic memory system for personal experiences."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        
        # Memory storage
        self.fragments: Dict[str, MemoryFragment] = {}
        self.episodes: Dict[str, MemoryEpisode] = {}
        
        # Indexes
        self.tag_index: Dict[str, Set[str]] = {}
        self.category_index: Dict[str, Set[str]] = {}
        self.temporal_index: List[Tuple[float, str]] = []  # (timestamp, fragment_id)
        
    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        # Load existing memories
        await self._load_memories()
        
        logger.info("Connected to EpisodicMemory")
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            
    async def _load_memories(self) -> None:
        """Load existing memories from Redis."""
        try:
            # Load fragments
            cursor = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match="episodic:fragment:*", count=100)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        fragment = MemoryFragment.from_dict(json.loads(data))
                        self.fragments[fragment.fragment_id] = fragment
                        self._update_indexes(fragment)
                        
            # Load episodes
            cursor = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match="episodic:episode:*", count=100)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        episode = MemoryEpisode(**json.loads(data))
                        self.episodes[episode.episode_id] = episode
                        
            logger.info("Loaded %d fragments and %d episodes", 
                       len(self.fragments), len(self.episodes))
                       
        except Exception as exc:
            logger.error("Failed to load memories: %s", exc)
            
    def _update_indexes(self, fragment: MemoryFragment) -> None:
        """Update search indexes."""
        # Tag index
        for tag in fragment.tags:
            if tag not in self.tag_index:
                self.tag_index[tag] = set()
            self.tag_index[tag].add(fragment.fragment_id)
            
        # Category index
        for category in fragment.categories:
            if category not in self.category_index:
                self.category_index[category] = set()
            self.category_index[category].add(fragment.fragment_id)
            
        # Temporal index
        self.temporal_index.append((fragment.created_at, fragment.fragment_id))
        self.temporal_index.sort(key=lambda x: x[0], reverse=True)
        
    async def store_fragment(self, fragment: MemoryFragment) -> str:
        """Store memory fragment."""
        # Update access time
        fragment.last_accessed = time.time()
        fragment.access_count += 1
        
        # Store in memory
        self.fragments[fragment.fragment_id] = fragment
        self._update_indexes(fragment)
        
        # Store in Redis
        if self._redis:
            key = f"episodic:fragment:{fragment.fragment_id}"
            await self._redis.setex(key, 86400 * 30, json.dumps(fragment.to_dict()))  # 30 days
            
        logger.debug("Stored fragment %s", fragment.fragment_id)
        return fragment.fragment_id
        
    async def store_episode(self, episode: MemoryEpisode) -> str:
        """Store memory episode."""
        # Calculate duration if not set
        if episode.end_time and not episode.duration:
            episode.duration = episode.end_time - episode.start_time
            
        # Store in memory
        self.episodes[episode.episode_id] = episode
        
        # Store in Redis
        if self._redis:
            key = f"episodic:episode:{episode.episode_id}"
            await self._redis.setex(key, 86400 * 90, json.dumps(episode.to_dict()))  # 90 days
            
        logger.debug("Stored episode %s", episode.episode_id)
        return episode.episode_id
        
    async def retrieve_fragments(
        self,
        query: str,
        memory_type: Optional[MemoryType] = None,
        tags: Optional[Set[str]] = None,
        limit: int = 10,
        min_activation: float = 0.1
    ) -> List[MemoryFragment]:
        """Retrieve memory fragments based on query."""
        candidates = []
        
        # Filter by type
        if memory_type:
            candidates = [
                frag for frag in self.fragments.values()
                if frag.memory_type == memory_type
            ]
        else:
            candidates = list(self.fragments.values())
            
        # Filter by tags
        if tags:
            candidates = [
                frag for frag in candidates
                if tags.intersection(frag.tags)
            ]
            
        # Filter by activation
        candidates = [
            frag for frag in candidates
            if frag.calculate_activation() >= min_activation
        ]
        
        # Simple text matching (in real implementation would use semantic search)
        if query:
            query_lower = query.lower()
            candidates = [
                frag for frag in candidates
                if query_lower in frag.content.lower() or
                   query_lower in " ".join(frag.tags).lower()
            ]
            
        # Sort by activation and limit
        candidates.sort(key=lambda f: f.calculate_activation(), reverse=True)
        return candidates[:limit]
        
    async def retrieve_episodes(
        self,
        query: str,
        tags: Optional[Set[str]] = None,
        time_range: Optional[Tuple[float, float]] = None,
        limit: int = 10
    ) -> List[MemoryEpisode]:
        """Retrieve memory episodes."""
        candidates = list(self.episodes.values())
        
        # Filter by tags
        if tags:
            candidates = [
                ep for ep in candidates
                if tags.intersection(ep.tags)
            ]
            
        # Filter by time range
        if time_range:
            start_time, end_time = time_range
            candidates = [
                ep for ep in candidates
                if start_time <= ep.start_time <= end_time
            ]
            
        # Simple text matching
        if query:
            query_lower = query.lower()
            candidates = [
                ep for ep in candidates
                if query_lower in ep.title.lower() or
                   query_lower in ep.description.lower()
            ]
            
        # Sort by importance and limit
        candidates.sort(key=lambda e: e.importance, reverse=True)
        return candidates[:limit]
        
    async def consolidate_memory(self, fragment_id: str) -> bool:
        """Consolidate memory fragment."""
        if fragment_id not in self.fragments:
            return False
            
        fragment = self.fragments[fragment_id]
        
        if not fragment.should_consolidate():
            return False
            
        # Update consolidation strength
        fragment.consolidation_strength = min(1.0, fragment.consolidation_strength + 0.2)
        fragment.rehearsal_count += 1
        fragment.status = MemoryStatus.CONSOLIDATED
        
        # Store updated fragment
        await self.store_fragment(fragment)
        
        logger.debug("Consolidated fragment %s", fragment_id)
        return True
        
    async def forget_fragment(self, fragment_id: str) -> bool:
        """Forget memory fragment."""
        if fragment_id not in self.fragments:
            return False
            
        fragment = self.fragments[fragment_id]
        fragment.status = MemoryStatus.FORGOTTEN
        
        # Remove from Redis
        if self._redis:
            key = f"episodic:fragment:{fragment_id}"
            await self._redis.delete(key)
            
        # Remove from memory
        del self.fragments[fragment_id]
        
        # Update indexes
        for tag in fragment.tags:
            if tag in self.tag_index and fragment_id in self.tag_index[tag]:
                self.tag_index[tag].remove(fragment_id)
                
        for category in fragment.categories:
            if category in self.category_index and fragment_id in self.category_index[category]:
                self.category_index[category].remove(fragment_id)
                
        # Remove from temporal index
        self.temporal_index = [
            (ts, fid) for ts, fid in self.temporal_index
            if fid != fragment_id
        ]
        
        logger.debug("Forgot fragment %s", fragment_id)
        return True


class ProceduralMemory:
    """Procedural memory system for skills and procedures."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        
        # Procedure storage
        self.procedures: Dict[str, Dict[str, Any]] = {}
        self.skill_levels: Dict[str, float] = {}
        
        # Performance tracking
        self.performance_history: Dict[str, List[Dict[str, Any]]] = {}
        
    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        # Load existing procedures
        await self._load_procedures()
        
        logger.info("Connected to ProceduralMemory")
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            
    async def _load_procedures(self) -> None:
        """Load existing procedures from Redis."""
        try:
            cursor = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match="procedural:*", count=100)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        procedure_id = key.split(":")[-1]
                        self.procedures[procedure_id] = json.loads(data)
                        
        except Exception as exc:
            logger.error("Failed to load procedures: %s", exc)
            
    async def store_procedure(
        self,
        procedure_id: str,
        steps: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Store procedural memory."""
        procedure = {
            "procedure_id": procedure_id,
            "steps": steps,
            "metadata": metadata or {},
            "created_at": time.time(),
            "last_practiced": time.time(),
            "practice_count": 0,
            "success_rate": 0.0,
            "average_time": 0.0,
        }
        
        self.procedures[procedure_id] = procedure
        
        # Store in Redis
        if self._redis:
            key = f"procedural:{procedure_id}"
            await self._redis.setex(key, 86400 * 365, json.dumps(procedure))  # 1 year
            
        logger.debug("Stored procedure %s", procedure_id)
        return procedure_id
        
    async def practice_procedure(
        self,
        procedure_id: str,
        execution_time: float,
        success: bool,
        errors: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Record practice session for procedure."""
        if procedure_id not in self.procedures:
            raise ValueError(f"Procedure {procedure_id} not found")
            
        procedure = self.procedures[procedure_id]
        
        # Update practice statistics
        procedure["practice_count"] += 1
        procedure["last_practiced"] = time.time()
        
        # Update performance history
        if procedure_id not in self.performance_history:
            self.performance_history[procedure_id] = []
            
        performance_record = {
            "timestamp": time.time(),
            "execution_time": execution_time,
            "success": success,
            "errors": errors or [],
        }
        
        self.performance_history[procedure_id].append(performance_record)
        
        # Keep only last 100 records
        if len(self.performance_history[procedure_id]) > 100:
            self.performance_history[procedure_id] = self.performance_history[procedure_id][-100:]
            
        # Update success rate
        recent_performances = self.performance_history[procedure_id][-20:]  # Last 20 practices
        success_count = sum(1 for p in recent_performances if p["success"])
        procedure["success_rate"] = success_count / len(recent_performances)
        
        # Update average time
        successful_times = [
            p["execution_time"] for p in recent_performances
            if p["success"]
        ]
        if successful_times:
            procedure["average_time"] = sum(successful_times) / len(successful_times)
            
        # Update skill level
        await self._update_skill_level(procedure_id)
        
        # Store updated procedure
        if self._redis:
            key = f"procedural:{procedure_id}"
            await self._redis.setex(key, 86400 * 365, json.dumps(procedure))
            
        return performance_record
        
    async def _update_skill_level(self, procedure_id: str) -> None:
        """Update skill level based on performance."""
        if procedure_id not in self.procedures:
            return
            
        procedure = self.procedures[procedure_id]
        
        # Calculate skill level based on success rate and practice count
        success_rate = procedure["success_rate"]
        practice_count = procedure["practice_count"]
        
        # Skill level formula
        if practice_count < 5:
            skill_level = 0.1  # Beginner
        elif practice_count < 20:
            skill_level = 0.3 + (success_rate * 0.2)  # Intermediate
        elif practice_count < 50:
            skill_level = 0.5 + (success_rate * 0.3)  # Advanced
        else:
            skill_level = 0.7 + (success_rate * 0.3)  # Expert
            
        self.skill_levels[procedure_id] = skill_level
        
    def get_procedure_performance(self, procedure_id: str) -> Dict[str, Any]:
        """Get performance statistics for procedure."""
        if procedure_id not in self.procedures:
            return {}
            
        procedure = self.procedures[procedure_id]
        
        return {
            "procedure_id": procedure_id,
            "practice_count": procedure["practice_count"],
            "success_rate": procedure["success_rate"],
            "average_time": procedure["average_time"],
            "skill_level": self.skill_levels.get(procedure_id, 0.0),
            "last_practiced": procedure["last_practiced"],
            "recent_performances": self.performance_history.get(procedure_id, [])[-10:],
        }


class GraphMemory:
    """Graph-based memory system for knowledge relationships."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        
        # Graph storage
        self.nodes: Dict[str, MemoryGraphNode] = {}
        self.edges: Dict[str, MemoryGraphEdge] = {}
        
        # Indexes
        self.concept_index: Dict[str, str] = {}  # concept -> node_id
        self.relation_index: Dict[str, Set[str]] = {}  # relation_type -> edge_ids
        
    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        # Load existing graph
        await self._load_graph()
        
        logger.info("Connected to GraphMemory")
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            
    async def _load_graph(self) -> None:
        """Load existing graph from Redis."""
        try:
            # Load nodes
            cursor = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match="graph:node:*", count=100)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        node = MemoryGraphNode(**json.loads(data))
                        self.nodes[node.node_id] = node
                        self.concept_index[node.concept] = node.node_id
                        
            # Load edges
            cursor = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match="graph:edge:*", count=100)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        edge = MemoryGraphEdge(**json.loads(data))
                        self.edges[edge.edge_id] = edge
                        
                        # Update relation index
                        if edge.relation_type not in self.relation_index:
                            self.relation_index[edge.relation_type] = set()
                        self.relation_index[edge.relation_type].add(edge.edge_id)
                        
            logger.info("Loaded %d nodes and %d edges", len(self.nodes), len(self.edges))
            
        except Exception as exc:
            logger.error("Failed to load graph: %s", exc)
            
    async def add_node(
        self,
        concept: str,
        concept_type: str = "entity",
        properties: Optional[Dict[str, Any]] = None,
        confidence: float = 0.5
    ) -> str:
        """Add node to knowledge graph."""
        # Check if concept already exists
        if concept in self.concept_index:
            return self.concept_index[concept]
            
        node = MemoryGraphNode(
            concept=concept,
            concept_type=concept_type,
            properties=properties or {},
            confidence=confidence,
        )
        
        self.nodes[node.node_id] = node
        self.concept_index[concept] = node.node_id
        
        # Store in Redis
        if self._redis:
            key = f"graph:node:{node.node_id}"
            await self._redis.setex(key, 86400 * 365, json.dumps(node.to_dict()))  # 1 year
            
        logger.debug("Added node %s for concept %s", node.node_id, concept)
        return node.node_id
        
    async def add_edge(
        self,
        source_concept: str,
        target_concept: str,
        relation_type: str,
        properties: Optional[Dict[str, Any]] = None,
        weight: float = 1.0,
        confidence: float = 0.5
    ) -> str:
        """Add edge to knowledge graph."""
        # Get or create nodes
        source_node_id = await self.add_node(source_concept)
        target_node_id = await self.add_node(target_concept)
        
        # Create edge
        edge = MemoryGraphEdge(
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            relation_type=relation_type,
            properties=properties or {},
            weight=weight,
            confidence=confidence,
        )
        
        self.edges[edge.edge_id] = edge
        
        # Update node relationships
        source_node = self.nodes[source_node_id]
        target_node = self.nodes[target_node_id]
        
        if relation_type not in source_node.outgoing_edges:
            source_node.outgoing_edges[relation_type] = []
        source_node.outgoing_edges[relation_type].append(target_node_id)
        
        if relation_type not in target_node.incoming_edges:
            target_node.incoming_edges[relation_type] = []
        target_node.incoming_edges[relation_type].append(source_node_id)
        
        # Update relation index
        if relation_type not in self.relation_index:
            self.relation_index[relation_type] = set()
        self.relation_index[relation_type].add(edge.edge_id)
        
        # Store in Redis
        if self._redis:
            key = f"graph:edge:{edge.edge_id}"
            await self._redis.setex(key, 86400 * 365, json.dumps(edge.to_dict()))  # 1 year
            
            # Update nodes
            source_key = f"graph:node:{source_node_id}"
            await self._redis.setex(source_key, 86400 * 365, json.dumps(source_node.to_dict()))
            
            target_key = f"graph:node:{target_node_id}"
            await self._redis.setex(target_key, 86400 * 365, json.dumps(target_node.to_dict()))
            
        logger.debug("Added edge %s: %s -> %s (%s)", 
                    edge.edge_id, source_concept, target_concept, relation_type)
        return edge.edge_id
        
    async def find_related_concepts(
        self,
        concept: str,
        relation_types: Optional[List[str]] = None,
        max_depth: int = 2,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Find concepts related to given concept."""
        if concept not in self.concept_index:
            return []
            
        start_node_id = self.concept_index[concept]
        visited = set()
        results = []
        
        async def explore(node_id: str, depth: int, path: List[str]) -> None:
            if depth > max_depth or node_id in visited or len(results) >= limit:
                return
                
            visited.add(node_id)
            node = self.nodes[node_id]
            
            if depth > 0:  # Don't include the starting node
                results.append({
                    "concept": node.concept,
                    "concept_type": node.concept_type,
                    "depth": depth,
                    "path": path.copy(),
                    "confidence": node.confidence,
                    "properties": node.properties,
                })
                
            # Explore outgoing edges
            for rel_type, target_ids in node.outgoing_edges.items():
                if relation_types and rel_type not in relation_types:
                    continue
                    
                for target_id in target_ids:
                    new_path = path + [f"{node.concept} -> {rel_type} -> {self.nodes[target_id].concept}"]
                    await explore(target_id, depth + 1, new_path)
                    
        await explore(start_node_id, 0, [])
        return results[:limit]
        
    async def get_concept_info(self, concept: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a concept."""
        if concept not in self.concept_index:
            return None
            
        node_id = self.concept_index[concept]
        node = self.nodes[node_id]
        
        # Get related concepts
        related = await self.find_related_concepts(concept, max_depth=1)
        
        return {
            "concept": concept,
            "concept_type": node.concept_type,
            "properties": node.properties,
            "confidence": node.confidence,
            "activation": node.activation,
            "importance": node.importance,
            "created_at": node.created_at,
            "last_updated": node.last_updated,
            "related_concepts": related,
            "outgoing_relations": {
                rel_type: len(target_ids)
                for rel_type, target_ids in node.outgoing_edges.items()
            },
            "incoming_relations": {
                rel_type: len(source_ids)
                for rel_type, source_ids in node.incoming_edges.items()
            },
        }


class AdvancedMemorySystem:
    """Integrated advanced memory system."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        
        # Memory systems
        self.episodic_memory = EpisodicMemory(redis_url)
        self.procedural_memory = ProceduralMemory(redis_url)
        self.graph_memory = GraphMemory(redis_url)
        
        # Consolidation and maintenance
        self.consolidation_task: Optional[asyncio.Task] = None
        self.maintenance_task: Optional[asyncio.Task] = None
        
    async def initialize(self) -> None:
        """Initialize all memory systems."""
        await self.episodic_memory.connect()
        await self.procedural_memory.connect()
        await self.graph_memory.connect()
        
        # Start background tasks
        self.consolidation_task = asyncio.create_task(self._consolidation_loop())
        self.maintenance_task = asyncio.create_task(self._maintenance_loop())
        
        logger.info("Advanced Memory System initialized")
        
    async def shutdown(self) -> None:
        """Shutdown all memory systems."""
        if self.consolidation_task:
            self.consolidation_task.cancel()
        if self.maintenance_task:
            self.maintenance_task.cancel()
            
        await self.episodic_memory.disconnect()
        await self.procedural_memory.disconnect()
        await self.graph_memory.disconnect()
        
        logger.info("Advanced Memory System shutdown")
        
    async def _consolidation_loop(self) -> None:
        """Background memory consolidation loop."""
        while True:
            try:
                await asyncio.sleep(3600)  # 1 hour
                
                # Consolidate eligible memories
                for fragment_id, fragment in self.episodic_memory.fragments.items():
                    if fragment.should_consolidate():
                        await self.episodic_memory.consolidate_memory(fragment_id)
                        
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Consolidation loop error: %s", exc)
                await asyncio.sleep(60)
                
    async def _maintenance_loop(self) -> None:
        """Background maintenance loop."""
        while True:
            try:
                await asyncio.sleep(86400)  # 24 hours
                
                # Forget old, unused memories
                current_time = time.time()
                for fragment_id, fragment in list(self.episodic_memory.fragments.items()):
                    if (
                        fragment.is_expired() or
                        (current_time - fragment.last_accessed > 86400 * 30 and  # 30 days
                         fragment.calculate_activation() < 0.1)
                    ):
                        await self.episodic_memory.forget_fragment(fragment_id)
                        
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Maintenance loop error: %s", exc)
                await asyncio.sleep(3600)
                
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get comprehensive memory statistics."""
        return {
            "episodic": {
                "fragments": len(self.episodic_memory.fragments),
                "episodes": len(self.episodic_memory.episodes),
                "tags": len(self.episodic_memory.tag_index),
                "categories": len(self.episodic_memory.category_index),
            },
            "procedural": {
                "procedures": len(self.procedural_memory.procedures),
                "skill_levels": len(self.procedural_memory.skill_levels),
            },
            "graph": {
                "nodes": len(self.graph_memory.nodes),
                "edges": len(self.graph_memory.edges),
                "concepts": len(self.graph_memory.concept_index),
                "relations": len(self.graph_memory.relation_index),
            },
        }


# Global memory system instance
advanced_memory: Optional[AdvancedMemorySystem] = None