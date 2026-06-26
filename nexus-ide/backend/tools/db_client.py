"""Database client tools — SQL queries and schema introspection.

Provides tools to execute SQL queries and inspect database schemas.
Supports SQLite out of the box and PostgreSQL when ``asyncpg`` is installed.
Database connection is configured via env var ``NEXUS_DB_URL`` (defaults to
``sqlite:///./nexus.db``). Write operations (INSERT/UPDATE/DELETE/DDL) require
explicit ``confirm=True`` to prevent accidental data loss.
"""

from __future__ import annotations

import logging
import os
import re

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------
_DB_URL = os.environ.get("NEXUS_DB_URL", "sqlite:///./nexus.db")


def _parse_db_url(url: str) -> tuple[str, str]:
    """Parse a DB URL like 'sqlite:///path' or 'postgresql://...'."""
    if url.startswith("sqlite:///"):
        return "sqlite", url[len("sqlite://"):]
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        return "postgresql", url
    raise ValueError(f"Unsupported DB URL scheme in '{url}' (use sqlite:/// or postgresql://)")


async def _execute(query: str, params: tuple | None = None, read_only: bool = True) -> dict:
    """Execute a query using aiosqlite (always available) or asyncpg (if installed)."""
    db_type, conn_str = _parse_db_url(_DB_URL)
    if db_type == "sqlite":
        try:
            import aiosqlite  # type: ignore
        except ImportError:
            return {"error": "aiosqlite not installed (pip install aiosqlite)"}
        try:
            async with aiosqlite.connect(conn_str) as db:
                if read_only:
                    await db.execute("BEGIN")
                cursor = await db.execute(query, params or ())
                if read_only:
                    rows = await cursor.fetchall()
                    columns = [d[0] for d in cursor.description] if cursor.description else []
                    await db.rollback()
                    return {"columns": columns, "rows": [list(r) for r in rows], "row_count": len(rows)}
                else:
                    await db.commit()
                    return {"affected_rows": cursor.rowcount, "lastrowid": cursor.lastrowid}
        except Exception as e:  # noqa: BLE001
            logger.exception("sqlite query failed")
            return {"error": str(e), "query": query}
    elif db_type == "postgresql":
        try:
            import asyncpg  # type: ignore
        except ImportError:
            return {"error": "asyncpg not installed (pip install asyncpg)"}
        try:
            conn = await asyncpg.connect(conn_str)
            try:
                if read_only:
                    rows = await conn.fetch(query, *(params or []))
                    if rows:
                        columns = list(rows[0].keys())
                        data = [[getattr(r, c) for c in columns] for r in rows]
                    else:
                        columns = []
                        data = []
                    return {"columns": columns, "rows": data, "row_count": len(data)}
                else:
                    status = await conn.execute(query, *(params or []))
                    # status looks like "INSERT 0 5"
                    parts = status.split()
                    affected = int(parts[-1]) if parts and parts[-1].isdigit() else 0
                    return {"status": status, "affected_rows": affected}
            finally:
                await conn.close()
        except Exception as e:  # noqa: BLE001
            logger.exception("postgres query failed")
            return {"error": str(e), "query": query}
    return {"error": f"Unknown DB type '{db_type}'"}


# ---------------------------------------------------------------------------
# Query classifiers
# ---------------------------------------------------------------------------
_READ_PREFIXES = ("SELECT", "PRAGMA", "EXPLAIN", "WITH")
_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "REPLACE", "TRUNCATE")

# Additional safety: single-statement only (no stacked queries with semicolons)
_MULTI_STMT_RE = re.compile(r";\s*\S", re.MULTILINE)


def _classify_query(query: str) -> str:
    """Return 'read', 'write', or 'unknown'."""
    q = query.strip().lstrip("(").lstrip().upper()
    if not q:
        return "unknown"
    first = q.split(None, 1)[0]
    if first in _READ_PREFIXES:
        return "read"
    if first in _WRITE_PREFIXES:
        return "write"
    return "unknown"


def _check_dangerous(query: str) -> str | None:
    """Return an error message if query looks dangerous, else None."""
    upper = query.upper()
    # Block sqlite_master access outside schema tool
    if "SQLITE_MASTER" in upper or "PG_CATALOG" in upper:
        return "Direct system-catalog access is not allowed; use db_schema tool instead"
    # Block stacked statements
    if _MULTI_STMT_RE.search(query.rstrip(";")):
        return "Multiple statements not allowed (remove extra semicolons)"
    return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
