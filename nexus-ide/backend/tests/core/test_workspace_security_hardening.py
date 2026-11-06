"""Security regression tests for the workspace sandbox hardening.

Covers the confirmed defects:

* D1 — sandbox escape through ``from os import system`` (and friends).  The
  check must resolve the SYMBOL, not the call syntax: ``from os import
  system`` binds the bare name ``system``, which looks nothing like the
  attribute access ``os.system`` and therefore slipped through while the code
  still ran with the full privileges of the backend process.
* D2 — shell allowlist bypass through ``git -c "alias.pwn=!<cmd>" pwn`` and
  friends.  Git must be restricted to a read-only subcommand allow-list.
* D3 — the ``"dd "`` substring blocked ``git add .`` / ``npm add lodash``.
"""

from __future__ import annotations

from backend.core.workspace_security import (
    _check_python_sandbox,
    _validate_shell_command,
    _validate_single_command,
)

# ---------------------------------------------------------------------------
# D1 — Python sandbox: the symbol, not the call syntax
# ---------------------------------------------------------------------------


def test_python_sandbox_rejects_from_os_import_system() -> None:
    """``from os import system`` must not be a way to run shell commands."""
    code = "from os import system\nsystem('echo NEXUS_SANDBOX_BYPASS_OS_SYSTEM')"

    is_safe, reason = _check_python_sandbox(code)

    assert not is_safe, "from os import system must be rejected"
    assert "system" in reason.lower()
    assert "os" in reason.lower()


def test_python_sandbox_rejects_from_subprocess_import() -> None:
    """Every import from ``subprocess`` stays blocked, star import included."""
    for code in (
        "from subprocess import run",
        "from subprocess import *",
        "from subprocess import Popen as popen",
    ):
        is_safe, reason = _check_python_sandbox(code)

        assert not is_safe, code
        assert "subprocess" in reason.lower()


def test_python_sandbox_rejects_os_environ_read() -> None:
    """``os.environ`` must not be readable, not even without a call."""
    for code in (
        "import os\nprint(os.environ)",
        "import os\nvalue = os.environ",
        "import os as o\nprint(o.environ)",
    ):
        is_safe, reason = _check_python_sandbox(code)

        assert not is_safe, code
        assert "environ" in reason.lower()


def test_python_sandbox_rejects_shutil_rmtree() -> None:
    """``shutil.rmtree`` must be blocked, as attribute and as direct import."""
    for code in (
        "import shutil\nshutil.rmtree('C:/Windows/Temp')",
        "from shutil import rmtree",
        "from shutil import rmtree as wipe",
    ):
        is_safe, reason = _check_python_sandbox(code)

        assert not is_safe, code
        assert "rmtree" in reason.lower()


def test_python_sandbox_allows_safe_imports() -> None:
    """Ordinary imports and calls must keep working."""
    code = (
        "import json\n"
        "import math\n"
        "from pathlib import Path\n"
        "from collections import OrderedDict\n"
        "from os import path\n"
        "data = json.dumps({'value': math.floor(1.5)})\n"
        "print(data, Path('.').name, list(OrderedDict({'a': 1})), path.sep)\n"
    )

    is_safe, reason = _check_python_sandbox(code)

    assert is_safe, reason


# ---------------------------------------------------------------------------
# D2 — Git must stay inside a read-only allow-list
# ---------------------------------------------------------------------------


def test_git_alias_with_bang_is_rejected() -> None:
    """``git -c alias.pwn=!<cmd> pwn`` executes an arbitrary shell command."""
    for command in (
        'git -c "alias.pwn=!echo NEXUS_GIT_ALIAS_BYPASS" pwn',
        "git -c alias.pwn=!echo NEXUS_GIT_ALIAS_BYPASS pwn",
    ):
        is_safe, reason = _validate_shell_command(command)

        assert not is_safe, command
        assert "git" in reason.lower()


def test_git_config_dash_c_is_rejected() -> None:
    """``git -c`` rewrites git's own configuration, so it stays blocked."""
    for command in (
        "git -c core.pager=cat status",
        "git --config-env=core.editor=evil status",
        "git --exec-path",
    ):
        is_safe, reason = _validate_shell_command(command)

        assert not is_safe, command
        assert "git" in reason.lower()


def test_git_read_only_subcommand_is_allowed() -> None:
    """Read-only git commands must keep working."""
    for command in (
        "git status",
        "git log --oneline -5",
        "git diff",
        "git show HEAD",
        "git branch --list",
        "git remote -v",
        "git rev-parse HEAD",
        "git ls-files",
        "git blame file.py",
        "git describe",
        "git tag --list",
    ):
        is_safe, reason = _validate_shell_command(command)

        assert is_safe, f"{command!r} was rejected: {reason}"


def test_git_mutating_subcommand_is_rejected() -> None:
    """Mutating git commands are not part of the read-only allow-list."""
    for command in (
        "git add .",
        "git commit -m 'oops'",
        "git checkout main",
        "git branch -d feature",
        "git tag v1.0",
        "git config user.name hacker",
    ):
        is_safe, reason = _validate_single_command(command)

        assert not is_safe, command
        assert "git" in reason.lower()


# ---------------------------------------------------------------------------
# D3 — "dd" must be matched as a whole word
# ---------------------------------------------------------------------------


def test_git_add_is_not_blocked_by_dd_pattern() -> None:
    """``git add``/``npm add`` were blocked by the ``"dd "`` substring."""
    for command in ("git add .", "npm add lodash", "yarn add lodash"):
        is_safe, reason = _validate_shell_command(command)

        if not is_safe:
            # The read-only git allow-list may still refuse ``git add``,
            # but never because of the "dd" substring.
            assert "dangerous pattern 'dd'" not in reason.lower(), (
                f"{command!r} was blocked by the dd pattern"
            )
            assert "git" in reason.lower() or "whitelist" in reason.lower()


def test_dd_if_still_blocked() -> None:
    """The real ``dd`` utility stays blocked."""
    is_safe, reason = _validate_shell_command("dd if=/dev/zero of=image.img")

    assert not is_safe
    assert "dd" in reason.lower()
