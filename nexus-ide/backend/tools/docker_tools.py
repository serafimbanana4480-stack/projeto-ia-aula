"""Docker integration tools for container management.

Provides tools to list, build, run, and manage Docker containers and
docker-compose stacks. Docker must be installed and accessible on PATH.
"""

from __future__ import annotations

import asyncio
import logging
import shutil

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


def _docker_available() -> bool:
    """Return True if docker CLI is on PATH."""
    return shutil.which("docker") is not None


async def _run(cmd: str, cwd: str | None = None, timeout: int = 120) -> dict:
    """Run a shell command safely and return structured output."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "command": cmd,
            "returncode": proc.returncode,
            "stdout": (stdout_b or b"").decode(errors="replace").strip(),
            "stderr": (stderr_b or b"").decode(errors="replace").strip(),
        }
    except TimeoutError:
        return {"error": f"Timeout after {timeout}s", "command": cmd}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "command": cmd}


async def docker_ps(all: bool = False, project_path: str | None = None) -> dict:
    """List running Docker containers.

    Args:
        all: If True, show all containers (including stopped).
        project_path: Optional working directory.
    """
    if not _docker_available():
        return {"error": "docker CLI not found on PATH"}
    flag = "-a" if all else ""
    return await _run(f"docker ps {flag} --format 'table {{.ID}}\\t{{.Image}}\\t{{.Status}}\\t{{.Names}}'", cwd=project_path)


async def docker_build(
    image_tag: str, dockerfile_path: str = "Dockerfile", project_path: str | None = None, no_cache: bool = False
) -> dict:
    """Build a Docker image.

    Args:
        image_tag: Tag for the built image (e.g. 'myapp:latest').
        dockerfile_path: Path to Dockerfile relative to project_path.
        project_path: Build context directory.
        no_cache: If True, build without using cache.
    """
    if not _docker_available():
        return {"error": "docker CLI not found on PATH"}
    if "/" not in image_tag and ":" not in image_tag:
        return {"error": f"Invalid image tag '{image_tag}' — must include name and version"}
    cache_flag = "--no-cache" if no_cache else ""
    return await _run(
        f"docker build {cache_flag} -t {image_tag} -f {dockerfile_path} .",
        cwd=project_path,
        timeout=600,  # 10min for builds
    )


async def docker_run(
    image: str,
    command: str | None = None,
    name: str | None = None,
    ports: str | None = None,
    env: dict[str, str] | None = None,
    detach: bool = False,
    project_path: str | None = None,
) -> dict:
    """Run a Docker container.

    Args:
        image: Image name:tag to run.
        command: Optional command to execute inside the container.
        name: Optional container name.
        ports: Optional port mapping (e.g. '8080:80').
        env: Optional environment variables dict.
        detach: If True, run in background.
        project_path: Optional working directory.
    """
    if not _docker_available():
        return {"error": "docker CLI not found on PATH"}
    parts = ["docker", "run", "--rm"]  # always remove after exit for safety
    if detach:
        parts.append("-d")
    if name:
        if not name.replace("_", "").replace("-", "").isalnum():
            return {"error": f"Invalid container name '{name}'"}
        parts.append(f"--name {name}")
    if ports:
        # Validate port format (basic)
        if ":" not in ports:
            return {"error": f"Invalid port mapping '{ports}' (expected 'host:container')"}
        parts.append(f"-p {ports}")
    if env:
        for k, v in env.items():
            if not k.replace("_", "").isalnum():
                return {"error": f"Invalid env var name '{k}'"}
            # Sanitize value to prevent shell injection
            safe_v = str(v).replace("'", "").replace('"', "").replace("`", "").replace("$", "")
            parts.append(f"-e {k}='{safe_v}'")
    parts.append(image)
    if command:
        parts.append(command)
    return await _run(" ".join(parts), cwd=project_path)


async def docker_compose_up(
    project_path: str | None = None, detach: bool = True, build: bool = False
) -> dict:
    """Run 'docker compose up'.

    Args:
        project_path: Directory containing docker-compose.yml.
        detach: If True, run in background.
        build: If True, build images before starting.
    """
    if not _docker_available():
        return {"error": "docker CLI not found on PATH"}
    flags = []
    if detach:
        flags.append("-d")
    if build:
        flags.append("--build")
    flag_str = " ".join(flags)
    # Try 'docker compose' (v2) first, fallback to 'docker-compose' (v1)
    return await _run(f"docker compose up {flag_str}", cwd=project_path, timeout=300)


async def docker_compose_down(project_path: str | None = None, volumes: bool = False) -> dict:
    """Run 'docker compose down'.

    Args:
        project_path: Directory containing docker-compose.yml.
        volumes: If True, also remove named volumes.
    """
    if not _docker_available():
        return {"error": "docker CLI not found on PATH"}
    flag = "-v" if volumes else ""
    return await _run(f"docker compose down {flag}", cwd=project_path, timeout=60)


async def docker_logs(
    container: str, tail: int = 100, follow: bool = False, project_path: str | None = None
) -> dict:
    """Get logs from a container.

    Args:
        container: Container name or ID.
        tail: Number of lines to show from end.
        follow: If True, stream logs (warning: blocking).
        project_path: Optional working directory.
    """
    if not _docker_available():
        return {"error": "docker CLI not found on PATH"}
    if not container.replace("_", "").replace("-", "").isalnum():
        return {"error": f"Invalid container name '{container}'"}
    flags = f"--tail {tail}"
    if follow:
        flags += " --follow"
    timeout = 60 if not follow else 600
    return await _run(f"docker logs {flags} {container}", cwd=project_path, timeout=timeout)


register_tool(
    ToolSpec(
        name="docker_ps",
        description="List Docker containers. By default shows only running; pass all=true to include stopped.",
        schema={
            "type": "object",
            "properties": {
                "all": {"type": "boolean", "description": "Show all containers (incl. stopped)", "default": False},
                "project_path": {"type": "string", "description": "Working directory"},
            },
        },
        handler=docker_ps,
        tags=["docker", "container", "list"],
        category="docker",
        risk_level="low",
        when_to_use="When you need to see what Docker containers are running or stopped",
        examples=[{"all": False}],
    )
)

register_tool(
    ToolSpec(
        name="docker_build",
        description="Build a Docker image from a Dockerfile. Supports --no-cache.",
        schema={
            "type": "object",
            "properties": {
                "image_tag": {"type": "string", "description": "Tag for the image (e.g. 'myapp:v1')"},
                "dockerfile_path": {"type": "string", "description": "Path to Dockerfile", "default": "Dockerfile"},
                "project_path": {"type": "string", "description": "Build context directory"},
                "no_cache": {"type": "boolean", "description": "Build without cache", "default": False},
            },
            "required": ["image_tag"],
        },
        handler=docker_build,
        tags=["docker", "container", "build"],
        category="docker",
        risk_level="medium",
        when_to_use="When you need to build a Docker image from a Dockerfile",
        examples=[{"image_tag": "myapp:v1", "project_path": "."}],
    )
)

register_tool(
    ToolSpec(
        name="docker_run",
        description="Run a Docker container (always --rm for safety). Supports port mapping, env vars, and detach mode.",
        schema={
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "Image name:tag to run"},
                "command": {"type": "string", "description": "Optional command to execute"},
                "name": {"type": "string", "description": "Container name (alphanumeric)"},
                "ports": {"type": "string", "description": "Port mapping 'host:container'"},
                "env": {"type": "object", "description": "Environment variables dict", "additionalProperties": {"type": "string"}},
                "detach": {"type": "boolean", "description": "Run in background", "default": False},
                "project_path": {"type": "string", "description": "Working directory"},
            },
            "required": ["image"],
        },
        handler=docker_run,
        tags=["docker", "container", "run"],
        category="docker",
        risk_level="medium",
        when_to_use="When you need to run a Docker container from an image",
        examples=[{"image": "nginx:latest", "ports": "8080:80", "detach": True}],
    )
)

register_tool(
    ToolSpec(
        name="docker_compose_up",
        description="Run 'docker compose up' in a project. Use build=true to build images first.",
        schema={
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Directory containing docker-compose.yml"},
                "detach": {"type": "boolean", "description": "Run in background", "default": True},
                "build": {"type": "boolean", "description": "Build images before starting", "default": False},
            },
        },
        handler=docker_compose_up,
        tags=["docker", "compose", "stack"],
        category="docker",
        risk_level="medium",
        when_to_use="When you need to start a docker-compose stack (multiple containers)",
        examples=[{"project_path": ".", "detach": True}],
    )
)

register_tool(
    ToolSpec(
        name="docker_compose_down",
        description="Run 'docker compose down' to stop and remove containers.",
        schema={
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Directory containing docker-compose.yml"},
                "volumes": {"type": "boolean", "description": "Also remove named volumes", "default": False},
            },
        },
        handler=docker_compose_down,
        tags=["docker", "compose", "stop"],
        category="docker",
        risk_level="medium",
        when_to_use="When you need to stop a docker-compose stack",
        examples=[{"project_path": "."}],
    )
)

register_tool(
    ToolSpec(
        name="docker_logs",
        description="Get logs from a Docker container (last N lines, or follow).",
        schema={
            "type": "object",
            "properties": {
                "container": {"type": "string", "description": "Container name or ID"},
                "tail": {"type": "integer", "description": "Lines to show from end", "default": 100},
                "follow": {"type": "boolean", "description": "Stream logs (blocking)", "default": False},
                "project_path": {"type": "string", "description": "Working directory"},
            },
            "required": ["container"],
        },
        handler=docker_logs,
        tags=["docker", "container", "logs"],
        category="docker",
        risk_level="low",
        when_to_use="When you need to inspect logs of a Docker container",
        examples=[{"container": "myapp", "tail": 100}],
    )
)
