r"""Compare a fresh `alembic upgrade head` schema against a fresh `schemas.sql` schema.

Run from nexus-ide/:
    .venv\Scripts\python.exe tools/ci/schema_parity.py

Writes both databases into a temp dir; never touches backend data/ or the
developer database. Exits non-zero and prints the delta when they differ.
This is the same comparison backend/tests/persistence/test_schema_parity.py
asserts, usable standalone and in CI.
"""

from __future__ import annotations

import pathlib
import sqlite3
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO / "backend" / "alembic.ini"
SCHEMAS_SQL = REPO / "backend" / "persistence" / "schemas.sql"

# Tables owned by the migration machinery rather than by schemas.sql.
INFRA_TABLES = {"alembic_version", "sqlite_sequence"}


def snapshot(db: pathlib.Path) -> dict[str, object]:
    """Return {tables}, {table: {columns}}, {indexes}} for an SQLite file."""
    conn = sqlite3.connect(str(db))
    try:
        tables = {
            str(r[0])
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        tables -= INFRA_TABLES
        columns = {
            t: {str(r[1]) for r in conn.execute(f"PRAGMA table_info({t})").fetchall()}
            for t in tables
        }
        indexes = {
            str(r[0])
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
    finally:
        conn.close()
    return {"tables": tables, "columns": columns, "indexes": indexes}


def build_alembic(target: pathlib.Path) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{target.as_posix()}")
    command.upgrade(cfg, "head")


def build_schemas(target: pathlib.Path) -> None:
    conn = sqlite3.connect(str(target))
    try:
        conn.executescript(SCHEMAS_SQL.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="nexus-schema-parity-") as tmp:
        tmpdir = pathlib.Path(tmp)
        mig_db = tmpdir / "alembic.db"
        sql_db = tmpdir / "schemas.db"

        try:
            build_alembic(mig_db)
        except Exception as exc:  # noqa: BLE001 - report, do not mask
            print(f"FAIL: `alembic upgrade head` on a fresh database raised: {exc}")
            return 2
        build_schemas(sql_db)

        mig, sql = snapshot(mig_db), snapshot(sql_db)

    ok = True
    only_mig = mig["tables"] - sql["tables"]
    only_sql = sql["tables"] - mig["tables"]
    if only_mig:
        ok = False
        print(f"tables only in alembic:    {sorted(only_mig)}")
    if only_sql:
        ok = False
        print(f"tables only in schemas.sql: {sorted(only_sql)}")
    if not only_mig and not only_sql:
        print(f"tables: IDENTICAL ({len(sql['tables'])} tables)")

    for table in sorted(mig["columns"].keys() & sql["columns"].keys()):
        a, b = mig["columns"][table], sql["columns"][table]
        if a - b:
            ok = False
            print(f"columns only in alembic  {table}: {sorted(a - b)}")
        if b - a:
            ok = False
            print(f"columns only in schemas  {table}: {sorted(b - a)}")
    if ok:
        print("columns: IDENTICAL")

    idx_mig, idx_sql = mig["indexes"], sql["indexes"]
    if idx_mig - idx_sql:
        ok = False
        print(f"indexes only in alembic:  {sorted(idx_mig - idx_sql)}")
    if idx_sql - idx_mig:
        ok = False
        print(f"indexes only in schemas:  {sorted(idx_sql - idx_mig)}")
    if not (idx_mig ^ idx_sql):
        print(f"indexes: IDENTICAL ({len(idx_sql)} indexes)")

    print("PARITY OK" if ok else "PARITY MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
