#!/bin/bash
set -e

for var in TELEGRAM_BOT_TOKEN DATABASE_URL WEBHOOK_URL; do
    if [ -z "${!var}" ]; then
        echo "ERROR: $var not set"
        exit 1
    fi
done

# Verify the schema matches this image, but never change it.
#
# DATABASE_URL authenticates as habit_app, which holds no DDL rights in the
# public schema (scripts/bootstrap-db-roles.sh), so "alembic upgrade head" here
# would die with "permission denied for schema public" the first time a
# revision emits real DDL. Migrations are applied by scripts/run-migrations.sh
# with the admin credential; this check only reads alembic_version and refuses
# to start -- with both revisions named -- if the schema is behind.
python -m habit_tracker.infrastructure.database.migration_check

exec python -m habit_tracker
