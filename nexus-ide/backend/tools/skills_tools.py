"""Loadable project skills for the agent.

Skills are plain directories containing a ``SKILL.md`` each, discovered in
``NEXUS_SKILLS_DIRS`` (``os.pathsep``-separated) or, by default, in
``<nexus-ide>/skills`` and ``<repo>/.opencode/skills``. ``list_skills`` shows
what is available; ``load_skill`` injects one into the conversation so the
agent can follow project-specific playbooks without them living in the system
prompt.

Protection is simple: only immediate subdirectories of a root are scanned,
symlinked entries are ignored, and a resolved ``SKILL.md`` must stay inside
its root.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from backend.core.skill_builder import SkillBuilder
from backend.core.skill_runtime import (
    configured_skill_roots,
    list_skill_summaries,
    load_skill_document,
    parse_skill_markdown,
)
from backend.tools.registry import ToolSpec, register_tool

_SKILL_MAX_CHARS = 4000
_TRUNCATION_NOTE = "\n\n[... skill truncado; lê o ficheiro original para o resto ...]"


def _default_skill_roots(project_path: str | Path | None = None) -> list[Path]:
    return configured_skill_roots(project_path)


def skill_roots(project_path: str | Path | None = None) -> list[Path]:
    """Configured skill roots: ``NEXUS_SKILLS_DIRS`` wins over the defaults."""
    return _default_skill_roots(project_path)


def _session_owner(session_id: str) -> str:
    """Resolve learned-skill ownership from the trusted tool session context."""
    if not session_id:
        return ""
    try:
        from backend.persistence.db import get_session

        session = get_session(session_id)
        return str((session or {}).get("user_id") or "")
    except Exception:
        return ""


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(candidate))) == str(root)
    except ValueError:
        return False


def _project_skill_root(project_path: str | Path) -> Path:
    """Create the conventional skill root without following child symlinks."""
    project = Path(project_path).expanduser().resolve(strict=True)
    if not project.is_dir():
        raise ValueError("project_path must point to an existing project directory")
    current = project / ".opencode"
    for directory in (current, current / "skills"):
        if directory.is_symlink():
            raise ValueError(f"skill destination cannot follow a symbolic link: {directory}")
        if directory.exists() and not directory.is_dir():
            raise ValueError(f"skill destination is not a directory: {directory}")
        if not directory.exists():
            directory.mkdir()
        if not _is_within(project, directory.resolve()):
            raise ValueError("skill destination resolves outside the selected project")
    return (current / "skills").resolve(strict=True)


async def list_skills(project_path: str = "", session_id: str = "") -> dict[str, Any]:
    """List available skills: name and first line of each ``SKILL.md``.

    Returns:
        Dict with the skill entries and the roots that were scanned.
    """
    skills = list_skill_summaries(
        project_path or None,
        include_memory=True,
        user_id=_session_owner(session_id),
    )
    return {
        "ok": True,
        "skills": skills,
        "roots": [str(root) for root in skill_roots(project_path or None)],
    }


async def load_skill(
    name: str = "", project_path: str = "", session_id: str = ""
) -> dict[str, Any]:
    """Load one skill's ``SKILL.md`` content (truncated to ~4000 chars).

    Args:
        name: Skill directory name (e.g. ``nexus-backend``).

    Returns:
        Dict with the skill content under a ``### Skill: <name>`` header.
    """
    wanted = str(name or "").strip()
    if not wanted:
        return {"ok": False, "error": "skill name is required (e.g. name='nexus-backend')."}

    loaded = load_skill_document(
        wanted,
        project_path or None,
        max_chars=_SKILL_MAX_CHARS,
        user_id=_session_owner(session_id),
    )
    if not loaded.get("ok"):
        return loaded
    header = f"### Skill: {loaded['name']}"
    content = str(loaded.get("content") or "")
    body = content.partition("\n\n")[2]
    if loaded.get("truncated"):
        body = body.removesuffix(
            "\n\n[... skill truncada; lê o ficheiro original para o resto ...]"
        )
        budget = _SKILL_MAX_CHARS - len(header) - len(_TRUNCATION_NOTE) - 2
        body = body[: max(0, budget)] + _TRUNCATION_NOTE
    return {
        "ok": True,
        "name": loaded["name"],
        "version": loaded.get("version", "1.0.0"),
        "path": loaded.get("path"),
        "source": loaded.get("source", "file"),
        "content": f"{header}\n\n{body}",
        "truncated": bool(loaded.get("truncated")),
    }


async def build_skill(
    request: str = "",
    name: str = "",
    observed_steps: list[str] | None = None,
    evidence: list[str] | None = None,
    experience_candidate: str = "",
    project_path: str = "",
) -> dict[str, Any]:
    """Create a validated reusable skill; experience-derived skills stay draft."""
    request = str(request or "")
    experience_candidate = str(experience_candidate or "").strip()
    if experience_candidate:
        try:
            candidates = await asyncio.to_thread(_discover_experience_candidates, "", 10)
        except Exception as exc:
            return {"ok": False, "error": f"Could not read successful task experience: {exc}"}
        candidate = next(
            (
                item
                for item in candidates
                if str(item.get("name", "")).casefold() == experience_candidate.casefold()
            ),
            None,
        )
        if candidate is None:
            return {
                "ok": False,
                "error": f"Experience candidate {experience_candidate!r} was not found among current successful traces.",
            }
        request = str(candidate.get("description") or candidate["name"])
        name = str(candidate["name"])
        observed_steps = [str(step) for step in candidate.get("action_sequence", [])]
        evidence = [
            "source=successful_trace_lake",
            f"frequency={candidate.get('frequency', 'unknown')}",
            f"confidence={candidate.get('confidence', 'unknown')}",
            *[f"task={task}" for task in candidate.get("example_tasks", [])[:3]],
        ]
    if not request.strip():
        return {"ok": False, "error": "request or experience_candidate is required"}
    try:
        built = SkillBuilder().build_and_write(
            request,
            name=name or None,
            observed_steps=observed_steps,
            evidence=evidence,
            destination=_project_skill_root(project_path) if project_path else None,
        )
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "name": built.name,
        "version": built.version,
        "path": str(built.path) if built.path else None,
        "status": built.validation.get("status"),
        "validation": built.validation,
        "triggers": parse_skill_markdown(built.content).manifest.triggers,
    }


def _discover_experience_candidates(
    component_kind: str, limit: int
) -> list[dict[str, Any]]:
    """Mine successful traces on demand; discovery never activates or writes skills."""
    from backend.evolution.skill_discovery import SkillDiscovery

    candidates = SkillDiscovery().discover(component_kind=component_kind or None)
    return candidates[: max(1, min(limit, 10))]


async def discover_skill_candidates(
    component_kind: str = "", limit: int = 5
) -> dict[str, Any]:
    """Return repeated successful trace patterns as inert review candidates."""
    try:
        candidates = await asyncio.to_thread(
            _discover_experience_candidates,
            str(component_kind or "")[:80],
            max(1, min(int(limit), 10)),
        )
    except Exception as exc:
        return {"ok": False, "error": f"Could not read successful task experience: {exc}"}
    return {
        "ok": True,
        "candidates": [
            {
                "name": str(item.get("name") or ""),
                "description": str(item.get("description") or ""),
                "action_sequence": list(item.get("action_sequence") or []),
                "frequency": item.get("frequency"),
                "confidence": item.get("confidence"),
                "example_tasks": list(item.get("example_tasks") or []),
                "component_kinds": list(item.get("component_kinds") or []),
                "status": "candidate_only",
            }
            for item in candidates
        ],
        "promotion": "none; experience-derived skills must be built as drafts and reviewed",
    }


register_tool(
    ToolSpec(
        name="list_skills",
        description=(
            "List the project skills available for loading (name + short "
            "description from each SKILL.md). Load one with load_skill."
        ),
        tags=["skills", "docs", "knowledge"],
        category="system",
        risk_level="low",
        when_to_use="Before starting work on an area you are not fluent in, to see which "
        "project playbooks exist.",
        schema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Active project is injected by NEXUS; omit this field.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Trusted session is injected by NEXUS; omit this field.",
                },
            },
        },
        handler=list_skills,
        timeout_seconds=10,
    )
)

register_tool(
    ToolSpec(
        name="discover_skill_candidates",
        description=(
            "Find recurring action patterns in successful NEXUS traces. This is read-only "
            "for skill promotion: results are candidates and never become active Skills."
        ),
        tags=["skills", "memory", "experience"],
        category="system",
        risk_level="medium",
        when_to_use="When asked to inspect prior successful work for reusable procedures.",
        schema={
            "type": "object",
            "properties": {
                "component_kind": {"type": "string", "maxLength": 80},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
        },
        handler=discover_skill_candidates,
        timeout_seconds=30,
    )
)

register_tool(
    ToolSpec(
        name="build_skill",
        description=(
            "Build and save a compact, validated SKILL.md from a clear natural-language "
            "workflow request, or turn one named successful-trace candidate into a draft. "
            "Python project audit requests use a detailed tested template. Experience-derived "
            "skills are never auto-promoted."
        ),
        tags=["skills", "knowledge", "memory"],
        category="system",
        # Writes a file into the user's project. "medium" let it run unattended;
        # the registry's high-risk gate is the real control here.
        risk_level="high",
        when_to_use="Only when the user explicitly asks to create or save a reusable skill, "
        "or asks to turn repeated verified experience into a skill.",
        schema={
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "The intended reusable skill in plain language."},
                "name": {"type": "string", "description": "Optional short skill name."},
                "experience_candidate": {
                    "type": "string",
                    "description": "Optional exact candidate name from discover_skill_candidates; builds a draft.",
                },
                "observed_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional trace-derived steps; supplying them keeps the result in draft status.",
                },
                "evidence": {"type": "array", "items": {"type": "string"}},
                "project_path": {
                    "type": "string",
                    "description": "Active project is injected by NEXUS; omit this field.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Trusted session is injected by NEXUS; omit this field.",
                },
            },
            "required": [],
        },
        handler=build_skill,
        timeout_seconds=10,
    )
)

register_tool(
    ToolSpec(
        name="load_skill",
        description=(
            "Load a project skill: returns the SKILL.md content (truncated to "
            "~4000 chars) so you can follow that playbook."
        ),
        tags=["skills", "docs", "knowledge"],
        category="system",
        risk_level="low",
        when_to_use="When a listed skill matches the current task area (e.g. nexus-backend "
        "for backend work) and you need its instructions.",
        schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name as shown by list_skills (e.g. 'nexus-backend').",
                },
                "project_path": {
                    "type": "string",
                    "description": "Active project is injected by NEXUS; omit this field.",
                },
            },
            "required": ["name"],
        },
        handler=load_skill,
        timeout_seconds=10,
    )
)
