#!/bin/bash
set -e

echo "========================================="
echo "AI Habit Tracker - Full Deployment Script"
echo "========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-}"
if [ -z "$RESOURCE_GROUP" ]; then
    echo -e "${RED}ERROR: AZURE_RESOURCE_GROUP is required.${NC}"
    exit 1
fi

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v tofu &> /dev/null; then
    echo -e "${RED}ERROR: OpenTofu (tofu) not found. Please install it first.${NC}"
    exit 1
fi

if ! command -v terragrunt &> /dev/null; then
    echo -e "${RED}ERROR: Terragrunt not found. Please install it first.${NC}"
    exit 1
fi

if ! command -v az &> /dev/null; then
    echo -e "${RED}ERROR: Azure CLI (az) not found. Please install it first.${NC}"
    exit 1
fi

# Check Azure login
echo "Verifying Azure CLI login..."
if ! az account show &> /dev/null; then
    echo -e "${RED}ERROR: Not logged in to Azure CLI. Run 'az login' first.${NC}"
    exit 1
fi

SUBSCRIPTION=$(az account show --query name -o tsv)
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)
echo -e "${GREEN}✓ Logged in to Azure subscription: $SUBSCRIPTION (${SUBSCRIPTION_ID})${NC}"

# Export subscription ID for azurerm provider
# Note: We only export ARM_SUBSCRIPTION_ID, not ARM_TENANT_ID
# Setting both causes "Please specify only one of subscription and tenant" errors in the backend
export ARM_SUBSCRIPTION_ID="$SUBSCRIPTION_ID"

# Load Terragrunt state configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="$PROJECT_ROOT/.tfstate-config"

# Check if Terragrunt remote state backend exists
echo ""
echo "Checking Terragrunt remote state backend..."

# Check if config file exists and load it
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
    
    if [ -z "$TFSTATE_STORAGE_ACCOUNT" ]; then
        echo -e "${YELLOW}⚠️  Configuration file exists but storage account name is empty${NC}"
        NEED_BOOTSTRAP=true
    else
        # Check if configured storage account exists
        if az storage account show --name "$TFSTATE_STORAGE_ACCOUNT" --resource-group "${TFSTATE_RESOURCE_GROUP:-$RESOURCE_GROUP}" &> /dev/null; then
            echo -e "${GREEN}✓ Remote state backend exists: $TFSTATE_STORAGE_ACCOUNT${NC}"
            NEED_BOOTSTRAP=false
        else
            echo -e "${YELLOW}⚠️  Configured storage account '$TFSTATE_STORAGE_ACCOUNT' not found${NC}"
            NEED_BOOTSTRAP=true
        fi
    fi
else
    echo -e "${YELLOW}⚠️  No bootstrap configuration found${NC}"
    NEED_BOOTSTRAP=true
fi

if [ "$NEED_BOOTSTRAP" = true ]; then
    echo "Terragrunt requires a storage account for remote state management."
    echo ""
read -p "Bootstrap storage account now? (yes/no): " BOOTSTRAP_CONFIRM

if [ "$BOOTSTRAP_CONFIRM" == "yes" ]; then
    echo ""
    echo "Running bootstrap script..."
        "$SCRIPT_DIR/bootstrap.sh"
        if [ $? -ne 0 ]; then
            echo -e "${RED}ERROR: Bootstrap failed${NC}"
            exit 1
        fi
        echo -e "${GREEN}✓ Bootstrap completed successfully${NC}"
        
        # Reload configuration
        source "$CONFIG_FILE"
    else
        echo -e "${RED}ERROR: Cannot proceed without remote state storage${NC}"
        echo "Please run './scripts/bootstrap.sh' manually before deploying."
        exit 1
    fi
fi

