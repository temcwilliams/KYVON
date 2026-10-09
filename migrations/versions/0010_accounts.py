"""hosted accounts: email, roles, terms acceptance, email tokens

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-10 09:00:00.000000

WARNING for future migrations: never use ``batch_alter_table("users")`` (it rebuilds the table on
SQLite, and ``DROP TABLE users`` cascades to every table that references it, silently deleting
all user data). Add columns and indexes directly instead.
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=254), nullable=True))
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    op.add_column(
        "users", sa.Column("role", sa.String(length=16), nullable=False, server_default="user")
    )
    op.add_column("users", sa.Column("disabled_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("terms_accepted_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("terms_version", sa.String(length=16), nullable=True))
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    # Everyone who exists before hosted accounts is the single owner of a personal install.
    op.execute(sa.text("UPDATE users SET role = 'admin'"))

    op.create_table(
        "email_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_email_tokens_user_purpose", "email_tokens", ["user_id", "purpose"])


def downgrade() -> None:
    op.drop_index("ix_email_tokens_user_purpose", table_name="email_tokens")
    op.drop_table("email_tokens")
    op.drop_index("ix_users_email", table_name="users")
    # Direct DROP COLUMN (SQLite 3.35+): no table rebuild, so no cascading data loss.
    for column in (
        "terms_version",
        "terms_accepted_at",
        "disabled_at",
        "role",
        "email_verified_at",
        "email",
    ):
        op.drop_column("users", column)
