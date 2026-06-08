#!/usr/bin/env python3
"""Extra edge-case and performance tests for Workspace Manager."""

import sys
import asyncio
import time
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.workspace import (
    write_file_absolute,
    read_file_absolute,
    list_dir_absolute,
    discover_projects,
    get_project_info,
)


async def test_backup_mechanism() -> None:
    print("=== BACKUP MECHANISM ===")
    tmp = Path.home() / "nexus_backup_test.txt"
    tmp.write_text("original content", encoding="utf-8")

    result = await write_file_absolute(str(tmp), "new content")
    backup = result.get("backup", {})
    print(f"  backup_meta: {backup}")

    result2 = await read_file_absolute(str(tmp))
    print(f"  content after write: {repr(result2.get('content'))}")

    backup_path = backup.get("backup_path")
    if backup_path:
        p = Path(backup_path)
        print(f"  backup exists: {p.exists()}")
        if p.exists():
            print(f"  backup content: {repr(p.read_text(encoding='utf-8'))}")

    # Cleanup
    tmp.unlink(missing_ok=True)
    if backup_path:
        Path(backup_path).unlink(missing_ok=True)


async def test_recursive_listing_perf() -> None:
    print("\n=== RECURSIVE LISTING PERFORMANCE ===")
    targets = [
        ("projeto-ia-aula", str(Path.home() / "Desktop" / "PROJETO IA AULA GIT CLONE" / "projeto-ia-aula")),
        ("nexus-ide", str(PROJECT_ROOT)),
    ]
    for name, path in targets:
        if not Path(path).exists():
            continue
        start = time.perf_counter()
        result = await list_dir_absolute(path, recursive=True)
        dur = (time.perf_counter() - start) * 1000
        count = result.get("count", 0)
        print(f"  {name}: {count} items in {dur:.1f} ms")


async def test_discover_deduplication() -> None:
    print("\n=== DISCOVER_PROJECTS DEDUPLICATION ===")
    tmp = Path.home() / "nexus_discover_test"
    parent = tmp / "parent_project"
    child = parent / "child_project"
    child.mkdir(parents=True, exist_ok=True)
    (parent / "pyproject.toml").write_text("[project]\nname = \"parent\"", encoding="utf-8")
    (child / "pyproject.toml").write_text("[project]\nname = \"child\"", encoding="utf-8")

    result = await discover_projects(str(tmp))
    names = [p["name"] for p in result.get("projects", [])]
    print(f"  Discovered: {names}")

    if "parent_project" in names and "child_project" in names:
        print("  BUG: Both parent and child reported (child should be deduplicated)")
    else:
        print("  Deduplication OK")

    shutil.rmtree(tmp, ignore_errors=True)


async def test_get_project_info_perf() -> None:
    print("\n=== GET_PROJECT_INFO PERFORMANCE ===")
    targets = [
        ("nexus-ide", str(PROJECT_ROOT)),
        ("Documents", str(Path.home() / "Documents")),
    ]
    for name, path in targets:
        if not Path(path).exists():
            continue
        start = time.perf_counter()
        result = await get_project_info(path)
        dur = (time.perf_counter() - start) * 1000
        print(
            f"  {name}: {dur:.1f} ms, "
            f"files={result.get('file_count')}, dirs={result.get('dir_count')}, "
            f"git={result.get('git', {}).get('is_repo')}"
        )


async def main() -> int:
    await test_backup_mechanism()
    await test_recursive_listing_perf()
    await test_discover_deduplication()
    await test_get_project_info_perf()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
