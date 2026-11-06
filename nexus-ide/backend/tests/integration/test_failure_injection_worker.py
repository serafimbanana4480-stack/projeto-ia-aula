"""Real-subprocess worker for the Fase 1 failure-injection suite.

This module is a *helper* (prefixed ``test_failure_injection_`` as the suite's
ownership requires): it holds no tests and is imported by pytest only as a
collectable module. What it provides is the child process
``test_run_failure_injection.py`` kills with SIGKILL in the middle of a side
effect, reusing the pattern of ``test_run_resume_e2e.py``: a real process, a
real database file, a real side effect on disk, and a kill that no shutdown
hook, ``finally`` block or graceful handler can survive.

The choreography it performs against the run the parent already created:

1. it applies the *first* side effect for real (a real append to a real file)
   and records it in the idempotency ledger — the confirmed one;
2. it writes the ``after_side_effect`` checkpoint that closes that boundary;
3. it signals readiness, then applies the *second* side effect for real and
   writes only its ``before_side_effect`` checkpoint: the real-world action has
   happened, the durable record never will. This is the state a killed process
   leaves behind;
4. it parks in a sleep loop and is killed by the parent.

Run it as::

    python -m backend.tests.integration.test_failure_injection_worker \
        --db <path> --run-id <id> --first-key <key> --second-key <key> \
        --effect-file <path> --ready-marker <path> --mid-marker <path>
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from backend.runtime.run_coordinator import RunCoordinator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="run-state database file")
    parser.add_argument("--run-id", required=True, help="run the parent created")
    parser.add_argument("--first-key", required=True, help="confirmed idempotency key")
    parser.add_argument("--second-key", required=True, help="mid-effect idempotency key")
    parser.add_argument("--effect-file", required=True, help="real file the side effects hit")
    parser.add_argument("--ready-marker", required=True, help="written after step 2")
    parser.add_argument("--mid-marker", required=True, help="written inside the second effect")
    args = parser.parse_args()

    coordinator = RunCoordinator(db_path=args.db)
    effect_file = Path(args.effect_file)
    ready = Path(args.ready_marker)
    mid = Path(args.mid_marker)

    # ── side effect 1: real action, real ledger row, closing checkpoint ────
    with effect_file.open("a", encoding="utf-8") as handle:
        handle.write("effect-one\n")
        handle.flush()
    coordinator.record_side_effect(
        args.run_id,
        args.first_key,
        kind="write_file",
        result_digest="digest-effect-one",
    )
    coordinator.checkpoint(
        args.run_id,
        phase="after_side_effect",
        payload={"idempotency_key": args.first_key, "tool": "write_file", "ok": True},
    )
    ready.write_text("effect-one confirmed\n", encoding="utf-8")

    # ── side effect 2: real action, checkpoint, no ledger row ──────────────
    with effect_file.open("a", encoding="utf-8") as handle:
        handle.write("effect-two\n")
        handle.flush()
    coordinator.checkpoint(
        args.run_id,
        phase="before_side_effect",
        payload={"idempotency_key": args.second_key, "tool": "write_file"},
    )
    mid.write_text("mid second side effect\n", encoding="utf-8")

    # ── parked here: the parent kills this process from the outside ────────
    while True:
        time.sleep(0.05)


if __name__ == "__main__":
    main()
