# backend/migrations — status and rules

## Which one is authoritative?

**`backend/persistence/schemas.sql` is the single source of truth.**
(AGENTS.md rule 6.) `backend/persistence/db.py::init_db` executes it with
`executescript` on a fresh database and on every existing one. Alembic is *not*
how the runtime builds its schema.

## So why does this directory exist, and is it kept correct?

Because it is checked in, and anyone who finds it will reasonably try
`alembic upgrade head`. A migration chain that cannot run is worse than no chain
at all, so the chain is kept **runnable and convergent**:

> A fresh `alembic upgrade head` produces the same tables, columns and indexes
> as a fresh `schemas.sql`.

That equivalence is not a claim, it is a test:
`backend/tests/persistence/test_schema_parity.py` (also runnable standalone as
`python tools/ci/schema_parity.py`, which CI invokes).

### What was broken, and what fixed it

| Problem | Fix |
| --- | --- |
| `upgrade head` on an empty DB died at 006: `ALTER TABLE session_runs` on a table no revision created | 006 now `CREATE TABLE IF NOT EXISTS session_runs` before altering it |
| 8 tables existed only in `schemas.sql`: `agent_states`, `git_commits`, `peer_review_requests`, `peer_review_results`, `persistent_memories`, `session_runs`, `whiteboard_entries`, `whiteboard_entry_links` | 007_schemas_sql_parity creates them (+ their indexes) |
| `permissions.created_at`, `role_permissions.assigned_at` existed only here | Removed from 002; `schemas.sql` is canonical and `db.py` seeds both tables with explicit column lists that omit them |
| 16 indexes on `projects`/`sessions`/`messages`/`tool_executions`/`routing_decisions`/`proposed_changes` existed only in `schemas.sql` | Added to 001 |
| `idx_users_username`, `idx_user_roles_role`, `idx_permissions_resource`, `idx_role_permissions_permission` existed only here | Removed from 002; all were already covered by implicit `sqlite_autoindex` UNIQUE constraints |
| 003's docstring claimed "persistent memories tables" | Corrected — 003 creates `user_profiles`, `user_routines`, `user_memories`; `persistent_memories` is 007 |
| Persisted chat messages had no stable run association | 008 adds nullable `messages.run_id` and its lookup index; legacy rows remain readable |

### Why this is safe for existing databases

`init_db` calls `_stamp_alembic()`, which stamps a fresh database straight to
`head`. Databases from earlier versions can still be stamped at 006/007. Startup
adds the nullable `messages.run_id` compatibility column before applying the
canonical schema/index, then 008 sees the same column and index and is a no-op.
Legacy message rows keep their contents and receive a NULL run link.
`test_production_stamped_database_upgrades_are_a_no_op` asserts exactly this.

Never convert those to bare `CREATE`/`ALTER`. That is the whole safety argument.

## Rules for changing this directory

1. **Add tables to `schemas.sql` first.** It is canonical. Then add the matching
   `CREATE TABLE IF NOT EXISTS` to a new revision, copied verbatim.
2. **Copy, do not import.** A revision must be an immutable snapshot, so it
   cannot read `schemas.sql` at run time. The parity test is what keeps the copy
   honest — if you edit `schemas.sql`, run
   `python tools/ci/schema_parity.py` and it will tell you exactly what drifted.
3. **Never edit an already-released revision to change data.** Adding an
   idempotent index/table to an old revision is fine (existing databases skip
   it); changing one that mutates rows is not.
4. **`downgrade()` must not destroy runtime data.** 007 and 008 are deliberately
   no-ops on downgrade; dropping their tables or run link would discard durable state.
5. `scripts/…` note: `alembic.ini` sets `script_location = backend/migrations`
   and `sqlalchemy.url = sqlite:///data/nexus.db`, both relative — run Alembic
   from the `nexus-ide/` directory, never from `backend/`.

## Running it by hand

```powershell
# from nexus-ide/
alembic upgrade head                # against data/nexus.db -- real data
alembic -x db=path/to/scratch.db upgrade head   # scratch only
python tools/ci/schema_parity.py    # temp dirs only, safe, read-only on data/
```
