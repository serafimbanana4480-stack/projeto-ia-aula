"""Memory Module — Advanced memory systems for AI agents.

This module provides comprehensive memory capabilities:
- Advanced memory systems (episodic, procedural, semantic)
- Cross-session memory persistence
- Memory consolidation and optimization
- Context continuity management
- Intelligent memory retrieval
"""

from .advanced_memory import AdvancedMemorySystem, MemoryType, MemoryStatus, MemoryItem
from .cross_session_memory import (
    CrossSessionMemoryManager, 
    CrossSessionMemory, 
    SessionLink, 
    MemoryConsolidation,
    MemoryType as CrossSessionMemoryType,
    MemoryStatus as CrossSessionMemoryStatus
)

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