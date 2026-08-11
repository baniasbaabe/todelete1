"""initial_schema

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-07-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create initial schema."""
    # Enable pgvector extension (used by mem0ai for vector storage)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=False)

    # Create habits table
    op.create_table(
        "habits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("frequency", sa.String(50), nullable=False),
        sa.Column("verification_policy", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_habits_user_id_is_active", "habits", ["user_id", "is_active"], unique=False)

    # Create completions table
    op.create_table(
        "completions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("habit_id", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proof_type", sa.String(50), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("verification_notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["habit_id"], ["habits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_completions_habit_id_completed_at",
        "completions",
        ["habit_id", "completed_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop all tables created in this migration."""
    op.drop_index("ix_completions_habit_id_completed_at", table_name="completions")
    op.drop_table("completions")
    op.drop_index("ix_habits_user_id_is_active", table_name="habits")
    op.drop_table("habits")
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS vector")
