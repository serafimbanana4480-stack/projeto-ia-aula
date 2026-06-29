"""Knowledge Graph System - Persistent memory with semantic relationships.

Maintains a graph of entities, concepts, and their relationships across sessions,
enabling cross-session context linking and intelligent query expansion.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict
from enum import Enum
import hashlib

from backend.tools.ollama_client import OllamaClient
from backend.config.settings import get_model_config

logger = logging.getLogger(__name__)


class EntityType(str, Enum):
    """Types of entities in the knowledge graph."""
    CONCEPT = "concept"
    PERSON = "person"
    ORGANIZATION = "organization"
    PROJECT = "project"
    TECHNOLOGY = "technology"
    LOCATION = "location"
    DOCUMENT = "document"
    CODE = "code"
    TASK = "task"
    DECISION = "decision"
    DEBATE = "debate"  # Enhanced Agent Parliament
    AGENT = "agent"  # AI Agent


class RelationType(str, Enum):
    """Types of relationships between entities."""
    RELATED_TO = "related_to"
    PART_OF = "part_of"
    IMPLEMENTS = "implements"
    DEPENDS_ON = "depends_on"
    SIMILAR_TO = "similar_to"
    CONTRASTS_WITH = "contrasts_with"
    EXAMPLE_OF = "example_of"
    DEFINED_BY = "defined_by"
    LOCATED_IN = "located_in"
    WORKS_ON = "works_on"
    USES = "uses"
    REPLACES = "replaces"
    PARTICIPATED_IN = "participated_in"  # Agent participated in debate
    VOTED_ON = "voted_on"  # Agent voted on decision
    ARGUED_FOR = "argued_for"  # Agent argued for position
    LED_TO = "led_to"  # Decision led to outcome
    INFORMED_BY = "informed_by"  # Decision informed by debate


@dataclass
class Entity:
    """An entity in the knowledge graph."""
    id: str
    name: str
    entity_type: EntityType
    description: str
    embedding: Optional[List[float]] = None
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    confidence: float = 1.0
    
    def __post_init__(self) -> None:
        self.id = self.id or self._generate_id()
    
    def _generate_id(self) -> str:
        """Generate a unique ID for the entity."""
        content = f"{self.entity_type}:{self.name}:{self.description}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class Relationship:
    """A relationship between two entities."""
    id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: RelationType
    properties: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    created_at: float = field(default_factory=time.time)
    
    def __post_init__(self) -> None:
        self.id = self.id or self._generate_id()
    
    def _generate_id(self) -> str:
        """Generate a unique ID for the relationship."""
        content = f"{self.source_entity_id}:{self.relation_type}:{self.target_entity_id}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class GraphStats:
    """Statistics about the knowledge graph."""
    total_entities: int = 0
    total_relationships: int = 0
    entities_by_type: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    relationships_by_type: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    avg_connections_per_entity: float = 0.0
    graph_density: float = 0.0


class KnowledgeGraph:
    """Persistent knowledge graph for cross-session memory.
    
    Features:
    - Entity extraction and relationship detection
    - Semantic similarity matching
    - Graph traversal and querying
    - Context linking across sessions
    - Automatic graph maintenance
    """
    
    def __init__(
        self,
        ollama_client: OllamaClient,
        *,
        embedding_model: str = "qwen2.5:0.5b",
        extraction_model: str = "qwen2.5:3b",
        max_entities: int = 50000,
        similarity_threshold: float = 0.7,
        auto_merge: bool = True,
    ) -> None:
        self.ollama = ollama_client
        self.embedding_model = embedding_model
        self.extraction_model = extraction_model
        self.max_entities = max_entities
        self.similarity_threshold = similarity_threshold
        self.auto_merge = auto_merge
        
        # Graph storage
        self._entities: Dict[str, Entity] = {}
        self._relationships: Dict[str, Relationship] = {}
        self._entity_index: Dict[str, Set[str]] = defaultdict(set)  # Name/keyword to entity IDs
        self._type_index: Dict[EntityType, Set[str]] = defaultdict(set)
        
        # Statistics
        self._stats = GraphStats()
        
        # Background tasks
        self._maintenance_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Lock for thread safety
        self._lock = asyncio.Lock()
    
    async def start(self) -> None:
        """Start the knowledge graph system."""
        if self._running:
            return
        
        self._running = True
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())
        
        logger.info("Knowledge Graph started")
    
    async def stop(self) -> None:
        """Stop the knowledge graph system."""
        self._running = False
        if self._maintenance_task:
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass
        logger.info("Knowledge Graph stopped")
    
    async def add_context(self, text: str, session_id: str, context_type: str = "general") -> List[str]:
        """Extract entities and relationships from text and add to graph."""
        async with self._lock:
            # Extract entities and relationships
            entities, relationships = await self._extract_knowledge(text, session_id, context_type)
            
            # Add entities to graph
            added_entity_ids = []
            for entity in entities:
                entity_id = await self._add_entity(entity)
                added_entity_ids.append(entity_id)
            
            # Add relationships to graph
            for relationship in relationships:
                await self._add_relationship(relationship)
            
            logger.debug(
                "Added %d entities and %d relationships from context (session: %s)",
                len(entities), len(relationships), session_id
            )
            
            return added_entity_ids
    
    async def query_entities(
        self,
        query: str,
        entity_types: Optional[List[EntityType]] = None,
        limit: int = 10
    ) -> List[Entity]:
        """Search for entities matching the query."""
        async with self._lock:
            # Generate query embedding
            query_embedding = await self._get_embedding(query)
            
            # Find similar entities
            similar_entities = []
            for entity in self._entities.values():
                if entity_types and entity.entity_type not in entity_types:
                    continue
                
                if entity.embedding:
                    similarity = self._cosine_similarity(query_embedding, entity.embedding)
                    if similarity >= self.similarity_threshold:
                        similar_entities.append((entity, similarity))
            
            # Sort by similarity and return top results
            similar_entities.sort(key=lambda x: x[1], reverse=True)
            return [entity for entity, _ in similar_entities[:limit]]
    
    async def get_related_entities(
        self,
        entity_id: str,
        relation_types: Optional[List[RelationType]] = None,
        max_depth: int = 2
    ) -> List[Tuple[Entity, Relationship, int]]:
        """Get entities related to the given entity."""
        async with self._lock:
            if entity_id not in self._entities:
                return []
            
            related = []
            visited = set()
            queue = [(entity_id, 0, None)]  # (entity_id, depth, incoming_relationship)
            
            while queue and len(related) < 100:  # Limit results
                current_id, depth, incoming_rel = queue.pop(0)
                
                if current_id in visited or depth > max_depth:
                    continue
                
                visited.add(current_id)
                
                # Find relationships
                for rel in self._relationships.values():
                    target_entity = None
                    relationship = None
                    
                    if rel.source_entity_id == current_id:
                        if rel.target_entity_id in self._entities:
                            target_entity = self._entities[rel.target_entity_id]
                            relationship = rel
                    elif rel.target_entity_id == current_id:
                        if rel.source_entity_id in self._entities:
                            target_entity = self._entities[rel.source_entity_id]
                            relationship = rel
                    
                    if target_entity and relationship:
                        if not relation_types or relationship.relation_type in relation_types:
                            related.append((target_entity, relationship, depth))
                        
                        # Add to queue for further exploration
                        next_id = (target_entity.id if rel.source_entity_id == current_id 
                                 else rel.source_entity_id)
                        if next_id not in visited:
                            queue.append((next_id, depth + 1, relationship))
            
            return related
    
    async def expand_query(self, query: str) -> str:
        """Expand a query using related concepts from the knowledge graph."""
        async with self._lock:
            # Find relevant entities
            entities = await self.query_entities(query, limit=5)
            
            if not entities:
                return query
            
            # Get related entities
            expansion_terms = []
            for entity in entities:
                related = await self.get_related_entities(entity.id, max_depth=1)
                for related_entity, _, _ in related[:3]:  # Top 3 related per entity
                    expansion_terms.append(related_entity.name)
            
            # Build expanded query
            if expansion_terms:
                expanded = f"{query} (related concepts: {', '.join(expansion_terms[:5])})"
                return expanded
            
            return query
    
    async def get_context_for_entity(self, entity_id: str, max_context_length: int = 1000) -> str:
        """Get relevant context for an entity."""
        async with self._lock:
            if entity_id not in self._entities:
                return ""
            
            entity = self._entities[entity_id]
            
            # Build context from entity and its relationships
            context_parts = [f"{entity.name}: {entity.description}"]
            
            related = await self.get_related_entities(entity_id, max_depth=1)
            for related_entity, relationship, _ in related[:5]:  # Top 5 related
                rel_desc = f"{relationship.relation_type.value} {related_entity.name}"
                if related_entity.description:
                    rel_desc += f" - {related_entity.description}"
                context_parts.append(rel_desc)
            
            context = " | ".join(context_parts)
            
            # Truncate if too long
            if len(context) > max_context_length:
                context = context[:max_context_length] + "..."
            
            return context
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get knowledge graph statistics."""
        async with self._lock:
            self._update_stats()
            
            return {
                "total_entities": self._stats.total_entities,
                "total_relationships": self._stats.total_relationships,
                "entities_by_type": dict(self._stats.entities_by_type),
                "relationships_by_type": dict(self._stats.relationships_by_type),
                "avg_connections_per_entity": self._stats.avg_connections_per_entity,
                "graph_density": self._stats.graph_density,
                "memory_usage_mb": self._estimate_memory_usage(),
            }
    
    async def _extract_knowledge(
        self,
        text: str,
        session_id: str,
        context_type: str
    ) -> Tuple[List[Entity], List[Relationship]]:
        """Extract entities and relationships from text using AI."""
        prompt = f"""Extract entities and relationships from the following text.

Text: {text}

Please identify:
1. Entities (concepts, people, projects, technologies, etc.)
2. Relationships between entities

Format your response as JSON:
{{
  "entities": [
    {{"name": "entity_name", "type": "concept|person|project|technology", "description": "brief description"}}
  ],
  "relationships": [
    {{"source": "entity1_name", "target": "entity2_name", "type": "related_to|implements|depends_on|similar_to", "description": "relationship description"}}
  ]
}}

Focus on the most important entities and clear relationships."""
        
        try:
            response = await self.ollama.chat_complete(
                model=self.extraction_model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.3, "num_predict": 1000}
            )
            
            # Parse JSON response
            extracted = json.loads(response)
            
            # Convert to Entity and Relationship objects
            entities = []
            for entity_data in extracted.get("entities", []):
                entity = Entity(
                    id="",  # Will be generated
                    name=entity_data["name"],
                    entity_type=EntityType(entity_data["type"]),
                    description=entity_data["description"],
                    properties={
                        "session_id": session_id,
                        "context_type": context_type,
                        "source_text": text[:200],  # First 200 chars
                    }
                )
                entities.append(entity)
            
            relationships = []
            for rel_data in extracted.get("relationships", []):
                # Note: We'll resolve entity IDs after adding entities
                relationship = Relationship(
                    id="",  # Will be generated
                    source_entity_id="",  # Will be resolved
                    target_entity_id="",  # Will be resolved
                    relation_type=RelationType(rel_data["type"]),
                    properties={
                        "session_id": session_id,
                        "description": rel_data.get("description", ""),
                    }
                )
                relationships.append(relationship)
            
            return entities, relationships
            
        except Exception as e:
            logger.error("Failed to extract knowledge: %s", e)
            return [], []
    
    async def _add_entity(self, entity: Entity) -> str:
        """Add an entity to the graph, merging if similar exists."""
        # Check for similar existing entities
        if self.auto_merge:
            existing_similar = await self._find_similar_entities(entity)
            if existing_similar:
                # Merge with existing entity
                existing_id = existing_similar[0]
                existing_entity = self._entities[existing_id]
                
                # Update existing entity
                existing_entity.access_count += 1
                existing_entity.last_accessed = time.time()
                existing_entity.confidence = max(existing_entity.confidence, entity.confidence)
                
                # Merge properties
                existing_entity.properties.update(entity.properties)
                
                return existing_id
        
        # Generate embedding for new entity
        entity.embedding = await self._get_embedding(entity.name + " " + entity.description)
        
        # Add to graph
        self._entities[entity.id] = entity
        
        # Update indexes
        self._entity_index[entity.name.lower()].add(entity.id)
        for word in entity.name.lower().split():
            if len(word) > 2:
                self._entity_index[word].add(entity.id)
        
        self._type_index[entity.entity_type].add(entity.id)
        
        # Check entity limit
        if len(self._entities) > self.max_entities:
            await self._prune_old_entities()
        
        return entity.id
    
    async def _add_relationship(self, relationship: Relationship) -> str:
        """Add a relationship to the graph."""
        # Resolve entity IDs from names (temporary solution)
        # In a real implementation, we'd maintain name-to-ID mapping
        
        self._relationships[relationship.id] = relationship
        return relationship.id
    
    def _find_similar_entities(self, entity: Entity) -> List[str]:
        """Find existing entities similar to the given entity."""
        if not entity.embedding:
            return []
        
        similar_ids = []
        for existing_id, existing_entity in self._entities.items():
            if (existing_entity.entity_type == entity.entity_type and
                existing_entity.embedding):
                
                similarity = self._cosine_similarity(entity.embedding, existing_entity.embedding)
                if similarity > self.similarity_threshold:
                    similar_ids.append(existing_id)
        
        return similar_ids
    
    async def _get_embedding(self, text: str) -> List[float]:
        """Get embedding for text."""
        try:
            response = await self.ollama.embeddings(
                model=self.embedding_model,
                prompt=text
            )
            return response["embedding"]
        except Exception as e:
            logger.error("Failed to generate embedding: %s", e)
            # Return zero embedding as fallback
            return [0.0] * 384  # Common embedding size
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two embeddings."""
        import numpy as np
        
        a_np = np.array(a)
        b_np = np.array(b)
        
        dot_product = np.dot(a_np, b_np)
        norm_a = np.linalg.norm(a_np)
        norm_b = np.linalg.norm(b_np)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(dot_product / (norm_a * norm_b))
    
    async def _prune_old_entities(self) -> None:
        """Prune old or rarely accessed entities to manage memory."""
        # Sort entities by access frequency and recency
        entity_scores = []
        current_time = time.time()
        
        for entity_id, entity in self._entities.items():
            # Score based on access count and recency
            time_factor = 1.0 / (1.0 + (current_time - entity.last_accessed) / 86400)  # Days
            score = entity.access_count * time_factor
            entity_scores.append((entity_id, score))
        
        # Sort by score (lowest first) and remove bottom 10%
        entity_scores.sort(key=lambda x: x[1])
        to_remove = max(1, len(self._entities) // 10)
        
        removed_count = 0
        for entity_id, _ in entity_scores[:to_remove]:
            if entity_id in self._entities:
                # Remove entity
                del self._entities[entity_id]
                
                # Remove from indexes
                entity = self._entities.get(entity_id)
                if entity:
                    self._entity_index[entity.name.lower()].discard(entity_id)
                    for word in entity.name.lower().split():
                        if len(word) > 2:
                            self._entity_index[word].discard(entity_id)
                    self._type_index[entity.entity_type].discard(entity_id)
                
                # Remove related relationships
                rels_to_remove = [
                    rel_id for rel_id, rel in self._relationships.items()
                    if rel.source_entity_id == entity_id or rel.target_entity_id == entity_id
                ]
                for rel_id in rels_to_remove:
                    del self._relationships[rel_id]
                
                removed_count += 1
        
        logger.info("Pruned %d old entities from knowledge graph", removed_count)
    
    async def _maintenance_loop(self) -> None:
        """Background maintenance loop."""
        while self._running:
            try:
                await self._perform_maintenance()
                await asyncio.sleep(3600)  # Run every hour
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Maintenance loop error: %s", e)
                await asyncio.sleep(3600)
    
    async def _perform_maintenance(self) -> None:
        """Perform periodic maintenance tasks."""
        # Update entity access times based on recent usage
        # Clean up orphaned relationships
        # Optimize indexes
        pass
    
    def _update_stats(self) -> None:
        """Update graph statistics."""
        self._stats.total_entities = len(self._entities)
        self._stats.total_relationships = len(self._relationships)
        
        # Entity type distribution
        self._stats.entities_by_type.clear()
        for entity in self._entities.values():
            self._stats.entities_by_type[entity.entity_type.value] += 1
        
        # Relationship type distribution
        self._stats.relationships_by_type.clear()
        for relationship in self._relationships.values():
            self._stats.relationships_by_type[relationship.relation_type.value] += 1
        
        # Average connections per entity
        if self._stats.total_entities > 0:
            total_connections = sum(len([
                rel for rel in self._relationships.values()
                if rel.source_entity_id == entity_id or rel.target_entity_id == entity_id
            ]) for entity_id in self._entities.keys())
            self._stats.avg_connections_per_entity = total_connections / self._stats.total_entities
        
        # Graph density (actual connections / possible connections)
        if self._stats.total_entities > 1:
            possible_connections = self._stats.total_entities * (self._stats.total_entities - 1)
            self._stats.graph_density = self._stats.total_relationships / possible_connections
        else:
            self._stats.graph_density = 0.0
    
    def _estimate_memory_usage(self) -> float:
        """Estimate memory usage in MB."""
        total_size = 0
        
        # Entities
        for entity in self._entities.values():
            total_size += len(entity.name.encode())
            total_size += len(entity.description.encode())
            total_size += len(json.dumps(entity.properties).encode())
            if entity.embedding:
                total_size += len(entity.embedding) * 4  # Float32
        
        # Relationships
        for rel in self._relationships.values():
            total_size += len(json.dumps(rel.properties).encode())
        
        return total_size / (1024 * 1024)  # Convert to MB


# Global knowledge graph instance
_knowledge_graph: Optional[KnowledgeGraph] = None


async def get_knowledge_graph() -> KnowledgeGraph:
    """Get the global knowledge graph instance."""
    global _knowledge_graph
    if _knowledge_graph is None:
        from backend.config.settings import get_settings
        settings = get_settings()
        ollama = OllamaClient(settings.ollama_host)
        _knowledge_graph = KnowledgeGraph(ollama)
        await _knowledge_graph.start()
    return _knowledge_graph
