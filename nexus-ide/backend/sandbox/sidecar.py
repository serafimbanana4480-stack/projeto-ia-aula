"""Sidecar Manager — ephemeral database containers for sandboxes.

Manages PostgreSQL and Redis sidecar containers that are created
alongside a sandbox, share its isolated network, and are destroyed
automatically when the sandbox completes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from docker.models.containers import Container
from docker.models.networks import Network

import docker

logger = logging.getLogger(__name__)


@dataclass
class SidecarConfig:
    """Configuration for database sidecars."""

    postgres_image: str = "postgres:15-alpine"
    redis_image: str = "redis:7-alpine"
    postgres_password: str = "test"
    postgres_database: str = "test"
    postgres_user: str = "postgres"


@dataclass
class PostgresConnection:
    """Connection info for a PostgreSQL sidecar."""

    host: str
    port: int
    database: str
    user: str
    password: str

    @property
    def connection_string(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


@dataclass
class RedisConnection:
    """Connection info for a Redis sidecar."""

    host: str
    port: int

    @property
    def connection_string(self) -> str:
        return f"redis://{self.host}:{self.port}/0"


class SidecarManager:
    """Manages ephemeral database sidecars for sandbox execution."""

    def __init__(self, config: SidecarConfig | None = None) -> None:
        self._config = config or SidecarConfig()
        self._client: docker.DockerClient | None = None

    def _get_client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def start_postgres(
        self,
        network: Network,
        sandbox_id: str,
    ) -> tuple[Container, PostgresConnection]:
        """Start a PostgreSQL sidecar container.

        Args:
            network: Docker network to connect the sidecar to.
            sandbox_id: Unique sandbox identifier.

        Returns:
            Tuple of (container, connection_info).
        """
        client = self._get_client()
        container_name = f"nexus-pg-{sandbox_id}"

        container = client.containers.run(
            image=self._config.postgres_image,
            name=container_name,
            network=network.name,
            environment={
                "POSTGRES_PASSWORD": self._config.postgres_password,
                "POSTGRES_DB": self._config.postgres_database,
                "POSTGRES_USER": self._config.postgres_user,
            },
            tmpfs={"/var/lib/postgresql/data": "rw,noexec,nosuid,size=100m"},
            labels={
                "nexus.sandbox.sidecar": "true",
                "nexus.sandbox.sidecar.type": "postgres",
                "nexus.sandbox.id": sandbox_id,
            },
            detach=True,
            remove=True,
            auto_remove=True,
        )

        logger.info("PostgreSQL sidecar started: %s", container_name)

        connection = PostgresConnection(
            host=container_name,  # Container name resolves in Docker network
            port=5432,
            database=self._config.postgres_database,
            user=self._config.postgres_user,
            password=self._config.postgres_password,
        )
        return container, connection

    def start_redis(
        self,
        network: Network,
        sandbox_id: str,
    ) -> tuple[Container, RedisConnection]:
        """Start a Redis sidecar container.

        Args:
            network: Docker network to connect the sidecar to.
            sandbox_id: Unique sandbox identifier.

        Returns:
            Tuple of (container, connection_info).
        """
        client = self._get_client()
        container_name = f"nexus-redis-{sandbox_id}"

        container = client.containers.run(
            image=self._config.redis_image,
            name=container_name,
            network=network.name,
            command=[
                "redis-server",
                "--appendonly", "no",
                "--save", "",
                "--maxmemory", "64mb",
                "--maxmemory-policy", "allkeys-lru",
            ],
            labels={
                "nexus.sandbox.sidecar": "true",
                "nexus.sandbox.sidecar.type": "redis",
                "nexus.sandbox.id": sandbox_id,
            },
            detach=True,
            remove=True,
            auto_remove=True,
        )

        logger.info("Redis sidecar started: %s", container_name)

        connection = RedisConnection(
            host=container_name,
            port=6379,
        )
        return container, connection

    def healthcheck_postgres(self, connection: PostgresConnection) -> bool:
        """Check if PostgreSQL sidecar is healthy."""
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=connection.host,
                port=connection.port,
                database=connection.database,
                user=connection.user,
                password=connection.password,
                connect_timeout=5,
            )
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            return True
        except Exception as exc:
            logger.debug("PostgreSQL healthcheck failed: %s", exc)
            return False

    def healthcheck_redis(self, connection: RedisConnection) -> bool:
        """Check if Redis sidecar is healthy."""
        try:
            import redis as redis_lib
            r = redis_lib.Redis(
                host=connection.host,
                port=connection.port,
                socket_connect_timeout=5,
            )
            return r.ping()
        except Exception as exc:
            logger.debug("Redis healthcheck failed: %s", exc)
            return False

    def stop_all(self, sandbox_id: str) -> None:
        """Stop and remove all sidecars for a sandbox."""
        client = self._get_client()
        label_filter = f"nexus.sandbox.id={sandbox_id}"

        containers = client.containers.list(
            filters={"label": [label_filter]},
            all=True,
        )

        for container in containers:
            try:
                container.remove(force=True)
                logger.debug("Stopped sidecar: %s", container.name)
            except Exception as exc:
                logger.warning("Failed to stop sidecar %s: %s", container.name, exc)

        logger.info("Stopped %d sidecars for sandbox %s", len(containers), sandbox_id)
