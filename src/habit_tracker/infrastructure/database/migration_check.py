"""Read-only startup check that the database is at the code's Alembic head.

The runtime container authenticates as ``habit_app``, a least-privilege role
that holds no DDL rights in the ``public`` schema (see
``scripts/bootstrap-db-roles.sh``). It therefore cannot run ``alembic upgrade
head``: the first revision that emits real DDL would fail with "permission
denied for schema public" and crash-loop the App Service with that traceback
buried in container logs. Migrations are applied out of band by
``scripts/run-migrations.sh``, which uses the server admin credential.

What remains for startup is an assertion, not a mutation: refuse to serve
traffic against a schema the code does not expect, and say exactly which
revisions disagree.

Every statement issued here is a SELECT.
``MigrationContext.get_current_heads()`` returns ``()`` when ``alembic_version``
is absent rather than creating it -- only ``run_migrations()`` and ``stamp()``
call ``_ensure_version_table()``. ``tests/unit/test_migration_check.py`` pins
that by asserting no DDL reaches the driver.

Reading ``alembic_version`` as ``habit_app`` is covered by the ``ALTER DEFAULT
PRIVILEGES FOR ROLE <admin> ... ON TABLES`` grant in
``scripts/bootstrap-db-roles.sh``: the table is created by the admin when
migrations first run, so the default-privileges grant applies to it.
"""

from __future__ import annotations

from pathlib import Path
import sys

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool
import structlog

from habit_tracker.infrastructure.config.settings import DatabaseSettings
from habit_tracker.infrastructure.logging.logger import configure_logging

logger = structlog.get_logger()

# src/habit_tracker/infrastructure/database/migration_check.py -> repo root.
# Same layout in the container image: /app/src/... alongside /app/alembic.ini.
_PROJECT_ROOT = Path(__file__).resolve().parents[4]

_REMEDY = "run scripts/run-migrations.sh with the admin credential, then restart this container"


def alembic_config(project_root: Path | None = None) -> Config:
    """Load alembic.ini.

    Loading the config does not execute ``alembic/env.py`` -- only the alembic
    command entry points do. That matters here: env.py builds its own engine and
    would open a second connection as a side effect of reading the head.
    """
    root = project_root if project_root is not None else _PROJECT_ROOT
    return Config(str(root / "alembic.ini"))


def expected_heads(config: Config | None = None) -> tuple[str, ...]:
    """Head revision(s) of the migration scripts shipped in this image."""
    return tuple(ScriptDirectory.from_config(config if config is not None else alembic_config()).get_heads())


def current_revisions(connection: Connection) -> tuple[str, ...]:
    """Revisions recorded in ``alembic_version``, or ``()`` when it is absent.

    Issues no DDL: a missing version table is reported as "no revisions", never
    created.
    """
    return MigrationContext.configure(connection).get_current_heads()


def sync_url(database_url: str) -> str:
    """Swap the asyncpg driver for psycopg2, mirroring ``alembic/env.py``.

    The version table is read synchronously; psycopg2 also picks up the
    ``PGSSLMODE=verify-full`` and ``PGSSLROOTCERT`` values set in the Dockerfile.
    """
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


def main(settings: DatabaseSettings | None = None) -> int:
    configure_logging()

    database_url = (settings if settings is not None else DatabaseSettings()).database_url

    heads = expected_heads()
    # create_engine() parses the URL and so can raise ArgumentError on a
    # malformed DATABASE_URL. Keep it inside the try: ArgumentError is a
    # SQLAlchemyError, so a typo'd connection string produces the same one-line
    # message as every other failure here rather than a raw traceback.
    engine = None
    try:
        engine = create_engine(sync_url(database_url), poolclass=NullPool)
        with engine.connect() as connection:
            current = current_revisions(connection)
    except SQLAlchemyError as exc:
        # Deliberately not the exception variant of this call: it would attach a
        # ~120-line SQLAlchemy traceback to a container-startup log line. The
        # point of this check is that the operator reads one legible message,
        # and the driver's own text ("Connection refused", "password
        # authentication failed for user ...") is the part with diagnostic value.
        logger.error(  # noqa: TRY400
            "migration_check_failed",
            reason="could not read the schema revision from the database",
            expected_revision=",".join(heads),
            remedy=_REMEDY,
            error=str(exc),
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()

    if current and set(current) == set(heads):
        logger.info("schema_at_head", revision=",".join(sorted(current)))
        return 0

    logger.error(
        "schema_out_of_date",
        reason=(
            "the database has never been migrated"
            if not current
            else "the database revision does not match this image's Alembic head"
        ),
        database_revision=",".join(sorted(current)) or "none (no alembic_version table)",
        expected_revision=",".join(sorted(heads)),
        remedy=_REMEDY,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
