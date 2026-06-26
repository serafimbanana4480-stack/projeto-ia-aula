"""Tests for DatabaseManager schema and seeding."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.sandbox.database import DatabaseConfig, DatabaseManager, DatabaseProvisionResult
from backend.sandbox.sidecar import PostgresConnection, RedisConnection, SidecarManager


class TestDatabaseConfig:
    def test_defaults(self) -> None:
        config = DatabaseConfig()
        assert config.postgres is False
        assert config.redis is False
        assert config.synthetic_data is True
        assert config.schema_sql is None
        assert config.seed_script is None

    def test_postgres_enabled(self) -> None:
        config = DatabaseConfig(postgres=True, schema_sql="schema.sql")
        assert config.postgres is True
        assert config.schema_sql == "schema.sql"


class TestDatabaseManager:
    def test_provision_databases_postgres(self) -> None:
        sidecar_mgr = MagicMock(spec=SidecarManager)
        mock_container = MagicMock()
        pg_conn = PostgresConnection(
            host="nexus-pg-abc",
            port=5432,
            database="test",
            user="postgres",
            password="test",
        )
        sidecar_mgr.start_postgres.return_value = (mock_container, pg_conn)

        db_mgr = DatabaseManager(sidecar_mgr)
        config = DatabaseConfig(postgres=True)
        mock_network = MagicMock()
        mock_network.name = "nexus-net-abc"

        result = db_mgr.provision_databases("abc", mock_network, config)

        assert result.postgres_connection is not None
        assert result.postgres_connection.host == "nexus-pg-abc"
        assert result.success is True
        sidecar_mgr.start_postgres.assert_called_once()

    def test_provision_databases_redis(self) -> None:
        sidecar_mgr = MagicMock(spec=SidecarManager)
        mock_container = MagicMock()
        redis_conn = RedisConnection(host="nexus-redis-abc", port=6379)
        sidecar_mgr.start_redis.return_value = (mock_container, redis_conn)

        db_mgr = DatabaseManager(sidecar_mgr)
        config = DatabaseConfig(redis=True)
        mock_network = MagicMock()

        result = db_mgr.provision_databases("abc", mock_network, config)

        assert result.redis_connection is not None
        assert result.redis_connection.host == "nexus-redis-abc"
        assert result.success is True
        sidecar_mgr.start_redis.assert_called_once()

    def test_destroy_calls_stop_all(self) -> None:
        sidecar_mgr = MagicMock(spec=SidecarManager)
        db_mgr = DatabaseManager(sidecar_mgr)
        db_mgr.destroy("sandbox-123")
        sidecar_mgr.stop_all.assert_called_once_with("sandbox-123")
