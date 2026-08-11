"""Migration checks against a clean PostgreSQL Testcontainer database."""

from __future__ import annotations

from sqlalchemy import Engine, event, inspect, text

from habit_tracker.infrastructure.database.migration_check import current_revisions

DDL_KEYWORDS = ("create ", "alter ", "drop ", "truncate ")


def _capture_statements(engine: Engine) -> list[str]:
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: PLR0917
        statements.append(statement)

    return statements


def _assert_no_ddl(statements: list[str]) -> None:
    offenders = [statement for statement in statements if any(word in statement.lower() for word in DDL_KEYWORDS)]
    assert offenders == [], f"schema check issued DDL: {offenders}"


def test_missing_version_table_is_not_created(unmigrated_postgres_engine: Engine) -> None:
    statements = _capture_statements(unmigrated_postgres_engine)

    with unmigrated_postgres_engine.connect() as connection:
        assert current_revisions(connection) == ()

    _assert_no_ddl(statements)
    with unmigrated_postgres_engine.connect() as connection:
        assert not inspect(connection).has_table("alembic_version")


def test_existing_version_table_is_only_read(unmigrated_postgres_engine: Engine) -> None:
    with unmigrated_postgres_engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('d4e5f6a7b8c9')"))

    statements = _capture_statements(unmigrated_postgres_engine)
    with unmigrated_postgres_engine.connect() as connection:
        assert current_revisions(connection) == ("d4e5f6a7b8c9",)

    _assert_no_ddl(statements)
