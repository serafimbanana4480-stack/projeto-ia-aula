"""Workspace Manager — full filesystem and terminal access for NEXUS agents.

Replaces sandboxed file_ops / shell_runner with absolute-path operations.
Dangerous commands and system paths are blocked via blacklist; user home and
project directories are always allowed. All operations are logged and writes
are backed up to ``.nexus/backups/``.

Exposes both a :class:`WorkspaceManager` (used by legacy ``file_ops.py`` and
``shell_runner.py``) and free functions (registered as new absolute-path tools).

This module is a **facade** that re-exports implementations from the
specialised sub-modules so that existing imports continue to work unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

# Re-export backup layer ----------------------------------------------------
from backend.core.workspace_backup import (
    _is_git_repo,
    list_backups,
    restore_backup,
)

# Re-export filesystem layer ------------------------------------------------
from backend.core.workspace_fs import (
    copy_file_absolute,
    create_dir_absolute,
    delete_dir_absolute,
    delete_file_absolute,
    get_file_info_absolute,
    list_dir_absolute,
    move_file_absolute,
    read_file_absolute,
    read_multiple_files_absolute,
    search_files_absolute,
    write_file_absolute,
)

# Re-export security layer --------------------------------------------------
from backend.core.workspace_security import (
    _check_file_size_limit,
    _is_blocked_path,
    _is_path_within_project,
    _is_safe_git_remote,
)

# Re-export shell layer -----------------------------------------------------
from backend.core.workspace_shell import (
    execute_python,
    execute_script,
    execute_shell,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Git integration
# ---------------------------------------------------------------------------


async def _git_raw(args: list[str], cwd: str, timeout: int = 60) -> dict[str, Any]:
    """Run a raw git command and return structured output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            return {
                "exit_code": proc.returncode,
                "error": err or out,
                "command": f"git {' '.join(args)}",
            }

        return {"output": out, "command": f"git {' '.join(args)}", "exit_code": 0}
    except TimeoutError:
        return {"error": f"Git command timed out: git {' '.join(args)}"}
    except FileNotFoundError:
        return {"error": "Git is not installed or not in PATH"}
    except Exception as exc:
        return {"error": f"Git operation failed: {exc}"}


async def git_init(path: str) -> dict[str, Any]:
    """Initialise a git repository at *path*."""
    logger.info("git_init: %s", path)
    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": f"Blocked path: {reason}"}
    target = await asyncio.to_thread(lambda: Path(path).expanduser().resolve())
    await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)
    return await _git_raw(["init"], str(target))


async def git_clone(url: str, path: str) -> dict[str, Any]:
    """Clone a git repository into *path*."""
    logger.info("git_clone: %s -> %s", url, path)
    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": f"Blocked path: {reason}"}
    target = await asyncio.to_thread(lambda: Path(path).expanduser().resolve())
    await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
    return await _git_raw(["clone", url, str(target)], str(target.parent), timeout=180)


async def git_commit_all(
    path: str, message: str = "auto: changes from NEXUS workspace"
) -> dict[str, Any]:
    """Stage all changes and commit in *path*."""
    logger.info("git_commit_all: %s message='%s'", path, message)
    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": f"Blocked path: {reason}"}
    target = str(await asyncio.to_thread(lambda: Path(path).expanduser().resolve()))

    safe_message = message.replace('"', '\\"').replace("`", "").replace("$", "")[:500]

    add_res = await _git_raw(["add", "-A"], target)
    if "error" in add_res and add_res.get("exit_code", 0) != 0:
        return {"error": f"git add failed: {add_res.get('error')}", "add": add_res}

    commit_res = await _git_raw(["commit", "-m", safe_message], target)
    return {"add": add_res, "commit": commit_res}


async def git_push(path: str, remote: str = "origin", branch: str | None = None) -> dict[str, Any]:
    """Push commits from *path*. Only safe remotes are permitted."""
    logger.info("git_push: %s remote=%s branch=%s", path, remote, branch)
    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": f"Blocked path: {reason}"}
    target = str(await asyncio.to_thread(lambda: Path(path).expanduser().resolve()))

    # Validate remote URL before pushing
    remote_check = await _git_raw(["remote", "get-url", remote], target, timeout=30)
    if "error" in remote_check and remote_check.get("exit_code", 0) != 0:
        return {
            "error": f"Cannot verify remote '{remote}': {remote_check.get('error')}",
            "command": f"git push {remote}",
        }

    remote_url = remote_check.get("output", "")
    if not _is_safe_git_remote(remote_url):
        logger.warning("Blocked git_push to unsafe remote: %s", remote_url)
        return {
            "error": (
                f"Push to remote '{remote}' (URL: {remote_url}) is not allowed. "
                "Only GitHub, GitLab, and Bitbucket remotes are permitted."
            ),
            "command": f"git push {remote}",
        }

    args = ["push", remote]
    if branch:
        args.append(branch)
    return await _git_raw(args, target, timeout=120)


