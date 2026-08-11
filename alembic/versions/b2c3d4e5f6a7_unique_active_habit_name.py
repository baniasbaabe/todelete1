"""unique_active_habit_name

Adds a partial unique index on (user_id, name) for active habits.

It is partial because deletion is a soft delete: inactive rows keep their name
and must not reserve it forever. Before this, the only guard against duplicates
was a read in CreateHabit, which is not atomic with the insert that follows it.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-27 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "uq_habits_user_id_active_name"


def upgrade() -> None:
    # Existing rows may already violate the constraint, in which case creating
    # the index would abort the migration. Keep the newest active habit for
    # each (user_id, name) and soft-delete the older ones — the newest is the
    # row the user most recently created and is the one their streaks and
    # completions are accumulating against.
    op.execute(
        sa.text("""
        UPDATE habits SET is_active = false
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY user_id, name ORDER BY created_at DESC, id DESC
                ) AS rn
                FROM habits
                WHERE is_active
            ) ranked
            WHERE rn > 1
        )
        """)
    )

    op.create_index(
        INDEX_NAME,
        "habits",
        ["user_id", "name"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    # The rows deactivated above are not reactivated: which duplicate was
    # "supposed" to be active is no longer recoverable.
    op.drop_index(INDEX_NAME, table_name="habits")
