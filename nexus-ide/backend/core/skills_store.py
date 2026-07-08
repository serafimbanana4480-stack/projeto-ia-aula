"""Persistent Skills Store — NEXUS IDE evolves like Hermes Agent.

Skills are structured knowledge that the system saves and reuses:
- bug_fix: how to fix a specific bug pattern
- workflow: how to accomplish a recurring task
- config: how to configure something
- prompt: an agent prompt refinement
- pattern: a reusable code pattern

Each skill has: trigger conditions, steps, verification, and auto-applies
when the trigger matches a new situation.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "skills"
SKILLS_INDEX = SKILLS_DIR / "_index.json"


@dataclass
class Skill:
    """A reusable skill learned by the system."""

    id: str
    name: str
    skill_type: str  # bug_fix | workflow | config | prompt | pattern
    description: str
    trigger_pattern: str  # Keywords or regex that trigger this skill
    steps: list[str]  # Step-by-step instructions
    verification: str  # How to verify the skill was applied correctly
    tags: list[str] = field(default_factory=list)
    confidence: float = 1.0  # How reliable this skill is (0.0-1.0)
    times_used: int = 0
    success_count: int = 0
    fail_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    source: str = ""  # How this skill was learned (auto|manual)
    auto_apply: bool = False  # Auto-apply when trigger matches


class SkillsStore:
    """Persistent store for learned skills.

    Skills are stored as individual JSON files under data/skills/.
    An _index.json maintains a lightweight search index.
    """

    _instance: SkillsStore | None = None

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        self._load_index()

    @classmethod
    def get_instance(cls) -> SkillsStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── CRUD ───────────────────────────────────────────────────────────

    def create_skill(
        self,
        name: str,
        skill_type: str,
        description: str,
        trigger_pattern: str,
        steps: list[str],
        verification: str = "",
        tags: list[str] | None = None,
        source: str = "auto",
        auto_apply: bool = False,
    ) -> Skill:
        """Create and persist a new skill."""
        import uuid

        skill_id = f"skill_{uuid.uuid4().hex[:12]}"
        skill = Skill(
            id=skill_id,
            name=name,
            skill_type=skill_type,
            description=description,
            trigger_pattern=trigger_pattern,
            steps=steps,
            verification=verification,
            tags=tags or [],
            source=source,
            auto_apply=auto_apply,
        )
        self._skills[skill_id] = skill
        self._save_skill(skill)
        self._rebuild_index()
        logger.info("Skill created: %s (%s)", name, skill_type)
        return skill

    def get_skill(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def list_skills(
        self,
        skill_type: str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
    ) -> list[Skill]:
        results = list(self._skills.values())
        if skill_type:
            results = [s for s in results if s.skill_type == skill_type]
        if tags:
            results = [s for s in results if any(t in s.tags for t in tags)]
        results.sort(key=lambda s: (s.confidence, s.times_used), reverse=True)
        return results[:limit]

    def search_skills(self, query: str, limit: int = 10) -> list[Skill]:
        """Search skills by name, description, trigger, and tags."""
        q = query.lower()
        results = []
        for skill in self._skills.values():
            if (
                q in skill.name.lower()
                or q in skill.description.lower()
                or q in skill.trigger_pattern.lower()
                or any(q in t.lower() for t in skill.tags)
            ):
                results.append(skill)
        results.sort(key=lambda s: s.confidence, reverse=True)
        return results[:limit]

    def find_matching_skills(self, context: str) -> list[Skill]:
        """Find skills whose trigger matches the given context string."""
        q = context.lower()
        matches = []
        for skill in self._skills.values():
            pattern = skill.trigger_pattern.lower()
            # Simple keyword matching (can be enhanced with regex/LLM)
            if any(kw.strip() in q for kw in pattern.split(",")):
                matches.append(skill)
        matches.sort(key=lambda s: (s.confidence, s.times_used), reverse=True)
        return matches

    def record_use(self, skill_id: str, success: bool) -> None:
        """Record a skill usage outcome."""
        skill = self._skills.get(skill_id)
        if not skill:
            return
        skill.times_used += 1
        if success:
            skill.success_count += 1
        else:
            skill.fail_count += 1
        # Update confidence based on success rate
        total = skill.success_count + skill.fail_count
        if total > 0:
            skill.confidence = min(1.0, skill.success_count / total + 0.1)
        skill.updated_at = time.time()
        self._save_skill(skill)
        self._rebuild_index()

    def delete_skill(self, skill_id: str) -> bool:
        if skill_id not in self._skills:
            return False
        del self._skills[skill_id]
        skill_path = SKILLS_DIR / f"{skill_id}.json"
        if skill_path.exists():
            skill_path.unlink()
        self._rebuild_index()
        return True

    # ── Persistence ────────────────────────────────────────────────────

    def _save_skill(self, skill: Skill) -> None:
        path = SKILLS_DIR / f"{skill.id}.json"
        data = {
            "id": skill.id,
            "name": skill.name,
            "skill_type": skill.skill_type,
            "description": skill.description,
            "trigger_pattern": skill.trigger_pattern,
            "steps": skill.steps,
            "verification": skill.verification,
            "tags": skill.tags,
            "confidence": skill.confidence,
            "times_used": skill.times_used,
            "success_count": skill.success_count,
            "fail_count": skill.fail_count,
            "created_at": skill.created_at,
            "updated_at": skill.updated_at,
            "source": skill.source,
            "auto_apply": skill.auto_apply,
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_index(self) -> None:
        """Load all skills from disk."""
        if not SKILLS_DIR.exists():
            return
        for path in SKILLS_DIR.glob("skill_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._skills[data["id"]] = Skill(**data)
            except Exception as exc:
                logger.warning("Failed to load skill %s: %s", path.name, exc)
        logger.info("Loaded %d skills from disk", len(self._skills))

    def _rebuild_index(self) -> None:
        """Rebuild the skills index file."""
        index_data = {}
        for sid, skill in self._skills.items():
            index_data[sid] = {
                "name": skill.name,
                "type": skill.skill_type,
                "confidence": skill.confidence,
                "times_used": skill.times_used,
                "tags": skill.tags,
                "updated_at": skill.updated_at,
            }
        SKILLS_INDEX.write_text(
            json.dumps(index_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def stats(self) -> dict[str, Any]:
        return {
            "total_skills": len(self._skills),
            "by_type": {
                t: len([s for s in self._skills.values() if s.skill_type == t])
                for t in {"bug_fix", "workflow", "config", "prompt", "pattern"}
            },
            "total_uses": sum(s.times_used for s in self._skills.values()),
            "avg_confidence": round(
                sum(s.confidence for s in self._skills.values()) / max(1, len(self._skills)), 2
            ),
        }