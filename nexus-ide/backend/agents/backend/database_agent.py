"""DatabaseAgent — schema design, query optimization, and migration planning specialist."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from backend.agents.base import AgentBase, AgentRequest

logger = logging.getLogger(__name__)


@dataclass
class SchemaSuggestion:
    """Structured database schema suggestion."""

    tables: list[dict[str, Any]] = field(default_factory=list)
    indexes: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class DatabaseAgent(AgentBase):
    """Specialist agent for database schema design, query optimization, and migrations."""

    name = "DATABASE"
    model_key = "coder"
    prompt_file = "database_system"
    supported_actions = set()

    def __init__(self) -> None:
        super().__init__()
        self._stats: dict[str, int] = {
            "schema_requests": 0,
            "query_opt_requests": 0,
            "migration_requests": 0,
        }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Handle database-related queries: schema design, query optimization, migration planning."""
        yield f"<event>database_start|{request.query[:50]}</event>"

        query = request.query.lower()
        if any(k in query for k in ["schema", "design", "table", "entity", "model"]):
            self._stats["schema_requests"] += 1
            yield "## Schema Design\n\n"
            yield "Provide requirements as context to get a tailored schema suggestion.\n"
            yield self._schema_design_principles()
        elif any(k in query for k in ["query", "optimize", "slow", "index", "performance"]):
            self._stats["query_opt_requests"] += 1
            yield "## Query Optimization\n\n"
            yield self._query_optimization_tips()
        elif any(k in query for k in ["migration", "migrate", "alembic", "flyway", "evolve"]):
            self._stats["migration_requests"] += 1
            yield "## Migration Planning\n\n"
            yield self._migration_planning_guide()
        else:
            yield "Database Agent ready. Ask for:\n"
            yield "- Schema design suggestions\n"
            yield "- Query optimization tips\n"
            yield "- Migration planning guide\n"

        yield "<event>database_end</event>"

    def _schema_design_principles(self) -> str:
        """Return core schema design principles."""
        return (
            "### Normalization\n"
            "- 1NF: atomic columns, no repeating groups\n"
            "- 2NF: remove partial dependencies\n"
            "- 3NF: remove transitive dependencies\n\n"
            "### Keys & Constraints\n"
            "- Every table needs a primary key (prefer surrogate keys)\n"
            "- Use foreign keys for referential integrity\n"
            "- Add unique constraints for business rules\n\n"
            "### Indexing Strategy\n"
            "- Index columns used in JOIN, WHERE, ORDER BY\n"
            "- Avoid over-indexing on high-write tables\n"
            "- Consider partial and composite indexes\n"
        )

    def _query_optimization_tips(self) -> str:
        """Return query optimization guidelines."""
        return (
            "### Execution Plan Analysis\n"
            "- Use `EXPLAIN (ANALYZE, BUFFERS)` to identify bottlenecks\n"
            "- Look for Sequential Scans on large tables\n"
            "- Check for high `rows_removed_by_filter` counts\n\n"
            "### Common Optimizations\n"
            "- Select only needed columns; avoid `SELECT *`\n"
            "- Use appropriate indexes for filtering and sorting\n"
            "- Batch inserts/updates instead of row-by-row\n"
            "- Add `LIMIT` when only a subset is needed\n\n"
            "### Anti-Patterns to Avoid\n"
            "- N+1 queries: use JOINs or batched loaders\n"
            "- Functions on indexed columns in WHERE clauses\n"
            "- Implicit conversions that prevent index usage\n"
        )

    def _migration_planning_guide(self) -> str:
        """Return migration planning best practices."""
        return (
            "### Migration Strategy\n"
            "- Use a migration framework (Alembic, Flyway, Liquibase)\n"
            "- Version every migration with timestamp or semantic version\n"
            "- Keep migrations idempotent where possible\n\n"
            "### Safety Checklist\n"
            "- Always backup before applying migrations\n"
            "- Run migrations in a transaction (rollback on failure)\n"
            "- Test migrations against a production-like dataset\n"
            "- Add backward-compatible changes first; drop old later\n\n"
            "### Zero-Downtime Patterns\n"
            "- Expand-contract: add new column/table, backfill, switch reads, drop old\n"
            "- Use feature flags to toggle between old/new schema\n"
            "- Avoid long-running locks during peak hours\n"
        )

    def suggest_schema(self, requirements: str) -> SchemaSuggestion:
        """Suggest a database schema based on natural-language requirements.

        Args:
            requirements: Description of entities, relationships, and constraints.

        Returns:
            Structured schema suggestion with tables, indexes, and notes.
        """
        tables: list[dict[str, Any]] = []
        indexes: list[str] = []
        constraints: list[str] = []
        notes: list[str] = []

        req_lower = requirements.lower()

        # Heuristic table extraction
        if "user" in req_lower or "account" in req_lower:
            tables.append({
                "name": "users",
                "columns": [
                    {"name": "id", "type": "UUID PRIMARY KEY"},
                    {"name": "email", "type": "VARCHAR(255) UNIQUE NOT NULL"},
                    {"name": "created_at", "type": "TIMESTAMP DEFAULT NOW()"},
                ],
            })
            indexes.append("CREATE INDEX idx_users_email ON users(email);")
            constraints.append("ALTER TABLE users ADD CONSTRAINT chk_email_format CHECK (email ~* '^.+@.+'$');")

        if "order" in req_lower or "purchase" in req_lower:
            tables.append({
                "name": "orders",
                "columns": [
                    {"name": "id", "type": "SERIAL PRIMARY KEY"},
                    {"name": "user_id", "type": "UUID NOT NULL"},
                    {"name": "status", "type": "VARCHAR(50) NOT NULL"},
                    {"name": "total", "type": "DECIMAL(12,2) NOT NULL"},
                    {"name": "created_at", "type": "TIMESTAMP DEFAULT NOW()"},
                ],
            })
            indexes.append("CREATE INDEX idx_orders_user_id ON orders(user_id);")
            indexes.append("CREATE INDEX idx_orders_status_created ON orders(status, created_at);")
            constraints.append("ALTER TABLE orders ADD CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users(id);")

        if "product" in req_lower or "item" in req_lower:
            tables.append({
                "name": "products",
                "columns": [
                    {"name": "id", "type": "SERIAL PRIMARY KEY"},
                    {"name": "sku", "type": "VARCHAR(100) UNIQUE NOT NULL"},
                    {"name": "name", "type": "VARCHAR(255) NOT NULL"},
                    {"name": "price", "type": "DECIMAL(12,2) NOT NULL"},
                ],
            })
            indexes.append("CREATE INDEX idx_products_sku ON products(sku);")

        if not tables:
            tables.append({
                "name": "entities",
                "columns": [
                    {"name": "id", "type": "SERIAL PRIMARY KEY"},
                    {"name": "name", "type": "VARCHAR(255) NOT NULL"},
                    {"name": "created_at", "type": "TIMESTAMP DEFAULT NOW()"},
                ],
            })
            notes.append("Generic schema returned; provide more specific requirements for tailored design.")

        notes.append("Review foreign key cascade rules based on your business logic.")
        notes.append("Consider partitioning large tables by date or tenant.")

        logger.info("Schema suggestion generated: tables=%d indexes=%d", len(tables), len(indexes))
        return SchemaSuggestion(
            tables=tables,
            indexes=indexes,
            constraints=constraints,
            notes=notes,
        )

    def stats(self) -> dict[str, Any]:
        """Return agent usage statistics."""
        return {
            "agent": self.name,
            **self._stats,
            "total_requests": sum(self._stats.values()),
        }
