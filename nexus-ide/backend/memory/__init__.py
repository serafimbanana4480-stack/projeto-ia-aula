"""Memory Module — Advanced memory systems for AI agents.

This module provides comprehensive memory capabilities:
- Advanced memory systems (episodic, procedural, semantic)
- Cross-session memory persistence
- Memory consolidation and optimization
- Context continuity management
- Intelligent memory retrieval
"""

#: ``MemoryItem`` was in this module's public ``__all__`` but never existed in
#: ``advanced_memory`` — every import of ``backend.memory`` died with
#: ``ImportError: cannot import name 'MemoryItem'``, which also broke
#: ``backend.memory.memory_dashboard``, ``backend.memory.cross_session_memory``
#: and ``backend.orchestrator.main_enhanced``.  The durable unit of this module
#: is :class:`MemoryFragment`, so that is what the name resolves to.  No
#: consumer in the tree imported ``MemoryItem``, so the public contract is
#: unchanged for every caller that actually existed.
from .advanced_memory import AdvancedMemorySystem, MemoryStatus, MemoryType
from .advanced_memory import MemoryFragment as MemoryItem
from .cross_session_memory import (
    CrossSessionMemory,
    CrossSessionMemoryManager,
    MemoryConsolidation,
    SessionLink,
)
from .cross_session_memory import MemoryStatus as CrossSessionMemoryStatus
from .cross_session_memory import MemoryType as CrossSessionMemoryType

__all__ = [
    "AdvancedMemorySystem",
    "MemoryType",
    "MemoryStatus", 
    "MemoryItem",
    "CrossSessionMemoryManager",
    "CrossSessionMemory",
    "SessionLink",
    "MemoryConsolidation",
    "CrossSessionMemoryType",
    "CrossSessionMemoryStatus"
]