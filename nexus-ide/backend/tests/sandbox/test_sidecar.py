"""Tests for SidecarManager database sidecars."""
from __future__ import annotations

from unittest.mock import MagicMock

from backend.sandbox.sidecar import (
    PostgresConnection,
    RedisConnection,
    SidecarConfig,
    SidecarManager,
)


class TestSidecarManager:
    def test_config_defaults(self) -> None:
        config = SidecarConfig()
        assert config.postgres_image == "postgres:15-alpine"
        assert config.redis_image == "redis:7-alpine"
        assert config.postgres_password == "test"

    def test_postgres_connection_string(self) -> None:
        conn = PostgresConnection(
            host="nexus-pg-abc123",
            port=5432,
            database="test",
            user="postgres",
            password="test",
        )
        assert conn.connection_string == "postgresql://postgres:test@nexus-pg-abc123:5432/test"

    def test_redis_connection_string(self) -> None:
        conn = RedisConnection(host="nexus-redis-abc123", port=6379)
        assert conn.connection_string == "redis://nexus-redis-abc123:6379/0"

    def test_stop_all_removes_labeled_containers(self) -> None:
        manager = SidecarManager()
        mock_client = MagicMock()
        manager._client = mock_client

        mock_container = MagicMock()
        mock_container.name = "nexus-pg-test"
        mock_client.containers.list.return_value = [mock_container]

        manager.stop_all("test")
        mock_container.remove.assert_called_once_with(force=True)
