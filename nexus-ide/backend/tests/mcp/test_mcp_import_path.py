"""The in-repo ``backend/mcp`` package must never shadow the MCP SDK.

The NEXUS backend puts the ``backend/`` directory on ``sys.path`` (see
``backend/migrations/env.py``, which runs inside ``init_db()`` at every
process start). When that happens, the *top-level* name ``mcp`` used to
resolve to the in-repo connector package instead of the installed SDK, and
``from mcp import ClientSession`` raised ``ImportError``: the whole MCP
subsystem was dead in a running process.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"


def _run_clean_interpreter(code: str, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run *code* in a fresh interpreter without the parent's ``sys.path``."""
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(cwd or REPO_ROOT),
        env=env,
    )


def test_in_repo_mcp_package_does_not_shadow_the_sdk():
    """``import mcp`` must resolve to the installed SDK, not to backend/mcp.

    The subprocess reproduces exactly what a NEXUS process does: the
    ``backend/`` directory is inserted at ``sys.path[0]``.
    """
    code = "\n".join(
        [
            "import sys",
            f"sys.path.insert(0, {str(REPO_ROOT)!r})",
            # This is the mutation done by backend/migrations/env.py.
            f"sys.path.insert(0, {str(BACKEND_DIR)!r})",
            "import mcp",
            "from mcp import ClientSession",
            "from mcp.server import Server",
            "from mcp.types import Tool",
            "import backend.mcp",
            "print(mcp.__file__)",
            "print(backend.mcp.__file__)",
        ]
    )

    completed = _run_clean_interpreter(code)

    assert completed.returncode == 0, completed.stderr
    sdk_path, backend_path = completed.stdout.strip().splitlines()[-2:]
    resolved = Path(sdk_path).resolve()
    assert resolved != (BACKEND_DIR / "mcp" / "__init__.py").resolve()
    assert resolved.name == "__init__.py"
    assert resolved.parent.name == "mcp"
    assert "site-packages" in resolved.parts
    # The in-repo package keeps its own identity under ``backend.mcp``.
    assert Path(backend_path).resolve().parent == (BACKEND_DIR / "mcp").resolve()


def test_mcp_builder_works_after_init_db(tmp_path):
    """After ``init_db()`` the SDK — and the Builder — must still import.

    ``init_db()`` is the startup path of every NEXUS process; it is what
    puts ``backend/`` on ``sys.path`` and used to break every MCP import.
    """
    db_path = tmp_path / "nexus-init-db.db"
    code = "\n".join(
        [
            "import pathlib, sys",
            f"sys.path.insert(0, {str(REPO_ROOT)!r})",
            "from backend.persistence import db",
            f"db.DB_PATH = pathlib.Path({str(db_path)!r})",
            "db.init_db()",
            # The migration environment (backend/migrations/env.py) puts the
            # backend directory first on sys.path.
            f"sys.path.insert(0, {str(BACKEND_DIR)!r})",
            "import mcp",
            "from mcp import ClientSession",
            "from mcp.server import Server",
            "from backend.mcp import builder, runtime, store",
            "from backend.mcp.builder import MCPBuilderError, build_from_description",
            "print(mcp.__file__)",
        ]
    )

    completed = _run_clean_interpreter(code)

    assert completed.returncode == 0, completed.stderr
    sdk_path = completed.stdout.strip().splitlines()[-1]
    resolved = Path(sdk_path).resolve()
    assert "site-packages" in resolved.parts
    assert resolved != (BACKEND_DIR / "mcp" / "__init__.py").resolve()
