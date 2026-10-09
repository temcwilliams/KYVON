"""shared rate-limit hits

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-10 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_hits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rate_hits_key_at", "rate_hits", ["key", "at"])


def downgrade() -> None:
    op.drop_index("ix_rate_hits_key_at", table_name="rate_hits")
    op.drop_table("rate_hits")
