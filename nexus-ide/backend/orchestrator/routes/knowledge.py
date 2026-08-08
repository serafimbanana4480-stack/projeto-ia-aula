
"""Knowledge routes for dashboard.

Provides endpoints for knowledge graph and memory systems.
"""

import logging
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class MemoryStats(BaseModel):
    """Memory system statistics."""
    semantic: dict[str, int]
    episodic: dict[str, int]
    vector: dict[str, int]
    graph: dict[str, int]
    procedural: dict[str, int]
    vector_db_size: int = 0
    total_retrievals: int = 0
    avg_relevance: float = 0.0


class KnowledgeStats(BaseModel):
    """Knowledge graph statistics."""
    collections: int
    entities: int
    relations: int
    documents: int
    embeddings: int


@router.get("/knowledge/stats", response_model=KnowledgeStats, tags=["knowledge"])
async def get_knowledge_stats() -> dict:
    """Return knowledge graph statistics from Qdrant.

    Returns real-time statistics about the knowledge graph including
    collection count, entity count, and vector counts from Qdrant.

    **Example Response:**
    ```json
    {
        "collections": 3,
        "entities": 1250,
        "relations": 625,
        "documents": 1250,
        "embeddings": 1250
    }
    ```

    **Returns:**
        Dictionary with knowledge graph statistics
    """
    # Try to get real stats from Qdrant
    try:
        from backend.knowledge.qdrant_backend import QdrantBackend, QDRANT_AVAILABLE
        
        if QDRANT_AVAILABLE:
            qdrant = QdrantBackend()
            vector_count = qdrant.count()
            
            # Get collection info for more stats
            collections = qdrant._client.get_collections().collections
            collection_count = len(collections)
            
            return {
                "collections": collection_count,
                "entities": vector_count,
                "relations": vector_count // 2,  # Estimate
                "documents": vector_count,
                "embeddings": vector_count,
            }
    except Exception as e:
        logger.warning(f"Failed to get Qdrant stats: {e}")
    
    # Fallback to estimated stats
    return {
        "collections": 1,
        "entities": 0,
        "relations": 0,
        "documents": 0,
        "embeddings": 0,
    }


@router.get("/memory/stats", response_model=MemoryStats, tags=["memory"])
async def get_memory_stats() -> dict:
    """Return memory system statistics from Redis and Qdrant.

    Provides real-time statistics about all memory types including
    semantic, episodic, vector, graph, and procedural memory.
    Data is sourced from Redis (for semantic/episodic) and Qdrant (for vectors).

    **Example Response:**
    ```json
    {
        "semantic": {"count": 150, "size": 1024000},
        "episodic": {"count": 75, "size": 512000},
        "vector": {"count": 150, "size": 460800},
        "graph": {"nodes": 150, "edges": 75},
        "procedural": {"count": 50, "size": 340000}
    }
    ```

    **Returns:**
        Dictionary with memory statistics for each memory type
    """
    # The SQLite-backed store is the canonical source for the chat path.
    # Redis/Qdrant are optional adapters and must not produce invented counts
    # when they are offline.
    from backend.knowledge.memory import get_memory_store

    memories = get_memory_store().all_memories()
    by_kind: dict[str, list[Any]] = {"semantic": [], "episodic": [], "procedural": []}
    for memory in memories:
        by_kind.setdefault(memory.kind, []).append(memory)

    def size_of(items: list[Any]) -> int:
        return sum(len(memory.content.encode("utf-8")) for memory in items)

    vector_memories = [memory for memory in memories if memory.embedding]
    total_retrievals = sum(memory.access_count for memory in memories)
    related_edges = sum(len(memory.related_memory_ids) for memory in memories)
    return {
        "semantic": {"count": len(by_kind["semantic"]), "size": size_of(by_kind["semantic"])},
        "episodic": {"count": len(by_kind["episodic"]), "size": size_of(by_kind["episodic"])},
        "vector": {
            "count": len(vector_memories),
            "size": sum(len(memory.embedding) * 4 for memory in vector_memories),
        },
        "graph": {"nodes": len(memories), "edges": related_edges // 2},
        "procedural": {"count": len(by_kind["procedural"]), "size": size_of(by_kind["procedural"])},
        "vector_db_size": len(vector_memories),
        "total_retrievals": total_retrievals,
        "avg_relevance": 0.0,
    }


@router.get("/memory/stream", tags=["memory"])
async def memory_stream():
    """Stream memory updates via Server-Sent Events (SSE).

    Provides real-time streaming of memory metrics and updates from the
    memory dashboard. Events include heartbeats and memory metrics updates.

    **Event Types:**
    - `heartbeat`: Keep-alive signal sent every 2 seconds
    - `memory_metrics`: Memory statistics update

    **Example Event:**
    ```
    data: {"type": "memory_metrics", "metrics": {...}}
    ```

    **Returns:**
        StreamingResponse with SSE events
    """
    import json
    import asyncio
    
    async def event_generator():
        while True:
            # Send heartbeat
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
            
            # Try to get real memory events from memory dashboard
            try:
                from backend.memory.memory_dashboard import get_memory_dashboard
                from backend.observability.event_system import get_event_bus
                
                event_bus = await get_event_bus()
                memory_dashboard = await get_memory_dashboard(event_bus)
                
                # Get current memory status
                status = await memory_dashboard.get_memory_status()
                
                # Stream memory metrics update
                yield f"data: {json.dumps({'type': 'memory_metrics', 'metrics': status})}\n\n"
                
            except Exception as e:
                logger.warning(f"Failed to get memory dashboard events: {e}")
                # Fallback to minimal heartbeat only
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
            
            await asyncio.sleep(2)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
