#!/bin/bash
set -euo pipefail

# Creates the least-privilege PostgreSQL roles used by the Phoenix container
# and by the bot container.
#
# Terraform/ARM can create databases but not SQL roles — roles are data-plane
# objects — so this runs once after the postgres and postgres-firewall-deployer
# units are applied, and is idempotent thereafter.
#
# Requires: az login, psql, and a firewall rule for this machine
# (set DEPLOYER_IP before applying postgres-firewall-deployer).

echo "========================================="
echo "Bootstrapping PostgreSQL roles"
echo "========================================="

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LIVE_DIR="$PROJECT_ROOT/infra/live"

for cmd in az psql terragrunt; do
    if ! command -v "$cmd" &> /dev/null; then
        echo -e "${RED}ERROR: $cmd is required but not installed${NC}"
        exit 1
    fi
done

# The terragrunt output calls below open the encrypted remote state backend.
# Without these the script dies in an opaque Terragrunt error instead of saying
# what is missing; deploy.sh exports them, a standalone run must too.
for var in PBKDF2_PASSPHRASE TFSTATE_STORAGE_ACCOUNT ARM_SUBSCRIPTION_ID; do
    if [ -z "${!var:-}" ]; then
        echo -e "${RED}ERROR: $var is not set - required to read Terragrunt state${NC}"
        echo "Load them from your deployment environment, or run scripts/deploy.sh."
        exit 1
    fi
done

if ! az account show &> /dev/null; then
    echo -e "${RED}ERROR: Not logged in to Azure CLI. Run 'az login' first.${NC}"
    exit 1
fi

POSTGRES_HOST=$(cd "$LIVE_DIR/postgres" && terragrunt output -raw postgres_fqdn)
POSTGRES_USER=$(cd "$LIVE_DIR/postgres" && terragrunt output -raw postgres_admin_user)
PHOENIX_DB=$(cd "$LIVE_DIR/postgres" && terragrunt output -raw phoenix_db_name)
APP_DB=$(cd "$LIVE_DIR/postgres" && terragrunt output -raw habit_tracker_db_name)
KV_NAME=$(cd "$LIVE_DIR/keyvault" && terragrunt output -raw keyvault_name)

echo "Retrieving credentials from Key Vault '$KV_NAME'..."
PGPASSWORD=$(az keyvault secret show --vault-name "$KV_NAME" \
    --name "postgres-admin-password" --query value -o tsv)
PHOENIX_DB_PASSWORD=$(az keyvault secret show --vault-name "$KV_NAME" \
    --name "phoenix-db-password" --query value -o tsv)
HABIT_APP_PASSWORD=$(az keyvault secret show --vault-name "$KV_NAME" \
    --name "habit-app-db-password" --query value -o tsv)
export PGPASSWORD

# Authenticate the server, do not merely encrypt the channel.
# Use the OS CA bundle so this works on GitHub Actions runners and other
# environments that lack ~/.postgresql/root.crt.
export PGSSLMODE=verify-full
export PGSSLROOTCERT=system

run_sql() {
    local database="$1"
    shift
    psql --host "$POSTGRES_HOST" --port 5432 --username "$POSTGRES_USER" \
        --dbname "$database" --no-psqlrc --quiet --set ON_ERROR_STOP=1 "$@"
}

echo "Creating phoenix_app role..."
# :'phoenix_pw' applies psql's own literal quoting, so the password is never
# concatenated into the SQL text.
#
# The ALTER ROLE statements here and below still carry the password in
# cleartext SQL. The server does not log them today (log_statement is unset, so
# Azure's default of "none" applies), but PostgreSQLLogs are shipped to Log
# Analytics by infra/modules/postgres/main.tf: turning on log_statement=all,
# ddl or mod would persist these passwords into that workspace.
run_sql "postgres" --set phoenix_pw="$PHOENIX_DB_PASSWORD" <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'phoenix_app') THEN
        CREATE ROLE phoenix_app LOGIN;
    END IF;
END
$$;
SQL

run_sql "postgres" --set phoenix_pw="$PHOENIX_DB_PASSWORD" <<'SQL'
ALTER ROLE phoenix_app WITH LOGIN PASSWORD :'phoenix_pw';
SQL

echo "Granting phoenix_app access to the '$PHOENIX_DB' database only..."
run_sql "postgres" <<SQL
REVOKE ALL ON DATABASE "$PHOENIX_DB" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE "$PHOENIX_DB" TO phoenix_app;
SQL

# PostgreSQL 15+ no longer grants CREATE on the public schema to PUBLIC, so
# Phoenix needs it explicitly to build its own tables.
run_sql "$PHOENIX_DB" <<'SQL'
GRANT USAGE, CREATE ON SCHEMA public TO phoenix_app;
SQL

echo "Revoking default PUBLIC access to the '$APP_DB' database..."
# Every role, including phoenix_app, inherits CONNECT and TEMPORARY on all
# databases from PUBLIC by default. This is what keeps Phoenix out of the
# application data. Revoking ALL (not just CONNECT) also strips TEMPORARY,
# matching what is done for $PHOENIX_DB above.
run_sql "postgres" <<SQL
REVOKE ALL ON DATABASE "$APP_DB" FROM PUBLIC;
SQL

echo "Creating habit_app role..."
# The bot container authenticates as this role instead of the server admin, so
# a compromise of the bot image cannot alter the Alembic-managed schema or
# reach the Phoenix database. The admin credential is used only by
# scripts/run-migrations.sh.
run_sql "postgres" <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'habit_app') THEN
        CREATE ROLE habit_app LOGIN;
    END IF;
END
$$;
SQL

