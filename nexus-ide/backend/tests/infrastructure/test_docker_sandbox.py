"""Tests for DockerSandbox infrastructure module.

Covers:
- Image building (mocked Docker client)
- Container lifecycle (run, stop, list, logs, exec)
- Health checks
- Error handling paths
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.infrastructure.docker_sandbox import (
    DockerSandbox,
    DockerSandboxConfig,
)


class TestDockerSandboxConfig:
    def test_default_values(self) -> None:
        config = DockerSandboxConfig()
        assert config.default_image == "python:3.12-slim"
        assert config.default_timeout == 30
        assert config.max_memory_mb == 512
        assert config.max_cpu_cores == 0.5
        assert config.network_mode == "none"
        assert config.auto_remove is False
        assert config.read_only_root is True

    def test_custom_values(self) -> None:
        config = DockerSandboxConfig(
            default_image="node:20-alpine",
            max_memory_mb=1024,
            max_cpu_cores=1.0,
            network_mode="bridge",
        )
        assert config.default_image == "node:20-alpine"
        assert config.max_memory_mb == 1024
        assert config.max_cpu_cores == 1.0
        assert config.network_mode == "bridge"


class TestDockerSandboxInit:
    def test_init_with_defaults(self) -> None:
        ds = DockerSandbox()
        assert ds._config is not None
        assert ds._client is None

    def test_init_with_custom_config(self) -> None:
        config = DockerSandboxConfig(max_memory_mb=2048)
        ds = DockerSandbox(config)
        assert ds._config.max_memory_mb == 2048


class TestDockerSandboxBuildImage:
    def test_build_image_success(self, tmp_path: Path) -> None:
        mock_image = MagicMock()
        mock_image.id = "sha256:abc123"

        mock_client = MagicMock()
        mock_client.images.build.return_value = (mock_image, [{"stream": "Step 1/5"}])
        mock_client.ping.return_value = True

        ds = DockerSandbox()
        ds._client = mock_client

        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.12-slim\n")

        image_id = ds.build_image(str(tmp_path), "nexus-test:latest")
        assert image_id == "sha256:abc123"

        mock_client.images.build.assert_called_once()
        call_kwargs = mock_client.images.build.call_args.kwargs
        assert call_kwargs["path"] == str(tmp_path)
        assert call_kwargs["tag"] == "nexus-test:latest"

    def test_build_image_with_build_args(self, tmp_path: Path) -> None:
        mock_image = MagicMock()
        mock_image.id = "sha256:def456"

        mock_client = MagicMock()
        mock_client.images.build.return_value = (mock_image, [])
        mock_client.ping.return_value = True

        ds = DockerSandbox()
        ds._client = mock_client

        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.12-slim\n")

        ds.build_image(str(tmp_path), "nexus-test:v2", build_args={"VERSION": "1.0"})

        call_kwargs = mock_client.images.build.call_args.kwargs
        assert call_kwargs["buildargs"] == {"VERSION": "1.0"}

    def test_build_image_error(self, tmp_path: Path) -> None:
        mock_client = MagicMock()
        mock_client.images.build.return_value = (
            None,
            [{"error": "base image not found"}],
        )
        mock_client.ping.return_value = True

        ds = DockerSandbox()
        ds._client = mock_client

        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM nonexistent:latest\n")

        with pytest.raises(RuntimeError, match="Docker build error"):
            ds.build_image(str(tmp_path), "fail:latest")

    def test_build_image_docker_unavailable(self) -> None:
        from docker.errors import DockerException

        with patch(
            "backend.infrastructure.docker_sandbox.docker.from_env",
            side_effect=DockerException("daemon not running"),
        ):
            ds = DockerSandbox()
            with pytest.raises(RuntimeError, match="Docker is not available"):
                ds.build_image("/tmp/fake", "test:latest")


class TestDockerSandboxRunContainer:
    def test_run_container_defaults(self) -> None:
        mock_container = MagicMock()
        mock_container.short_id = "a1b2c3"
        mock_container.status = "running"

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container
        mock_client.ping.return_value = True

        ds = DockerSandbox()
        ds._client = mock_client

        container = ds.run_container("python:3.12-slim", "echo hello")

        assert container.short_id == "a1b2c3"
        mock_client.containers.run.assert_called_once()
        kwargs = mock_client.containers.run.call_args.kwargs
        assert kwargs["image"] == "python:3.12-slim"
        assert kwargs["command"] == "echo hello"
        assert kwargs["network_mode"] == "none"
        assert kwargs["mem_limit"] == "512m"

    def test_run_container_with_volumes_and_env(self) -> None:
        mock_container = MagicMock()
        mock_container.short_id = "d4e5f6"

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container
        mock_client.ping.return_value = True

        ds = DockerSandbox()
        ds._client = mock_client

        container = ds.run_container(
            "node:20",
            ["node", "app.js"],
            volumes={"/host/data": "/app/data"},
            env={"NODE_ENV": "production"},
            name="test-node",
            network="bridge",
        )

        assert container.short_id == "d4e5f6"
        kwargs = mock_client.containers.run.call_args.kwargs
        assert kwargs["name"] == "test-node"
        assert kwargs["network_mode"] == "bridge"
        assert kwargs["environment"] == {"NODE_ENV": "production"}
        assert kwargs["volumes"] == {"/host/data": {"bind": "/app/data", "mode": "rw"}}


class TestDockerSandboxStopContainer:
    def test_stop_container(self) -> None:
        mock_container = MagicMock()
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_client.ping.return_value = True

        ds = DockerSandbox()
        ds._client = mock_client

        ds.stop_container("abc123", timeout=5)
        mock_container.stop.assert_called_once_with(timeout=5)

    def test_stop_and_remove(self) -> None:
        mock_container = MagicMock()
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_client.ping.return_value = True

        ds = DockerSandbox()
        ds._client = mock_client

        ds.stop_container("abc123", remove=True)
        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once_with(force=True)

    def test_stop_container_not_found(self) -> None:
        from docker.errors import NotFound

        mock_client = MagicMock()
        mock_client.containers.get.side_effect = NotFound("no such container")
        mock_client.ping.return_value = True

        ds = DockerSandbox()
        ds._client = mock_client

        # Should not raise
        ds.stop_container("missing")


class TestDockerSandboxListContainers:
    def test_list_containers(self) -> None:
        mock_c1 = MagicMock()
        mock_c1.id = "c1"
        mock_c1.image.tags = ["nexus-test:latest"]
        mock_c1.status = "running"
        mock_c1.names = ["/wt-1"]
        mock_c1.labels = {"managed_by": "nexus-docker-sandbox"}
        mock_c1.ports = {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}
        mock_c1.attrs = {
            "Config": {"Cmd": ["python", "app.py"]},
            "Created": "2024-01-01T00:00:00Z",
            "State": {"Status": "running"},
        }

        mock_client = MagicMock()
        mock_client.containers.list.return_value = [mock_c1]
        mock_client.ping.return_value = True

        ds = DockerSandbox()
        ds._client = mock_client

        infos = ds.list_containers()
        assert len(infos) == 1
        assert infos[0].container_id == "c1"
        assert infos[0].image == "nexus-test:latest"
        assert infos[0].status == "running"
        mock_client.containers.list.assert_called_once_with(
            all=False,
            filters={"label": ["managed_by=nexus-docker-sandbox"]},
        )

    def test_list_all_containers(self) -> None:
        mock_client = MagicMock()
        mock_client.containers.list.return_value = []
        mock_client.ping.return_value = True

        ds = DockerSandbox()
        ds._client = mock_client

        ds.list_containers(all_containers=True)
        mock_client.containers.list.assert_called_once_with(
            all=True,
            filters={"label": ["managed_by=nexus-docker-sandbox"]},
        )


class TestDockerSandboxGetLogs:
    def test_get_logs(self) -> None:
        mock_container = MagicMock()
        mock_container.logs.return_value = b"hello world\nsecond line"

        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_client.ping.return_value = True

        ds = DockerSandbox()
        ds._client = mock_client

        logs = ds.get_logs("abc123", tail=50)
        assert logs == "hello world\nsecond line"
        mock_container.logs.assert_called_once_with(
            stdout=True,
            stderr=True,
            tail=50,
            timestamps=False,
            follow=False,
        )

    def test_get_logs_not_found(self) -> None:
        from docker.errors import NotFound

        mock_client = MagicMock()
        mock_client.containers.get.side_effect = NotFound("no such container")
        mock_client.ping.return_value = True

        ds = DockerSandbox()
        ds._client = mock_client

        assert ds.get_logs("missing") == ""


class TestDockerSandboxExecInContainer:
    def test_exec_in_container(self) -> None:
        mock_api = MagicMock()
        mock_api.exec_create.return_value = {"Id": "exec-id-456"}
        mock_api.exec_start.return_value = b"output line\n"
        mock_api.exec_inspect.return_value = {"ExitCode": 0}

        mock_client = MagicMock()
        mock_client.api = mock_api
        mock_client.ping.return_value = True

        mock_container = MagicMock()
        mock_container.id = "container-id-123"
        mock_container.client = mock_client

        mock_client.containers.get.return_value = mock_container

        ds = DockerSandbox()
        ds._client = mock_client

        result = ds.exec_in_container("c123", "echo hello")
        assert result["output"] == "output line\n"
        assert result["exit_code"] == 0
        assert result["exec_id"] == "exec-id-456"

    def test_exec_in_container_with_env_and_workdir(self) -> None:
        mock_api = MagicMock()
        mock_api.exec_create.return_value = {"Id": "exec-id-789"}
        mock_api.exec_start.return_value = b"done"
        mock_api.exec_inspect.return_value = {"ExitCode": 1}

        mock_client = MagicMock()
        mock_client.api = mock_api
        mock_client.ping.return_value = True

        mock_container = MagicMock()
        mock_container.id = "container-id-123"
        mock_container.client = mock_client

        mock_client.containers.get.return_value = mock_container

        ds = DockerSandbox()
        ds._client = mock_client

        result = ds.exec_in_container(
            "c123",
            ["npm", "test"],
            working_dir="/app",
            env={"CI": "true"},
        )
        assert result["exit_code"] == 1
        call_kwargs = mock_api.exec_create.call_args.kwargs
        assert call_kwargs["workdir"] == "/app"
        assert call_kwargs["environment"] == {"CI": "true"}

    def test_exec_in_container_detach(self) -> None:
        mock_api = MagicMock()
        mock_api.exec_create.return_value = {"Id": "eid"}

        mock_client = MagicMock()
        mock_client.api = mock_api
        mock_client.ping.return_value = True

        mock_container = MagicMock()
        mock_container.id = "cid"
        mock_container.client = mock_client

        mock_client.containers.get.return_value = mock_container

        ds = DockerSandbox()
        ds._client = mock_client

        result = ds.exec_in_container("c123", "sleep 10", detach=True)
        assert result["exit_code"] is None
        assert result["exec_id"] == "eid"
        mock_api.exec_start.assert_called_once_with("eid", detach=True)

    def test_exec_in_container_not_found(self) -> None:
        from docker.errors import NotFound

        mock_client = MagicMock()
        mock_client.containers.get.side_effect = NotFound("missing")
        mock_client.ping.return_value = True

        ds = DockerSandbox()
        ds._client = mock_client

        with pytest.raises(RuntimeError, match="not found"):
            ds.exec_in_container("missing", "echo hello")


class TestDockerSandboxHealth:
    def test_health_healthy(self) -> None:
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.version.return_value = {"Version": "24.0.7"}

        ds = DockerSandbox()
        ds._client = mock_client

        health = ds.health()
        assert health["healthy"] is True
        assert "24.0.7" in health["details"]

    def test_health_unhealthy(self) -> None:
        with patch(
            "backend.infrastructure.docker_sandbox.docker.from_env",
            side_effect=Exception("connection refused"),
        ):
            ds = DockerSandbox()
            health = ds.health()
            assert health["healthy"] is False
            assert "connection refused" in health["details"]
