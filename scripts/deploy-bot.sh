#!/bin/bash
set -e

echo "========================================="
echo "AI Habit Tracker - Docker Build & Deploy"
echo "========================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    echo -e "${RED}ERROR: Docker not found. Please install Docker first.${NC}"
    exit 1
fi

if ! command -v az &> /dev/null; then
    echo -e "${RED}ERROR: Azure CLI (az) not found${NC}"
    exit 1
fi

if ! az account show &> /dev/null; then
    echo -e "${RED}ERROR: Not logged in to Azure CLI. Run 'az login' first.${NC}"
    exit 1
fi

# Needed by run-migrations.sh below; the bot container cannot migrate itself.
if ! command -v uv &> /dev/null; then
    echo -e "${RED}ERROR: uv not found. It is required to run Alembic migrations.${NC}"
    exit 1
fi

# Get ACR and Web App information from Azure
echo "Retrieving deployment information from Azure..."

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-}"
if [ -z "$RESOURCE_GROUP" ]; then
    echo -e "${RED}ERROR: AZURE_RESOURCE_GROUP is required.${NC}"
    exit 1
fi

# Find ACR
ACR_NAME=$(az acr list --resource-group "$RESOURCE_GROUP" --query "[0].name" -o tsv 2>/dev/null)

if [ -z "$ACR_NAME" ]; then
    echo -e "${RED}ERROR: Azure Container Registry not found in resource group $RESOURCE_GROUP${NC}"
    echo "Please run ./scripts/deploy.sh first to deploy the infrastructure."
    exit 1
fi

# Get ACR login server
ACR_LOGIN=$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query "loginServer" -o tsv 2>/dev/null)

# Find Web App
WEBAPP_NAME=$(az webapp list --resource-group "$RESOURCE_GROUP" --query "[0].name" -o tsv 2>/dev/null)

if [ -z "$WEBAPP_NAME" ]; then
    echo -e "${RED}ERROR: Web App not found in resource group $RESOURCE_GROUP${NC}"
    echo "Please run ./scripts/deploy.sh first to deploy the infrastructure."
    exit 1
fi

echo -e "${GREEN}✓ Found ACR: $ACR_NAME${NC}"
echo -e "  Login Server: $ACR_LOGIN"
echo -e "${GREEN}✓ Found Web App: $WEBAPP_NAME${NC}"

# Set image details
IMAGE_NAME="habit-tracker-bot"
IMAGE_TAG="${1:-latest}"
FULL_IMAGE_NAME="${ACR_LOGIN}/${IMAGE_NAME}:${IMAGE_TAG}"

echo ""
echo "========================================="
echo "Step 1: Running Database Migrations"
echo "========================================="

# The container no longer migrates on startup: it authenticates as habit_app,
# which has no DDL rights, and scripts/startup.sh only *checks* the revision and
# refuses to start when the schema is behind. So this fast path has to advance
# the schema itself with the admin credential, in the same order deploy.sh uses
# (Phase 3.5 migrations, then Phase 5 web app). Running it first also means a
# failure costs nothing: no image has been built or pushed yet.

PG_SERVER=$(az postgres flexible-server list --resource-group "$RESOURCE_GROUP" \
    --query "[0].name" -o tsv 2>/dev/null)

if [ -z "$PG_SERVER" ]; then
    echo -e "${RED}ERROR: PostgreSQL flexible server not found in resource group $RESOURCE_GROUP${NC}"
    echo "Please run ./scripts/deploy.sh first to deploy the infrastructure."
    exit 1
fi

POSTGRES_HOST=$(az postgres flexible-server show --resource-group "$RESOURCE_GROUP" \
    --name "$PG_SERVER" --query "fullyQualifiedDomainName" -o tsv)
POSTGRES_USER=$(az postgres flexible-server show --resource-group "$RESOURCE_GROUP" \
    --name "$PG_SERVER" --query "administratorLogin" -o tsv)

KV_NAME=$(az keyvault list --resource-group "$RESOURCE_GROUP" \
    --query "[0].name" -o tsv 2>/dev/null)

if [ -z "$KV_NAME" ]; then
    echo -e "${RED}ERROR: Key Vault not found in resource group $RESOURCE_GROUP${NC}"
    exit 1
fi

echo "Retrieving PostgreSQL admin password from Key Vault '$KV_NAME'..."
if ! POSTGRES_PASSWORD=$(az keyvault secret show --vault-name "$KV_NAME" \
    --name "postgres-admin-password" --query value -o tsv 2>&1); then
    echo -e "${RED}ERROR: could not read 'postgres-admin-password' from Key Vault '$KV_NAME'${NC}"
    echo "$POSTGRES_PASSWORD"
    echo "Your account needs the 'Key Vault Secrets User' role on that vault."
    exit 1
