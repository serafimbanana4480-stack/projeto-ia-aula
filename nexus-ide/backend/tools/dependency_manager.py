"""Dependency manager tool — install and update project dependencies.

Supports pip, npm, cargo, and poetry package managers.
Runs in subprocess with timeout and updates requirement/package files.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

_SUPPORTED_MANAGERS = {"pip", "npm", "cargo", "poetry"}


def _get_install_command(package: str, manager: str, project_path: Path) -> list[str]:
    """Build the install command for the given package manager."""
    if manager == "pip":
        return ["pip", "install", package]
    elif manager == "npm":
        return ["npm", "install", package, "--save"]
    elif manager == "cargo":
        return ["cargo", "add", package]
    elif manager == "poetry":
        return ["poetry", "add", package]
    else:
        raise ValueError(f"Unsupported manager: {manager}")


def _update_requirements_file(package: str, project_path: Path, manager: str) -> dict:
    """Update the requirements/package file after installation."""
    updated = False
    files_touched: list[str] = []

    if manager == "pip":
        req_file = project_path / "requirements.txt"
        if req_file.exists():
            content = req_file.read_text(encoding="utf-8")
            lines = content.splitlines()
            pkg_base = package.split("==")[0].split(">=")[0].split("<")[0].strip()
            already_present = any(
                line.strip().split("==")[0].split(">=")[0].split("<")[0].strip().lower()
                == pkg_base.lower()
                for line in lines
                if line.strip() and not line.strip().startswith("#")
            )
            if not already_present:
                lines.append(package)
                req_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
                files_touched.append(str(req_file))
                updated = True

    elif manager == "npm":
        pkg_file = project_path / "package.json"
        if pkg_file.exists():
            try:
                data = json.loads(pkg_file.read_text(encoding="utf-8"))
                deps = data.setdefault("dependencies", {})
                if package not in deps:
                    deps[package] = "^latest"
                    pkg_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                    files_touched.append(str(pkg_file))
                    updated = True
            except Exception:
                pass

    elif manager == "cargo":
        cargo_file = project_path / "Cargo.toml"
        if cargo_file.exists():
            try:
                import tomllib

                data = tomllib.loads(cargo_file.read_text(encoding="utf-8"))
                if package not in data.get("dependencies", {}):
                    # tomllib is read-only; append manually
                    with cargo_file.open("a", encoding="utf-8") as f:
                        f.write(f'\n[dependencies]\n{package} = "*"\n')
                    files_touched.append(str(cargo_file))
                    updated = True
            except Exception:
                pass

    elif manager == "poetry":
        pyproject = project_path / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                # Poetry updates pyproject.toml automatically via `poetry add`
                files_touched.append(str(pyproject))
                updated = True
            except Exception:
                pass

    return {"updated": updated, "files": files_touched}


async def install_dependency(
    package: str,
    project_path: str = ".",
    manager: str = "pip",
    timeout: int = 120,
) -> dict:
    """Install a dependency using the specified package manager.

    Args:
        package: Package name (optionally with version spec, e.g. 'requests>=2.28').
        project_path: Project root path.
        manager: Package manager to use ('pip', 'npm', 'cargo', 'poetry').
        timeout: Maximum execution time in seconds.

    Returns:
        Dict with installation result, stdout, stderr, and exit code.
    """
    if manager not in _SUPPORTED_MANAGERS:
        return {
            "error": (
                f"Unsupported manager '{manager}'. "
                f"Supported: {', '.join(sorted(_SUPPORTED_MANAGERS))}"
            ),
        }

    # Sanitize package name (basic prevention of command injection)
    sanitized = package.strip()
    if not sanitized or ";" in sanitized or "&&" in sanitized or "|" in sanitized:
        return {"error": "Invalid package name"}

    project = Path(project_path).resolve()
    if not project.exists():
        return {"error": f"Project path not found: {project_path}"}

    try:
        cmd = _get_install_command(sanitized, manager, project)
        logger.info("Running dependency install: %s in %s", " ".join(cmd), project)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(project),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=float(timeout)
        )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            return {
                "package": sanitized,
                "manager": manager,
                "exit_code": proc.returncode,
                "error": stderr.strip() or stdout.strip(),
                "stdout": stdout,
                "stderr": stderr,
            }

        # Update requirements/package files
        update_info = _update_requirements_file(sanitized, project, manager)

        return {
            "package": sanitized,
            "manager": manager,
            "installed": True,
            "exit_code": 0,
            "stdout": stdout,
            "stderr": stderr,
            "files_updated": update_info["files"],
        }

    except TimeoutError:
        logger.warning("Dependency install timed out: %s", sanitized)
        return {
            "package": sanitized,
            "manager": manager,
            "error": f"Installation timed out after {timeout} seconds",
        }
    except FileNotFoundError:
        return {
            "package": sanitized,
            "manager": manager,
            "error": f"'{manager}' is not installed or not in PATH",
        }
    except Exception as exc:
        logger.exception("Dependency install failed: %s", exc)
        return {
            "package": sanitized,
            "manager": manager,
            "error": f"Installation failed: {exc}",
        }


async def list_dependencies(project_path: str = ".") -> dict:
    """List dependencies found in the project."""
    from pathlib import Path

    project = Path(project_path).resolve()
    result = {}
    req = project / "requirements.txt"
    if req.exists():
        result["pip"] = [
            l.strip() for l in req.read_text().splitlines() if l.strip() and not l.startswith("#")
        ]
    pkg = project / "package.json"
    if pkg.exists():
        import json

        data = json.loads(pkg.read_text())
        result["npm_dependencies"] = list(data.get("dependencies", {}).keys())
        result["npm_dev_dependencies"] = list(data.get("devDependencies", {}).keys())
    cargo = project / "Cargo.toml"
    if cargo.exists():
        result["cargo"] = "Found"
    return result


register_tool(
    ToolSpec(
        name="install_dependency",
        description=(
            "Install a dependency using pip, npm, cargo, or poetry. "
            "Runs in a subprocess with timeout and updates requirements/package files."
        ),
        schema={
            "type": "object",
            "properties": {
                "package": {
                    "type": "string",
                    "description": "Package name (optionally with version spec, e.g. 'requests>=2.28')",
                },
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
                "manager": {
                    "type": "string",
                    "enum": ["pip", "npm", "cargo", "poetry"],
                    "default": "pip",
                    "description": "Package manager to use",
                },
                "timeout": {
                    "type": "integer",
                    "default": 120,
                    "description": "Timeout in seconds",
                },
            },
            "required": ["package"],
        },
        handler=install_dependency,
    )
)

register_tool(
    ToolSpec(
        name="list_dependencies",
        description="List all dependencies found in the project",
        schema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
            },
        },
        handler=list_dependencies,
    )
)
