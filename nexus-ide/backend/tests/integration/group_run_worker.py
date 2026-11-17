"""Subprocess worker for the group-run ownership integration test.

The test starts this module in separate operating-system processes so the
claim/lease rules are proven against a shared SQLite file, not against a
process-local Python object. ``NEXUS_DB_PATH`` carries the isolated database;
the parent seeds the schema and reads the rows back with plain ``sqlite3``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def _write(path: str, payload: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


def _claim(args: argparse.Namespace) -> dict[str, Any]:
    from backend.persistence import bot_group_runs

    token = bot_group_runs.claim_task(
        args.task, args.worker, lease_seconds=args.lease
    )
    return {"token": token}


def _recover_and_claim(args: argparse.Namespace) -> dict[str, Any]:
    from backend.persistence import bot_group_runs

    counts = bot_group_runs.interrupt_unfinished()
    token = bot_group_runs.claim_task(
        args.task, args.worker, lease_seconds=args.lease
    )
    return {"counts": counts, "token": token}


def _complete(args: argparse.Namespace) -> dict[str, Any]:
    from backend.persistence import bot_group_runs

    try:
        ok = bot_group_runs.complete_task(
            args.task, args.worker, args.token or "", result=args.result
        )
        return {"ok": ok}
    except Exception as exc:  # noqa: BLE001 - the type is the assertion
        return {"ok": False, "error": type(exc).__name__}


def _interrupt(_args: argparse.Namespace) -> dict[str, Any]:
    from backend.persistence import bot_group_runs

    return {"counts": bot_group_runs.interrupt_unfinished()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("claim", "recover_and_claim", "complete", "interrupt"),
    )
    parser.add_argument("--task", default="")
    parser.add_argument("--worker", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--result", default="done")
    parser.add_argument("--out", required=True)
    parser.add_argument("--gate", default="")
    parser.add_argument("--lease", type=float, default=60.0)
    parser.add_argument("--hold", type=float, default=0.0)
    args = parser.parse_args(argv)

    if args.gate:
        gate = Path(args.gate)
        deadline = time.time() + 30
        while not gate.exists() and time.time() < deadline:
            time.sleep(0.01)

    handlers = {
        "claim": _claim,
        "recover_and_claim": _recover_and_claim,
        "complete": _complete,
        "interrupt": _interrupt,
    }
    try:
        payload = handlers[args.action](args)
    except Exception as exc:  # noqa: BLE001 - reported to the parent
        payload = {"error": f"{type(exc).__name__}: {exc}"}
    _write(args.out, payload)
    if args.hold:
        time.sleep(args.hold)
    return 0


if __name__ == "__main__":
    sys.exit(main())