# Export storage account and container for Terragrunt
export TF_VAR_tfstate_storage_account="$TFSTATE_STORAGE_ACCOUNT"
export TF_VAR_tfstate_container="${TFSTATE_CONTAINER:-tofu-state}"
export TF_VAR_tfstate_resource_group="${TFSTATE_RESOURCE_GROUP:-$RESOURCE_GROUP}"
export TFSTATE_STORAGE_ACCOUNT
export TFSTATE_CONTAINER="${TFSTATE_CONTAINER:-tofu-state}"

# Prompt for state encryption passphrase
echo ""
echo -e "${YELLOW}Terragrunt uses PBKDF2 encryption for remote state.${NC}"
echo -e "${YELLOW}This is configured in infra/root.hcl.${NC}"
echo ""
read -sp "Enter state encryption passphrase: " PBKDF2_PASSPHRASE
echo ""
export PBKDF2_PASSPHRASE

if [ -z "$PBKDF2_PASSPHRASE" ]; then
    echo -e "${RED}ERROR: Passphrase cannot be empty${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Passphrase set${NC}"

# Change to infrastructure directory
cd "$(dirname "$0")/../infra/live"

echo ""
echo "========================================="
echo "Phase 1: Deploying Azure Container Registry"
echo "========================================="
cd acr
terragrunt init
terragrunt apply -auto-approve
cd ..

echo ""
echo -e "${GREEN}✓ Azure Container Registry deployed successfully${NC}"

echo ""
echo "========================================="
echo "Phase 1.5: Deploying Log Analytics Workspace"
echo "========================================="
cd log-analytics
terragrunt init
terragrunt apply -auto-approve
cd ..

echo ""
echo -e "${GREEN}✓ Log Analytics Workspace deployed successfully${NC}"

echo ""
echo "========================================="
echo "Phase 2: Deploying Key Vault"
echo "========================================="
cd keyvault
terragrunt init
terragrunt apply -auto-approve
cd ..

echo ""
echo -e "${GREEN}✓ Key Vault deployed successfully${NC}"

echo ""
echo "========================================="
echo "Phase 3: Deploying PostgreSQL"
echo "========================================="
cd postgres
terragrunt init
terragrunt apply -auto-approve
cd ..

echo ""
echo -e "${GREEN}✓ PostgreSQL deployed successfully${NC}"

echo ""
echo "========================================="
echo "Phase 3.2: Opening PostgreSQL to this machine"
echo "========================================="

