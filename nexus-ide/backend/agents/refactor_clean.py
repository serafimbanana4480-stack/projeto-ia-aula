"""REFACTOR_CLEAN — code cleanliness and maintainability refactoring agent.

Model: qwen2.5-coder:7b (CODER tier). Context 8K.
Prompt: config/prompts/refactor_clean.md

Supports autonomous execution via ReAct loop:
- Reads files to understand existing code
- Applies SOLID principles and removes duplication (DRY)
- Improves naming, documentation, and type hints
- Reduces cognitive complexity
- Follows language-specific style guides (PEP8, etc.)
- Generates refactoring reports with before/after diffs
"""

from __future__ import annotations

from .base import AgentAction, AgentBase


class RefactorCleanAgent(AgentBase):
    """Code cleanliness refactoring agent with ReAct tool-use loop.

    Uses the ReAct loop from AgentBase to autonomously:
    1. Read existing files to understand the codebase
    2. Identify code smells, duplication, and complexity issues
    3. Apply SOLID principles and improve naming/documentation
    4. Add type hints and follow language-specific style guides
    5. Write refactored files
    6. Generate refactoring reports with before/after diffs
    """

    name = "REFACTOR_CLEAN"
    model_key = "coder"
    prompt_file = "refactor_clean"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.WRITE_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.CONSULT_AGENT,
    }
