"""Docker Sandbox System — container lifecycle management for isolated execution.

Provides a high-level interface for building images, running containers,
and managing their lifecycle using the official Docker SDK.

Features:
- Image building from Dockerfiles
- Container creation with volume and environment bindings
- Container stop / list / log retrieval
- Command execution inside running containers
- Automatic cleanup and health checks

Architecture:
- ``DockerSandbox``: main orchestrator class
- ``DockerSandboxConfig``: configuration dataclass
- ``ContainerInfo``: metadata about a running or stopped container

Security:
- All container operations are logged
- Resource limits are applied by default
- Network can be disabled for fully isolated runs
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import docker
from docker.errors import DockerException, NotFound, APIError
from docker.models.containers import Container

logger = logging.getLogger(__name__)


@dataclass
class DockerSandboxConfig:
    """Configuration for DockerSandbox operations."""

    default_image: str = "python:3.12-slim"
    default_timeout: int = 30
    max_memory_mb: int = 512
    max_cpu_cores: float = 0.5
    network_mode: str = "none"
    auto_remove: bool = False
    read_only_root: bool = True
    labels: dict[str, str] = field(default_factory=lambda: {"managed_by": "nexus-docker-sandbox"})


@dataclass
class ContainerInfo:
    """Metadata snapshot of a Docker container."""

    container_id: str
    image: str
    status: str
    command: str
    names: list[str]
    labels: dict[str, str]
    ports: dict[str, Any]
    created: str
    state: str = ""


class DockerSandbox:
    """Manages Docker containers for isolated code execution.

    Wraps the docker-py client with retry logic, structured logging,
    and project-specific defaults.
    """

    def __init__(self, config: DockerSandboxConfig | None = None) -> None:
        self._config = config or DockerSandboxConfig()
        self._client: docker.DockerClient | None = None

    def _get_client(self) -> docker.DockerClient:
        """Lazy-initialise the Docker client from environment."""
        if self._client is None:
            try:
                self._client = docker.from_env()
                # Warm-up ping to catch connection errors early
                self._client.ping()
            except DockerException as exc:
                logger.error("Failed to connect to Docker daemon: %s", exc)
                raise RuntimeError("Docker is not available") from exc
        return self._client

    def build_image(
        self,
        dockerfile_path: str | Path,
        tag: str,
        *,
        build_args: dict[str, str] | None = None,
        no_cache: bool = False,
    ) -> str:
        """Build a Docker image from a Dockerfile.

        Args:
            dockerfile_path: Path to the Dockerfile or the directory containing it.
            tag: Repository tag to assign the built image (e.g. ``nexus-sandbox:latest``).
            build_args: Optional build-time variables.
            no_cache: When ``True``, disables layer caching.

        Returns:
            The image ID of the newly built image.

        Raises:
            RuntimeError: If the build fails or Docker is unreachable.
        """
        path = Path(dockerfile_path)
        build_context = path if path.is_dir() else path.parent
        dockerfile_name = path.name if path.is_file() else "Dockerfile"

        logger.info("Building image '%s' from context %s", tag, build_context)
        client = self._get_client()

        try:
            image, build_logs = client.images.build(
                path=str(build_context),
                dockerfile=dockerfile_name,
                tag=tag,
                buildargs=build_args or {},
                nocache=no_cache,
                rm=True,
                forcerm=True,
            )
            for log_line in build_logs:
                if "stream" in log_line:
                    logger.debug(log_line["stream"].strip())
                elif "error" in log_line:
                    raise RuntimeError(f"Docker build error: {log_line['error']}")
            logger.info("Image built successfully: %s", image.id)
            return image.id
        except APIError as exc:
            logger.error("Docker API error during build: %s", exc)
            raise RuntimeError(f"Docker build failed: {exc}") from exc

    def run_container(
        self,
        image: str,
        command: str | list[str] | None = None,
        *,
        volumes: dict[str, str] | None = None,
        env: dict[str, str] | None = None,
        name: str | None = None,
        detach: bool = True,
        network: str | None = None,
        mem_limit: str | None = None,
        cpu_limit: float | None = None,
        labels: dict[str, str] | None = None,
        working_dir: str | None = None,
    ) -> Container:
        """Run a new container from the specified image.

        Args:
            image: Docker image name or ID.
            command: Command string or list to execute inside the container.
            volumes: Mapping of ``{host_path: container_path}`` or
                     ``{host_path: {"bind": container_path, "mode": "rw"}}``.
            env: Environment variables to inject.
            name: Optional human-readable container name.
            detach: Run in background; returns a :class:`Container` object.
            network: Docker network mode (overrides default ``none`` if provided).
            mem_limit: Memory limit string, e.g. ``"512m"``.
            cpu_limit: CPU quota as a fraction of a core.
            labels: Extra labels in addition to the default sandbox labels.
            working_dir: Working directory inside the container.

        Returns:
            A :class:`docker.models.containers.Container` instance.

        Raises:
            RuntimeError: If the container fails to start.
        """
        client = self._get_client()
        merged_labels = {**self._config.labels, **(labels or {})}
        network_mode = network or self._config.network_mode

        # Convert simple dict to docker-py volume format
        volume_bindings: dict[str, Any] | None = None
        if volumes:
            volume_bindings = {}
            for host, container in volumes.items():
                if isinstance(container, str):
                    volume_bindings[host] = {"bind": container, "mode": "rw"}
                else:
                    volume_bindings[host] = container

        mem = mem_limit or f"{self._config.max_memory_mb}m"
        cpu = cpu_limit or self._config.max_cpu_cores

        logger.info(
            "Running container image='%s' command='%s' network='%s'",
            image, command, network_mode,
        )

        try:
            container = client.containers.run(
                image=image,
                command=command,
                name=name,
                detach=detach,
                volumes=volume_bindings,
                environment=env or {},
                network_mode=network_mode,
                mem_limit=mem,
                cpu_quota=int(cpu * 100000),
                cpu_period=100000,
                labels=merged_labels,
                auto_remove=self._config.auto_remove,
                read_only=self._config.read_only_root,
                working_dir=working_dir or "/workspace",
                stderr=True,
                stdout=True,
            )
            logger.info("Container started: %s (%s)", container.short_id, container.status)
            return container
        except APIError as exc:
            logger.error("Failed to start container: %s", exc)
            raise RuntimeError(f"Container start failed: {exc}") from exc

    def stop_container(
        self,
        container_id: str,
        *,
        timeout: int = 10,
        remove: bool = False,
    ) -> None:
        """Stop a running container.

        Args:
            container_id: Container ID or name.
            timeout: Seconds to wait before force-killing.
            remove: If ``True``, also remove the container after stopping.

        Raises:
            RuntimeError: If the container cannot be stopped.
        """
        client = self._get_client()
        try:
            container = client.containers.get(container_id)
            container.stop(timeout=timeout)
            logger.info("Container %s stopped", container_id)
            if remove:
                container.remove(force=True)
                logger.info("Container %s removed", container_id)
        except NotFound:
            logger.warning("Container %s not found; nothing to stop", container_id)
        except APIError as exc:
            logger.error("Error stopping container %s: %s", container_id, exc)
            raise RuntimeError(f"Failed to stop container {container_id}: {exc}") from exc

    def list_containers(
        self,
        *,
        all_containers: bool = False,
        filters: dict[str, Any] | None = None,
    ) -> list[ContainerInfo]:
        """List containers managed by the sandbox.

        Args:
            all_containers: Include stopped containers.
            filters: Additional Docker API filters.

        Returns:
            List of :class:`ContainerInfo` snapshots.
        """
        client = self._get_client()
        merged_filters: dict[str, Any] = {"label": [f"managed_by={self._config.labels['managed_by']}"]}
        if filters:
            merged_filters.update(filters)

        try:
            containers = client.containers.list(all=all_containers, filters=merged_filters)
            return [
                ContainerInfo(
                    container_id=c.id,
                    image=c.image.tags[0] if c.image.tags else c.image.id,
                    status=c.status,
                    command=c.attrs.get("Config", {}).get("Cmd", []),
                    names=c.names or [],
                    labels=c.labels or {},
                    ports=c.ports or {},
                    created=c.attrs.get("Created", ""),
                    state=c.attrs.get("State", {}).get("Status", ""),
                )
                for c in containers
            ]
        except APIError as exc:
            logger.error("Failed to list containers: %s", exc)
            raise RuntimeError(f"Failed to list containers: {exc}") from exc

    def get_logs(
        self,
        container_id: str,
        *,
        tail: int = 100,
        follow: bool = False,
        timestamps: bool = False,
    ) -> str:
        """Retrieve stdout/stderr logs from a container.

        Args:
            container_id: Container ID or name.
            tail: Number of lines to return from the end.
            follow: Stream logs (returns a generator when ``True``).
            timestamps: Include Docker timestamps.

        Returns:
            Decoded log string, or a generator if ``follow=True``.

        Raises:
            RuntimeError: If the container cannot be found or logs are unreadable.
        """
        client = self._get_client()
        try:
            container = client.containers.get(container_id)
            logs = container.logs(
                stdout=True,
                stderr=True,
                tail=tail,
                timestamps=timestamps,
                follow=follow,
            )
            if follow:
                return logs  # type: ignore[return-value]
            return logs.decode("utf-8", errors="replace") if isinstance(logs, bytes) else str(logs)
        except NotFound:
            logger.warning("Container %s not found; cannot retrieve logs", container_id)
            return ""
        except APIError as exc:
            logger.error("Error retrieving logs for %s: %s", container_id, exc)
            raise RuntimeError(f"Failed to get logs for {container_id}: {exc}") from exc

    def exec_in_container(
        self,
        container_id: str,
        command: str | list[str],
        *,
        working_dir: str | None = None,
        env: dict[str, str] | None = None,
        detach: bool = False,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Execute a command inside an already-running container.

        Args:
            container_id: Container ID or name.
            command: Shell command or argument list.
            working_dir: Override working directory for this execution.
            env: Extra environment variables.
            detach: Return immediately without waiting for completion.
            timeout: Seconds to wait before raising.

        Returns:
            Dictionary with ``output``, ``exit_code``, and ``exec_id`` keys.

        Raises:
            RuntimeError: If the container is not found or the command fails to start.
        """
        client = self._get_client()
        try:
            container = client.containers.get(container_id)
        except NotFound as exc:
            raise RuntimeError(f"Container {container_id} not found") from exc

        exec_config: dict[str, Any] = {
            "cmd": command,
            "stdout": True,
            "stderr": True,
            "stdin": False,
            "tty": False,
            "detach": detach,
        }
        if working_dir:
            exec_config["workdir"] = working_dir
        if env:
            exec_config["environment"] = env

        logger.info("Executing command in %s: %s", container_id, command)
        try:
            exec_result = container.client.api.exec_create(container.id, **exec_config)
            exec_id = exec_result["Id"]

            if detach:
                container.client.api.exec_start(exec_id, detach=True)
                return {"output": "", "exit_code": None, "exec_id": exec_id}

            output = container.client.api.exec_start(exec_id, stream=False)
            inspect = container.client.api.exec_inspect(exec_id)
            exit_code = inspect.get("ExitCode", -1)

            decoded = (
                output.decode("utf-8", errors="replace")
                if isinstance(output, bytes)
                else str(output)
            )
            logger.info("Command in %s exited with code %s", container_id, exit_code)
            return {"output": decoded, "exit_code": exit_code, "exec_id": exec_id}
        except APIError as exc:
            logger.error("Exec failed in container %s: %s", container_id, exc)
            raise RuntimeError(f"Exec failed in {container_id}: {exc}") from exc

    def health(self) -> dict[str, Any]:
        """Return a health-check dictionary for the Docker daemon connection.

        Returns:
            Dictionary with ``healthy`` (bool) and ``details`` (str).
        """
        try:
            client = self._get_client()
            version = client.version()
            return {
                "healthy": True,
                "details": f"Docker {version.get('Version', 'unknown')} connected",
            }
        except Exception as exc:  # noqa: BLE001
            return {"healthy": False, "details": str(exc)}