async def git_status(path: str) -> dict[str, Any]:
    """Return git status for *path*."""
    logger.info("git_status: %s", path)
    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": f"Blocked path: {reason}"}
    target = str(await asyncio.to_thread(lambda: Path(path).expanduser().resolve()))
    return await _git_raw(["status", "-sb"], target)


# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------

_LANGUAGE_INDICATORS: dict[str, list[str]] = {
    "python": ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile"],
    "javascript": ["package.json", "package-lock.json", "yarn.lock"],
    "typescript": ["tsconfig.json", "package.json"],
    "rust": ["Cargo.toml", "Cargo.lock"],
    "go": ["go.mod", "go.sum"],
    "ruby": ["Gemfile", "Gemfile.lock"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "dotnet": [".csproj", ".sln"],
    "php": ["composer.json", "composer.lock"],
    "elixir": ["mix.exs", "mix.lock"],
    "haskell": ["stack.yaml", "cabal.project"],
    "c": ["CMakeLists.txt", "Makefile"],
    "cpp": ["CMakeLists.txt", "Makefile", "conanfile.txt"],
}

_FRAMEWORK_INDICATORS: dict[str, list[str]] = {
    "django": ["manage.py", "wsgi.py", "asgi.py"],
    "flask": ["app.py", "wsgi.py"],
    "fastapi": ["main.py", "app/main.py"],
    "react": ["src/App.jsx", "src/App.tsx", "public/index.html"],
    "vue": ["vue.config.js", "vite.config.ts"],
    "angular": ["angular.json", ".angular-cli.json"],
    "nextjs": ["next.config.js", "next.config.mjs"],
    "rails": ["config/routes.rb", "Rakefile"],
    "laravel": ["artisan", "webpack.mix.js"],
    "spring": ["src/main/java", "src/main/resources/application.properties"],
}

_SKIP_DIRS: set[str] = {
    "node_modules",
    ".venv",
    "__pycache__",
    ".git",
    "dist",
    "build",
    ".next",
    "target",
    ".cargo",
}


async def _detect_language(project_path: Path) -> str:
    scores: dict[str, int] = {}
    for lang, indicators in _LANGUAGE_INDICATORS.items():
        for indicator in indicators:
            if await asyncio.to_thread((project_path / indicator).exists):
                scores[lang] = scores.get(lang, 0) + 1
    return max(scores, key=scores.get) if scores else "unknown"


async def _detect_framework(project_path: Path, language: str) -> str | None:
    for framework, indicators in _FRAMEWORK_INDICATORS.items():
        for indicator in indicators:
            if await asyncio.to_thread((project_path / indicator).exists):
                return framework
    return None


async def _get_dependencies(project_path: Path, language: str) -> list[str]:
    deps: list[str] = []
    try:
        if language == "python":
            req_file = project_path / "requirements.txt"
            if await asyncio.to_thread(req_file.exists):
                try:
                    text = await asyncio.to_thread(
                        req_file.read_text, encoding="utf-8", errors="ignore"
                    )
                except (PermissionError, FileNotFoundError):
                    text = ""
                for line in text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        deps.append(line.split("=")[0].split("<")[0].split(">")[0].strip())
            elif await asyncio.to_thread((project_path / "pyproject.toml").exists):
                deps.append("pyproject.toml")
        elif language in ("javascript", "typescript"):
            pkg_file = project_path / "package.json"
            if await asyncio.to_thread(pkg_file.exists):
                try:
                    text = await asyncio.to_thread(pkg_file.read_text, encoding="utf-8")
                    data = json.loads(text)
                    deps.extend(data.get("dependencies", {}).keys())
                    deps.extend(data.get("devDependencies", {}).keys())
                except Exception:
                    logger.debug("Failed to parse package.json in %s", project_path, exc_info=True)
        elif language == "rust":
            if await asyncio.to_thread((project_path / "Cargo.toml").exists):
                deps.append("Cargo.toml")
        elif language == "go":
            if await asyncio.to_thread((project_path / "go.mod").exists):
                deps.append("go.mod")
    except (PermissionError, FileNotFoundError):
        logger.debug(
            "Permission or file not found error reading dependencies in %s",
            project_path,
            exc_info=True,
        )
    return deps[:50]


# ---------------------------------------------------------------------------
# Discovery cache
# ---------------------------------------------------------------------------

_DISCOVERY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_DISCOVERY_CACHE_TTL = 300  # 5 minutes


async def discover_projects(
    root_path: str, max_depth: int = 5, max_results: int = 100
) -> dict[str, Any]:
    """Find all git repos and common project structures under *root_path*."""
    logger.info("discover_projects: %s", root_path)

    blocked, reason = _is_blocked_path(root_path)
    if blocked:
        return {"error": reason}

    try:
        root = await asyncio.to_thread(lambda: Path(root_path).expanduser().resolve())
        if not await asyncio.to_thread(root.exists):
            return {"error": f"Root path not found: {root_path}"}
        if not await asyncio.to_thread(root.is_dir):
            return {"error": f"Path is not a directory: {root_path}"}
    except (PermissionError, OSError) as exc:
        return {"error": f"Failed to access root path: {exc}"}

    cache_key = f"{root}:{max_depth}:{max_results}"
    now = time.monotonic()
    cached = _DISCOVERY_CACHE.get(cache_key)
    if cached is not None:
        cached_at, result = cached
        if now - cached_at < _DISCOVERY_CACHE_TTL:
            return {**result, "cached": True}

    projects: list[dict[str, Any]] = []
    seen: set[str] = set()

    async def _is_project_root(path: Path) -> tuple[bool, bool]:
        """Return (is_git_root, is_project) for *path*."""
        try:
            has_git = await asyncio.to_thread((path / ".git").exists)
        except (PermissionError, OSError):
            has_git = False
        is_project = False
        for indicators in _LANGUAGE_INDICATORS.values():
            for indicator in indicators:
                if await asyncio.to_thread((path / indicator).exists):
                    is_project = True
                    break
            if is_project:
                break
        return has_git, is_project

    # If root itself is a project, return it immediately.
    root_git, root_project = await _is_project_root(root)
    if root_git or root_project:
        lang = await _detect_language(root)
        projects.append(
            {
                "path": str(root),
                "name": root.name,
                "is_git_repo": root_git,
                "detected_language": lang,
                "detected_framework": await _detect_framework(root, lang),
            }
        )
        result = {"root": str(root), "projects": projects, "count": len(projects)}
        _DISCOVERY_CACHE[cache_key] = (now, result)
        return {**result, "cached": False}

    async def scan(path: Path, depth: int) -> None:
        if depth > max_depth or len(projects) >= max_results:
            return
        try:
            entries = await asyncio.to_thread(lambda: list(os.scandir(path)))
            for entry in entries:
                if not await asyncio.to_thread(entry.is_dir, follow_symlinks=False):
                    continue
                name = entry.name
                if name in _SKIP_DIRS or name.startswith("."):
                    continue
                child = Path(entry.path)
                child_key = str(child)
                if child_key in seen:
                    continue
                has_git, is_project = await _is_project_root(child)
                if has_git or is_project:
                    seen.add(child_key)
                    lang = await _detect_language(child)
                    projects.append(
                        {
                            "path": child_key,
                            "name": child.name,
                            "is_git_repo": has_git,
                            "detected_language": lang,
                            "detected_framework": await _detect_framework(child, lang),
                        }
                    )
                    # Don't recurse into identified projects — fixes deduplication
                    continue
                await scan(child, depth + 1)
        except PermissionError:
            logger.debug("Permission denied scanning %s", path, exc_info=True)
        except OSError:
            logger.debug("OS error scanning %s", path, exc_info=True)

    try:
        await scan(root, 1)
    except PermissionError:
        logger.debug("Permission denied scanning root %s", root, exc_info=True)
    except OSError:
        logger.debug("OS error scanning root %s", root, exc_info=True)

    result = {"root": str(root), "projects": projects, "count": len(projects)}
    _DISCOVERY_CACHE[cache_key] = (now, result)
    return {**result, "cached": False}


async def get_project_info(path: str) -> dict[str, Any]:
    """Detect language, framework, dependencies and git status for *path*."""
    logger.info("get_project_info: %s", path)

    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": reason}

    try:
        project = await asyncio.to_thread(lambda: Path(path).expanduser().resolve())
        if not await asyncio.to_thread(project.exists):
            return {"error": f"Path not found: {path}"}

        language = await _detect_language(project)
        framework = await _detect_framework(project, language)
        dependencies = await _get_dependencies(project, language)

        git_info: dict[str, Any] = {"is_repo": False}
        if await _is_git_repo(project):
            try:
                branch_proc = await asyncio.create_subprocess_exec(
                    "git",
                    "rev-parse",
                    "--abbrev-ref",
                    "HEAD",
                    cwd=str(project),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                branch_stdout, _ = await asyncio.wait_for(branch_proc.communicate(), timeout=10)
                branch = branch_stdout.decode("utf-8", errors="replace").strip()

                remote_proc = await asyncio.create_subprocess_exec(
                    "git",
                    "remote",
                    "get-url",
                    "origin",
                    cwd=str(project),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                remote_stdout, _ = await asyncio.wait_for(remote_proc.communicate(), timeout=10)
                remote = remote_stdout.decode("utf-8", errors="replace").strip()

                git_info = {"is_repo": True, "branch": branch, "remote": remote}
            except Exception:
                git_info = {"is_repo": True, "branch": "unknown", "remote": None}

        file_count = 0
        dir_count = 0
        try:
            entries = await asyncio.to_thread(lambda: list(project.rglob("*")))
            for e in entries:
                if await asyncio.to_thread(e.is_file):
                    file_count += 1
                elif await asyncio.to_thread(e.is_dir):
                    dir_count += 1
        except (PermissionError, FileNotFoundError, OSError):
            logger.debug("Failed to count files/dirs in %s", project, exc_info=True)

        return {
            "path": str(project),
            "name": project.name,
            "language": language,
            "framework": framework,
            "dependencies": dependencies,
            "git": git_info,
            "file_count": file_count,
            "dir_count": dir_count,
        }
    except PermissionError:
        return {"error": f"Permission denied: {path}"}
    except Exception as exc:
        return {"error": f"Failed to get project info: {exc}"}


# ---------------------------------------------------------------------------
# System info & process management
# ---------------------------------------------------------------------------


async def get_system_info() -> dict[str, Any]:
    """Get CPU, RAM, disk, and GPU information."""
    info: dict[str, Any] = {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
    }

    try:
        import psutil

        mem = psutil.virtual_memory()
        info["ram"] = {
            "total_gb": round(mem.total / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "percent_used": mem.percent,
        }

        disk = psutil.disk_usage("/")
        info["disk"] = {
            "total_gb": round(disk.total / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent_used": disk.percent,
        }

        info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
    except ImportError:
        info["ram"] = "psutil not installed"
        info["disk"] = "psutil not installed"
        info["cpu_percent"] = "psutil not installed"

    info["gpu"] = []
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    info["gpu"].append(
                        {
                            "name": parts[0],
                            "memory_total_mb": parts[1],
                            "memory_used_mb": parts[2],
                            "utilization_percent": parts[3],
                        }
                    )
    except Exception:
        logger.debug("nvidia-smi failed or GPU not available", exc_info=True)

    if not info["gpu"]:
        info["gpu"] = "No GPU detected or nvidia-smi not available"

    return info


async def find_processes(name: str = "") -> dict[str, Any]:
    """Find running processes by name (case-insensitive substring match)."""
    processes: list[dict[str, Any]] = []

    try:
        import psutil

        for proc in psutil.process_iter(
            ["pid", "name", "cmdline", "cpu_percent", "memory_percent"]
        ):
            proc_name = proc.info.get("name") or ""
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if name.lower() in proc_name.lower() or name.lower() in cmdline.lower():
                processes.append(
                    {
                        "pid": proc.info.get("pid"),
                        "name": proc_name,
                        "cmdline": cmdline,
                        "cpu_percent": proc.info.get("cpu_percent"),
                        "memory_percent": round(proc.info.get("memory_percent") or 0, 2),
                    }
                )
    except ImportError:
        if platform.system() == "Windows":
            result = await asyncio.to_thread(
                subprocess.run,
                ["tasklist", "/FO", "CSV"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n")[1:]:
                    parts = [p.strip('"') for p in line.split('","')]
                    if len(parts) >= 2 and name.lower() in parts[0].lower():
                        processes.append(
                            {
                                "pid": parts[1],
                                "name": parts[0],
                                "cmdline": "",
                                "cpu_percent": None,
                                "memory_percent": None,
                            }
                        )
        else:
            result = await asyncio.to_thread(
                subprocess.run,
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n")[1:]:
                    if name.lower() in line.lower():
                        parts = line.split()
                        if len(parts) >= 11:
                            processes.append(
                                {
                                    "pid": parts[1],
                                    "name": parts[10],
                                    "cmdline": " ".join(parts[10:]),
                                    "cpu_percent": parts[2],
                                    "memory_percent": parts[3],
                                }
                            )

    return {"name": name, "processes": processes, "count": len(processes)}


async def kill_process(pid: int) -> dict[str, Any]:
    """Kill a process by PID."""
    try:
        try:
            import psutil

            proc = psutil.Process(pid)
            proc.terminate()
            gone, alive = psutil.wait_procs([proc], timeout=5)
            if proc in alive:
                proc.kill()
                return {"killed": True, "force": True, "pid": pid}
        except ImportError:
            if platform.system() == "Windows":
                await asyncio.to_thread(
                    subprocess.run,
                    ["taskkill", "/PID", str(pid), "/F"],
                    check=True,
                    timeout=10,
                )
            else:
                await asyncio.to_thread(
                    subprocess.run,
                    ["kill", "-9", str(pid)],
                    check=True,
                    timeout=10,
                )

        return {"killed": True, "force": False, "pid": pid}
    except Exception as exc:
        return {"error": f"Failed to kill process {pid}: {exc}"}


# ---------------------------------------------------------------------------
# WorkspaceManager class — backward-compatible wrapper
# ---------------------------------------------------------------------------


class WorkspaceManager:
    """Central manager for filesystem and shell operations.

    Wraps the free functions so that ``file_ops.py`` and ``shell_runner.py``
    can continue to instantiate ``WorkspaceManager(project_path)``.
    """

    def __init__(self, project_path: str = "."):
        self.project_path = Path(project_path).resolve()

    def _resolve(self, path: str) -> str:
        """Resolve *path* relative to ``project_path`` if it is not absolute."""
        if Path(path).is_absolute():
            blocked, reason = _is_blocked_path(path)
            if blocked:
                raise PermissionError(f"Blocked path: {reason}")
            return str(Path(path).expanduser().resolve())
        resolved = (self.project_path / path).expanduser().resolve()
        try:
            resolved.relative_to(self.project_path)
        except ValueError:
            raise PermissionError(
                f"Access not allowed — path {resolved} is outside project root {self.project_path}"
            ) from None
        return str(resolved)

    def _resolve_path(self, path: str) -> Path:
        """Return a :class:`Path` resolved relative to ``project_path``."""
        if Path(path).is_absolute():
            blocked, reason = _is_blocked_path(path)
            if blocked:
                raise PermissionError(f"Blocked path: {reason}")
            return Path(path).expanduser().resolve()
        resolved = (self.project_path / path).expanduser().resolve()
        try:
            resolved.relative_to(self.project_path)
        except ValueError:
            raise PermissionError(
                f"Access not allowed — path {resolved} is outside project root {self.project_path}"
            ) from None
        return resolved

    def _validate_path(self, path: Path, _operation: str = "") -> None:
        """Raise ``PermissionError`` if *path* is outside ``project_path``."""
        ok, reason = _is_path_within_project(str(self.project_path), str(path))
        if not ok:
            raise PermissionError(reason)

    def _check_project_trust(self, _path: Path) -> None:
        """Raise ``PermissionError`` if the project is not trusted."""
        from backend.persistence.db import get_project_by_path

        project = get_project_by_path(str(self.project_path))
        if project and not project.get("trust", False):
            raise PermissionError(
                f"Project '{project['name']}' is NOT trusted. "
                "Enable trust in project settings before allowing file modifications."
            )

    async def read_file(self, path: str) -> dict[str, Any]:
        return await read_file_absolute(self._resolve(path))

    async def read_multiple_files(
        self, paths: list[str], max_total_bytes: int = 5 * 1024 * 1024, max_files: int = 100
    ) -> dict[str, Any]:
        """Read several project files in one batch."""
        resolved = [self._resolve(p) for p in paths]
        return await read_multiple_files_absolute(
            resolved, max_total_bytes=max_total_bytes, max_files=max_files
        )

    async def write_file(
        self,
        path: str,
        content: str,
        session_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        abs_path = self._resolve(path)

        # Trust verification — block writes to untrusted projects
        from backend.persistence.db import get_project_by_path

        project = get_project_by_path(str(self.project_path))
        if project and not project.get("trust", False):
            return {
                "error": (
                    f"Project '{project['name']}' is NOT trusted. "
                    "Enable trust in project settings before allowing file modifications."
                )
            }

        result = await write_file_absolute(abs_path, content)

        if session_id and "error" not in result:
            from backend.persistence.db import propose_change

            propose_change(
                session_id=session_id,
                project_id=project_id,
                file_path=str(Path(abs_path).relative_to(self.project_path)),
                operation="modify" if result.get("backup", {}).get("backed_up") else "create",
                new_content=content,
            )

        return result

    async def list_directory(self, path: str, recursive: bool = False) -> dict[str, Any]:
        return await list_dir_absolute(self._resolve(path), recursive=recursive)

    async def search_files(self, path: str, pattern: str, glob: str = "*.py") -> dict[str, Any]:
        # The legacy signature expects path + pattern + glob.
        # We perform a content search under *path* and filter by glob.
        search_root = self._resolve(path)
        results = []
        count = 0
        try:
            root = Path(search_root)
            file_paths = await asyncio.to_thread(lambda: list(root.rglob(glob)))
            for file_path in file_paths:
                if not await asyncio.to_thread(file_path.is_file):
                    continue
                ok, _size, _err = _check_file_size_limit(file_path)
                if not ok:
                    continue
                try:
                    content = await asyncio.to_thread(
                        file_path.read_text, encoding="utf-8", errors="ignore"
                    )
                except Exception:
                    continue
                if pattern.lower() in content.lower():
                    lines = content.splitlines()
                    matches = [
                        (i + 1, line)
                        for i, line in enumerate(lines)
                        if pattern.lower() in line.lower()
                    ]
                    if matches:
                        results.append(
                            {
                                "path": str(file_path.relative_to(root)),
                                "matches": len(matches),
                                "preview": matches[:3],
                            }
                        )
                        count += 1
        except Exception as exc:
            return {"error": f"Search failed: {exc}"}

        return {"query": pattern, "results": results, "count": count}

    async def execute_shell(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 120,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        resolved_cwd = self._resolve(cwd) if cwd else str(self.project_path)
        return await execute_shell(command, cwd=resolved_cwd, timeout=timeout, env=env)

    async def execute_python(
        self, code: str, cwd: str | None = None, timeout: int = 120
    ) -> dict[str, Any]:
        resolved_cwd = self._resolve(cwd) if cwd else str(self.project_path)
        return await execute_python(code, cwd=resolved_cwd, timeout=timeout)

    async def create_directory(self, path: str) -> dict[str, Any]:
        return await create_dir_absolute(self._resolve(path))

    async def delete_file(self, path: str, move_to_trash: bool = True) -> dict[str, Any]:
        return await delete_file_absolute(self._resolve(path), move_to_trash=move_to_trash)

    async def delete_directory(self, path: str, move_to_trash: bool = True) -> dict[str, Any]:
        return await delete_dir_absolute(self._resolve(path), move_to_trash=move_to_trash)

    async def move_file(self, src: str, dest: str) -> dict[str, Any]:
        return await move_file_absolute(self._resolve(src), self._resolve(dest))

    async def copy_file(self, src: str, dest: str) -> dict[str, Any]:
        return await copy_file_absolute(self._resolve(src), self._resolve(dest))

    async def get_file_info(self, path: str) -> dict[str, Any]:
        return await get_file_info_absolute(self._resolve(path))

    async def list_backups(self, path: str | None = None) -> dict[str, Any]:
        return await list_backups(self._resolve(path) if path else str(self.project_path))

    async def restore_backup(self, backup_path: str, target_path: str) -> dict[str, Any]:
        return await restore_backup(backup_path, self._resolve(target_path))

    async def git_init(self, path: str | None = None) -> dict[str, Any]:
        return await git_init(self._resolve(path) if path else str(self.project_path))

    async def git_clone(self, url: str, path: str) -> dict[str, Any]:
        return await git_clone(url, self._resolve(path))

    async def git_commit_all(
        self, path: str | None = None, message: str = "auto: changes from NEXUS workspace"
    ) -> dict[str, Any]:
        return await git_commit_all(
            self._resolve(path) if path else str(self.project_path), message
        )

    async def git_push(
        self, path: str | None = None, remote: str = "origin", branch: str | None = None
    ) -> dict[str, Any]:
        return await git_push(
            self._resolve(path) if path else str(self.project_path), remote, branch
        )

    async def git_status(self, path: str | None = None) -> dict[str, Any]:
        return await git_status(self._resolve(path) if path else str(self.project_path))

    async def git_commit(
        self, repo_path: str = ".", message: str = "auto: changes from NEXUS agent"
    ) -> dict[str, Any]:
        """Safely commit changes (without add)."""
        return await git_commit_all(self._resolve(repo_path), message=message)

    async def get_system_info(self) -> dict[str, Any]:
        return await get_system_info()

    async def find_processes(self, name: str = "") -> dict[str, Any]:
        return await find_processes(name)

    async def kill_process(self, pid: int) -> dict[str, Any]:
        return await kill_process(pid)

    # ── Auto-trust ──────────────────────────────────────────────────────────

    def auto_trust_project(self, path: str | Path) -> None:
        """Mark a project path as auto-trusted (created by the system)."""
        from backend.persistence.db import get_project_by_path, update_project

        resolved = Path(path).resolve()
        logger.info("Auto-trusted project path: %s", resolved)

        try:
            project = get_project_by_path(str(resolved))
            if project and not project.get("trust", False):
                update_project(project["id"], trust=True)
                logger.info("Updated project %s trust status in database", project["id"])
        except Exception:
            logger.exception("Failed to update project trust in database")

    def create_project_auto_trusted(
        self,
        name: str,
        path: str,
        description: str = "",
        mode: str = "auto",
        preferred_model: str | None = None,
    ) -> dict[str, Any]:
        """Create a project and mark it as auto-trusted."""
        from backend.persistence.db import create_project

        project = create_project(
            name=name,
            path=path,
            description=description,
            mode=mode,
            preferred_model=preferred_model,
            trust=True,
        )
        self.auto_trust_project(path)
        return project

    # ── Audit logging ───────────────────────────────────────────────────────

    async def _log_operation(
        self,
        operation: str,
        args: dict[str, Any],
        result: Any,
        success: bool = True,
        error: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Log an operation to the audit log and database."""
        logger.info(
            "Workspace operation: %s success=%s error=%s",
            operation,
            success,
            error,
        )
        try:
            from backend.persistence.db import log_tool_execution

            log_tool_execution(
                session_id=session_id,
                tool_name=f"workspace.{operation}",
                args=args,
                result=result,
                success=success,
                error=error,
                duration_ms=0,
            )
        except Exception:
            logger.exception("Failed to log workspace operation to database")


# ---------------------------------------------------------------------------
# Tool registration — new absolute-path tools
# ---------------------------------------------------------------------------

from backend.tools.registry import ToolSpec, register_tool  # noqa: E402

register_tool(
    ToolSpec(
        name="read_file_absolute",
        description="Read any file using an absolute path (user permissions apply)",
        schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Absolute file path"}},
            "required": ["path"],
        },
        handler=read_file_absolute,
    )
)

register_tool(
    ToolSpec(
        name="write_file_absolute",
        description="Write any file using an absolute path. Creates a backup automatically.",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
                "content": {"type": "string", "description": "Content to write"},
                "overwrite": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to overwrite if the file exists (always honored)",
                },
            },
            "required": ["path", "content"],
        },
        handler=write_file_absolute,
    )
)

register_tool(
    ToolSpec(
        name="list_dir_absolute",
        description="List any directory using an absolute path",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute directory path"},
                "recursive": {
                    "type": "boolean",
                    "default": False,
                    "description": "Recursive listing",
                },
            },
            "required": ["path"],
        },
        handler=list_dir_absolute,
    )
)

register_tool(
    ToolSpec(
        name="create_dir_absolute",
        description="Create directories recursively using an absolute path",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute directory path"},
            },
            "required": ["path"],
        },
        handler=create_dir_absolute,
    )
)

register_tool(
    ToolSpec(
        name="delete_file_absolute",
        description="Delete a file using an absolute path (moves to trash by default)",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
                "move_to_trash": {
                    "type": "boolean",
                    "default": True,
                    "description": "Move to trash instead of permanent delete",
                },
            },
            "required": ["path"],
        },
        handler=delete_file_absolute,
    )
)

register_tool(
    ToolSpec(
        name="delete_dir_absolute",
        description="Delete a directory recursively using an absolute path (moves to trash by default)",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute directory path"},
                "move_to_trash": {
                    "type": "boolean",
                    "default": True,
                    "description": "Move to trash instead of permanent delete",
                },
            },
            "required": ["path"],
        },
        handler=delete_dir_absolute,
    )
)

register_tool(
    ToolSpec(
        name="move_file_absolute",
        description="Move or rename a file or directory using absolute paths",
        schema={
            "type": "object",
            "properties": {
                "src": {"type": "string", "description": "Absolute source path"},
                "dest": {"type": "string", "description": "Absolute destination path"},
            },
            "required": ["src", "dest"],
        },
        handler=move_file_absolute,
    )
)

register_tool(
    ToolSpec(
        name="copy_file_absolute",
        description="Copy a file using absolute paths",
        schema={
            "type": "object",
            "properties": {
                "src": {"type": "string", "description": "Absolute source path"},
                "dest": {"type": "string", "description": "Absolute destination path"},
            },
            "required": ["src", "dest"],
        },
        handler=copy_file_absolute,
    )
)

register_tool(
    ToolSpec(
        name="get_file_info_absolute",
        description="Get metadata for a file or directory using an absolute path",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file or directory path"},
            },
            "required": ["path"],
        },
        handler=get_file_info_absolute,
    )
)

register_tool(
    ToolSpec(
        name="search_files_absolute",
        description="Grep-like search across files under an absolute root path",
        schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text pattern to search for"},
                "root_path": {
                    "type": "string",
                    "description": "Absolute root directory to search in",
                },
                "max_results": {
                    "type": "integer",
                    "default": 100,
                    "description": "Maximum number of files to return",
                },
            },
            "required": ["pattern", "root_path"],
        },
        handler=search_files_absolute,
    )
)

register_tool(
    ToolSpec(
        name="list_backups",
        description="List available backups for files under an absolute path",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to list backups for"},
            },
            "required": ["path"],
        },
        handler=list_backups,
    )
)

register_tool(
    ToolSpec(
        name="restore_backup",
        description="Restore a backup file to its original absolute path",
        schema={
            "type": "object",
            "properties": {
                "backup_path": {"type": "string", "description": "Absolute backup file path"},
                "target_path": {
                    "type": "string",
                    "description": "Absolute target path to restore to",
                },
            },
            "required": ["backup_path", "target_path"],
        },
        handler=restore_backup,
    )
)

register_tool(
    ToolSpec(
        name="read_multiple_files_absolute",
        description="Read multiple files by absolute path in one call. Returns a map of path -> content and a map of path -> error.",
        schema={
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of absolute file paths to read",
                },
                "max_total_bytes": {
                    "type": "integer",
                    "default": 5 * 1024 * 1024,
                    "description": "Maximum combined bytes to return",
                },
                "max_files": {
                    "type": "integer",
                    "default": 100,
                    "description": "Maximum number of files to read",
                },
            },
            "required": ["paths"],
        },
        handler=read_multiple_files_absolute,
    )
)

register_tool(
    ToolSpec(
        name="execute_shell",
        description="Execute any shell command (dangerous patterns are blocked). Supports custom cwd, timeout and env.",
        schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "cwd": {"type": "string", "description": "Working directory (absolute path)"},
                "timeout": {"type": "integer", "default": 120, "description": "Timeout in seconds"},
                "env": {"type": "object", "description": "Additional environment variables"},
            },
            "required": ["command"],
        },
        handler=execute_shell,
    )
)

register_tool(
    ToolSpec(
        name="execute_python",
        description="Execute a Python code string in a temporary file",
        schema={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"},
                "cwd": {"type": "string", "description": "Working directory (absolute path)"},
                "timeout": {"type": "integer", "default": 120, "description": "Timeout in seconds"},
            },
            "required": ["code"],
        },
        handler=execute_python,
    )
)

register_tool(
    ToolSpec(
        name="execute_script",
        description="Execute any script file by absolute path (auto-detects interpreter)",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute script path"},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command-line arguments",
                },
                "cwd": {"type": "string", "description": "Working directory (absolute path)"},
                "timeout": {"type": "integer", "default": 120, "description": "Timeout in seconds"},
            },
            "required": ["path"],
        },
        handler=execute_script,
    )
)

register_tool(
    ToolSpec(
        name="git_init",
        description="Initialise a git repository at an absolute path",
        schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Absolute directory path"}},
            "required": ["path"],
        },
        handler=git_init,
    )
)

register_tool(
    ToolSpec(
        name="git_clone",
        description="Clone a git repository into an absolute path",
        schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Repository URL"},
                "path": {"type": "string", "description": "Absolute destination path"},
            },
            "required": ["url", "path"],
        },
        handler=git_clone,
    )
)

register_tool(
    ToolSpec(
        name="git_commit_all",
        description="Stage all changes and commit in a git repository",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute repository path"},
                "message": {
                    "type": "string",
                    "default": "auto: changes from NEXUS workspace",
                    "description": "Commit message",
                },
            },
            "required": ["path"],
        },
        handler=git_commit_all,
    )
)

register_tool(
    ToolSpec(
        name="git_push",
        description="Push commits from a git repository (allowed for workspace manager)",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute repository path"},
                "remote": {"type": "string", "default": "origin", "description": "Remote name"},
                "branch": {"type": "string", "description": "Branch name (optional)"},
            },
            "required": ["path"],
        },
        handler=git_push,
    )
)

register_tool(
    ToolSpec(
        name="git_status",
        description="Return git status for a repository at an absolute path",
        schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Absolute repository path"}},
            "required": ["path"],
        },
        handler=git_status,
    )
)

register_tool(
    ToolSpec(
        name="discover_projects",
        description="Discover git repos and common project structures under an absolute root path",
        schema={
            "type": "object",
            "properties": {
                "root_path": {"type": "string", "description": "Absolute root directory"},
                "max_depth": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum recursion depth",
                },
                "max_results": {
                    "type": "integer",
                    "default": 100,
                    "description": "Maximum number of projects to return",
                },
            },
            "required": ["root_path"],
        },
        handler=discover_projects,
    )
)

register_tool(
    ToolSpec(
        name="get_project_info",
        description="Detect language, framework, dependencies and git status for a project path",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute project path"},
            },
            "required": ["path"],
        },
        handler=get_project_info,
    )
)
