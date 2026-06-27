"""Cross-Session Memory — Persistent memory system for agents across sessions.

This module provides:
- Cross-session memory persistence
- Context continuity management
- Session linking and recovery
- Memory consolidation and optimization
- Intelligent memory retrieval
"""

from __future__ import annotations

import asyncio
import logging
import json
import pickle
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Set, TYPE_CHECKING
from dataclasses import dataclass, field
from enum import Enum
import uuid

import redis
import numpy as np

if TYPE_CHECKING:
    from backend.knowledge.memory import MemorySystem

from backend.observability.event_bus import EventBus
from backend.observability.events import Event

logger = logging.getLogger(__name__)


class MemoryType(Enum):
    """Types of memory stored across sessions."""
    EPISODIC = "episodic"         # Episode-based memories
    PROCEDURAL = "procedural"     # Skill and procedure memories
    SEMANTIC = "semantic"         # Knowledge and facts
    WORKING = "working"           # Current working memory
    LONG_TERM = "long_term"       # Long-term persistent memory


class MemoryStatus(Enum):
    """Status of memory items."""
    ACTIVE = "active"             # Currently in use
    DORMANT = "dormant"           # Not recently used
    CONSOLIDATED = "consolidated" # Consolidated into long-term
    ARCHIVED = "archived"         # Archived for storage
    DEPRECATED = "deprecated"     # Outdated memory


@dataclass
class CrossSessionMemory:
    """Represents a cross-session memory item."""
    memory_id: str
    agent_id: str
    memory_type: MemoryType
    content: Dict[str, Any]
    context: Dict[str, Any]
    session_ids: List[str]
    created_at: datetime
    last_accessed: datetime
    access_count: int
    importance_score: float
    retrieval_count: int
    status: MemoryStatus
    tags: List[str] = field(default_factory=list)
    related_memories: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionLink:
    """Represents a link between sessions."""
    link_id: str
    source_session_id: str
    target_session_id: str
    link_type: str
    strength: float
    shared_memories: List[str]
    created_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryConsolidation:
    """Represents a memory consolidation process."""
    consolidation_id: str
    agent_id: str
    source_memories: List[str]
    consolidated_memory: str
    consolidation_type: str
    timestamp: datetime
    effectiveness_score: float


