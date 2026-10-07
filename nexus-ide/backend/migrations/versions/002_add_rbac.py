"""Add RBAC (Role-Based Access Control) tables

Revision ID: 002_add_rbac
Revises: 001_initial
Create Date: 2025-01-12

"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "002_add_rbac"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create users table
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            TEXT PRIMARY KEY,
            username      TEXT NOT NULL UNIQUE,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name     TEXT,
            is_active     INTEGER DEFAULT 1,
            created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)

    # Create roles table
    op.execute("""
        CREATE TABLE IF NOT EXISTS roles (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL UNIQUE,
            description   TEXT,
            created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)

    # Create permissions table
    # NOTE: no `created_at` column. backend/persistence/schemas.sql -- the
    # canonical schema (AGENTS.md rule 6) -- has no such column, and
    # persistence/db.py seeds this table with an explicit column list that omits
    # it, so keeping it here produced a schema the runtime can never produce.
    # Removed 2026-09-26 to make the two sources converge; see
    # backend/tests/persistence/test_schema_parity.py.
    op.execute("""
        CREATE TABLE IF NOT EXISTS permissions (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL UNIQUE,
            description   TEXT,
            resource      TEXT NOT NULL,
            action        TEXT NOT NULL
        )
    """)

    # Create user_roles junction table
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_roles (
            id            TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL,
            role_id       TEXT NOT NULL,
            assigned_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
            UNIQUE(user_id, role_id)
        )
    """)

    # Create role_permissions junction table
    # NOTE: no `assigned_at` column, for the same reason as permissions above.
    op.execute("""
        CREATE TABLE IF NOT EXISTS role_permissions (
            id            TEXT PRIMARY KEY,
            role_id       TEXT NOT NULL,
            permission_id TEXT NOT NULL,
            FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
            FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE,
            UNIQUE(role_id, permission_id)
        )
    """)

    # Create indexes
    # NOTE: idx_users_username, idx_user_roles_role, idx_permissions_resource
    # and idx_role_permissions_permission were dropped 2026-09-26 because
    # schemas.sql does not define them. Every remaining UNIQUE column is already
    # covered by the implicit sqlite_autoindex, so they were pure overhead.
    op.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_role_permissions_role ON role_permissions(role_id)")

    # Insert default roles
    op.execute("""
        INSERT INTO roles (id, name, description) VALUES
            ('role_admin', 'admin', 'Administrator with full access'),
            ('role_user', 'user', 'Standard user with limited access'),
            ('role_viewer', 'viewer', 'Read-only access')
    """)

    # Insert default permissions
    op.execute("""
        INSERT INTO permissions (id, name, description, resource, action) VALUES
            ('perm_project_create', 'project:create', 'Create new projects', 'project', 'create'),
            ('perm_project_read', 'project:read', 'Read projects', 'project', 'read'),
            ('perm_project_update', 'project:update', 'Update projects', 'project', 'update'),
            ('perm_project_delete', 'project:delete', 'Delete projects', 'project', 'delete'),
            ('perm_session_create', 'session:create', 'Create new sessions', 'session', 'create'),
            ('perm_session_read', 'session:read', 'Read sessions', 'session', 'read'),
            ('perm_session_update', 'session:update', 'Update sessions', 'session', 'update'),
            ('perm_session_delete', 'session:delete', 'Delete sessions', 'session', 'delete'),
            ('perm_user_manage', 'user:manage', 'Manage users', 'user', 'manage'),
            ('perm_settings_manage', 'settings:manage', 'Manage system settings', 'settings', 'manage')
    """)

    # Assign all permissions to admin role
    op.execute("""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT
            'rp_' || substr(perm.id, 6) || '_' || substr(role.id, 6),
            role.id,
            perm.id
        FROM roles role, permissions perm
        WHERE role.name = 'admin'
    """)

    # Assign limited permissions to user role
    op.execute("""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT
            'rp_' || substr(perm.id, 6) || '_' || substr(role.id, 6),
            role.id,
            perm.id
        FROM roles role, permissions perm
        WHERE role.name = 'user'
        AND perm.name IN ('project:create', 'project:read', 'project:update', 'session:create', 'session:read', 'session:update')
    """)

    # Assign read-only permissions to viewer role
    op.execute("""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT
            'rp_' || substr(perm.id, 6) || '_' || substr(role.id, 6),
            role.id,
            perm.id
        FROM roles role, permissions perm
        WHERE role.name = 'viewer'
        AND perm.name IN ('project:read', 'session:read')
    """)


def downgrade() -> None:
    # Drop indexes
    op.execute("DROP INDEX IF EXISTS idx_permissions_resource")
    op.execute("DROP INDEX IF EXISTS idx_role_permissions_permission")
    op.execute("DROP INDEX IF EXISTS idx_role_permissions_role")
    op.execute("DROP INDEX IF EXISTS idx_user_roles_role")
    op.execute("DROP INDEX IF EXISTS idx_user_roles_user")
    op.execute("DROP INDEX IF EXISTS idx_users_email")
    op.execute("DROP INDEX IF EXISTS idx_users_username")

    # Drop tables
    op.execute("DROP TABLE IF EXISTS role_permissions")
    op.execute("DROP TABLE IF EXISTS user_roles")
    op.execute("DROP TABLE IF EXISTS permissions")
    op.execute("DROP TABLE IF EXISTS roles")
    op.execute("DROP TABLE IF EXISTS users")
