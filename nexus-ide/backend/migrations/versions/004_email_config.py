"""Add email_accounts table

Revision ID: 004_email_config
Revises: 003_user_profile
Create Date: 2025-01-12

"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "004_email_config"
down_revision = "003_user_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS email_accounts (
            id                 TEXT PRIMARY KEY,
            user_id            TEXT NOT NULL,
            label              TEXT NOT NULL DEFAULT 'Email',
            host               TEXT NOT NULL,
            port               INTEGER NOT NULL DEFAULT 993,
            username           TEXT NOT NULL,
            password_encrypted TEXT NOT NULL,
            use_ssl            INTEGER DEFAULT 1,
            active             INTEGER DEFAULT 1,
            created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_email_accounts_user ON email_accounts(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_email_accounts_active ON email_accounts(active)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_email_accounts_active")
    op.execute("DROP INDEX IF EXISTS idx_email_accounts_user")
    op.execute("DROP TABLE IF EXISTS email_accounts")
