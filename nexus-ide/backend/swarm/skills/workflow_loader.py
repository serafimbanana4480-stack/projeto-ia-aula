"""Workflow YAML loader.

Loads ``.yaml`` files from ``config/workflows/`` and converts them into
:class:`Skill` definitions. The catalogue of YAML workflows is merged with
the Python catalogue from :mod:`backend.swarm.skills.skills`.

Expected YAML schema
--------------------

```yaml
id: my-workflow
name: My Workflow
description: What it does
category: code-quality
icon: wrench
mode: review            # architecture | investigation | implementation | review | bugfix | planning | research
strategy: ensemble      # divide | ensemble | pipeline | debate | adaptive
agents: [ARCHITECT, REVIEWER]
max_iterations: 1000
tags: [experimental]
variables:
  - name: target
    label: Target
    description: What to act on
    required: true
    multiline: false
objective_template: |
  Do {{target}} carefully.
```
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from backend.swarm.core.types import AgentRole, OperationalMode, SwarmStrategy
from backend.swarm.skills.skills import SKILL_CATALOGUE, Skill, SkillVariable, get_skill

logger = logging.getLogger(__name__)


# Default directory for user-defined workflows — resolved relative to
# the project root, not the CWD. The orchestrator package sits at
# ``backend/orchestrator/`` so the project root is 3 levels up from
# any of the swarm package files.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DIR = _PROJECT_ROOT / "config" / "workflows"


def _parse_agent(value: str) -> AgentRole:
    """Map a string like 'ARCHITECT' to AgentRole.ARCHITECT."""
    v = value.strip().lower()
    for role in AgentRole:
        if role.value == v:
            return role
    # Map common names
    aliases = {
        "planner": AgentRole.COORDINATOR,
        "coder": AgentRole.IMPLEMENTER,
        "analyzer": AgentRole.INVESTIGATOR,
    }
    if v in aliases:
        return aliases[v]
    raise ValueError(f"Unknown agent role: {value!r}")


def _parse_mode(value: str) -> OperationalMode:
    v = value.strip().lower()
    for m in OperationalMode:
        if m.value == v:
            return m
    raise ValueError(f"Unknown operational mode: {value!r}")


def _parse_strategy(value: str) -> SwarmStrategy:
    v = value.strip().lower()
    for s in SwarmStrategy:
        if s.value == v:
            return s
    raise ValueError(f"Unknown swarm strategy: {value!r}")


def _yaml_to_skill(data: dict[str, Any]) -> Skill:
    """Convert a parsed YAML dict into a Skill."""
    skill_id = data.get("id")
    if not skill_id:
        raise ValueError("workflow YAML is missing 'id'")
    if get_skill(skill_id) is not None:
        raise ValueError(f"workflow id {skill_id!r} clashes with built-in skill")

    return Skill(
        id=skill_id,
        name=data.get("name", skill_id),
        description=data.get("description", ""),
        category=data.get("category", "general"),
        icon=data.get("icon", "workflow"),
        mode=_parse_mode(data.get("mode", "investigation")),
        strategy=_parse_strategy(data.get("strategy", "ensemble")),
        agents=[_parse_agent(a) for a in data.get("agents", [])],
        objective_template=data.get("objective_template", ""),
        variables=[
            SkillVariable(
                name=v["name"],
                label=v.get("label", v["name"]),
                description=v.get("description", ""),
                required=bool(v.get("required", True)),
                default=str(v.get("default", "")),
                multiline=bool(v.get("multiline", False)),
            )
            for v in data.get("variables", [])
        ],
        tags=list(data.get("tags", [])),
        max_iterations=int(data.get("max_iterations", 1000)),
        estimated_seconds=int(data.get("estimated_seconds", 60)),
    )


def load_workflows(directory: str | Path = DEFAULT_DIR) -> list[Skill]:
    """Load all ``*.yaml``/``*.yml`` files from ``directory`` and return Skills."""
    root = Path(directory)
    if not root.exists():
        return []
    out: list[Skill] = []
    for path in sorted(list(root.glob("*.yaml")) + list(root.glob("*.yml"))):
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as exc:
            logger.warning("failed to read workflow %s: %s", path, exc)
            continue
        if not isinstance(data, dict):
            logger.warning("workflow %s is not a dict — skipping", path)
            continue
        # Support a single file holding multiple workflows under "workflows"
        if "workflows" in data and isinstance(data["workflows"], list):
            for w in data["workflows"]:
                try:
                    out.append(_yaml_to_skill(w))
                except Exception as exc:
                    logger.warning("bad workflow in %s: %s", path, exc)
        else:
            try:
                out.append(_yaml_to_skill(data))
            except Exception as exc:
                logger.warning("bad workflow %s: %s", path, exc)
    return out


def merged_catalogue(directory: str | Path = DEFAULT_DIR) -> list[Skill]:
    """Built-in skills + YAML-loaded workflows (YAML wins on id collision)."""
    yaml_skills = load_workflows(directory)
    by_id: dict[str, Skill] = {s.id: s for s in SKILL_CATALOGUE}
    for s in yaml_skills:
        by_id[s.id] = s
    return list(by_id.values())


__all__ = ["load_workflows", "merged_catalogue", "DEFAULT_DIR"]