class CrossSessionMemoryManager:
    """Manages cross-session memory persistence and retrieval."""
    
    def __init__(self, memory_system: MemorySystem, event_bus: EventBus, 
                 redis_client: redis.Redis = None):
        self.memory_system = memory_system
        self.event_bus = event_bus
        self.redis_client = redis_client
        
        # Memory storage
        self.cross_session_memories: Dict[str, CrossSessionMemory] = {}
        self.session_links: Dict[str, SessionLink] = {}
        self.consolidation_history: List[MemoryConsolidation] = []
        
        # Session tracking
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.session_memories: Dict[str, List[str]] = {}
        
        # Memory optimization
        self.memory_index: Dict[str, Set[str]] = {}  # Tag-based index
        self.agent_memory_index: Dict[str, List[str]] = {}  # Agent-based index
        
        # Configuration
        self.max_memory_per_agent = 10000
        self.consolidation_threshold = 100
        self.dormancy_threshold_days = 30
        
        # Start background tasks
        self._consolidation_task = asyncio.create_task(self._periodic_consolidation())
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
    
    async def store_memory(self, agent_id: str, session_id: str, 
                          memory_type: MemoryType, content: Dict[str, Any],
                          context: Dict[str, Any] = None, 
                          importance_score: float = 0.5) -> str:
        """Store a memory item across sessions."""
        
        memory_id = str(uuid.uuid4())
        
        # Create cross-session memory
        memory = CrossSessionMemory(
            memory_id=memory_id,
            agent_id=agent_id,
            memory_type=memory_type,
            content=content,
            context=context or {},
            session_ids=[session_id],
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            access_count=1,
            importance_score=importance_score,
            retrieval_count=0,
            status=MemoryStatus.ACTIVE,
            tags=self._extract_tags(content, context)
        )
        
        # Store memory
        self.cross_session_memories[memory_id] = memory
        
        # Update indexes
        self._update_memory_indexes(memory)
        
        # Track session memories
        if session_id not in self.session_memories:
            self.session_memories[session_id] = []
        self.session_memories[session_id].append(memory_id)
        
        # Store in persistent storage if available
        if self.redis_client:
            await self._store_in_redis(memory)
        
        # Emit storage event
        await self.event_bus.emit(Event(
            type="cross_session_memory_stored",
            data={
                "memory_id": memory_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "memory_type": memory_type.value,
                "importance_score": importance_score
            }
        ))
        
        logger.info(f"Cross-session memory stored: {memory_id} for agent {agent_id}")
        
        return memory_id
    
    async def retrieve_memory(self, memory_id: str, session_id: str = None) -> Optional[CrossSessionMemory]:
        """Retrieve a memory item."""
        
        if memory_id not in self.cross_session_memories:
            return None
        
        memory = self.cross_session_memories[memory_id]
        
        # Update access statistics
        memory.last_accessed = datetime.now()
        memory.access_count += 1
        memory.retrieval_count += 1
        
        # Add session to memory's session list if provided
        if session_id and session_id not in memory.session_ids:
            memory.session_ids.append(session_id)
            
            # Update session memories
            if session_id not in self.session_memories:
                self.session_memories[session_id] = []
            self.session_memories[session_id].append(memory_id)
        
        # Update status if needed
        if memory.status == MemoryStatus.DORMANT:
            memory.status = MemoryStatus.ACTIVE
        
        # Emit retrieval event
        await self.event_bus.emit(Event(
            type="cross_session_memory_retrieved",
            data={
                "memory_id": memory_id,
                "agent_id": memory.agent_id,
                "access_count": memory.access_count,
                "retrieval_count": memory.retrieval_count
            }
        ))
        
        return memory
    
    async def search_memories(self, agent_id: str, query: str, 
                            memory_type: MemoryType = None,
                            session_id: str = None,
                            limit: int = 100) -> List[CrossSessionMemory]:
        """Search for memories based on query."""
        
        results = []
        
        # Get candidate memories
        if memory_type:
            candidates = [m for m in self.cross_session_memories.values() 
                        if m.agent_id == agent_id and m.memory_type == memory_type]
        else:
            candidates = [m for m in self.cross_session_memories.values() 
                        if m.agent_id == agent_id]
        
        # Filter by session if specified
        if session_id:
            candidates = [m for m in candidates if session_id in m.session_ids]
        
        # Simple text search (can be enhanced with vector search)
        query_lower = query.lower()
        for memory in candidates:
            # Search in content
            content_text = json.dumps(memory.content).lower()
            if query_lower in content_text:
                results.append(memory)
                continue
            
            # Search in context
            context_text = json.dumps(memory.context).lower()
            if query_lower in context_text:
                results.append(memory)
                continue
            
            # Search in tags
            if any(query_lower in tag.lower() for tag in memory.tags):
                results.append(memory)
        
        # Sort by relevance (importance_score * retrieval_count)
        results.sort(key=lambda m: m.importance_score * (m.retrieval_count + 1), reverse=True)
        
        return results[:limit]
    
    async def link_sessions(self, source_session_id: str, target_session_id: str,
                          link_type: str, shared_memories: List[str] = None) -> str:
        """Create a link between sessions."""
        
        link_id = str(uuid.uuid4())
        
        # Calculate link strength based on shared memories
        if shared_memories is None:
            source_memories = set(self.session_memories.get(source_session_id, []))
            target_memories = set(self.session_memories.get(target_session_id, []))
            shared_memories = list(source_memories & target_memories)
        
        strength = len(shared_memories) / max(
            len(self.session_memories.get(source_session_id, [])),
            len(self.session_memories.get(target_session_id, [])),
            1
        )
        
        # Create session link
        link = SessionLink(
            link_id=link_id,
            source_session_id=source_session_id,
            target_session_id=target_session_id,
            link_type=link_type,
            strength=strength,
            shared_memories=shared_memories,
            created_at=datetime.now()
        )
        
        self.session_links[link_id] = link
        
        # Update related memories
        for memory_id in shared_memories:
            if memory_id in self.cross_session_memories:
                memory = self.cross_session_memories[memory_id]
                if target_session_id not in memory.session_ids:
                    memory.session_ids.append(target_session_id)
        
        # Emit link event
        await self.event_bus.emit(Event(
            type="sessions_linked",
            data={
                "link_id": link_id,
                "source_session_id": source_session_id,
                "target_session_id": target_session_id,
                "link_type": link_type,
                "strength": strength,
                "shared_memories_count": len(shared_memories)
            }
        ))
        
        logger.info(f"Sessions linked: {source_session_id} -> {target_session_id}")
        
        return link_id
    
    async def get_session_continuity(self, session_id: str) -> Dict[str, Any]:
        """Get session continuity information."""
        
        # Find linked sessions
        linked_sessions = []
        for link in self.session_links.values():
            if link.source_session_id == session_id:
                linked_sessions.append({
                    "session_id": link.target_session_id,
                    "link_type": link.link_type,
                    "strength": link.strength,
                    "shared_memories": len(link.shared_memories)
                })
            elif link.target_session_id == session_id:
                linked_sessions.append({
                    "session_id": link.source_session_id,
                    "link_type": link.link_type,
                    "strength": link.strength,
                    "shared_memories": len(link.shared_memories)
                })
        
        # Get session memories
        session_memory_ids = self.session_memories.get(session_id, [])
        session_memories = []
        for memory_id in session_memory_ids:
            if memory_id in self.cross_session_memories:
                memory = self.cross_session_memories[memory_id]
                session_memories.append({
                    "memory_id": memory_id,
                    "memory_type": memory.memory_type.value,
                    "importance_score": memory.importance_score,
                    "access_count": memory.access_count,
                    "tags": memory.tags
                })
        
        return {
            "session_id": session_id,
            "linked_sessions": linked_sessions,
            "memory_count": len(session_memories),
            "memories_by_type": self._group_memories_by_type(session_memories),
            "continuity_score": self._calculate_continuity_score(session_id)
        }
    
    async def consolidate_memories(self, agent_id: str, memory_type: MemoryType = None) -> List[str]:
        """Consolidate memories for an agent."""
        
        # Get memories to consolidate
        memories_to_consolidate = []
        for memory in self.cross_session_memories.values():
            if memory.agent_id == agent_id:
                if memory_type is None or memory.memory_type == memory_type:
                    if memory.status == MemoryStatus.ACTIVE and memory.access_count > 1:
                        memories_to_consolidate.append(memory)
        
        # Group similar memories
        consolidated_groups = self._group_similar_memories(memories_to_consolidate)
        
        consolidation_results = []
        
        for group in consolidated_groups:
            if len(group) > 1:  # Only consolidate groups with multiple memories
                consolidated_memory_id = await self._create_consolidated_memory(group)
                consolidation_results.append(consolidated_memory_id)
        
        return consolidation_results
    
    async def _create_consolidated_memory(self, memories: List[CrossSessionMemory]) -> str:
        """Create a consolidated memory from a group of similar memories."""
        
        if not memories:
            return ""
        
        # Create consolidated content
        consolidated_content = {
            "original_memories": [m.memory_id for m in memories],
            "consolidated_data": self._merge_memory_contents(memories),
            "consolidation_timestamp": datetime.now().isoformat(),
            "source_types": [m.memory_type.value for m in memories]
        }
        
        # Determine the most common memory type
        type_counts = {}
        for memory in memories:
            type_counts[memory.memory_type] = type_counts.get(memory.memory_type, 0) + 1
        
        dominant_type = max(type_counts, key=type_counts.get)
        
        # Calculate combined importance
        combined_importance = sum(m.importance_score for m in memories) / len(memories)
        
        # Merge contexts
        merged_context = {}
        for memory in memories:
            merged_context.update(memory.context)
        
        # Merge session IDs
        all_session_ids = []
        for memory in memories:
            all_session_ids.extend(memory.session_ids)
        unique_session_ids = list(set(all_session_ids))
        
        # Store consolidated memory
        consolidated_memory_id = await self.store_memory(
            agent_id=memories[0].agent_id,
            session_id=unique_session_ids[0] if unique_session_ids else "consolidated",
            memory_type=dominant_type,
            content=consolidated_content,
            context=merged_context,
            importance_score=combined_importance
        )
        
        # Mark original memories as consolidated
        for memory in memories:
            memory.status = MemoryStatus.CONSOLIDATED
            memory.related_memories.append(consolidated_memory_id)
        
        # Record consolidation
        consolidation = MemoryConsolidation(
            consolidation_id=str(uuid.uuid4()),
            agent_id=memories[0].agent_id,
            source_memories=[m.memory_id for m in memories],
            consolidated_memory=consolidated_memory_id,
            consolidation_type="automatic",
            timestamp=datetime.now(),
            effectiveness_score=0.0  # Will be updated based on usage
        )
        
        self.consolidation_history.append(consolidation)
        
        # Emit consolidation event
        await self.event_bus.emit(Event(
            type="memory_consolidated",
            data={
                "consolidation_id": consolidation.consolidation_id,
                "agent_id": consolidation.agent_id,
                "source_count": len(memories),
                "consolidated_memory_id": consolidated_memory_id
            }
        ))
        
        logger.info(f"Memory consolidated: {consolidated_memory_id} from {len(memories)} memories")
        
        return consolidated_memory_id
    
    def _extract_tags(self, content: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
        """Extract tags from content and context."""
        
        tags = []
        
        # Extract from content keys
        tags.extend(content.keys())
        
        # Extract from context
        tags.extend(context.keys())
        
        # Extract from content values (simple text extraction)
        for value in content.values():
            if isinstance(value, str):
                # Simple keyword extraction
                words = value.lower().split()
                tags.extend([word for word in words if len(word) > 3])
        
        # Remove duplicates and limit
        unique_tags = list(set(tags))
        return unique_tags[:20]  # Limit to 20 tags
    
    def _update_memory_indexes(self, memory: CrossSessionMemory) -> None:
        """Update memory indexes for efficient retrieval."""
        
        # Update tag index
        for tag in memory.tags:
            if tag not in self.memory_index:
                self.memory_index[tag] = set()
            self.memory_index[tag].add(memory.memory_id)
        
        # Update agent index
        if memory.agent_id not in self.agent_memory_index:
            self.agent_memory_index[memory.agent_id] = []
        self.agent_memory_index[memory.agent_id].append(memory.memory_id)
    
    def _group_memories_by_type(self, memories: List[Dict[str, Any]]) -> Dict[str, int]:
        """Group memories by type."""
        
        type_counts = {}
        for memory in memories:
            memory_type = memory["memory_type"]
            type_counts[memory_type] = type_counts.get(memory_type, 0) + 1
        
        return type_counts
    
    def _calculate_continuity_score(self, session_id: str) -> float:
        """Calculate continuity score for a session."""
        
        # Get linked sessions
        linked_count = 0
        total_strength = 0.0
        
        for link in self.session_links.values():
            if link.source_session_id == session_id or link.target_session_id == session_id:
                linked_count += 1
                total_strength += link.strength
        
        if linked_count == 0:
            return 0.0
        
        # Calculate average strength
        avg_strength = total_strength / linked_count
        
        # Consider memory count
        memory_count = len(self.session_memories.get(session_id, []))
        memory_factor = min(1.0, memory_count / 10.0)  # Normalize to 0-1
        
        # Combined score
        return (avg_strength * 0.7 + memory_factor * 0.3)
    
    def _group_similar_memories(self, memories: List[CrossSessionMemory]) -> List[List[CrossSessionMemory]]:
        """Group similar memories for consolidation."""
        
        groups = []
        
        # Simple grouping by memory type and tags
        type_groups = {}
        for memory in memories:
            key = (memory.memory_type, tuple(sorted(memory.tags[:5])))  # Use first 5 tags
            if key not in type_groups:
                type_groups[key] = []
            type_groups[key].append(memory)
        
        # Filter groups with multiple memories
        for group in type_groups.values():
            if len(group) > 1:
                groups.append(group)
        
        return groups
    
    def _merge_memory_contents(self, memories: List[CrossSessionMemory]) -> Dict[str, Any]:
        """Merge contents of similar memories."""
        
        merged = {}
        
        # Merge all content
        for memory in memories:
            for key, value in memory.content.items():
                if key not in merged:
                    merged[key] = []
                merged[key].append(value)
        
        # Process merged values
        for key, values in merged.items():
            if all(isinstance(v, (int, float)) for v in values):
                # Numeric values - take average
                merged[key] = sum(values) / len(values)
            elif all(isinstance(v, str) for v in values):
                # String values - concatenate
                merged[key] = " | ".join(values)
            elif all(isinstance(v, list) for v in values):
                # List values - extend
                merged[key] = []
                for v in values:
                    merged[key].extend(v)
            else:
                # Mixed types - keep all
                merged[key] = values
        
        return merged
    
    async def _store_in_redis(self, memory: CrossSessionMemory) -> None:
        """Store memory in Redis for persistence."""
        
        if not self.redis_client:
            return
        
        try:
            # Serialize memory
            memory_data = {
                "memory_id": memory.memory_id,
                "agent_id": memory.agent_id,
                "memory_type": memory.memory_type.value,
                "content": memory.content,
                "context": memory.context,
                "session_ids": memory.session_ids,
                "created_at": memory.created_at.isoformat(),
                "last_accessed": memory.last_accessed.isoformat(),
                "access_count": memory.access_count,
                "importance_score": memory.importance_score,
                "retrieval_count": memory.retrieval_count,
                "status": memory.status.value,
                "tags": memory.tags,
                "related_memories": memory.related_memories,
                "metadata": memory.metadata
            }
            
            # Store with TTL (30 days)
            await self.redis_client.setex(
                f"cross_session_memory:{memory.memory_id}",
                30 * 24 * 3600,  # 30 days in seconds
                json.dumps(memory_data)
            )
            
        except Exception as e:
            logger.error(f"Failed to store memory in Redis: {e}")
    
    async def _load_from_redis(self, memory_id: str) -> Optional[CrossSessionMemory]:
        """Load memory from Redis."""
        
        if not self.redis_client:
            return None
        
        try:
            data = await self.redis_client.get(f"cross_session_memory:{memory_id}")
            if not data:
                return None
            
            memory_data = json.loads(data)
            
            # Reconstruct memory object
            memory = CrossSessionMemory(
                memory_id=memory_data["memory_id"],
                agent_id=memory_data["agent_id"],
                memory_type=MemoryType(memory_data["memory_type"]),
                content=memory_data["content"],
                context=memory_data["context"],
                session_ids=memory_data["session_ids"],
                created_at=datetime.fromisoformat(memory_data["created_at"]),
                last_accessed=datetime.fromisoformat(memory_data["last_accessed"]),
                access_count=memory_data["access_count"],
                importance_score=memory_data["importance_score"],
                retrieval_count=memory_data["retrieval_count"],
                status=MemoryStatus(memory_data["status"]),
                tags=memory_data["tags"],
                related_memories=memory_data["related_memories"],
                metadata=memory_data["metadata"]
            )
            
            return memory
            
        except Exception as e:
            logger.error(f"Failed to load memory from Redis: {e}")
            return None
    
    async def _periodic_consolidation(self) -> None:
        """Background task for periodic memory consolidation."""
        
        while True:
            try:
                # Check each agent for consolidation needs
                agent_ids = set(m.agent_id for m in self.cross_session_memories.values())
                
                for agent_id in agent_ids:
                    # Count active memories for this agent
                    active_memories = [m for m in self.cross_session_memories.values() 
                                    if m.agent_id == agent_id and m.status == MemoryStatus.ACTIVE]
                    
                    # Consolidate if too many active memories
                    if len(active_memories) > self.consolidation_threshold:
                        await self.consolidate_memories(agent_id)
                
                # Sleep for 1 hour
                await asyncio.sleep(3600)
                
            except Exception as e:
                logger.error(f"Error in periodic consolidation: {e}")
                await asyncio.sleep(300)
    
    async def _periodic_cleanup(self) -> None:
        """Background task for periodic cleanup of old memories."""
        
        while True:
            try:
                now = datetime.now()
                cutoff_date = now - timedelta(days=self.dormancy_threshold_days)
                
                # Find dormant memories
                dormant_memories = []
                for memory_id, memory in self.cross_session_memories.items():
                    if (memory.status == MemoryStatus.ACTIVE and 
                        memory.last_accessed < cutoff_date and
                        memory.importance_score < 0.7):
                        dormant_memories.append(memory_id)
                
                # Mark as dormant
                for memory_id in dormant_memories:
                    if memory_id in self.cross_session_memories:
                        self.cross_session_memories[memory_id].status = MemoryStatus.DORMANT
                
                if dormant_memories:
                    logger.info(f"Marked {len(dormant_memories)} memories as dormant")
                
                # Sleep for 24 hours
                await asyncio.sleep(24 * 3600)
                
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {e}")
                await asyncio.sleep(3600)
    
    async def get_memory_statistics(self, agent_id: str = None) -> Dict[str, Any]:
        """Get memory statistics."""
        
        memories = list(self.cross_session_memories.values())
        
        if agent_id:
            memories = [m for m in memories if m.agent_id == agent_id]
        
        # Calculate statistics
        total_memories = len(memories)
        memories_by_type = {}
        memories_by_status = {}
        
        total_access_count = 0
        total_retrieval_count = 0
        avg_importance = 0.0
        
        for memory in memories:
            # By type
            memory_type = memory.memory_type.value
            memories_by_type[memory_type] = memories_by_type.get(memory_type, 0) + 1
            
            # By status
            status = memory.status.value
            memories_by_status[status] = memories_by_status.get(status, 0) + 1
            
            # Aggregate stats
            total_access_count += memory.access_count
            total_retrieval_count += memory.retrieval_count
            avg_importance += memory.importance_score
        
        if total_memories > 0:
            avg_importance /= total_memories
        
        return {
            "total_memories": total_memories,
            "memories_by_type": memories_by_type,
            "memories_by_status": memories_by_status,
            "total_access_count": total_access_count,
            "total_retrieval_count": total_retrieval_count,
            "average_importance_score": avg_importance,
            "consolidation_count": len(self.consolidation_history),
            "active_sessions": len(self.session_memories),
            "session_links": len(self.session_links)
        }
    
    async def shutdown(self) -> None:
        """Shutdown the cross-session memory manager."""
        
        # Cancel background tasks
        if self._consolidation_task:
            self._consolidation_task.cancel()
            try:
                await self._consolidation_task
            except asyncio.CancelledError:
                pass
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Cross-session memory manager shutdown completed")