fi

# The habit_tracker database name is fixed in infra/modules/postgres/main.tf.
# TLS comes from PGSSLMODE, not an sslmode query parameter: verify-full
# authenticates the server certificate and hostname, sslmode=require would not.
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:5432/habit_tracker"
export PGSSLMODE=verify-full
# psycopg2-binary bundles its own libpq and does not support PGSSLROOTCERT=system.
# Use the explicit CA bundle path; fall back to system for macOS / other distros.
if [ -f "/etc/ssl/certs/ca-certificates.crt" ]; then
    export PGSSLROOTCERT="/etc/ssl/certs/ca-certificates.crt"
elif [ -f "/etc/pki/tls/certs/ca-bundle.crt" ]; then
    export PGSSLROOTCERT="/etc/pki/tls/certs/ca-bundle.crt"
else
    export PGSSLROOTCERT=system
fi

if ! "$SCRIPT_DIR/run-migrations.sh"; then
    echo ""
    echo -e "${RED}ERROR: Migrations failed - aborting before anything is deployed.${NC}"
    echo "Most likely this machine's public IP is not allowlisted on the server."
    echo "Set DEPLOYER_IP and apply infra/live/postgres-firewall-deployer, or run"
    echo "./scripts/deploy.sh, then retry."
    exit 1
fi

unset DATABASE_URL POSTGRES_PASSWORD

echo ""
echo "========================================="
echo "Step 2: Building Docker Image"
echo "========================================="

# Change to project root for Docker build
cd "$PROJECT_ROOT"

echo "Building image: $FULL_IMAGE_NAME"
echo "(This may take a few minutes...)"

docker build -t "$FULL_IMAGE_NAME" .

echo -e "${GREEN}✓ Docker image built successfully${NC}"

echo ""
echo "========================================="
echo "Step 3: Logging in to Azure Container Registry"
echo "========================================="

echo "Logging in to ACR: $ACR_NAME"

az acr login --name "$ACR_NAME"

echo -e "${GREEN}✓ Logged in to ACR${NC}"

echo ""
echo "========================================="
echo "Step 4: Pushing Image to ACR"
echo "========================================="

echo "Pushing image: $FULL_IMAGE_NAME"
echo "(This may take a few minutes...)"

docker push "$FULL_IMAGE_NAME"

echo -e "${GREEN}✓ Image pushed to ACR successfully${NC}"

echo ""
echo "========================================="
echo "Step 5: Restarting Web App"
echo "========================================="

echo "Restarting Web App to pull new image..."

az webapp restart \
    --name "$WEBAPP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --output none

echo -e "${GREEN}✓ Web App restarted${NC}"

# Wait a few seconds for restart
sleep 5

echo ""
echo "========================================="
echo "Step 6: Verifying Deployment"
echo "========================================="

WEBAPP_STATE=$(az webapp show \
    --name "$WEBAPP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "state" -o tsv)

echo "Web App state: $WEBAPP_STATE"

if [ "$WEBAPP_STATE" = "Running" ]; then
    echo -e "${GREEN}✓ Web App is running${NC}"
else
    echo -e "${YELLOW}⚠ Web App state: $WEBAPP_STATE${NC}"
fi

echo ""
echo "========================================="
echo "Deployment Complete"
echo "========================================="
echo ""
echo "Docker image deployed:"
echo "  Image: $FULL_IMAGE_NAME"
echo "  ACR: $ACR_LOGIN"
echo "  Web App: $WEBAPP_NAME"
echo ""
echo "Useful commands:"
echo ""
echo "1. View live logs:"
echo -e "   ${YELLOW}az webapp log tail --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP${NC}"
echo ""
echo "2. Check container logs:"
echo -e "   ${YELLOW}az webapp log show --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP${NC}"
echo ""
echo "3. List images in ACR:"
echo -e "   ${YELLOW}az acr repository show-tags --name $ACR_NAME --repository $IMAGE_NAME${NC}"
echo ""
echo "4. Restart the app:"
echo -e "   ${YELLOW}az webapp restart --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP${NC}"
echo ""
echo "5. Test Telegram bot:"
echo "   Open Telegram and send /start to your bot"
echo ""
echo -e "${GREEN}🚀 Bot is now live!${NC}"
echo ""
