"""Database Manager — schema migration and synthetic data seeding for sandbox DBs.

Applies SQL schemas and seeds test data into ephemeral PostgreSQL/Redis
instances managed by SidecarManager.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.sandbox.sidecar import (
    PostgresConnection,
    RedisConnection,
    SidecarManager,
)

logger = logging.getLogger(__name__)


@dataclass
class DatabaseConfig:
    """Configuration for database provisioning."""

    postgres: bool = False
    redis: bool = False
    schema_sql: str | None = None  # Path to schema SQL file
    seed_script: str | None = None  # Path to seed script
    synthetic_data: bool = True  # Generate faker data if no seed script


@dataclass
class DatabaseProvisionResult:
    """Result of database provisioning."""

    postgres_connection: PostgresConnection | None = None
    redis_connection: RedisConnection | None = None
    schema_applied: bool = False
    seed_records: int = 0
    success: bool = True
    error: str | None = None


class DatabaseManager:
    """Manages schema application and data seeding for ephemeral databases."""

    def __init__(self, sidecar_manager: SidecarManager) -> None:
        self._sidecar_manager = sidecar_manager

    def provision_databases(
        self,
        sandbox_id: str,
        network: Any,  # Docker Network object
        config: DatabaseConfig,
    ) -> DatabaseProvisionResult:
        """Provision all requested databases for a sandbox.

        Args:
            sandbox_id: Unique sandbox identifier.
            network: Docker network to connect sidecars to.
            config: Database configuration.

        Returns:
            DatabaseProvisionResult with connection info and status.
        """
        result = DatabaseProvisionResult()

        if config.postgres:
            try:
                container, pg_conn = self._sidecar_manager.start_postgres(
                    network, sandbox_id,
                )
                result.postgres_connection = pg_conn
                logger.info("PostgreSQL provisioned for %s", sandbox_id)
            except Exception as exc:
                logger.error("Failed to provision PostgreSQL: %s", exc)
                result.success = False
                result.error = f"PostgreSQL: {exc}"
                return result

        if config.redis:
            try:
                container, redis_conn = self._sidecar_manager.start_redis(
                    network, sandbox_id,
                )
                result.redis_connection = redis_conn
                logger.info("Redis provisioned for %s", sandbox_id)
            except Exception as exc:
                logger.error("Failed to provision Redis: %s", exc)
                result.success = False
                result.error = f"Redis: {exc}"
                return result

        return result

    def apply_schema(
        self,
        connection: PostgresConnection,
        schema_sql: str | Path,
    ) -> bool:
        """Apply a SQL schema to a PostgreSQL database.

        Args:
            connection: PostgreSQL connection info.
            schema_sql: SQL schema string or path to SQL file.

        Returns:
            True if schema applied successfully.
        """
        try:
            import psycopg2

            # Read schema if path provided
            sql = schema_sql
            if isinstance(schema_sql, (str, Path)) and Path(schema_sql).exists():
                sql = Path(schema_sql).read_text()

            conn = psycopg2.connect(
                host=connection.host,
                port=connection.port,
                database=connection.database,
                user=connection.user,
                password=connection.password,
            )
            conn.autocommit = False
            cursor = conn.cursor()

            # Execute schema SQL
            cursor.execute(sql)
            conn.commit()
            cursor.close()
            conn.close()

            logger.info("Schema applied to PostgreSQL")
            return True

        except Exception as exc:
            logger.error("Failed to apply schema: %s", exc)
            return False

    def seed_data(
        self,
        connection: PostgresConnection,
        seed_script: str | Path | None = None,
        synthetic_count: int = 10,
    ) -> int:
        """Seed test data into a PostgreSQL database.

        Args:
            connection: PostgreSQL connection info.
            seed_script: SQL seed script or path.
            synthetic_count: Number of synthetic records to generate.

        Returns:
            Number of records inserted.
        """
        try:
            import psycopg2

            conn = psycopg2.connect(
                host=connection.host,
                port=connection.port,
                database=connection.database,
                user=connection.user,
                password=connection.password,
            )
            conn.autocommit = False
            cursor = conn.cursor()

            records_inserted = 0

            if seed_script:
                # Execute provided seed script
                sql = seed_script
                if isinstance(seed_script, (str, Path)) and Path(seed_script).exists():
                    sql = Path(seed_script).read_text()
                cursor.execute(sql)
                records_inserted = cursor.rowcount
            else:
                # Generate synthetic data using faker
                try:
                    from faker import Faker
                    fake = Faker()

                    # Create a generic test table if not exists
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS nexus_test_data (
                            id SERIAL PRIMARY KEY,
                            name VARCHAR(100),
                            email VARCHAR(100),
                            created_at TIMESTAMP DEFAULT NOW()
                        )
                    """)

                    for _ in range(synthetic_count):
                        cursor.execute(
                            "INSERT INTO nexus_test_data (name, email) VALUES (%s, %s)",
                            (fake.name(), fake.email()),
                        )
                        records_inserted += 1

                except ImportError:
                    logger.warning("faker not available, skipping synthetic data")

            conn.commit()
            cursor.close()
            conn.close()

            logger.info("Seeded %d records into PostgreSQL", records_inserted)
            return records_inserted

        except Exception as exc:
            logger.error("Failed to seed data: %s", exc)
            return 0

    def reset_database(self, connection: PostgresConnection) -> bool:
        """Reset PostgreSQL database (drop and recreate public schema).

        Args:
            connection: PostgreSQL connection info.

        Returns:
            True if reset successfully.
        """
        try:
            import psycopg2

            conn = psycopg2.connect(
                host=connection.host,
                port=connection.port,
                database=connection.database,
                user=connection.user,
                password=connection.password,
            )
            conn.autocommit = True
            cursor = conn.cursor()
            cursor.execute("DROP SCHEMA public CASCADE")
            cursor.execute("CREATE SCHEMA public")
            cursor.execute("GRANT ALL ON SCHEMA public TO postgres")
            cursor.execute("GRANT ALL ON SCHEMA public TO public")
            cursor.close()
            conn.close()

            logger.info("PostgreSQL database reset")
            return True

        except Exception as exc:
            logger.error("Failed to reset database: %s", exc)
            return False

    def destroy(self, sandbox_id: str) -> None:
        """Destroy all sidecars for a sandbox."""
        self._sidecar_manager.stop_all(sandbox_id)
