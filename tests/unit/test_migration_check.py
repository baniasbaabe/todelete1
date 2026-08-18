"""Pure tests for startup migration-check configuration."""

from habit_tracker.infrastructure.database.migration_check import expected_heads, sync_url


def test_expected_heads_is_single():
    heads = expected_heads()

    assert len(heads) == 1, f"the Alembic chain must stay single-headed, got {heads}"


def test_sync_url_swaps_asyncpg_for_psycopg2():
    assert sync_url("postgresql+asyncpg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    assert sync_url("postgresql://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
