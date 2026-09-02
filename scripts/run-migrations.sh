#!/bin/bash
set -e

echo "========================================="
echo "Running Database Migrations"
echo "========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Alembic will automatically load DATABASE_URL from .env file if it exists
# If running in Azure/CI, DATABASE_URL should be set as environment variable

# Check if DATABASE_URL is set (either from .env or environment)
if [ -z "$DATABASE_URL" ]; then
    echo -e "${RED}ERROR: DATABASE_URL environment variable is not set${NC}"
    echo ""
    echo "For local development:"
    echo "  Create a .env file with: DATABASE_URL=postgresql://user:pass@host:5432/dbname"
    echo ""
    echo "For deployment:"
    echo "  Set DATABASE_URL environment variable before running this script"
    exit 1
fi

echo -e "${GREEN}✓ DATABASE_URL is set${NC}"

# psycopg2-binary bundles its own libpq/OpenSSL and does not honour
# PGSSLROOTCERT=system. Default to the Debian/Ubuntu CA bundle when the caller
# has not already set the variable.
export PGSSLROOTCERT="${PGSSLROOTCERT:-/etc/ssl/certs/ca-certificates.crt}"

echo ""

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Change to project root (where alembic.ini is located)
cd "$PROJECT_ROOT"

# Check if alembic is available
if ! command -v alembic &> /dev/null; then
    echo -e "${YELLOW}Installing dependencies (uv sync)...${NC}"
    uv sync
fi

echo "Running Alembic migrations..."
echo "DATABASE_URL: ${DATABASE_URL:0:20}..."
echo ""

# Explicitly pass DATABASE_URL to uv run
DATABASE_URL="$DATABASE_URL" uv run alembic upgrade head

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ Migrations completed successfully${NC}"
else
    echo ""
    echo -e "${RED}ERROR: Migrations failed${NC}"
    exit 1
fi
