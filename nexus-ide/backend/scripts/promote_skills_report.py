"""Human-readable long-term learning report for the NEXUS skill pipeline.

Scans three sources and writes one dated markdown report:

(a) ``.opencode/learnings/LOG.md``          — learnings count by month,
(b) ``.opencode/skills/_proposed/**/SKILL.md`` — candidates awaiting review,
(c) ``nexus-ide/backend/data/evolution_journal.jsonl`` — promotion/rollback outcomes.

It also extracts repeated keyword patterns (>= 2 occurrences) from the learning
descriptors, per the nexus-skill-forge promotion rule.

Stdlib only. Read-only over the sources; never deletes or overwrites an
existing report. Exit code is 0 even when there is no data (the report then
says "no data yet").

Usage (from the repository root, PowerShell):

    nexus-ide\\.venv\\Scripts\\python.exe nexus-ide\\backend\\scripts\\promote_skills_report.py
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPORT_DIR_PARTS = ("docs", "auditorias")
JOURNAL_REL_PARTS = ("nexus-ide", "backend", "data", "evolution_journal.jsonl")
LOG_REL_PARTS = (".opencode", "learnings", "LOG.md")
PROPOSED_REL_PARTS = (".opencode", "skills", "_proposed")
SKILL_FILENAME = "SKILL.md"

MIN_PATTERN_OCCURRENCES = 2
MIN_KEYWORD_LEN = 4
RECENT_CYCLE_LIMIT = 10
EXPLANATION_MAX_CHARS = 110

LEARNING_LINE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s*\|\s*(?P<kind>[^|]+?)\s*\|"
    r"\s*(?P<descriptor>[^|]+?)\s*\|\s*(?P<lesson>.+?)\s*$"
)
KEYWORD_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
NO_DATA_YET = "_(no data yet)_"


@dataclass(frozen=True)
class Learning:
    """One parsed line of ``.opencode/learnings/LOG.md``."""

    date: str
    kind: str
    descriptor: str
    lesson: str


@dataclass(frozen=True)
class ProposedSkill:
    """A candidate skill found under ``.opencode/skills/_proposed/``."""

    rel_path: str
    name: str
    description: str


@dataclass(frozen=True)
class CycleOutcome:
    """One promotion/rollback outcome extracted from the evolution journal."""

    timestamp: str
    promoted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    regressions: int = 0
    explanation: str = ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the dated skills/learning markdown report."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detected from this script's location).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: <root>/docs/auditorias).",
    )
    return parser.parse_args(argv)


def detect_repo_root() -> Path:
    """Best-effort repository root detection (script location first, then cwd)."""
    candidates = [Path(__file__).resolve().parents[3], Path.cwd().resolve()]
    for candidate in candidates:
        if Path(candidate, *LOG_REL_PARTS).is_file():
            return candidate
    return candidates[0]


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def parse_learnings(log_path: Path) -> list[Learning]:
    learnings: list[Learning] = []
    for raw_line in read_text_safe(log_path).splitlines():
        match = LEARNING_LINE_RE.match(raw_line.strip())
        if match:
            learnings.append(Learning(**match.groupdict()))
    return learnings


def learnings_by_month(learnings: list[Learning]) -> dict[str, Counter[str]]:
    by_month: dict[str, Counter[str]] = defaultdict(Counter)
    for learning in learnings:
        by_month[learning.date[:7]][learning.kind.strip()] += 1
    return dict(sorted(by_month.items()))


def keywords_from_descriptor(descriptor: str) -> set[str]:
    tokens = KEYWORD_TOKEN_RE.findall(descriptor.lower())
    return {
        token
        for token in tokens
        if len(token) >= MIN_KEYWORD_LEN and any(ch.isalpha() for ch in token)
    }


def repeated_patterns(
    learnings: list[Learning],
) -> list[tuple[str, int, list[str]]]:
    """Group learnings by shared keyword; keep keywords with >= 2 occurrences."""
    occurrences: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for learning in learnings:
        label = f"`{learning.descriptor}` ({learning.date[:7]})"
        for keyword in keywords_from_descriptor(learning.descriptor):
            occurrences[keyword] += 1
            bucket = examples[keyword]
            if label not in bucket:
                bucket.append(label)
    ranked = sorted(occurrences.items(), key=lambda item: (-item[1], item[0]))
    return [
        (keyword, count, examples[keyword])
        for keyword, count in ranked
        if count >= MIN_PATTERN_OCCURRENCES
    ]


def parse_proposed_skill(path: Path) -> ProposedSkill:
    frontmatter: dict[str, str] = {}
    for line in read_text_safe(path).splitlines()[:30]:
        if line.strip() == "---":
            continue
        key, sep, value = line.partition(":")
        if sep and key.strip() in {"name", "description"}:
            frontmatter[key.strip()] = value.strip()
    rel_path = path.as_posix()
    return ProposedSkill(
        rel_path=rel_path,
        name=frontmatter.get("name", "(sem frontmatter name)"),
        description=frontmatter.get("description", ""),
    )


def find_proposed_skills(proposed_dir: Path) -> list[ProposedSkill]:
    if not proposed_dir.is_dir():
        return []
    return sorted(
        (parse_proposed_skill(p) for p in proposed_dir.rglob(SKILL_FILENAME)),
        key=lambda skill: skill.rel_path,
    )


def parse_journal(journal_path: Path) -> tuple[list[CycleOutcome], dict[str, int]]:
    totals = {"cycles": 0, "promoted": 0, "rejected": 0, "regressions": 0}
    outcomes: list[CycleOutcome] = []
    for raw_line in read_text_safe(journal_path).splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("type") not in (None, "cycle_summary"):
            continue
        promoted = [str(item) for item in entry.get("promoted") or []]
        rejected = [str(item) for item in entry.get("rejected") or []]
        regressions = int(entry.get("regressions") or 0)
        totals["cycles"] += 1
        totals["promoted"] += len(promoted)
        totals["rejected"] += len(rejected)
        totals["regressions"] += regressions
        outcomes.append(
            CycleOutcome(
                timestamp=str(entry.get("timestamp") or entry.get("started_at") or "?"),
                promoted=promoted,
                rejected=rejected,
                regressions=regressions,
                explanation=str(entry.get("explanation") or ""),
            )
        )
    return outcomes, totals


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_learnings_section(by_month: dict[str, Counter[str]]) -> list[str]:
    lines = ["## 1. Aprendizagens por mês", ""]
    if not by_month:
        lines.append(NO_DATA_YET)
    else:
        lines += ["| Mês | Total | Por tipo |", "| --- | --- | --- |"]
        for month, kinds in by_month.items():
            total = sum(kinds.values())
            breakdown = " · ".join(
                f"{kind}: {count}"
                for kind, count in sorted(kinds.items(), key=lambda kv: -kv[1])
            )
            lines.append(f"| {month} | {total} | {breakdown} |")
    return lines


def render_patterns_section(
    patterns: list[tuple[str, int, list[str]]],
) -> list[str]:
    lines = [
        "## 2. Padrões repetidos (>= 2 ocorrências)",
        "",
        "Palavra-chave extraída dos descritores do LOG; >= 2 é o gatilho de "
        "promoção a skill (ver nexus-skill-forge).",
        "",
    ]
    if not patterns:
        lines.append(NO_DATA_YET)
    else:
        lines += ["| Palavra-chave | Ocorrências | Descritores onde aparece |", "| --- | --- | --- |"]
        for keyword, count, labels in patterns[:20]:
            sample = "; ".join(labels[:3]) + (" …" if len(labels) > 3 else "")
            lines.append(f"| `{keyword}` | {count} | {sample} |")
    return lines


def render_proposed_section(skills: list[ProposedSkill]) -> list[str]:
    lines = ["## 3. Skills propostas à espera de revisão", ""]
    if not skills:
        lines.append(NO_DATA_YET)
    else:
        for skill in skills:
            description = f" — {skill.description}" if skill.description else ""
            lines.append(f"- `{skill.rel_path}`: **{skill.name}**{description}")
    return lines


def render_journal_section(
    outcomes: list[CycleOutcome], totals: dict[str, int]
) -> list[str]:
    lines = ["## 4. Promoções/rollbacks recentes (evolution journal)", ""]
    lines.append(
        f"Totais acumulados: ciclos {totals['cycles']} · promovidos "
        f"{totals['promoted']} · rejeitados {totals['rejected']} · regressões "
        f"{totals['regressions']}."
    )
    lines.append("")
    recent = outcomes[-RECENT_CYCLE_LIMIT:]
    if not recent:
        lines.append(NO_DATA_YET)
    else:
        lines += ["| Timestamp (UTC) | Promovidos | Rejeitados | Regressões | Nota |", "| --- | --- | --- | --- | --- |"]
        for outcome in reversed(recent):
            when = outcome.timestamp.replace("T", " ")[:19]
            lines.append(
                f"| {when} | {', '.join(outcome.promoted) or '—'} "
                f"| {', '.join(outcome.rejected) or '—'} "
                f"| {outcome.regressions} | {truncate(outcome.explanation, EXPLANATION_MAX_CHARS)} |"
            )
    return lines


def build_report(root: Path, now: datetime) -> str:
    log_path = Path(root, *LOG_REL_PARTS)
    proposed_dir = Path(root, *PROPOSED_REL_PARTS)
    journal_path = Path(root, *JOURNAL_REL_PARTS)

    learnings = parse_learnings(log_path)
    by_month = learnings_by_month(learnings)
    patterns = repeated_patterns(learnings)
    proposed = find_proposed_skills(proposed_dir)
    outcomes, totals = parse_journal(journal_path)

    sources = ", ".join(
        f"`{Path(*parts).as_posix()}`"
        for parts in (
            LOG_REL_PARTS,
            (*PROPOSED_REL_PARTS, "**", SKILL_FILENAME),
            JOURNAL_REL_PARTS,
        )
    )
    lines = [
        "# Relatório de Skills — aprendizagens, padrões e promoções",
        "",
        f"Gerado por `nexus-ide/backend/scripts/promote_skills_report.py` em "
        f"{now.strftime('%Y-%m-%d %H:%M')} (hora local).",
        f"Fontes: {sources}.",
        "",
    ]
    if not (learnings or proposed or outcomes):
        lines.append("Sem dados recolhidos de nenhuma fonte (no data yet).")
        lines.append("")
    lines += render_learnings_section(by_month)
    lines.append("")
    lines += render_patterns_section(patterns)
    lines.append("")
    lines += render_proposed_section(proposed)
    lines.append("")
    lines += render_journal_section(outcomes, totals)
    lines.append("")
    lines.append("---")
    lines.append(
        "Regenerar: `nexus-ide\\.venv\\Scripts\\python.exe "
        "nexus-ide\\backend\\scripts\\promote_skills_report.py`"
    )
    return "\n".join(lines) + "\n"


def unique_output_path(out_dir: Path, stamp: str) -> Path:
    candidate = out_dir / f"SKILLS_REPORT_{stamp}.md"
    counter = 1
    while candidate.exists():
        candidate = out_dir / f"SKILLS_REPORT_{stamp}-{counter}.md"
        counter += 1
    return candidate


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve() if args.root is not None else detect_repo_root()
    out_dir = (
        args.out_dir.resolve()
        if args.out_dir is not None
        else Path(root, *REPORT_DIR_PARTS)
    )

    now = datetime.now()
    report_text = build_report(root, now)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = unique_output_path(out_dir, now.strftime("%Y%m%d_%H%M"))
    out_path.write_text(report_text, encoding="utf-8", newline="\n")

    print(f"Relatorio escrito em: {out_path}")
    print(
        "Resumo: "
        f"{len(parse_learnings(Path(root, *LOG_REL_PARTS)))} learnings, "
        f"{len(find_proposed_skills(Path(root, *PROPOSED_REL_PARTS)))} propostas, "
        f"{len(parse_journal(Path(root, *JOURNAL_REL_PARTS))[0])} ciclos de evolucao."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
