"""Knowledge graph tools — search, add, and retrieve from the NEXUS knowledge store.

These tools expose :class:`backend.knowledge.memory.MemoryStore` operations so
agents can build and query a semantic knowledge graph across sessions.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.knowledge.memory import MemoryType, get_memory_store
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


async def search_knowledge(
    query: str = "",
    session_id: str = "",
    project_id: str = "",
    memory_type: str = "",
    top_k: int = 5,
) -> dict[str, Any]:
    """Semantic search over the knowledge store.

    Args:
        query: Free-text search query.
        session_id: Optional session scope.
        project_id: Optional project scope.
        memory_type: Optional memory type filter (session, project, global, etc.).
        top_k: Maximum results (1–20).

    Returns:
        Dict with matching memories and similarity scores.
    """
    if not query.strip():
        return {"error": "query is required."}

    try:
        store = get_memory_store()
        mem_type = None
        if memory_type:
            try:
                mem_type = MemoryType(memory_type)
            except ValueError:
                mem_type = None

        results = await store.search(
            query,
            session_id=session_id or None,
            project_id=project_id or None,
            memory_type=mem_type,
            top_k=min(max(int(top_k), 1), 20),
        )

        memories = []
        for mem, similarity in results:
            memories.append(
                {
                    "id": mem.memory_id[:8],
                    "type": mem.memory_type.value,
                    "content": mem.content[:500],
                    "summary": mem.summary,
                    "relevance": round(similarity, 3),
                    "source": mem.source,
                    "tags": mem.tags,
                    "file_path": mem.file_path,
                    "session_id": mem.session_id,
                    "project_id": mem.project_id,
                    "created_at": mem.created_at,
                }
            )

        return {
            "ok": True,
            "query": query,
            "memories": memories,
            "total": len(memories),
        }
    except Exception as exc:
        logger.exception("search_knowledge failed: %s", exc)
        return {"error": str(exc)}


async def add_knowledge(
    content: str = "",
    memory_type: str = "session",
    session_id: str = "",
    project_id: str = "",
    tags: str = "",
    source: str = "",
    importance: float = 0.5,
    file_path: str = "",
    language: str = "",
    related_memory_ids: str = "",
) -> dict[str, Any]:
    """Add a new node to the knowledge graph.

    Args:
        content: The content to store.
        memory_type: Type of memory (session, project, global, code_snippet, etc.).
        session_id: Optional session scope.
        project_id: Optional project scope.
        tags: Comma-separated tags.
        source: Agent or tool that created this memory.
        importance: Importance score 0.0–1.0.
        file_path: Optional related file path.
        language: Optional programming language.
        related_memory_ids: Comma-separated memory ids to link.

    Returns:
        Dict with the stored memory id and metadata.
    """
    if not content.strip():
        return {"error": "content is required."}

    try:
        store = get_memory_store()
        try:
            mem_type = MemoryType(memory_type)
        except ValueError:
            mem_type = MemoryType.SESSION

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        rel_ids = [r.strip() for r in related_memory_ids.split(",") if r.strip()] if related_memory_ids else []

        memory = await store.store(
            content,
            memory_type=mem_type,
            session_id=session_id,
            project_id=project_id,
            tags=tag_list,
            source=source,
            importance=max(0.0, min(1.0, float(importance))),
            file_path=file_path,
            language=language,
            related_memory_ids=rel_ids,
        )

        return {
            "ok": True,
            "memory_id": memory.memory_id,
            "type": memory.memory_type.value,
            "stored": True,
            "session_id": memory.session_id,
            "project_id": memory.project_id,
        }
    except Exception as exc:
        logger.exception("add_knowledge failed: %s", exc)
        return {"error": str(exc)}


async def get_knowledge_memory(memory_id: str = "") -> dict[str, Any]:
    """Retrieve a single memory by its full id.

    Args:
        memory_id: The full memory id (not the short 8-char prefix).

    Returns:
        Dict with memory details or an error if not found.
    """
    if not memory_id.strip():
        return {"error": "memory_id is required."}

    try:
        store = get_memory_store()
        mem = store._memories.get(memory_id)
        if mem is None:
            return {"error": f"Memory {memory_id} not found."}

        return {
            "ok": True,
            "memory": {
                "memory_id": mem.memory_id,
                "type": mem.memory_type.value,
                "content": mem.content[:500],
                "summary": mem.summary,
                "source": mem.source,
                "tags": mem.tags,
                "file_path": mem.file_path,
                "language": mem.language,
                "importance": mem.importance,
                "kind": mem.kind,
                "session_id": mem.session_id,
                "project_id": mem.project_id,
                "created_at": mem.created_at,
                "last_accessed_at": mem.last_accessed_at,
                "access_count": mem.access_count,
                "related_memory_ids": mem.related_memory_ids,
            },
        }
    except Exception as exc:
        logger.exception("get_knowledge_memory failed: %s", exc)
        return {"error": str(exc)}


register_tool(
    ToolSpec(
        name="search_knowledge",
        description=(
            "Semantic search over the NEXUS knowledge graph. Finds memories "
            "related to the query across sessions, projects, and global scope."
        ),
        tags=["knowledge", "memory", "search", "semantic"],
        category="knowledge",
        risk_level="low",
        when_to_use="When you need to recall related concepts, decisions, or facts "
        "from previous sessions or projects.",
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "session_id": {"type": "string", "description": "Optional session scope.", "default": ""},
                "project_id": {"type": "string", "description": "Optional project scope.", "default": ""},
                "memory_type": {"type": "string", "description": "Optional type filter.", "default": ""},
                "top_k": {"type": "integer", "description": "Max results (1–20).", "default": 5, "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
        },
        handler=search_knowledge,
        timeout_seconds=20,
    )
)

register_tool(
    ToolSpec(
        name="add_knowledge",
        description=(
            "Add a new memory node to the NEXUS knowledge graph. Optionally "
            "link it to existing memories via related_memory_ids."
        ),
        tags=["knowledge", "memory", "add", "write"],
        category="knowledge",
        risk_level="low",
        when_to_use="When you want to persist a fact, decision, or insight for "
        "future recall across sessions.",
        schema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Content to store."},
                "memory_type": {"type": "string", "enum": [
                    "session", "project", "global", "code_snippet", "conversation",
                    "documentation", "file_content", "tool_result",
                ], "default": "session"},
                "session_id": {"type": "string", "default": ""},
                "project_id": {"type": "string", "default": ""},
                "tags": {"type": "string", "description": "Comma-separated tags.", "default": ""},
                "source": {"type": "string", "default": ""},
                "importance": {"type": "number", "description": "Importance 0.0–1.0.", "default": 0.5, "minimum": 0.0, "maximum": 1.0},
                "file_path": {"type": "string", "default": ""},
                "language": {"type": "string", "default": ""},
                "related_memory_ids": {"type": "string", "description": "Comma-separated memory ids to link.", "default": ""},
            },
            "required": ["content"],
        },
        handler=add_knowledge,
        timeout_seconds=20,
    )
)

register_tool(
    ToolSpec(
        name="get_knowledge_memory",
        description=(
            "Retrieve a single memory from the knowledge graph by its full id."
        ),
        tags=["knowledge", "memory", "read"],
        category="knowledge",
        risk_level="low",
        when_to_use="When you have a memory id and need its full contents.",
        schema={
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "Full memory id (not the short prefix)."},
            },
            "required": ["memory_id"],
        },
        handler=get_knowledge_memory,
        timeout_seconds=10,
    )
)
