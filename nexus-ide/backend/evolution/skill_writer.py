"""SkillWriter — renders discovered-skill candidates as proposed SKILL.md files.

FASE 10 (continued). Takes candidates produced by SkillDiscovery (or any
mapping with ``name`` / ``description`` / steps + evidence fields) and writes
opencode-style SKILL.md proposals under
``.opencode/skills/_proposed/<kebab-name>/SKILL.md``.

Rules:
- never overwrite an existing skill directory; if ``<name>`` exists, the
  proposal is written to the next free versioned dir (``<name>-v2``, ...).
- output is Windows-safe: names are slugified to kebab-case and all paths go
  through :class:`pathlib.Path`.
- rendered files are capped at MAX_FILE_LINES lines.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PROPOSALS_DIR = Path(".opencode") / "skills" / "_proposed"
MAX_FILE_LINES = 60
MAX_NAME_LEN = 60
MAX_EVIDENCE_LINES = 6
_TEMPLATE_OVERHEAD_LINES = 14


def _kebab(name: str) -> str:
    """Slugify a skill name to a Windows-safe kebab-case dir name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    slug = slug[:MAX_NAME_LEN].rstrip("-")
    return slug or "discovered-skill"


def _yaml_quote(text: str) -> str:
    """Single-line, double-quoted YAML-safe string."""
    one_line = " ".join(str(text).split())
    escaped = one_line.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


@dataclass
class SkillProposal:
    """A candidate skill ready to be rendered to disk."""

    name: str
    description: str
    steps: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    @classmethod
    def from_discovered(cls, candidate: dict[str, Any]) -> SkillProposal:
        """Adapt a SkillDiscovery output dict into a proposal."""
        steps = [str(s) for s in (candidate.get("action_sequence") or [])]
        evidence = ["source=NEXUS SkillDiscovery"]
        frequency = candidate.get("frequency")
        confidence = candidate.get("confidence")
        if frequency is not None or confidence is not None:
            evidence.append(f"frequency={frequency} confidence={confidence}")
        tasks = [str(t) for t in (candidate.get("example_tasks") or [])]
        if tasks:
            evidence.append("tasks=" + ", ".join(tasks))
        components = [str(c) for c in (candidate.get("component_kinds") or [])]
        if components:
            evidence.append("components=" + ", ".join(components))
        return cls(
            name=str(candidate.get("name") or "discovered-skill"),
            description=str(candidate.get("description") or "Discovered action sequence."),
            steps=steps,
            evidence=evidence,
        )


class SkillWriter:
    """Writes discovered skills as proposed SKILL.md files.

    Usage:
        writer = SkillWriter()                       # ./.opencode/skills/_proposed
        paths = writer.write_proposals(discovered)   # SkillDiscovery.discover()
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else DEFAULT_PROPOSALS_DIR

    def write_proposals(self, candidates: list[dict[str, Any] | SkillProposal]) -> list[Path]:
        """Write one SKILL.md per candidate. Failures are logged, not raised."""
        written: list[Path] = []
        for candidate in candidates:
            try:
                written.append(self.write_proposal(candidate))
            except OSError:
                logger.exception("Failed to write skill proposal for %r", candidate)
        return written

    def write_proposal(self, candidate: dict[str, Any] | SkillProposal) -> Path:
        """Render a single candidate into a versioned proposal dir."""
        proposal = (
            candidate
            if isinstance(candidate, SkillProposal)
            else SkillProposal.from_discovered(candidate)
        )
        target = self._next_available_dir(_kebab(proposal.name))
        target.mkdir(parents=True, exist_ok=False)
        path = target / "SKILL.md"
        path.write_text(self.render(proposal), encoding="utf-8", newline="\n")
        logger.info("Wrote skill proposal %s", path)
        return path

    def render(self, proposal: SkillProposal) -> str:
        """Render the SKILL.md content (frontmatter + numbered rules), line-capped."""
        evidence = [
            "<!-- " + " ".join(str(e).split()) + " -->"
            for e in proposal.evidence[:MAX_EVIDENCE_LINES]
        ]
        budget = max(1, MAX_FILE_LINES - _TEMPLATE_OVERHEAD_LINES - len(evidence))
        steps = [str(s) for s in proposal.steps if str(s).strip()]
        truncated = len(steps) > budget - 1 if steps else False
        shown = steps[: budget - 1] if truncated else steps[:budget]

        lines: list[str] = []
        lines.append("---")
        lines.append(f"name: {_yaml_quote(proposal.name)}")
        lines.append(f"description: {_yaml_quote(proposal.description)}")
        lines.append("---")
        lines.append("")
        lines.append(f"# {_kebab(proposal.name)}")
        lines.append("")
        lines.append("## Rules")
        lines.append("")
        if not shown:
            lines.append("1. (no steps recorded)")
        else:
            for i, step in enumerate(shown, start=1):
                lines.append(f"{i}. {step}")
            if truncated:
                lines.append(f"{len(shown) + 1}. ({len(steps) - len(shown)} more steps omitted)")
        lines.append("")
        lines.append("## Evidence")
        lines.extend(evidence)
        lines.append("")
        lines.append("_Proposed automatically by NEXUS evolution; review before promotion._")

        assert len(lines) <= MAX_FILE_LINES, "SKILL.md template exceeded line cap"
        return "\n".join(lines) + "\n"

    def _next_available_dir(self, slug: str) -> Path:
        """First non-existing dir: <slug>, then <slug>-v2, <slug>-v3, ..."""
        candidate = self.base_dir / slug
        if not candidate.exists():
            return candidate
        version = 2
        while True:
            candidate = self.base_dir / f"{slug}-v{version}"
            if not candidate.exists():
                return candidate
            version += 1


__all__ = [
    "DEFAULT_PROPOSALS_DIR",
    "MAX_FILE_LINES",
    "SkillProposal",
    "SkillWriter",
]
