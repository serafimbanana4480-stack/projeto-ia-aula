"""CLI entry point for the Autonomous Improvement System.

Usage:
    nexus-improve init                    # Initialize in any project
    nexus-improve config --project .      # Configure for current project
    nexus-improve run --once              # Single improvement cycle
    nexus-improve run --daemon            # Continuous daemon mode
    nexus-improve status                  # Show cycle status
    nexus-improve export-skills --out ./skills_pack.json
    nexus-improve import-skills --in ./skills_pack.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def cmd_init(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    (project / ".nexus").mkdir(parents=True, exist_ok=True)
    (project / ".nexus" / "knowledge_base").mkdir(parents=True, exist_ok=True)
    (project / ".nexus" / "skills").mkdir(parents=True, exist_ok=True)
    print(f"Initialized autonomous improvement in {project}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    from backend.core.project_adapter import ProjectAdapter

    project = Path(args.project).resolve()
    adapter = ProjectAdapter(project)
    print(json.dumps({
        "project_root": str(adapter.project_root),
        "language": adapter.config.language,
        "test_command": adapter.config.test_command,
        "lint_command": adapter.config.lint_command,
        "type_check_command": adapter.config.type_check_command,
        "quality_gates": adapter.get_quality_gates(),
        "agent_registry": adapter.get_agent_registry(),
    }, indent=2))
    return 0


async def _run_once(project: Path) -> int:
    from backend.orchestrator.autonomous_improvement_orchestrator import (
        get_autonomous_improvement_orchestrator,
    )
    from backend.config.settings import get_autonomous_improvement_config

    config = get_autonomous_improvement_config()
    orchestrator = get_autonomous_improvement_orchestrator(config=config)
    result = await orchestrator.run_cycle()
    print(f"Cycle {result.cycle_id}: generated={result.proposals_generated} applied={result.proposals_applied} verified={result.proposals_verified}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    if args.once:
        return asyncio.run(_run_once(project))
    try:
        asyncio.run(_run_daemon(project))
    except KeyboardInterrupt:
        print("Daemon stopped")
    return 0


async def _run_daemon(project: Path) -> int:
    from backend.orchestrator.autonomous_improvement_orchestrator import (
        get_autonomous_improvement_orchestrator,
    )
    from backend.config.settings import get_autonomous_improvement_config

    config = get_autonomous_improvement_config()
    orchestrator = get_autonomous_improvement_orchestrator(config=config)
    await orchestrator.start()
    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        await orchestrator.stop()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from backend.orchestrator.autonomous_improvement_orchestrator import (
        get_autonomous_improvement_orchestrator,
    )
    from backend.config.settings import get_autonomous_improvement_config

    config = get_autonomous_improvement_config()
    orchestrator = get_autonomous_improvement_orchestrator(config=config)
    status = orchestrator.get_status()
    print(json.dumps(status, indent=2, default=str))
    return 0


def cmd_export_skills(args: argparse.Namespace) -> int:
    from backend.core.skills_store import SkillsStore

    store = SkillsStore.get_instance()
    skills = store.list_skills(limit=1000)
    out_path = Path(args.out)
    payload = [s.__dict__ for s in skills]
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"Exported {len(skills)} skills to {out_path}")
    return 0


def cmd_import_skills(args: argparse.Namespace) -> int:
    from backend.core.skills_store import SkillsStore

    store = SkillsStore.get_instance()
    in_path = Path(args.in_)
    if not in_path.exists():
        print(f"File not found: {in_path}", file=sys.stderr)
        return 1
    payload = json.loads(in_path.read_text(encoding="utf-8"))
    imported = 0
    for skill_data in payload:
        try:
            store.create_skill(
                name=skill_data.get("name", ""),
                skill_type=skill_data.get("skill_type", "workflow"),
                description=skill_data.get("description", ""),
                trigger_pattern=skill_data.get("trigger_pattern", ""),
                steps=skill_data.get("steps", []),
                verification=skill_data.get("verification", ""),
                tags=skill_data.get("tags", []),
                source=skill_data.get("source", "imported"),
                auto_apply=skill_data.get("auto_apply", False),
            )
            imported += 1
        except Exception:
            logger.exception("Failed to import skill %s", skill_data.get("name"))
    print(f"Imported {imported} skills from {in_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nexus-improve", description="NEXUS IDE Autonomous Improvement CLI")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Initialize autonomous improvement in a project")
    p_init.add_argument("--project", default=".", help="Project root")

    p_config = sub.add_parser("config", help="Show detected project configuration")
    p_config.add_argument("--project", default=".", help="Project root")

    p_run = sub.add_parser("run", help="Run improvement cycle(s)")
    p_run.add_argument("--once", action="store_true", help="Run one cycle and exit")
    p_run.add_argument("--project", default=".", help="Project root")

    p_status = sub.add_parser("status", help="Show orchestrator status")
    p_status.add_argument("--project", default=".", help="Project root")

    p_export = sub.add_parser("export-skills", help="Export skills to JSON")
    p_export.add_argument("--out", default="./skills_pack.json", help="Output file path")

    p_import = sub.add_parser("import-skills", help="Import skills from JSON")
    p_import.add_argument("--in", dest="in_", required=True, help="Input file path")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    commands = {
        "init": cmd_init,
        "config": cmd_config,
        "run": cmd_run,
        "status": cmd_status,
        "export-skills": cmd_export_skills,
        "import-skills": cmd_import_skills,
    }
    handler = commands.get(args.command)
    if not handler:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
