"""SkillDiscovery — auto-discovers reusable skills from task trajectories.

FASE 10. Analyzes successful traces in the TraceLake to identify recurring
action patterns that can be abstracted into reusable skills. Discovered
skills are registered in the skill registry and can be used by future
agent generations.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import UTC
from pathlib import Path
from typing import Any

from backend.evolution.registry import DEFAULT_DB_PATH
from backend.experience.lake import TraceLake, get_trace_lake

logger = logging.getLogger(__name__)

# Minimum occurrences for a pattern to be considered a skill
DEFAULT_MIN_OCCURRENCES = 3
# Minimum sequence length to be considered a skill
DEFAULT_MIN_SEQUENCE_LEN = 3


class SkillDiscovery:
    """Discovers reusable skills from task trajectories.

    A "skill" is a recurring sequence of actions (tool calls + observations)
    that can be abstracted into a reusable function. The miner looks for
    frequent action patterns in successful traces and extracts them as
    candidate skills.

    Usage:
        miner = SkillDiscovery()
        skills = miner.discover(min_occurrences=3)
        miner.register_skills(skills)
    """

    def __init__(
        self,
        lake: TraceLake | None = None,
        db_path: str | Path | None = None,
        min_occurrences: int = DEFAULT_MIN_OCCURRENCES,
        min_sequence_len: int = DEFAULT_MIN_SEQUENCE_LEN,
    ) -> None:
        self._lake = lake or get_trace_lake()
        self.db_path = Path(db_path) if db_path else Path(DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.min_occurrences = min_occurrences
        self.min_sequence_len = min_sequence_len
        self._init_schema()

    def _init_schema(self) -> None:
        """Create discovered_skills table if it doesn't exist."""
        from backend.evolution.registry import _connect
        conn = _connect(self.db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discovered_skills (
                    id              TEXT PRIMARY KEY,
                    name            TEXT NOT NULL,
                    description     TEXT,
                    action_sequence TEXT NOT NULL,
                    frequency       INTEGER,
                    confidence      REAL,
                    component_kinds TEXT,
                    registered_at   TEXT,
                    UNIQUE(name)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def discover(
        self,
        component_kind: str | None = None,
        min_occurrences: int | None = None,
    ) -> list[dict[str, Any]]:
        """Discover recurring skill patterns from successful traces.

        Args:
            component_kind: If set, only analyze traces for this component.
            min_occurrences: Minimum times a pattern must appear.

        Returns:
            List of discovered skill dicts, each containing:
                - name: skill name
                - description: what the skill does
                - action_sequence: list of action+tool steps
                - frequency: how often it appears
                - example_tasks: task IDs where it was used
                - component_kinds: which components use it
        """
        min_occ = min_occurrences or self.min_occurrences

        # Get successful traces
        traces = self._lake.query_traces(
            success=True,
            component_kind=component_kind,
            limit=1000,
        )

        if not traces:
            logger.info("No successful traces for skill discovery")
            return []

        # Extract action sequences from trace trajectories
        action_sequences: dict[str, list[str]] = {}
        task_components: dict[str, set[str]] = defaultdict(set)
        pattern_tasks: dict[str, list[str]] = defaultdict(list)

        for trace_row in traces:
            task_id = trace_row.get("task_id", "")
            component = trace_row.get("component_kind", "unknown")
            traj_json = trace_row.get("trajectory_json", "[]")

            # Extract trajectory directly from the trajectory_json column
            try:
                trajectory = json.loads(traj_json) if traj_json else []
            except (json.JSONDecodeError, TypeError):
                continue

            if not trajectory:
                continue

            # Extract action sequence
            sequence: list[str] = []
            for entry in trajectory:
                if isinstance(entry, dict):
                    action = entry.get("action", "")
                    tool = entry.get("tool", "")
                    if action or tool:
                        step = tool if tool else action
                        sequence.append(step)

            # Generate sliding window patterns
            if len(sequence) >= self.min_sequence_len:
                action_key = "->".join(sequence)
                action_sequences[task_id] = sequence
                task_components[action_key].add(component)
                pattern_tasks[action_key].append(task_id)

        # Find frequent sub-patterns
        subpattern_counts: Counter[str] = Counter()
        subpattern_tasks: dict[str, list[str]] = defaultdict(list)
        subpattern_components: dict[str, set[str]] = defaultdict(set)

        for task_id, sequence in action_sequences.items():
            component = task_components[action_key] if (action_key := self._sequence_to_key(sequence)) else set()
            for sub_pattern in self._generate_subpatterns(sequence):
                if len(sub_pattern) < self.min_sequence_len:
                    continue
                pattern_key = "->".join(sub_pattern)
                subpattern_counts[pattern_key] += 1
                if task_id not in subpattern_tasks[pattern_key]:
                    subpattern_tasks[pattern_key].append(task_id)
                subpattern_components[pattern_key].update(component)

        # Filter by minimum occurrences
        skills: list[dict[str, Any]] = []
        seen_skills: set[str] = set()

        for pattern_key, count in subpattern_counts.most_common(min_occ * 10):
            if count < min_occ:
                continue

            # Generate a skill name from the pattern
            skill_name = self._generate_skill_name(pattern_key)
            if skill_name in seen_skills:
                continue
            seen_skills.add(skill_name)

            skill = {
                "name": skill_name,
                "description": self._generate_skill_description(pattern_key),
                "action_sequence": pattern_key.split("->"),
                "frequency": count,
                "example_tasks": subpattern_tasks[pattern_key][:10],
                "component_kinds": list(subpattern_components[pattern_key]),
                "confidence": min(count / self.min_occurrences, 1.0),
            }
            skills.append(skill)

        # Sort by frequency and confidence
        skills.sort(key=lambda s: (s["frequency"], s["confidence"]), reverse=True)
        return skills

    def _generate_subpatterns(self, sequence: list[str]) -> list[list[str]]:
        """Generate all contiguous sub-patterns of a sequence."""
        subpatterns: list[list[str]] = []
        n = len(sequence)
        for length in range(self.min_sequence_len, min(n + 1, self.min_sequence_len + 3)):
            for start in range(n - length + 1):
                subpatterns.append(sequence[start:start + length])
        return subpatterns

    def _sequence_to_key(self, sequence: list[str]) -> str:
        """Convert a sequence to a dictionary key."""
        return "->".join(sequence)

    def _generate_skill_name(self, pattern_key: str) -> str:
        """Generate a readable skill name from a pattern."""
        steps = pattern_key.split("->")
        # Use first 2 steps as basis for name
        name_parts = []
        for step in steps[:2]:
            # Extract the core action from the step
            cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", step.strip())
            cleaned = re.sub(r"_+", "_", cleaned)
            if cleaned:
                name_parts.append(cleaned)

        if name_parts:
            return f"skill_{'_'.join(name_parts)[:60]}"
        return f"skill_{hash(pattern_key) % 10000}"

    def _generate_skill_description(self, pattern_key: str) -> str:
        """Generate a description for a discovered skill."""
        steps = pattern_key.split("->")
        return f"Automated sequence of {len(steps)} actions: {' -> '.join(steps)}"

    def register_skills(self, skills: list[dict[str, Any]]) -> list[str]:
        """Register discovered skills into the skill registry.

        Writes to the same database as ChampionRegistry (skills table
        is a separate concern — this stores discovered skill metadata).
        """
        import uuid
        from datetime import datetime

        from backend.evolution.registry import _connect
        conn = _connect(self.db_path)
        try:
            conn.execute("BEGIN")
            # Ensure skills table exists
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discovered_skills (
                    id              TEXT PRIMARY KEY,
                    name            TEXT NOT NULL,
                    description     TEXT,
                    action_sequence TEXT NOT NULL,
                    frequency       INTEGER,
                    confidence      REAL,
                    component_kinds TEXT,
                    registered_at   TEXT,
                    UNIQUE(name)
                )
                """
            )
            registered_ids: list[str] = []
            for skill in skills:
                skill_id = f"skill-{uuid.uuid4().hex[:8]}"
                conn.execute(
                    "INSERT OR REPLACE INTO discovered_skills "
                    "(id, name, description, action_sequence, frequency, confidence, "
                    " component_kinds, registered_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        skill_id,
                        skill["name"],
                        skill["description"],
                        json.dumps(skill["action_sequence"]),
                        skill["frequency"],
                        skill["confidence"],
                        json.dumps(skill["component_kinds"]),
                        datetime.now(UTC).isoformat(),
                    ),
                )
                registered_ids.append(skill_id)
            conn.commit()
            logger.info(f"Registered {len(registered_ids)} discovered skills")
            return registered_ids
        finally:
            conn.close()

    def get_discovered_skills(self) -> list[dict[str, Any]]:
        """Retrieve all discovered skills."""
        from backend.evolution.registry import _connect
        conn = _connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM discovered_skills ORDER BY frequency DESC, confidence DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