async def db_query(query: str, params: list | None = None) -> dict:
    """Execute a read-only SQL query (SELECT/PRAGMA/EXPLAIN/WITH).

    Args:
        query: SQL query string.
        params: Optional positional parameters for parameterised queries.
    """
    kind = _classify_query(query)
    if kind == "write":
        return {"error": "db_query is read-only; use db_execute for write operations"}
    if kind == "unknown":
        return {"error": "Query must start with SELECT, PRAGMA, EXPLAIN, or WITH"}

    err = _check_dangerous(query)
    if err:
        return {"error": err}

    result = await _execute(query, tuple(params) if params else None, read_only=True)
    return result


async def db_execute(query: str, params: list | None = None, confirm: bool = False) -> dict:
    """Execute a write SQL query (INSERT/UPDATE/DELETE/CREATE/DROP/ALTER).

    **Requires explicit confirmation** via ``confirm=True`` to prevent
    accidental data loss. If not confirmed, returns a preview without executing.
    """
    if not confirm:
        return {
            "status": "preview",
            "message": "Write not executed. Pass confirm=True to actually execute.",
            "query": query,
            "params": params,
        }

    kind = _classify_query(query)
    if kind == "read":
        return {"error": "db_execute is for write operations; use db_query for reads"}
    if kind == "unknown":
        return {"error": "Unrecognised query type"}

    err = _check_dangerous(query)
    if err:
        return {"error": err}

    result = await _execute(query, tuple(params) if params else None, read_only=False)
    result["status"] = "executed"
    return result


async def db_schema() -> dict:
    """List all tables and their columns in the database."""
    db_type, _ = _parse_db_url(_DB_URL)
    if db_type == "sqlite":
        return await _execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
            read_only=True,
        )
    if db_type == "postgresql":
        return await _execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name",
            read_only=True,
        )
    return {"error": f"Unknown DB type '{db_type}'"}


async def db_tables() -> dict:
    """List tables (alias for db_schema, returns simplified structure).

    Returns a dict {table_name: [column_name, ...]} for easy consumption.
    """
    db_type, _ = _parse_db_url(_DB_URL)
    schema = await db_schema()
    if "error" in schema:
        return schema
    table_names = [row[0] for row in schema.get("rows", [])]
    result = {}
    for table in table_names:
        if db_type == "sqlite":
            col_info = await _execute(
                f"PRAGMA table_info({table})", read_only=True
            )
        else:
            col_info = await _execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name=$1 ORDER BY ordinal_position",
                (table,),
                read_only=True,
            )
        if "rows" in col_info:
            # PRAGMA table_info returns (cid, name, type, notnull, dflt_value, pk)
            # information_schema returns (column_name,)
            if col_info["columns"] and col_info["columns"][0] == "cid":
                result[table] = [r[1] for r in col_info["rows"]]
            else:
                result[table] = [r[0] for r in col_info["rows"]]
    return result


register_tool(
    ToolSpec(
        name="db_query",
        description=(
            "Execute a read-only SQL query (SELECT/PRAGMA/EXPLAIN/WITH). "
            "Supports SQLite (default) and PostgreSQL via env NEXUS_DB_URL. "
            "Use params for parameterised queries to prevent injection. "
            "Returns columns + rows."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "SQL query (read-only)"},
                "params": {"type": "array", "description": "Optional positional parameters", "items": {"type": ["string", "number", "boolean", "null"]}},
            },
            "required": ["query"],
        },
        handler=db_query,
    )
)

register_tool(
    ToolSpec(
        name="db_execute",
        description=(
            "Execute a write SQL query (INSERT/UPDATE/DELETE/CREATE/DROP/ALTER). "
            "**Requires explicit confirm=True** to prevent accidental data loss. "
            "Without confirm, returns a preview. Multi-statement queries are blocked."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "SQL write query"},
                "params": {"type": "array", "description": "Optional positional parameters", "items": {"type": ["string", "number", "boolean", "null"]}},
                "confirm": {"type": "boolean", "description": "Must be true to actually execute", "default": False},
            },
            "required": ["query"],
        },
        handler=db_execute,
    )
)

register_tool(
    ToolSpec(
        name="db_schema",
        description="List all tables and views in the database (catalog-level).",
        schema={"type": "object", "properties": {}},
        handler=db_schema,
    )
)

register_tool(
    ToolSpec(
        name="db_tables",
        description=(
            "List all tables and their columns as a {table: [columns]} dict. "
            "Convenience wrapper around db_schema with per-table introspection."
        ),
        schema={"type": "object", "properties": {}},
        handler=db_tables,
    )
)
