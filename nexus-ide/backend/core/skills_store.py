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
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "skills"
SKILLS_INDEX = SKILLS_DIR / "_index.json"

#: Lifecycle states a store-backed skill can be in. Mirrors the file-backed
#: ``SkillStatus`` vocabulary so both kinds of skill share one lifecycle.
SKILL_STATUS_DRAFT = "draft"
SKILL_STATUS_ACTIVE = "active"
SKILL_STATUS_DEPRECATED = "deprecated"
SKILL_STATUS_DISABLED = "disabled"

#: States in which a stored skill must never be injected again.
RETIRED_SKILL_STATUSES = frozenset({SKILL_STATUS_DEPRECATED, SKILL_STATUS_DISABLED})


def trigger_keywords(pattern: str) -> list[str]:
    """Split a trigger pattern into its non-empty keywords.

    ``"".split(",") == [""]`` and ``"" in text`` is always ``True``, so an empty
    trigger pattern used to match EVERY context. An empty pattern is not a
    wildcard: it is a missing trigger, and it must match nothing.
    """
    return [
        keyword.strip() for keyword in str(pattern or "").split(",") if keyword.strip()
    ]


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
    user_id: str = ""
    #: Lifecycle state. A skill is only ACTIVE after an explicit promotion;
    #: DEPRECATED/DISABLED skills are never injected again.
    status: str = SKILL_STATUS_DRAFT


#: The persisted fields of a skill. Older/newer files that carry an unknown
#: key are tolerated instead of aborting the whole load.
_SKILL_FIELDS: frozenset[str] = frozenset(item.name for item in fields(Skill))


