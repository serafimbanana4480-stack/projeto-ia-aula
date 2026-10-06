"""Quality ratchet: fail on regression, never on the existing backlog.

`ruff check backend` reports ~215 findings and `mypy` (strict) reports ~2052
across 309 files. Almost all of those are in files owned by other people, and
turning CI red on them would mean nobody could merge anything. But a ratchet
that only ever fails is worthless, and a ratchet that can be tightened by
accident is worse than none.

So this script records the current counts and then enforces exactly one rule:

    a metric may shrink, or hold. It may never grow.

Per-code (ruff) and per-file (mypy) breakdowns are stored, not just totals, so
the ratchet catches a *new* file joining an existing error class even when the
total is unchanged -- which is the regression a bare total would miss.

Tighten the numbers (the intended workflow)::

    python tools/ci/check_quality_ratchet.py --update

Review the resulting diff before committing it: `--update` lowers a baseline to
whatever the tree currently measures, so running it while someone else's work is
mid-flight bakes their errors in as acceptable.

Exit codes: 0 = at or under baseline, 1 = regression, 2 = tooling failure.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from functools import cache
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
BASELINE = REPO / "tools" / "ci" / "quality_baseline.json"

# mypy: "path:line: error: message  [code]"
MYPY_LINE = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):\s+error:\s+(?P<msg>.*?)(?:\s+\[(?P<code>[a-z0-9-]+)\])?$")
# ruff concise: "path:line:col: CODE message"
RUFF_LINE = re.compile(r"^(?P<file>[^:]+):\d+:\d+:\s+(?P<code>[A-Z]+\d+)\s+")


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603
        cmd, cwd=REPO, capture_output=True, text=True, check=False, timeout=1800
    )
    return proc.returncode, proc.stdout + proc.stderr


@cache
def resolve_tool(name: str) -> list[str] | None:
    """Return argv prefix for `name`, or None if it cannot be found here.

    The ratchet runs on ubuntu-latest as well as on developer Windows machines,
    so the venv layout differs (`.venv/bin/ruff` vs `.venv/Scripts/ruff.exe`);
    hard-coding one layout made the gate fail before it ever ran. `python -m` is
    the last resort and is verified with `--version` because an environment can
    expose no console script at all.
    """
    paths = [
        REPO / ".venv" / "Scripts" / f"{name}.exe",
        REPO / ".venv" / "bin" / name,
    ]
    on_path = shutil.which(name)
    if on_path:
        paths.append(Path(on_path))

    for path in paths:
        if path.exists() and _run([str(path), "--version"])[0] == 0:
            return [str(path)]

    if _run([sys.executable, "-m", name, "--version"])[0] == 0:
        return [sys.executable, "-m", name]
    return None


def ruff_metrics() -> dict[str, Any]:
    """Return {'total': int, 'by_code': {...}} for `ruff check backend`."""
    ruff = resolve_tool("ruff")
    if ruff is None:
        return {"total": -1, "by_code": {}}
    _, out = _run([*ruff, "check", "backend", "--output-format", "concise"])
    by_code: Counter[str] = Counter()
    for line in out.splitlines():
        m = RUFF_LINE.match(line.strip())
        if m:
            by_code[m.group("code")] += 1
    # Cross-check against ruff's own total so a parse change cannot silently
    # report a smaller number than ruff does.
    found = re.search(r"Found (\d+) errors?", out)
    total = int(found.group(1)) if found else sum(by_code.values())
    return {"total": total, "by_code": dict(sorted(by_code.items()))}


def mypy_metrics() -> dict[str, Any]:
    """Return {'total': int, 'files': int, 'by_file': {...}} for strict mypy."""
    mypy = resolve_tool("mypy")
    if mypy is None:
        return {"total": -1, "files": -1, "by_file": {}}
    _, out = _run(mypy)
    by_file: Counter[str] = Counter()
    for line in out.splitlines():
        m = MYPY_LINE.match(line.strip())
        if m:
            by_file[Path(m.group("file")).as_posix()] += 1
    found = re.search(r"Found (\d+) errors? in (\d+) files?", out)
    if found:
        total, files = int(found.group(1)), int(found.group(2))
    else:
        total, files = sum(by_file.values()), len(by_file)
    return {"total": total, "files": files, "by_file": dict(sorted(by_file.items()))}


def collect() -> dict[str, Any]:
    return {"ruff": ruff_metrics(), "mypy": mypy_metrics()}


def _compare(
    name: str,
    current: dict[str, Any],
    baseline: dict[str, Any],
    regressions: list[str],
    improvements: list[str],
) -> None:
    cur_t = current.get("total", 0)
    base_t = baseline.get("total", 0)
    if cur_t > base_t:
        regressions.append(f"{name}: {cur_t} errors, baseline allows {base_t} (+{cur_t - base_t})")
    elif cur_t < base_t:
        improvements.append(f"{name}: {cur_t} errors, down from {base_t} (-{base_t - cur_t})")

    if name == "ruff":
        cur_b, base_b = current.get("by_code", {}), baseline.get("by_code", {})
        for code in sorted(set(cur_b) | set(base_b)):
            c, b = cur_b.get(code, 0), base_b.get(code, 0)
            if c > b:
                regressions.append(f"ruff {code}: {c}, baseline allows {b} (+{c - b})")
            elif c < b:
                improvements.append(f"ruff {code}: {c}, down from {b} (-{b - c})")
    else:
        cur_f, base_f = current.get("by_file", {}), baseline.get("by_file", {})
        for f in sorted(set(cur_f) | set(base_f)):
            c, b = cur_f.get(f, 0), base_f.get(f, 0)
            if c > b:
                regressions.append(f"mypy {f}: {c} errors, baseline allows {b} (+{c - b})")
            elif c < b:
                improvements.append(f"mypy {f}: {c} errors, down from {b} (-{b - c})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--update",
        action="store_true",
        help="rewrite the baseline to the current measurements (tightens the ratchet)",
    )
    args = ap.parse_args()

    current = collect()
    if current["ruff"]["total"] < 0 or current["mypy"]["total"] < 0:
        print(
            "FAIL: ruff or mypy not found (tried .venv/Scripts, .venv/bin, "
            "PATH, and `python -m`)",
            file=sys.stderr,
        )
        return 2

    if args.update:
        BASELINE.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        print(f"baseline updated -> {BASELINE.relative_to(REPO)}")
        print(f"  ruff  total={current['ruff']['total']}")
        print(f"  mypy  total={current['mypy']['total']} in {current['mypy']['files']} files")
        return 0

    if not BASELINE.exists():
        print(
            f"FAIL: no baseline at {BASELINE.relative_to(REPO)}.\n"
            f"Create it with:  python tools/ci/check_quality_ratchet.py --update",
            file=sys.stderr,
        )
        return 2

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    regressions: list[str] = []
    improvements: list[str] = []
    for tool in ("ruff", "mypy"):
        _compare(tool, current[tool], baseline.get(tool, {}), regressions, improvements)

    for line in improvements:
        print(f"IMPROVED  {line}")
    if improvements:
        print("  -> tighten the ratchet: python tools/ci/check_quality_ratchet.py --update")

    if regressions:
        print("\nRATCHET REGRESSION (baseline must not grow):", file=sys.stderr)
        for line in regressions:
            print(f"  {line}", file=sys.stderr)
        print(
            "\nEither fix the findings, or --update the baseline if the new "
            "findings are pre-existing debt you are knowingly accepting.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK  ruff={current['ruff']['total']}/{baseline['ruff']['total']}  "
        f"mypy={current['mypy']['total']}/{baseline['mypy']['total']} "
        f"(no regression)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
