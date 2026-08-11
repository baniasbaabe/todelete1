"""add_bot_persistence_table

The bot_persistence table was previously created at runtime by
PostgresPersistence._ensure_table(). Moving it to Alembic lets the
least-privilege habit_app role operate without DDL permissions on
the public schema.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Deployments that ran the old code already have this table, created at
    # runtime by _ensure_table(). op.create_table() has no IF NOT EXISTS, so
    # without this guard the first deploy after the switch would abort here.
    # The column definitions below reproduce that runtime DDL exactly, so
    # skipping is safe rather than merely convenient.
    if sa.inspect(op.get_bind()).has_table("bot_persistence"):
        return

    op.create_table(
        "bot_persistence",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("bot_persistence")