# The server has no firewall rules by default — not even the Azure-wide
# 0.0.0.0 rule, which would admit any VM in any tenant. Migrations and role
# bootstrap need this machine allowlisted explicitly.
if [ -z "${DEPLOYER_IP:-}" ]; then
    echo "DEPLOYER_IP not set, detecting public IP..."
    DEPLOYER_IP=$(curl -fsS --max-time 10 https://api.ipify.org)
    export DEPLOYER_IP
fi
echo "Allowlisting deployer IP: $DEPLOYER_IP"

cd postgres-firewall-deployer
terragrunt init
terragrunt apply -auto-approve
cd ..

echo ""
echo "========================================="
echo "Phase 3.4: Bootstrapping database roles"
echo "========================================="
"$SCRIPT_DIR/bootstrap-db-roles.sh"

cd "$PROJECT_ROOT/infra/live"

echo ""
echo "========================================="
echo "Phase 3.5: Running Database Migrations"
echo "========================================="

# Get PostgreSQL connection details from Terragrunt outputs
cd postgres
POSTGRES_HOST=$(terragrunt output -raw postgres_host)
POSTGRES_USER=$(terragrunt output -raw postgres_admin_user)
POSTGRES_DB=$(terragrunt output -raw habit_tracker_db_name)
cd ..

# Retrieve PostgreSQL password from Key Vault
cd keyvault
KV_NAME=$(terragrunt output -raw keyvault_name)
cd ..

echo "Retrieving PostgreSQL password from Key Vault..."
POSTGRES_PASSWORD=$(az keyvault secret show --vault-name "$KV_NAME" --name "postgres-admin-password" --query value -o tsv)

# Construct DATABASE_URL. TLS comes from PGSSLMODE rather than an sslmode
# query parameter: verify-full authenticates the server certificate and
# hostname, where sslmode=require would encrypt without verifying either.
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:5432/${POSTGRES_DB}"
export PGSSLMODE=verify-full

# Run migrations
"$SCRIPT_DIR/run-migrations.sh"

echo ""
echo -e "${GREEN}✓ Database migrations completed${NC}"

cd "$PROJECT_ROOT/infra/live"

echo ""
echo "========================================="
echo "Phase 4: Deploying Phoenix (Arize)"
echo "========================================="
cd phoenix
terragrunt init
terragrunt apply -auto-approve
cd ..

echo ""
echo -e "${GREEN}✓ Phoenix deployed successfully${NC}"

echo ""
echo "========================================="
echo "Phase 5: Deploying Web App"
echo "========================================="
cd web-app
terragrunt init
terragrunt apply -auto-approve
cd ..

echo ""
echo -e "${GREEN}✓ Web App deployed successfully${NC}"

echo ""
echo "========================================="
echo "Phase 6: Allowlisting workload egress IPs"
echo "========================================="
# Applied last: it needs the App Service and Container App egress addresses.
# Until this lands the bot crash-loops on its startup schema check (it cannot
# reach the database to read alembic_version) and Phoenix cannot reach its
# database either; both recover once the rules exist.
cd postgres-firewall
terragrunt init
terragrunt apply -auto-approve
cd ..

echo ""
echo -e "${GREEN}✓ PostgreSQL firewall configured${NC}"

# Get output values
echo ""
echo "========================================="
echo "Deployment Summary"
echo "========================================="

cd acr
ACR_NAME=$(terragrunt output -raw acr_name 2>/dev/null || echo "N/A")
ACR_LOGIN=$(terragrunt output -raw acr_login_server 2>/dev/null || echo "N/A")
cd ../keyvault
KV_NAME=$(terragrunt output -raw keyvault_name 2>/dev/null || echo "N/A")
cd ../postgres
PG_FQDN=$(terragrunt output -raw postgres_fqdn 2>/dev/null || echo "N/A")
cd ../phoenix
PHOENIX_URL=$(terragrunt output -raw phoenix_url 2>/dev/null || echo "N/A")
cd ../web-app
WEBAPP_NAME=$(terragrunt output -raw web_app_name 2>/dev/null || echo "N/A")
WEBAPP_URL=$(terragrunt output -raw web_app_url 2>/dev/null || echo "N/A")
cd ../..

echo ""
echo -e "${GREEN}Infrastructure deployed successfully!${NC}"
echo ""
echo "Resources created:"
echo "  ACR Name:        $ACR_NAME"
echo "  ACR Login:       $ACR_LOGIN"
echo "  Key Vault:       $KV_NAME"
echo "  PostgreSQL:      $PG_FQDN"
echo "  Phoenix URL:     $PHOENIX_URL"
echo "  Web App Name:    $WEBAPP_NAME"
echo "  Web App URL:     $WEBAPP_URL"
echo ""
echo "========================================="
echo "Next Steps"
echo "========================================="
echo ""
echo "1. Run post-deployment configuration:"
echo -e "   ${YELLOW}./scripts/post-deploy.sh${NC}"
echo ""
echo "2. Deploy application code:"
echo -e "   ${YELLOW}./scripts/deploy-bot.sh${NC}"
echo ""
echo "3. Access Phoenix dashboard:"
echo -e "   URL: ${YELLOW}$PHOENIX_URL${NC}"
echo -e "   User: ${YELLOW}admin@localhost${NC}"
echo "   Password: Retrieve from Key Vault secret 'phoenix-admin-password'"
echo ""
echo "4. View bot logs:"
echo -e "   ${YELLOW}az webapp log tail --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP${NC}"
echo ""
