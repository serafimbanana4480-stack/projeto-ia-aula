"""Store-level defects of the SkillsStore.

Covers the trigger-pattern matching rules and the freshness of the on-disk
index. Every test redirects the store to a temporary directory so nothing is
written into the repository.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core import skills_store as skills_store_module
from backend.core.skills_store import SkillsStore


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SkillsStore:
    """An isolated store backed by a temporary directory."""
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    monkeypatch.setattr(skills_store_module, "SKILLS_DIR", skill_dir)
    monkeypatch.setattr(skills_store_module, "SKILLS_INDEX", skill_dir / "_index.json")
    monkeypatch.setattr(SkillsStore, "_instance", None)
    instance = SkillsStore()
    monkeypatch.setattr(SkillsStore, "_instance", instance)
    return instance


def _create(store: SkillsStore, **overrides: object) -> object:
    payload: dict[str, object] = {
        "name": "Audit routine",
        "skill_type": "workflow",
        "description": "Audit the repository",
        "trigger_pattern": "audit repository",
        "steps": ["Read the project", "Report the findings"],
        "verification": "Every finding cites a file",
        "tags": ["audit"],
        "user_id": "owner",
    }
    payload.update(overrides)
    return store.create_skill(**payload)  # type: ignore[arg-type]


def test_empty_trigger_pattern_matches_nothing(store: SkillsStore) -> None:
    """An empty trigger pattern is a missing trigger, not a wildcard.

    ``"".split(",") == [""]`` and ``"" in context`` is always ``True``, so a
    skill created without a trigger pattern used to be returned for ANY
    context.
    """
    skill = _create(store, trigger_pattern="")

    assert skill.id
    assert store.find_matching_skills("an unrelated query") == []
    assert store.find_matching_skills("") == []
    assert store.find_matching_skills("audit repository") == []


def test_whitespace_trigger_pattern_matches_nothing(store: SkillsStore) -> None:
    """A whitespace-only trigger pattern is still an empty trigger."""
    _create(store, trigger_pattern="   ")
    _create(store, name="Padded", trigger_pattern=" , , ")

    assert store.find_matching_skills("an unrelated query") == []
    assert store.find_matching_skills("audit") == []


def test_store_picks_up_a_new_skill_file(store: SkillsStore, tmp_path: Path) -> None:
    """A skill file added on disk becomes visible without a restart.

    The store used to be a snapshot frozen at import time and only read
    ``skill_*.json``, so a hand-placed file with another prefix was silently
    ignored for the lifetime of the process.
    """
    assert store.list_skills() == []

    hand_placed = {
        "id": "hand-placed-1",
        "name": "Hand placed",
        "skill_type": "workflow",
        "description": "Written by hand",
        "trigger_pattern": "hand placed",
        "steps": ["Do it"],
        "verification": "",
        "tags": [],
        "user_id": "owner",
    }
    (skills_store_module.SKILLS_DIR / "hand-placed.json").write_text(
        json.dumps(hand_placed), encoding="utf-8"
    )

    listed = store.list_skills()
    assert [skill.id for skill in listed] == ["hand-placed-1"]
    assert listed[0].name == "Hand placed"
    assert [skill.id for skill in store.find_matching_skills("hand placed")] == [
        "hand-placed-1"
    ]


def test_store_refresh_picks_up_a_deleted_skill_file(store: SkillsStore) -> None:
    """A removed file disappears from the store."""
    skill = _create(store)
    assert store.list_skills() != []

    (skills_store_module.SKILLS_DIR / f"{skill.id}.json").unlink()

    assert store.list_skills() == []
