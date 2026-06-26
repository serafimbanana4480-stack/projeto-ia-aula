"""Goal Decomposer — decompose business objectives into atomic user stories.

Uses LLM to break down high-level goals into actionable, testable
user stories that can be assigned to specialized agents.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from backend.config.settings import get_settings
from backend.tools.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class StoryPriority(str, Enum):
    CRITICAL = "critical"  # Blocks everything else
    HIGH = "high"  # Core functionality
    MEDIUM = "medium"  # Important but not blocking
    LOW = "low"  # Nice to have


@dataclass
class UserStory:
    """An atomic, actionable user story."""

    story_id: str = field(default_factory=lambda: f"story-{uuid.uuid4().hex[:8]}")
    title: str = ""
    description: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    priority: StoryPriority = StoryPriority.MEDIUM
    estimated_effort: str = ""  # e.g., "2h", "1d", "3d"
    dependencies: list[str] = field(default_factory=list)  # story_ids
    assigned_agent: str = ""  # e.g., "architect", "coder", "tester"
    status: str = "pending"  # pending, in_progress, completed, blocked

    def to_dict(self) -> dict[str, Any]:
        return {
            "story_id": self.story_id,
            "title": self.title,
            "description": self.description,
            "acceptance_criteria": self.acceptance_criteria,
            "priority": self.priority.value,
            "estimated_effort": self.estimated_effort,
            "dependencies": self.dependencies,
            "assigned_agent": self.assigned_agent,
            "status": self.status,
        }


class GoalDecomposer:
    """Decomposes business objectives into user stories using LLM."""

    SYSTEM_PROMPT = """You are a senior software architect and product manager.
Your task is to decompose software development goals into atomic, actionable user stories.

Rules:
1. Each story must be atomic — one clear deliverable
2. Include concrete acceptance criteria (testable conditions)
3. Estimate effort in hours (h) or days (d)
4. Assign to the appropriate agent: architect, coder, tester, reviewer
5. Identify dependencies between stories
6. CRITICAL priority for core/blocking features

Output JSON format:
{
  "stories": [
    {
      "title": "...",
      "description": "...",
      "acceptance_criteria": ["...", "..."],
      "priority": "critical|high|medium|low",
      "estimated_effort": "2h",
      "dependencies": [],
      "assigned_agent": "architect|coder|tester|reviewer"
    }
  ]
}"""

    def __init__(self, ollama_client: OllamaClient | None = None) -> None:
        self._client = ollama_client or OllamaClient(get_settings().ollama_host)

    async def decompose(
        self,
        goal: str,
        context: str = "",
    ) -> list[UserStory]:
        """Decompose a goal into user stories.

        Args:
            goal: Business objective (e.g., "Create a user management API").
            context: Additional project context.

        Returns:
            List of atomic user stories.
        """
        prompt = f"""Decompose the following goal into user stories:

GOAL: {goal}

CONTEXT: {context}

Return ONLY valid JSON matching the specified format."""

        try:
            response = await self._client.chat(
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model="llama3.2",
                temperature=0.3,
            )

            # Extract JSON from response
            content = response.content if hasattr(response, "content") else str(response)
            stories = self._parse_stories(content)

            logger.info("Decomposed goal into %d stories", len(stories))
            return stories

        except Exception as exc:
            logger.error("Decomposition failed: %s", exc)
            # Return a minimal fallback story
            return [UserStory(
                title=f"Implement: {goal[:50]}",
                description=goal,
                acceptance_criteria=["Implementation is functional"],
                priority=StoryPriority.HIGH,
                estimated_effort="1d",
                assigned_agent="coder",
            )]

    def _parse_stories(self, content: str) -> list[UserStory]:
        """Parse LLM response into UserStory objects."""
        stories: list[UserStory] = []

        # Try to extract JSON from markdown code blocks or raw text
        json_str = content
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(json_str)
            story_list = data.get("stories", [])

            for s in story_list:
                story = UserStory(
                    title=s.get("title", ""),
                    description=s.get("description", ""),
                    acceptance_criteria=s.get("acceptance_criteria", []),
                    priority=StoryPriority(s.get("priority", "medium")),
                    estimated_effort=s.get("estimated_effort", ""),
                    dependencies=s.get("dependencies", []),
                    assigned_agent=s.get("assigned_agent", ""),
                )
                stories.append(story)

        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse stories JSON: %s", exc)
            # Try line-by-line parsing as fallback
            lines = [l.strip("- ") for l in content.split("\n") if l.strip().startswith("-")]
            for line in lines[:5]:  # Limit to first 5
                stories.append(UserStory(
                    title=line,
                    description=line,
                    acceptance_criteria=["Feature is implemented"],
                    priority=StoryPriority.MEDIUM,
                    assigned_agent="coder",
                ))

        return stories

    def build_dependency_graph(
        self,
        stories: list[UserStory],
    ) -> dict[str, list[str]]:
        """Build a dependency graph from stories.

        Returns:
            Dict mapping story_id -> list of dependency story_ids.
        """
        graph: dict[str, list[str]] = {}
        story_ids = {s.story_id for s in stories}

        for story in stories:
            # Validate dependencies exist
            valid_deps = [d for d in story.dependencies if d in story_ids]
            graph[story.story_id] = valid_deps

        return graph
