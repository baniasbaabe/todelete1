#!/bin/bash
set -e

echo "========================================="
echo "AI Habit Tracker - Destroy Infrastructure"
echo "========================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Resource group selected by the operator.
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-}"
if [ -z "$RESOURCE_GROUP" ]; then
    echo -e "${RED}ERROR: AZURE_RESOURCE_GROUP is required.${NC}"
    exit 1
fi

# Load state config if present
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="$PROJECT_ROOT/.tfstate-config"

if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
fi

# Ensure Azure subscription context for azurerm provider
if ! az account show &> /dev/null; then
    echo -e "${RED}ERROR: Not logged in to Azure CLI.${NC}"
    echo "Please run: az login"
    exit 1
fi

SUBSCRIPTION=$(az account show --query name -o tsv)
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)
echo -e "${GREEN}✓ Logged in to Azure subscription: $SUBSCRIPTION (${SUBSCRIPTION_ID})${NC}"

# Export subscription ID for azurerm provider
# Note: We only export ARM_SUBSCRIPTION_ID, not ARM_TENANT_ID
export ARM_SUBSCRIPTION_ID="$SUBSCRIPTION_ID"

echo ""
echo -e "${RED}⚠️  WARNING: This will DELETE ALL Azure resources!${NC}"
echo ""
echo "This includes:"
echo "  - Web App (and all application data)"
echo "  - Phoenix Container App"
echo "  - PostgreSQL Flexible Server (ALL DATABASES AND DATA)"
echo "  - Key Vault (and all secrets)"
echo "  - Azure Container Registry (and all Docker images)"
echo "  - Log Analytics Workspace"
echo "  - App Service Plan"
echo ""
echo -e "${YELLOW}This action CANNOT be undone!${NC}"
echo ""

read -p "Type 'destroy' to confirm: " CONFIRM

if [ "$CONFIRM" != "destroy" ]; then
    echo "Destruction cancelled."
    exit 0
fi

echo ""
read -p "Are you ABSOLUTELY SURE? Type 'yes' to proceed: " CONFIRM2

if [ "$CONFIRM2" != "yes" ]; then
    echo "Destruction cancelled."
    exit 0
fi

# Prompt for state encryption passphrase
echo ""
echo -e "${YELLOW}Enter state encryption passphrase:${NC}"
read -sp "Passphrase: " PBKDF2_PASSPHRASE
echo ""
export PBKDF2_PASSPHRASE

if [ -z "$PBKDF2_PASSPHRASE" ]; then
    echo -e "${RED}ERROR: Passphrase cannot be empty${NC}"
    exit 1
fi

cd "$(dirname "$0")/../infra/live"

echo ""
echo "========================================="
echo "Destroying Resources (in reverse order)"
echo "========================================="

echo ""
echo "Phase 0: Destroying PostgreSQL workload firewall rules..."
# Must precede web-app and phoenix: this unit depends on their outputs.
cd postgres-firewall && terragrunt destroy -auto-approve && cd ..

echo ""
echo "Phase 1: Destroying Web App..."
cd web-app && terragrunt destroy -auto-approve && cd ..

echo ""
echo "Phase 2: Destroying Phoenix..."
cd phoenix && terragrunt destroy -auto-approve && cd ..

echo ""
echo "Phase 2.5: Destroying PostgreSQL deployer firewall rule..."
cd postgres-firewall-deployer && terragrunt destroy -auto-approve && cd ..

echo ""
echo "Phase 3: Destroying PostgreSQL..."
cd postgres && terragrunt destroy -auto-approve && cd ..

echo ""
echo "Phase 4: Destroying Key Vault..."
cd keyvault && terragrunt destroy -auto-approve && cd ..

echo ""
echo "Phase 5: Destroying Azure Container Registry..."
cd acr && terragrunt destroy -auto-approve && cd ..

echo ""
echo "Phase 5.5: Destroying Log Analytics Workspace..."
cd log-analytics && terragrunt destroy -auto-approve && cd ..

