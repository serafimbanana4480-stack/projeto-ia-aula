"""Small, bounded runtime for discovering and activating operational skills.

Skill files remain ordinary Markdown. A short YAML frontmatter block carries
the metadata needed for routing; the body is read only after a skill matches.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from backend.contracts.skills import SkillManifest, SkillStatus

logger = logging.getLogger(__name__)

MAX_SKILL_FILE_CHARS = 64_000
MAX_SKILLS_PER_RUN = 3
MAX_SKILL_CONTEXT_CHARS = 8_000
MAX_SKILL_METADATA_CHARS = 8_192
_CACHE_SIZE = 128

DEFAULT_SKILL_ROOTS = (
    Path(__file__).resolve().parents[2] / "skills",
    Path(__file__).resolve().parents[3] / ".opencode" / "skills",
)

_CONTENT_CACHE: OrderedDict[tuple[str, int, int], SkillDocument] = OrderedDict()
_METADATA_CACHE: OrderedDict[tuple[str, int, int], SkillDocument] = OrderedDict()
_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")
_STOP_WORDS = frozenset(
    [
        "a", "as", "ao", "aos", "com", "da", "das", "de", "do", "dos", "e", "em",
        "na", "nas", "no", "nos", "para", "por", "que", "um", "uma", "uns", "umas",
        "the", "an", "and", "or", "for", "to", "of", "in", "on", "with", "this", "that",
        "from", "into", "project", "task", "skill", "skills", "agent", "use", "using",
        "quero", "preciso", "fazer", "faz", "criar", "projeto",
    ]
)
_TOKEN_ALIASES = {
    "auditoria": "audit",
    "auditorias": "audit",
    "auditar": "audit",
    "auditing": "audit",
    "audits": "audit",
    "analysis": "analyze",
    "analise": "analyze",
    "analisar": "analyze",
    "projetos": "project",
    "projects": "project",
    "revisao": "review",
    "revisar": "review",
    "testes": "test",
}


@dataclass(frozen=True, slots=True)
class SkillDocument:
    """Validated metadata and text for one reusable skill."""

    manifest: SkillManifest
    content: str
    body: str
    path: Path | None
    source: str = "file"
    memory_id: str = ""
    confidence: float = 1.0

    @property
    def name(self) -> str:
        return self.manifest.name


def configured_skill_roots(project_path: str | Path | None = None) -> list[Path]:
    """Resolve project-local and configured roots, preserving override semantics."""
    roots: list[Path] = []
    if project_path:
        project = Path(project_path).expanduser()
        roots.extend((project / ".opencode" / "skills", project / "skills"))

    env_value = os.environ.get("NEXUS_SKILLS_DIRS", "")
    if env_value.strip():
        roots.extend(
            Path(part.strip()).expanduser()
            for part in env_value.split(os.pathsep)
            if part.strip()
        )
    else:
        roots.extend(DEFAULT_SKILL_ROOTS)

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        marker = os.path.normcase(str(root.resolve(strict=False)))
        if marker not in seen:
            seen.add(marker)
            unique.append(root)
    return unique


def _normalise(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(plain.split())


def _terms(value: str) -> set[str]:
    terms: set[str] = set()
    for token in _TOKEN_RE.findall(_normalise(value)):
        if token in _STOP_WORDS or len(token) < 2:
            continue
        if token not in _TOKEN_ALIASES and token.endswith("s") and len(token) > 4:
            token = token[:-1]
        terms.add(_TOKEN_ALIASES.get(token, token))
    return terms


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def _description_from_body(body: str) -> str:
    for line in body.splitlines():
        text = line.strip()
        if text and not text.startswith(("#", "```", "<!--")):
            return text[:2_000]
    return ""


def parse_skill_markdown(
    content: str,
    *,
    fallback_name: str = "",
    path: Path | None = None,
    source: str = "file",
) -> SkillDocument:
    """Parse and validate a SKILL.md document without executing its contents."""
    if len(content) > MAX_SKILL_FILE_CHARS:
        raise ValueError(f"skill file exceeds {MAX_SKILL_FILE_CHARS} characters")

    metadata: dict[str, Any] = {}
    body = content
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end < 0:
            raise ValueError("frontmatter is missing its closing '---'")
        if end > 8_000:
            raise ValueError("frontmatter exceeds 8000 characters")
        parsed = yaml.safe_load(content[3:end]) or {}
        if not isinstance(parsed, dict):
            raise ValueError("frontmatter must be a YAML mapping")
        metadata = parsed
        body = content[end + 4 :].lstrip("\r\n")

    name = str(metadata.get("name") or fallback_name).strip()
    if not name:
        raise ValueError("skill name is required")
    description = str(metadata.get("description") or _description_from_body(body)).strip()
    triggers = _as_string_list(
        metadata.get("triggers", metadata.get("trigger_patterns", metadata.get("trigger_pattern")))
    )
    manifest_data = {
        "schema_version": str(metadata.get("schema_version") or "1.0"),
        "skill_id": str(metadata.get("skill_id") or name),
        "name": name,
        "version": str(metadata.get("version") or "1.0.0"),
        "domain": str(metadata.get("domain") or metadata.get("category") or "general"),
        "status": str(metadata.get("status") or "active"),
        "description": description,
        "triggers": triggers,
        "tags": _as_string_list(metadata.get("tags")),
        "priority": int(metadata.get("priority", 50)),
        "dependencies": _as_string_list(metadata.get("dependencies")),
        "conflicts": _as_string_list(metadata.get("conflicts")),
        "compatible_agents": _as_string_list(metadata.get("compatible_agents")),
        "required_tools": _as_string_list(metadata.get("required_tools")),
        "required_mcps": _as_string_list(metadata.get("required_mcps")),
        "max_context_chars": int(metadata.get("max_context_chars", 2_400)),
        "workflows": _as_string_list(metadata.get("workflows")),
        "templates": _as_string_list(metadata.get("templates")),
        "best_practices": _as_string_list(metadata.get("best_practices")),
        "anti_patterns": _as_string_list(metadata.get("anti_patterns")),
        "troubleshooting": _as_string_list(metadata.get("troubleshooting")),
        "validation_rules": metadata.get("validation_rules") or [],
    }
    manifest = SkillManifest.model_validate(manifest_data)
    if not description:
        raise ValueError("skill description is required")
    if any(dep.casefold() == name.casefold() for dep in manifest.dependencies):
        raise ValueError("skill cannot depend on itself")
    structured_sections = (
        ("workflows", "## Structured workflows"),
        ("templates", "## Structured templates"),
        ("best_practices", "## Structured best practices"),
        ("anti_patterns", "## Structured anti-patterns"),
        ("troubleshooting", "## Structured troubleshooting"),
    )
    rendered_sections: list[str] = []
    body_headings = {line.strip().casefold() for line in body.splitlines() if line.startswith("#")}
    for field_name, heading in structured_sections:
        values = getattr(manifest, field_name)
        if values:
            rendered_sections.extend((heading, "", *[f"- {value}" for value in values], ""))
    if manifest.validation_rules and "## validation rules" not in body_headings:
        rendered_sections.extend(("## Validation rules", ""))
        for rule in manifest.validation_rules:
            suffix = " (required)" if rule.required else " (optional)"
            command = f"; command: `{rule.command}`" if rule.command else ""
            rendered_sections.append(
                f"- {rule.name}: {rule.description}{suffix}{command}"
            )
        rendered_sections.append("")
    if rendered_sections:
        body = body.rstrip() + "\n\n" + "\n".join(rendered_sections).strip()
    return SkillDocument(
        manifest=manifest,
        content=content,
        body=body.strip(),
        path=path,
        source=source,
    )


def _inside(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(candidate))) == str(root)
    except ValueError:
        return False


def _load_file(
    path: Path,
    fallback_name: str,
    root: Path,
    *,
    full: bool = False,
) -> SkillDocument | None:
    try:
        stat = path.stat()
        if stat.st_size > MAX_SKILL_FILE_CHARS:
            logger.warning("Ignoring oversized skill file %s", path)
            return None
        resolved_root = root.resolve()
        resolved_path = path.resolve()
        if not _inside(resolved_root, resolved_path) or path.is_symlink():
            return None
        key = (str(resolved_path), stat.st_mtime_ns, stat.st_size)
        cache = _CONTENT_CACHE if full else _METADATA_CACHE
        cached = cache.get(key)
        if cached is not None:
            cache.move_to_end(key)
            return cached
        if full:
            content = path.read_text(encoding="utf-8", errors="replace")
        else:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                content = handle.read(MAX_SKILL_METADATA_CHARS)
        document = parse_skill_markdown(content, fallback_name=fallback_name, path=resolved_path)
        cache[key] = document
        cache.move_to_end(key)
        while len(cache) > _CACHE_SIZE:
            cache.popitem(last=False)
        return document
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        logger.warning("Ignoring invalid skill %s: %s", path, exc)
        return None


def discover_skills(project_path: str | Path | None = None) -> list[SkillDocument]:
    """Discover immediate child skills; earlier roots override later duplicates."""
    found: dict[str, SkillDocument] = {}
    for root in configured_skill_roots(project_path):
        try:
            if not root.is_dir() or root.is_symlink():
                continue
            resolved_root = root.resolve()
            root_found: dict[str, SkillDocument] = {}
            for entry in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
                if not entry.is_dir() or entry.is_symlink():
                    continue
                skill_path = entry / "SKILL.md"
                if not skill_path.is_file() or skill_path.is_symlink():
                    continue
                document = _load_file(skill_path, entry.name, resolved_root)
                if document is None:
                    continue
                key = document.name.casefold()
                current = root_found.get(key)
                if current is None or _version_key(document.manifest.version) > _version_key(
                    current.manifest.version
                ):
                    root_found[key] = document
            for key, document in root_found.items():
                found.setdefault(key, document)
        except OSError:
            logger.debug("Unreadable skill root: %s", root, exc_info=True)
    return sorted(found.values(), key=lambda item: item.name.casefold())


def _memory_skills(user_id: str | None = None) -> list[SkillDocument]:
    """Expose explicitly auto-applying learned skills as procedural memory."""
    owner_id = str(user_id or "").strip()
    if not owner_id:
        return []
    try:
        from backend.core.skills_store import SkillsStore

        stored = SkillsStore.get_instance().list_skills(limit=128, user_id=owner_id)
    except Exception:
        logger.debug("Learned skill memory is unavailable", exc_info=True)
        return []

    documents: list[SkillDocument] = []
    for skill in stored:
        if not skill.auto_apply or skill.confidence < 0.55:
            continue
        body_lines = [f"## Learned procedure\n{skill.description.strip()}", "## Steps"]
        body_lines.extend(f"{index}. {step}" for index, step in enumerate(skill.steps, 1))
        if skill.verification.strip():
            body_lines.extend(("## Verification", skill.verification.strip()))
        try:
            manifest = SkillManifest(
                skill_id=f"memory-{skill.id}",
                name=skill.name,
                version="learned",
                domain=skill.skill_type or "learned",
                status=SkillStatus.ACTIVE,
                description=skill.description[:2_000] or skill.name,
                triggers=_as_string_list(skill.trigger_pattern.replace(",", "\n")),
                tags=_as_string_list(skill.tags),
                priority=min(100, int(skill.confidence * 100)),
                max_context_chars=2_400,
            )
        except Exception:
            logger.debug("Skipping invalid learned skill %s", skill.id, exc_info=True)
            continue
        documents.append(
            SkillDocument(
                manifest=manifest,
                content="\n".join(body_lines),
                body="\n".join(body_lines),
                path=None,
                source="memory",
                memory_id=skill.id,
                confidence=skill.confidence,
            )
        )
    return documents


def list_skill_summaries(
    project_path: str | Path | None = None,
    *,
    include_memory: bool = False,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return metadata only; full instructions are not read into callers' prompts."""
    documents = discover_skills(project_path)
    if include_memory:
        names = {doc.name.casefold() for doc in documents}
        documents.extend(
            doc for doc in _memory_skills(user_id) if doc.name.casefold() not in names
        )
    return [
        {
            "name": doc.name,
            "description": doc.manifest.description[:200],
            "version": doc.manifest.version,
            "status": doc.manifest.status.value,
            "priority": doc.manifest.priority,
            "triggers": list(doc.manifest.triggers),
            "tags": list(doc.manifest.tags),
            "dependencies": list(doc.manifest.dependencies),
            "conflicts": list(doc.manifest.conflicts),
            "compatible_agents": list(doc.manifest.compatible_agents),
            "required_tools": list(doc.manifest.required_tools),
            "required_mcps": list(doc.manifest.required_mcps),
            "source": doc.source,
            "path": str(doc.path) if doc.path else None,
        }
        for doc in documents
    ]


