"""Interpreter resolution shared by every tool that shells out to Python.

``["python", ...]`` (or ``python3``) means "whatever is first on PATH", which
is routinely NOT the interpreter running NEXUS and, on Windows with an
unactivated project venv, is often a bare system Python with none of the
project's dependencies. That mismatch produced "No module named pytest" and,
because the caller only checked the failure count, a green verification over
zero executed tests (audit 2026-08-16, P3/P9i).

Resolution order, most specific first:

1. ``NEXUS_PYTHON`` — an explicit operator override;
2. the project's own virtualenv (``venv``/``.venv``/``env``);
3. ``sys.executable`` — the interpreter already running the backend;
4. ``python3``/``python`` from PATH, preserving historical behaviour.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

__all__ = ["resolve_python_interpreter"]

_VENV_DIRS = ("venv", ".venv", "env", ".env")
_VENV_BINS = (("Scripts", "python.exe"), ("bin", "python"), ("bin", "python3"))


def resolve_python_interpreter(project_path: str | None = None) -> str:
    """Return the best Python interpreter for running code in ``project_path``."""
    override = (os.environ.get("NEXUS_PYTHON") or "").strip()
    if override:
        return override

    if project_path:
        root = Path(project_path)
        for venv_name in _VENV_DIRS:
            for parts in _VENV_BINS:
                candidate = root.joinpath(venv_name, *parts)
                try:
                    if candidate.is_file():
                        return str(candidate)
                except OSError:  # pragma: no cover - unreadable path
                    continue

    if sys.executable:
        return sys.executable

    return shutil.which("python3") or shutil.which("python") or "python"
