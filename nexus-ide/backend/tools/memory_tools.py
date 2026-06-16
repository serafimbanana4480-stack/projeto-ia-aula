"""Memory recall and storage tools for agents.

Provides ``recall_context`` and ``store_memory`` actions — semantic search
over stored memories from previous sessions, conversations, code snippets,
and tool results.

These tools reuse the global :class:`~backend.knowledge.memory.MemoryStore`
(via :func:`~backend.knowledge.memory.get_memory_store`) so that agent
conversations, the Second Brain, and the persistent memory layer all share
the same semantic index and SQLite backing store.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.knowledge.memory import MemoryType, get_memory_store
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


async def recall_context(
    query: str = "",
    session_id: str = "",
    project_id: str = "",
    memory_type: str = "",
    top_k: int = 5,
) -> dict[str, Any]:
    """Search semantic memory for relevant context from past sessions.

    Uses embedding-based similarity search to find memories that are
    semantically related to the query. Returns the most relevant matches.

    Args:
        query: The search query to find relevant memories.
        session_id: Optional session ID to scope the search.
        project_id: Optional project ID to scope the search.
        memory_type: Optional memory type filter (session, project, global, etc.).
        top_k: Maximum number of results to return.

    Returns:
        Dict with matching memories and their relevance scores.
    """
    if not query.strip():
        return {"error": "Query cannot be empty."}

    try:
        store = get_memory_store()

        mem_type = None
        if memory_type:
            try:
                mem_type = MemoryType(memory_type)
            except ValueError:
                logger.warning("Invalid memory_type requested: %s", memory_type)

        results = await store.search(
            query,
            session_id=session_id or None,
            project_id=project_id or None,
            memory_type=mem_type,
            top_k=min(top_k, 10),
            min_similarity=0.2,
        )

        if not results:
            return {
                "query": query,
                "memories": [],
                "message": "No relevant memories found.",
            }

        memories = []
        for mem, similarity in results:
            memories.append({
                "id": mem.memory_id[:8],
                "type": mem.memory_type.value,
                "content": mem.content[:500],
                "summary": mem.summary,
                "relevance": round(similarity, 3),
                "source": mem.source,
                "tags": mem.tags,
                "file_path": mem.file_path,
                "language": mem.language,
                "session_id": mem.session_id,
                "project_id": mem.project_id,
            })

        return {
            "query": query,
            "memories": memories,
            "total_found": len(memories),
        }

    except Exception as exc:
        logger.exception("recall_context failed: %s", exc)
        return {"error": f"Memory recall failed: {exc}"}


async def store_memory(
    content: str = "",
    memory_type: str = "session",
    session_id: str = "",
    project_id: str = "",
    tags: str = "",
    source: str = "",
    importance: float = 0.5,
    file_path: str = "",
    language: str = "",
) -> dict[str, Any]:
    """Store a memory for future recall by agents.

    Args:
        content: The content to store in memory.
        memory_type: Type of memory (session, project, global, code_snippet,
            conversation, documentation, file_content, tool_result).
        session_id: Session ID to scope this memory.
        project_id: Project ID to scope this memory.
        tags: Comma-separated tags for categorization.
        source: Agent or tool that created this memory.
        importance: Importance score 0.0-1.0 (affects retention).
        file_path: Optional related file path.
        language: Optional programming language.

    Returns:
        Dict with the stored memory ID and metadata.
    """
    if not content.strip():
        return {"error": "Content cannot be empty."}

    try:
        store = get_memory_store()

        try:
            mem_type = MemoryType(memory_type)
        except ValueError:
            mem_type = MemoryType.SESSION

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        memory = await store.store(
            content,
            memory_type=mem_type,
            session_id=session_id,
            project_id=project_id,
            tags=tag_list,
            source=source,
            importance=max(0.0, min(1.0, importance)),
            file_path=file_path,
            language=language,
        )

        return {
            "memory_id": memory.memory_id,
            "type": memory.memory_type.value,
            "stored": True,
        }

    except Exception as exc:
        logger.exception("store_memory failed: %s", exc)
        return {"error": f"Memory storage failed: {exc}"}


register_tool(
    ToolSpec(
        name="recall_context",
        description=(
            "Search semantic memory for relevant context from past sessions, "
            "conversations, code snippets, and tool results. Use this when you "
            "need to recall information from earlier in the conversation or from "
            "previous sessions."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to find relevant memories",
                },
                "session_id": {
                    "type": "string",
                    "description": "Optional session ID to scope the search",
                    "default": "",
                },
                "project_id": {
                    "type": "string",
                    "description": "Optional project ID to scope the search",
                    "default": "",
                },
                "memory_type": {
                    "type": "string",
                    "description": "Optional memory type filter",
                    "default": "",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        handler=recall_context,
    )
)

register_tool(
    ToolSpec(
        name="store_memory",
        description=(
            "Store important information in memory for future recall. "
            "Use this to save key insights, decisions, results, or documentation "
            "that may be needed later in this session or in future sessions."
        ),
        schema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The content to store in memory",
                },
                "memory_type": {
                    "type": "string",
                    "enum": [
                        "session",
                        "project",
                        "global",
                        "code_snippet",
                        "conversation",
                        "documentation",
                        "file_content",
                        "tool_result",
                    ],
                    "default": "session",
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID to scope this memory",
                    "default": "",
                },
                "project_id": {
                    "type": "string",
                    "description": "Project ID to scope this memory",
                    "default": "",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags for categorization",
                    "default": "",
                },
                "source": {
                    "type": "string",
                    "description": "Agent or tool creating this memory",
                    "default": "",
                },
                "importance": {
                    "type": "number",
                    "description": "Importance score 0.0-1.0",
                    "default": 0.5,
                },
                "file_path": {
                    "type": "string",
                    "description": "Optional related file path",
                    "default": "",
                },
                "language": {
                    "type": "string",
                    "description": "Optional programming language",
                    "default": "",
                },
            },
            "required": ["content"],
        },
        handler=store_memory,
    )
)