run_sql "postgres" --set habit_app_pw="$HABIT_APP_PASSWORD" <<'SQL'
ALTER ROLE habit_app WITH LOGIN PASSWORD :'habit_app_pw';
SQL

echo "Granting habit_app access to the '$APP_DB' database only..."
run_sql "postgres" <<SQL
GRANT CONNECT ON DATABASE "$APP_DB" TO habit_app;
SQL

# CRUD but no DDL: the tables are owned by the admin and created by Alembic, so
# habit_app can read and write rows but cannot DROP, ALTER or CREATE anything
# in the public schema. No CREATE is granted, and PostgreSQL 15+ no longer hands
# it to PUBLIC either; the verification block below proves that empirically
# rather than assuming it.
run_sql "$APP_DB" <<'SQL'
GRANT USAGE ON SCHEMA public TO habit_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO habit_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO habit_app;
SQL

echo "Setting default privileges for future tables..."
# ON ALL TABLES above only covers tables that exist right now. Without this,
# every table a later Alembic revision creates would be invisible to habit_app.
# The role named here must be the one Alembic connects as — the server admin.
run_sql "$APP_DB" <<SQL
ALTER DEFAULT PRIVILEGES FOR ROLE "$POSTGRES_USER" IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO habit_app;
ALTER DEFAULT PRIVILEGES FOR ROLE "$POSTGRES_USER" IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO habit_app;
SQL

echo "Creating mem0 schema and granting habit_app access..."
# mem0's pgvector store builds its own tables on first use and has no migration
# story, so it genuinely needs CREATE TABLE. Confining that DDL to a dedicated
# schema is what allows public to stay DDL-free. Settings.get_mem0_config()
# pins mem0's search_path to this schema.
#
# The schema is created by the admin (not AUTHORIZATION habit_app), so habit_app
# does not own it and cannot DROP or ALTER it. USAGE, CREATE is exactly what
# mem0's create_col() needs and nothing more. No ALTER DEFAULT PRIVILEGES is
# required: habit_app owns every table it creates here, and owners already hold
# all privileges on their own objects.
run_sql "$APP_DB" <<'SQL'
CREATE SCHEMA IF NOT EXISTS mem0;
GRANT USAGE, CREATE ON SCHEMA mem0 TO habit_app;
SQL

echo "Verifying isolation..."
if PGPASSWORD="$PHOENIX_DB_PASSWORD" psql --host "$POSTGRES_HOST" --port 5432 \
    --username "phoenix_app" --dbname "$APP_DB" --no-psqlrc --quiet \
    --command "SELECT 1;" &> /dev/null; then
    echo -e "${RED}ERROR: phoenix_app can still connect to $APP_DB${NC}"
    exit 1
fi
echo -e "${GREEN}✓ phoenix_app is denied access to $APP_DB${NC}"

if ! PGPASSWORD="$PHOENIX_DB_PASSWORD" psql --host "$POSTGRES_HOST" --port 5432 \
    --username "phoenix_app" --dbname "$PHOENIX_DB" --no-psqlrc --quiet \
    --command "SELECT 1;" &> /dev/null; then
    echo -e "${RED}ERROR: phoenix_app cannot connect to $PHOENIX_DB${NC}"
    exit 1
fi
echo -e "${GREEN}✓ phoenix_app can connect to $PHOENIX_DB${NC}"

echo "Verifying habit_app isolation..."
if PGPASSWORD="$HABIT_APP_PASSWORD" psql --host "$POSTGRES_HOST" --port 5432 \
    --username "habit_app" --dbname "$PHOENIX_DB" --no-psqlrc --quiet \
    --command "SELECT 1;" &> /dev/null; then
    echo -e "${RED}ERROR: habit_app can connect to $PHOENIX_DB${NC}"
    exit 1
fi
echo -e "${GREEN}✓ habit_app is denied access to $PHOENIX_DB${NC}"

if ! PGPASSWORD="$HABIT_APP_PASSWORD" psql --host "$POSTGRES_HOST" --port 5432 \
    --username "habit_app" --dbname "$APP_DB" --no-psqlrc --quiet \
    --command "SELECT 1;" &> /dev/null; then
    echo -e "${RED}ERROR: habit_app cannot connect to $APP_DB${NC}"
    exit 1
fi
echo -e "${GREEN}✓ habit_app can connect to $APP_DB${NC}"

# A successful CREATE TABLE here would mean the bot container could rewrite the
# Alembic-managed schema, so treat it as a hard failure rather than a warning.
#
# This is the only automated check of that guarantee, so the failure has to be
# the *right* failure: discarding stderr would let a network blip, a wrong host
# or a bad password print the green checkmark below. Keep the output and require
# "permission denied" before calling it a pass.
if probe_output=$(PGPASSWORD="$HABIT_APP_PASSWORD" psql --host "$POSTGRES_HOST" --port 5432 \
    --username "habit_app" --dbname "$APP_DB" --no-psqlrc --quiet \
    --command "CREATE TABLE public.habit_app_ddl_probe (id int);" 2>&1); then
    echo -e "${RED}ERROR: habit_app can create tables in the public schema${NC}"
    run_sql "$APP_DB" --command "DROP TABLE IF EXISTS public.habit_app_ddl_probe;"
    exit 1
fi

if ! grep -qi "permission denied" <<< "$probe_output"; then
    echo -e "${RED}ERROR: the DDL probe failed for the wrong reason - privileges are unverified${NC}"
    echo "$probe_output"
    exit 1
fi
echo -e "${GREEN}✓ habit_app cannot create tables in the public schema${NC}"

echo ""
echo -e "${GREEN}✓ Role bootstrap complete${NC}"