def load_skill_document(
    name: str,
    project_path: str | Path | None = None,
    *,
    max_chars: int = 4_000,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Load one skill's body on demand, with a hard character bound."""
    wanted = str(name or "").strip()
    if not wanted:
        return {"ok": False, "error": "skill name is required"}
    for doc in discover_skills(project_path):
        if doc.name.casefold() == wanted.casefold() or doc.manifest.skill_id.casefold() == wanted.casefold():
            if doc.path is not None:
                doc = _load_file(doc.path, doc.name, doc.path.parent.parent, full=True) or doc
            limit = max(256, min(int(max_chars), MAX_SKILL_FILE_CHARS))
            header = f"### Skill: {doc.name} (v{doc.manifest.version})"
            body = doc.body[: max(0, limit - len(header) - 2)]
            truncated = len(doc.body) > len(body)
            content = f"{header}\n\n{body}"
            if truncated:
                content += "\n\n[... skill truncada; lê o ficheiro original para o resto ...]"
            return {
                "ok": True,
                "name": doc.name,
                "version": doc.manifest.version,
                "path": str(doc.path) if doc.path else None,
                "content": content,
                "truncated": truncated,
            }
    for doc in _memory_skills(user_id):
        if doc.name.casefold() == wanted.casefold() or doc.manifest.skill_id.casefold() == wanted.casefold():
            header = f"### Skill: {doc.name}"
            body = doc.body[: max(0, max_chars - len(header) - 2)]
            truncated = len(doc.body) > len(body)
            content = f"{header}\n\n{body}"
            if truncated:
                content += "\n\n[skill content trimmed to fit the loading budget]"
            return {
                "ok": True,
                "name": doc.name,
                "version": doc.manifest.version,
                "path": None,
                "source": "memory",
                "content": content,
                "truncated": truncated,
            }
    available = ", ".join(doc.name for doc in discover_skills(project_path)) or "(nenhuma skill disponível)"
    return {"ok": False, "error": f"Skill {name!r} not found. Available skills: {available}."}


def _score(document: SkillDocument, query: str) -> tuple[int, list[str], str]:
    terms = _terms(query)
    if not terms:
        return 0, [], ""
    manifest = document.manifest
    name_terms = _terms(manifest.name)
    trigger_terms = _terms(" ".join(manifest.triggers + manifest.tags))
    description_terms = _terms(manifest.description)
    domain_terms = _terms(manifest.domain)
    matched: list[str] = []
    score = 0
    for term in sorted(terms):
        if term in name_terms:
            score += 4
            matched.append(term)
        elif term in trigger_terms:
            score += 3
            matched.append(term)
        elif term in description_terms:
            score += 2
            matched.append(term)
        elif term in domain_terms:
            score += 1
            matched.append(term)
    query_norm = _normalise(query)
    trigger_match = next(
        (
            trigger
            for trigger in manifest.triggers
            if len(_terms(trigger)) >= 2 and _normalise(trigger) in query_norm
        ),
        "",
    )
    if trigger_match:
        score += 8
    return score, matched, trigger_match


def _version_key(version: str) -> tuple[int, int, int, int, int, str]:
    """Sort semantic skill releases above opaque labels and prefer stable versions."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", version.strip())
    if match is None:
        return (0, 0, 0, 0, 0, version.casefold())
    major, minor, patch, prerelease = match.groups()
    return (1, int(major), int(minor), int(patch), 1 if prerelease is None else 0, prerelease or "")


def _available_mcp_names() -> set[str] | None:
    """Return enabled, tested connectors without starting any MCP sessions."""
    try:
        from backend.mcp.store import MCPConnectorStore

        connectors = MCPConnectorStore.get_instance().list_connectors()
    except Exception:
        logger.warning("Could not inspect configured MCP connectors", exc_info=True)
        return None
    available: set[str] = set()
    for connector in connectors:
        if not connector.get("enabled") or connector.get("last_test_status") != "ok":
            continue
        for key in ("id", "name", "template_id"):
            value = str(connector.get(key) or "").strip().casefold()
            if value:
                available.add(value)
    return available


def select_skills(
    query: str,
    project_path: str | Path | None = None,
    *,
    available_tools: set[str] | None = None,
    available_mcps: set[str] | None = None,
    agent_name: str | None = None,
    max_skills: int = MAX_SKILLS_PER_RUN,
    max_chars: int = MAX_SKILL_CONTEXT_CHARS,
    include_memory: bool = True,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Select and load only relevant, compatible skills for a single task."""
    documents = discover_skills(project_path)
    if include_memory:
        file_names = {doc.name.casefold() for doc in documents}
        documents.extend(
            doc for doc in _memory_skills(user_id) if doc.name.casefold() not in file_names
        )

    by_name = {doc.name.casefold(): doc for doc in documents}
    ranked: list[tuple[int, int, float, str, SkillDocument, list[str], str]] = []
    rejected: list[dict[str, str]] = []
    mcp_names = available_mcps

    def eligible(document: SkillDocument) -> str | None:
        nonlocal mcp_names
        manifest = document.manifest
        if manifest.status is not SkillStatus.ACTIVE:
            return "dependency_not_active"
        if manifest.compatible_agents and (
            not agent_name
            or agent_name.casefold()
            not in {compatible.casefold() for compatible in manifest.compatible_agents}
        ):
            return f"incompatible_agent:{agent_name or 'unknown'}"
        if manifest.required_tools:
            if available_tools is None:
                return "tool_availability_unverified"
            available_tool_names = {tool.casefold() for tool in available_tools}
            missing = sorted(
                tool
                for tool in manifest.required_tools
                if tool.casefold() not in available_tool_names
            )
            if missing:
                return "missing_tools:" + ",".join(missing)
        if manifest.required_mcps:
            if mcp_names is None:
                mcp_names = _available_mcp_names()
            if mcp_names is None:
                return "mcp_availability_unverified"
            available_mcp_names = {name.casefold() for name in mcp_names}
            missing_mcps = sorted(
                mcp
                for mcp in manifest.required_mcps
                if mcp.casefold().removeprefix("mcp:").removeprefix("mcp_")
                not in available_mcp_names
            )
            if missing_mcps:
                return "missing_mcps:" + ",".join(missing_mcps)
        return None

    for doc in documents:
        if doc.manifest.status is not SkillStatus.ACTIVE:
            continue
        score, matched, trigger_match = _score(doc, query)
        if score <= 0:
            continue
        problem = eligible(doc)
        if problem:
            rejected.append({"name": doc.name, "reason": problem})
            continue
        ranked.append(
            (
                score,
                doc.manifest.priority,
                doc.confidence,
                doc.name.casefold(),
                doc,
                matched,
                trigger_match,
            )
        )
    ranked.sort(key=lambda row: (-row[0], -row[1], -row[2], row[3]))

    selected: list[tuple[SkillDocument, str, int]] = []
    selected_by_name: dict[str, SkillDocument] = {}
    skip_reasons: dict[str, str] = {}

    def dependency_plan(
        document: SkillDocument, visiting: set[str]
    ) -> tuple[list[SkillDocument] | None, str | None]:
        key = document.name.casefold()
        if key in selected_by_name:
            return [], None
        if key in visiting:
            return None, "dependency_cycle"
        problem = eligible(document)
        if problem:
            return None, problem
        planned: list[SkillDocument] = []
        for dependency in document.manifest.dependencies:
            dependency_doc = by_name.get(dependency.casefold())
            if dependency_doc is None:
                return None, f"missing_dependency:{dependency}"
            dependency_docs, dependency_problem = dependency_plan(
                dependency_doc, visiting | {key}
            )
            if dependency_problem:
                return None, f"unavailable_dependency:{dependency}:{dependency_problem}"
            for dependency_item in dependency_docs or []:
                if dependency_item.name.casefold() not in {
                    item.name.casefold() for item in planned
                }:
                    planned.append(dependency_item)
        planned.append(document)
        return planned, None

    def try_add(document: SkillDocument, reason: str, score: int) -> None:
        plan, problem = dependency_plan(document, set())
        if problem:
            skip_reasons[document.name] = problem
            return
        plan = plan or []
        additions = [item for item in plan if item.name.casefold() not in selected_by_name]
        prior_items = [item[0] for item in selected]
        for index, item in enumerate(additions):
            key = item.name.casefold()
            for other in prior_items + additions[:index]:
                other_key = other.name.casefold()
                if other_key in {name.casefold() for name in item.manifest.conflicts} or key in {
                    name.casefold() for name in other.manifest.conflicts
                }:
                    skip_reasons[document.name] = f"conflicts_with:{other.name}"
                    return
        budget = max(1, min(max_skills, MAX_SKILLS_PER_RUN))
        if len(selected) + len(additions) > budget:
            skip_reasons[document.name] = "skill_count_budget"
            return
        for item in additions:
            is_root = item.name.casefold() == document.name.casefold()
            item_reason = reason if is_root else f"dependency of {document.name}"
            item_score = score if is_root else 0
            selected.append((item, item_reason, item_score))
            selected_by_name[item.name.casefold()] = item

    for score, _priority, _confidence, _name, doc, matched, trigger_match in ranked:
        reason_parts = []
        if trigger_match:
            reason_parts.append(f"trigger '{trigger_match}' matched")
        if matched:
            reason_parts.append("keywords: " + ", ".join(matched))
        reason = "; ".join(reason_parts) or "task relevance score"
        try_add(doc, reason, score)

    entries: list[dict[str, Any]] = []
    chunks: list[str] = []
    remaining = max(0, min(max_chars, MAX_SKILL_CONTEXT_CHARS))
    for doc, reason, score in selected:
        manifest = doc.manifest
        if remaining <= 0:
            skip_reasons[doc.name] = "context_budget"
            continue
        if doc.path is not None:
            doc = _load_file(doc.path, doc.name, doc.path.parent.parent, full=True) or doc
        allowance = min(manifest.max_context_chars, remaining)
        header = f"### Skill: {doc.name} (v{manifest.version})\nActivation reason: {reason}\n\n"
        body = doc.body[: max(0, allowance - len(header) - 2)]
        block = header + body
        if len(doc.body) > len(body):
            note = "\n\n[skill content trimmed to fit the run context budget]"
            block = block[: max(0, allowance - len(note))] + note
        chunks.append(block)
        remaining -= len(block) + 2
        entries.append(
            {
                "name": doc.name,
                "version": manifest.version,
                "source": doc.source,
                "priority": manifest.priority,
                "score": score,
                "reason": reason,
                "path": str(doc.path) if doc.path else None,
                "memory_id": doc.memory_id or None,
            }
        )

    if entries:
        logger.info("Activated skills for task: %s", entries)
    return {
        "skills": entries,
        "context": "\n\n".join(chunks),
        "rejected": rejected,
        "skipped": skip_reasons,
        "context_chars": sum(len(chunk) for chunk in chunks),
    }


def select_skills_for_agent(
    query: str,
    project_path: str | Path | None,
    agent: Any,
    *,
    allowed_tools: set[str] | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Select skills against the real tool surface of one agent invocation."""
    available: set[str] = set()
    try:
        from backend.agents.action_registry import get_action_registry

        action_registry = get_action_registry()
        for action in getattr(agent, "supported_actions", set()):
            mapping = action_registry.get(action.name)
            if mapping is not None:
                available.add(mapping.tool)
    except Exception:
        logger.warning("Could not resolve agent tool dependencies for skill selection", exc_info=True)
    if allowed_tools is not None:
        available.intersection_update(allowed_tools)
    return select_skills(
        query,
        project_path,
        available_tools=available,
        agent_name=str(getattr(agent, "name", "") or ""),
        user_id=user_id,
    )


def clear_skill_cache() -> None:
    """Clear process-local skill text cache (used by tests and hot reloads)."""
    _CONTENT_CACHE.clear()
    _METADATA_CACHE.clear()


__all__ = [
    "DEFAULT_SKILL_ROOTS",
    "MAX_SKILL_CONTEXT_CHARS",
    "MAX_SKILL_FILE_CHARS",
    "MAX_SKILLS_PER_RUN",
    "SkillDocument",
    "clear_skill_cache",
    "configured_skill_roots",
    "discover_skills",
    "list_skill_summaries",
    "load_skill_document",
    "parse_skill_markdown",
    "select_skills",
    "select_skills_for_agent",
]