echo ""
echo "========================================="
echo "Phase 6: Bootstrap Storage Account"
echo "========================================="
echo ""
echo -e "${YELLOW}The storage account '${TFSTATE_STORAGE_ACCOUNT:-<unknown>}' contains Terragrunt state files.${NC}"
echo ""
echo "Options:"
echo "  1. Keep it (recommended if you plan to redeploy later)"
echo "  2. Delete it (removes all state history - cannot manage infra after this)"
echo ""
read -p "Delete bootstrap storage account? (yes/no): " CONFIRM_STORAGE

if [ "$CONFIRM_STORAGE" == "yes" ]; then
    echo ""
    if [ -z "$TFSTATE_STORAGE_ACCOUNT" ]; then
        echo -e "${RED}ERROR: TFSTATE_STORAGE_ACCOUNT is not set. Cannot delete storage account.${NC}"
    else
        echo "Deleting storage account '$TFSTATE_STORAGE_ACCOUNT'..."
        az storage account delete \
            --name "$TFSTATE_STORAGE_ACCOUNT" \
            --resource-group "${TFSTATE_RESOURCE_GROUP:-$RESOURCE_GROUP}" \
            --yes
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓ Bootstrap storage account deleted${NC}"
        else
            echo -e "${RED}✗ Failed to delete storage account${NC}"
        fi
    fi
else
    echo "Keeping bootstrap storage account."
    echo -e "${YELLOW}Note: You can manually delete it later if needed.${NC}"
fi

echo ""
echo "========================================="
echo "Destruction Complete"
echo "========================================="
echo ""
echo "✓ Destroyed Terragrunt resources:"
echo "  - Web App"
echo "  - Phoenix Container App"
echo "  - PostgreSQL Server"
echo "  - Key Vault"
echo "  - Azure Container Registry"
echo "  - Log Analytics Workspace"
echo ""

if [ "$CONFIRM_STORAGE" == "yes" ]; then
    echo "✓ Deleted bootstrap storage account"
else
    echo "⚠️  Bootstrap storage account still exists"
fi

echo ""
echo "Resource group '$RESOURCE_GROUP' still exists."
echo "To delete it, uncomment the code at the end of this script."
echo ""

# =============================================================================
# OPTIONAL: Resource Group Deletion
# =============================================================================
# 
# ⚠️  WARNING: Uncomment the code below ONLY if you want to delete the 
# selected resource group and ALL its contents.
#
# This will delete:
#   - The resource group itself
#   - ANY remaining resources not managed by Terragrunt
#   - ALL data, backups, and configurations
#
# This operation is IRREVERSIBLE and will wait for completion (synchronous).
#
# To enable resource group deletion, uncomment lines below:
# -----------------------------------------------------------------------------
#
# echo ""
# echo "========================================="
# echo "OPTIONAL: Resource Group Deletion"
# echo "========================================="
# echo ""
# echo -e "${RED}⚠️  FINAL WARNING: Delete ENTIRE resource group '$RESOURCE_GROUP'?${NC}"
# echo "This will delete ALL resources, including anything not managed by Terragrunt!"
# echo "This operation is PERMANENT and IRREVERSIBLE."
# echo ""
# read -p "Type 'DELETE-EVERYTHING' to confirm: " CONFIRM_RG
#
# if [ "$CONFIRM_RG" == "DELETE-EVERYTHING" ]; then
#     echo ""
#     echo "Deleting resource group '$RESOURCE_GROUP'..."
#     echo "This will take several minutes..."
#     az group delete --name "$RESOURCE_GROUP" --yes
#     
#     if [ $? -eq 0 ]; then
#         echo -e "${GREEN}✓ Resource group deleted${NC}"
#     else
#         echo -e "${RED}✗ Resource group deletion failed${NC}"
#         exit 1
#     fi
# else
#     echo "Resource group deletion cancelled."
# fi
