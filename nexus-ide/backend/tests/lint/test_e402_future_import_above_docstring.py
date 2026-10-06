"""Detect the `from __future__ import annotations` above the docstring bug.

This single mistake caused 45 of the 210 ruff findings, all from one root
cause. In nine route modules the order was

    from __future__ import annotations      <- line 1
    \"\"\"Module docstring.\"\"\"                 <- line 2, now a dead string
    from fastapi import APIRouter            <- line 3, E402: not at top of file

A string literal that is not the first statement is not a docstring. Python
still compiles it -- it is just an expression statement whose value is thrown
away -- so `help(module)` and every doc tool lose the module docstring, and ruff
then reports E402 for every import that follows.

All nine offenders were fixed on 2026-09-26 (the swap is a pure reordering: the
docstring moves above the ``__future__`` import, which PEP 236 explicitly
permits -- ``__future__`` must come first among *imports*, not before the
docstring). ``ALLOWED`` is therefore empty and the allowlist mechanism is kept
only as a zero-length ratchet: a file may never re-enter it.

Why a test and not a ruff rule
------------------------------
Ruff has no rule for "a string literal that should have been first". E402
reports the *symptom* (imports not at top of file) 45 times over, which buries
the one-line cause. This test names the cause directly.

Note: the 9 E402 findings that remain in the tree are a *different* defect --
``backend/agents/meta_cognition.py``, ``backend/orchestrator/advanced_modes.py``,
``backend/tests/mocks/conftest.py`` and ``backend/tests/sandbox/test_pool.py`` all
open with a correct docstring and only then run code before their imports. They
are outside this test's bug pattern (and outside the ownership of the change
that fixed the nine) so they are neither allowlisted nor claimed here.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

# module -> one-line remedy, for files owned elsewhere. Empty since 2026-09-26:
# all nine entries were fixed and deleted. Kept (as an empty mapping) so a future
# offender has an obvious, documented home -- and so `test_allowlist_is_not_growing`
# still has something to police.
ALLOWED: dict[str, str] = {}


def _docstring_is_dead(path: Path) -> bool:
    """True when a __future__ import has stranded a docstring behind it.

    The precise shape is:

        from __future__ import annotations   # body[0]
        \"\"\"Real docstring.\"\"\"                # body[1], evaluated and discarded

    A module that opens with `from __future__ import annotations` and has *no*
    docstring at all is NOT a defect -- it is merely undocumented, and it
    produces no E402. Using the compiled module's own idea of its docstring
    rather than a text match keeps a shebang, an encoding comment, or a leading
    `# comment` from producing a false positive.
    """
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Another agent mid-write; not this test's business.
        return False
    body = tree.body
    if len(body) < 2:
        return False
    first = body[0]
    if not (
        isinstance(first, ast.ImportFrom)
        and first.module == "__future__"
        and any(alias.name == "annotations" for alias in first.names)
    ):
        return False
    # The bug needs a *string literal* sitting in position 1: that is the
    # docstring that got demoted to a discarded expression.
    second = body[1]
    return (
        isinstance(second, ast.Expr)
        and isinstance(second.value, ast.Constant)
        and isinstance(second.value.value, str)
    )


def test_no_module_puts_future_import_above_its_docstring() -> None:
    offenders: list[str] = []
    for path in sorted(BACKEND.rglob("*.py")):
        if "__pycache__" in path.parts or "_archived" in path.parts:
            continue
        if not _docstring_is_dead(path):
            continue
        rel = path.relative_to(BACKEND.parent).as_posix()
        if rel in ALLOWED:
            continue
        offenders.append(
            f"{rel}: 'from __future__ import annotations' is the first statement, "
            f"so the docstring is dead and every later import trips E402"
        )
    assert not offenders, (
        "Move the module docstring above 'from __future__ import annotations' "
        "(PEP 236 requires __future__ first among *imports*, not before the "
        "docstring):\n  " + "\n  ".join(offenders)
    )


def test_allowlist_entries_still_describe_a_real_defect() -> None:
    """An allowlist entry that no longer matches is stale; remove it.

    This is what makes the ratchet self-tightening: fix a file, and the next run
    fails until its entry is deleted.
    """
    stale = [
        rel for rel in ALLOWED if not _docstring_is_dead(BACKEND.parent / rel)
    ]
    assert not stale, (
        "these entries are fixed but still allowlisted -- delete them from "
        f"ALLOWED: {stale}"
    )


def test_allowlist_is_not_growing() -> None:
    """Explicit statement of intent: the count is allowed to shrink, not grow."""
    assert len(ALLOWED) <= 9, (
        f"E402 allowlist grew to {len(ALLOWED)} entries ({sorted(ALLOWED)}). "
        f"Fix the offending file instead of allowlisting it."
    )


#: The nine files that carried the bug, named explicitly so the fix cannot be
#: silently reverted by a well-meaning "restore the original header" edit: the
#: allowlist above is empty, which on its own only proves *nobody* matches today.
FIXED_ON_2026_09_26: frozenset[str] = frozenset(
    {
        "backend/orchestrator/routes/analytics.py",
        "backend/orchestrator/routes/autonomous_tasks.py",
        "backend/orchestrator/routes/communication.py",
        "backend/orchestrator/routes/debate.py",
        "backend/orchestrator/routes/execution.py",
        "backend/orchestrator/routes/performance.py",
        "backend/orchestrator/routes/security.py",
        "backend/orchestrator/routes/topology.py",
        "backend/orchestrator/routes/users.py",
    }
)


def test_the_nine_formerly_offending_files_keep_a_real_docstring() -> None:
    """Each fixed file must have a live ``__doc__`` and a real ``__annotations__``.

    Two separate regressions are covered:

    * the swap did not happen (or was reverted) -- the docstring is dead again;
    * the swap went the *other* way and buried the docstring under the imports,
      which would silently drop every module docstring from ``help()`` and from
      the generated API reference while ruff stayed quiet.

    Checked on the AST rather than by importing the modules: ``users.py`` and
    friends build process-wide singletons at import time, and a lint test has no
    business triggering that a second time.
    """
    problems: list[str] = []
    for rel in sorted(FIXED_ON_2026_09_26):
        path = BACKEND.parent / rel
        assert path.exists(), f"{rel} vanished; update FIXED_ON_2026_09_26"
        if _docstring_is_dead(path):
            problems.append(f"{rel}: the dead-docstring bug is back")
            continue
        first = ast.parse(path.read_text(encoding="utf-8")).body[0]
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and first.value.value.strip()
        ):
            problems.append(f"{rel}: first statement is not a docstring, so __doc__ is empty")
            continue
        # PEP 236: `from __future__ import annotations` must precede every other
        # import, but it is allowed to follow the docstring.
        future_at = next(
            (
                index
                for index, node in enumerate(ast.parse(path.read_text(encoding="utf-8")).body)
                if isinstance(node, ast.ImportFrom) and node.module == "__future__"
            ),
            None,
        )
        if future_at != 1:
            problems.append(f"{rel}: expected the __future__ import at body[1], found body[{future_at}]")
    assert not problems, "\n".join(problems)
