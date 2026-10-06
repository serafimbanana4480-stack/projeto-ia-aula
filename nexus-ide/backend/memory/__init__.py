"""Memory Module — Advanced memory systems for AI agents.

This module provides comprehensive memory capabilities:
- Advanced memory systems (episodic, procedural, semantic)
- Cross-session memory persistence
- Memory consolidation and optimization
- Context continuity management
- Intelligent memory retrieval
"""

from .advanced_memory import AdvancedMemorySystem, MemoryItem, MemoryStatus, MemoryType
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