class SkillsStore:
    """Persistent store for learned skills.

    Skills are stored as individual JSON files under data/skills/.
    An _index.json maintains a lightweight search index.

    The store is a process-wide singleton but it is NOT a frozen snapshot: the
    skills directory is re-scanned whenever it changes on disk, so a skill
    written by another process (or placed by hand) becomes visible without a
    restart. ``refresh()`` forces an immediate re-scan.
    """

    _instance: SkillsStore | None = None

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._signature: tuple[int, int] = (0, 0)
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        self._load_index()

    @classmethod
    def get_instance(cls) -> SkillsStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Drop the process-wide singleton (used by tests)."""
        cls._instance = None

    # ── Freshness ─────────────────────────────────────────────────────

    @staticmethod
    def _disk_signature() -> tuple[int, int]:
        """Cheap fingerprint of the skills directory (mtime + file count)."""
        try:
            stat = SKILLS_DIR.stat()
            count = sum(1 for _ in SKILLS_DIR.glob("*.json"))
        except OSError:
            return (0, 0)
        return (stat.st_mtime_ns, count)

    def _ensure_fresh(self) -> None:
        """Re-read the skills directory when it changed on disk.

        The store used to be a snapshot frozen at import time, so a skill file
        added later was invisible for the lifetime of the process.
        """
        signature = self._disk_signature()
        if signature == self._signature:
            return
        self._load_index()

    def refresh(self) -> int:
        """Force a re-scan of the skills directory; returns the skill count."""
        self._load_index()
        return len(self._skills)

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
        user_id: str = "",
        status: str = SKILL_STATUS_DRAFT,
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
            steps=list(steps),
            verification=verification,
            tags=list(tags or []),
            source=source,
            auto_apply=auto_apply,
            user_id=user_id,
            status=str(status or SKILL_STATUS_DRAFT),
        )
        self._skills[skill_id] = skill
        self._save_skill(skill)
        self._rebuild_index()
        logger.info("Skill created: %s (%s)", name, skill_type)
        return skill

    def get_skill(self, skill_id: str, *, user_id: str | None = None) -> Skill | None:
        self._ensure_fresh()
        skill = self._skills.get(skill_id)
        if skill is not None and user_id is not None and skill.user_id != user_id:
            return None
        return skill

    def list_skills(
        self,
        skill_type: str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        *,
        user_id: str | None = None,
    ) -> list[Skill]:
        self._ensure_fresh()
        results = list(self._skills.values())
        if user_id is not None:
            results = [s for s in results if s.user_id == user_id]
        if skill_type:
            results = [s for s in results if s.skill_type == skill_type]
        if tags:
            results = [s for s in results if any(t in s.tags for t in tags)]
        results.sort(key=lambda s: (s.confidence, s.times_used), reverse=True)
        # A non-positive limit must not silently become "everything but the
        # last N" (Python slicing semantics); it means "no skills".
        return results[: max(0, int(limit))]

    def search_skills(
        self, query: str, limit: int = 10, *, user_id: str | None = None
    ) -> list[Skill]:
        """Search skills by name, description, trigger, and tags."""
        self._ensure_fresh()
        q = query.strip().lower()
        if not q:
            # An empty query matches nothing: it is not a wildcard.
            return []
        results = []
        for skill in self._skills.values():
            if user_id is not None and skill.user_id != user_id:
                continue
            if (
                q in skill.name.lower()
                or q in skill.description.lower()
                or q in skill.trigger_pattern.lower()
                or any(q in t.lower() for t in skill.tags)
            ):
                results.append(skill)
        results.sort(key=lambda s: s.confidence, reverse=True)
        return results[: max(0, int(limit))]

    def find_matching_skills(
        self, context: str, *, user_id: str | None = None
    ) -> list[Skill]:
        """Find skills whose trigger matches the given context string.

        A skill with an empty (or whitespace-only) trigger pattern matches
        NOTHING. ``"".split(",") == [""]`` and ``"" in context`` is always
        ``True``, so an empty pattern used to make the skill match every
        possible context.
        """
        self._ensure_fresh()
        q = context.lower()
        matches = []
        for skill in self._skills.values():
            if user_id is not None and skill.user_id != user_id:
                continue
            keywords = [keyword.lower() for keyword in trigger_keywords(skill.trigger_pattern)]
            if not keywords:
                continue
            # Simple keyword matching (can be enhanced with regex/LLM)
            if any(keyword in q for keyword in keywords):
                matches.append(skill)
        matches.sort(key=lambda s: (s.confidence, s.times_used), reverse=True)
        return matches

    def update_skill(
        self,
        skill_id: str,
        *,
        user_id: str | None = None,
        name: str | None = None,
        skill_type: str | None = None,
        description: str | None = None,
        trigger_pattern: str | None = None,
        steps: list[str] | None = None,
        verification: str | None = None,
        tags: list[str] | None = None,
        auto_apply: bool | None = None,
        status: str | None = None,
    ) -> Skill | None:
        """Persist the submitted fields of one skill; returns the saved skill.

        Only the fields that are actually provided are written, so a partial
        update never clears a field the caller did not mention.
        """
        self._ensure_fresh()
        skill = self._skills.get(skill_id)
        if skill is None or (user_id is not None and skill.user_id != user_id):
            return None
        if name is not None:
            skill.name = str(name)
        if skill_type is not None:
            skill.skill_type = str(skill_type)
        if description is not None:
            skill.description = str(description)
        if trigger_pattern is not None:
            skill.trigger_pattern = str(trigger_pattern)
        if steps is not None:
            skill.steps = [str(step) for step in steps]
        if verification is not None:
            skill.verification = str(verification)
        if tags is not None:
            skill.tags = [str(tag) for tag in tags]
        if auto_apply is not None:
            skill.auto_apply = bool(auto_apply)
        if status is not None:
            skill.status = str(status)
        skill.updated_at = time.time()
        self._save_skill(skill)
        self._rebuild_index()
        return skill

    def set_status(
        self, skill_id: str, status: str, *, user_id: str | None = None
    ) -> Skill | None:
        """Move one skill to another lifecycle state."""
        return self.update_skill(skill_id, user_id=user_id, status=str(status))

    def record_use(
        self, skill_id: str, success: bool, *, user_id: str | None = None
    ) -> None:
        """Record a skill usage outcome."""
        self._ensure_fresh()
        skill = self._skills.get(skill_id)
        if not skill or (user_id is not None and skill.user_id != user_id):
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

    def delete_skill(self, skill_id: str, *, user_id: str | None = None) -> bool:
        self._ensure_fresh()
        skill = self._skills.get(skill_id)
        if skill is None or (user_id is not None and skill.user_id != user_id):
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
            "user_id": skill.user_id,
            "status": skill.status,
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_index(self) -> None:
        """Load every skill file from disk.

        Every ``*.json`` file in the directory is a skill (the previous
        ``skill_*.json`` glob silently ignored a hand-placed file with another
        prefix). ``_index.json`` is the search index, not a skill.
        """
        if not SKILLS_DIR.exists():
            self._signature = self._disk_signature()
            return
        loaded: dict[str, Skill] = {}
        for path in sorted(SKILLS_DIR.glob("*.json")):
            if path.name.startswith("_") or path.name == SKILLS_INDEX.name:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("skill file must contain a JSON object")
                skill_id = str(data.get("id") or "").strip()
                if not skill_id:
                    raise ValueError("skill file has no id")
                fields = {key: value for key, value in data.items() if key in _SKILL_FIELDS}
                fields.setdefault("id", skill_id)
                loaded[skill_id] = Skill(**fields)
            except Exception as exc:
                logger.warning("Failed to load skill %s: %s", path.name, exc)
        self._skills = loaded
        self._signature = self._disk_signature()
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
                "status": skill.status,
            }
        SKILLS_INDEX.write_text(
            json.dumps(index_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def stats(self, *, user_id: str | None = None) -> dict[str, Any]:
        self._ensure_fresh()
        skills = list(self._skills.values())
        if user_id is not None:
            skills = [skill for skill in skills if skill.user_id == user_id]
        return {
            "total_skills": len(skills),
            "by_type": {
                t: len([s for s in skills if s.skill_type == t])
                for t in {"bug_fix", "workflow", "config", "prompt", "pattern"}
            },
            "total_uses": sum(s.times_used for s in skills),
            "avg_confidence": round(
                sum(s.confidence for s in skills) / max(1, len(skills)), 2
            ),
        }

