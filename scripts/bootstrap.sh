#!/bin/bash
set -e

echo "========================================="
echo "Bootstrap: Terragrunt Remote State Backend"
echo "========================================="
echo ""
echo "This script creates Azure Storage for Terragrunt state management."
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration file path
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="$PROJECT_ROOT/.tfstate-config"

# Default configuration
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-}"
CONTAINER_NAME="tofu-state"
LOCATION="swedencentral"
SKU="Standard_LRS"
NAME_PREFIX="st"

# Check prerequisites
echo "Checking prerequisites..."

if [ -z "$RESOURCE_GROUP" ]; then
    echo -e "${RED}ERROR: AZURE_RESOURCE_GROUP is required.${NC}"
    echo "Set it to the resource group that should hold the state storage account."
    exit 1
fi

if ! command -v az &> /dev/null; then
    echo -e "${RED}ERROR: Azure CLI (az) not found. Please install it first.${NC}"
    echo "Install guide: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli"
    exit 1
fi

echo -e "${GREEN}✓ Azure CLI found${NC}"

# Check Azure login
echo "Verifying Azure CLI authentication..."
if ! az account show &> /dev/null; then
    echo -e "${RED}ERROR: Not logged in to Azure CLI.${NC}"
    echo "Please run: az login"
    exit 1
fi

SUBSCRIPTION=$(az account show --query name -o tsv)
echo -e "${GREEN}✓ Logged in to Azure subscription: $SUBSCRIPTION${NC}"

# Check resource group exists
echo "Verifying resource group exists..."
if ! az group show --name "$RESOURCE_GROUP" &> /dev/null; then
    echo -e "${RED}ERROR: Resource group '$RESOURCE_GROUP' not found.${NC}"
    echo "Please create it first:"
    echo "  az group create --name $RESOURCE_GROUP --location $LOCATION"
    exit 1
fi

echo -e "${GREEN}✓ Resource group '$RESOURCE_GROUP' exists${NC}"

# Check if config file exists and has a storage account name
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
    if [ -n "$TFSTATE_STORAGE_ACCOUNT" ]; then
        echo ""
        echo "Found existing configuration: $TFSTATE_STORAGE_ACCOUNT"
        
        # Check if storage account exists
        if az storage account show --name "$TFSTATE_STORAGE_ACCOUNT" --resource-group "${TFSTATE_RESOURCE_GROUP:-$RESOURCE_GROUP}" &> /dev/null; then
            echo -e "${YELLOW}⚠️  Storage account '$TFSTATE_STORAGE_ACCOUNT' already exists${NC}"
            echo ""
            echo "This is fine! The bootstrap has already been completed."
            echo "Terragrunt can use this storage account for remote state."
            echo ""
            
            # Verify container exists
            if az storage container show --name "${TFSTATE_CONTAINER:-$CONTAINER_NAME}" --account-name "$TFSTATE_STORAGE_ACCOUNT" &> /dev/null 2>&1; then
                echo -e "${GREEN}✓ Container '${TFSTATE_CONTAINER:-$CONTAINER_NAME}' exists${NC}"
            else
                echo -e "${YELLOW}⚠️  Container '${TFSTATE_CONTAINER:-$CONTAINER_NAME}' not found. Creating it...${NC}"
                az storage container create \
                    --name "${TFSTATE_CONTAINER:-$CONTAINER_NAME}" \
                    --account-name "$TFSTATE_STORAGE_ACCOUNT" \
                    --public-access off \
                    --output none
                echo -e "${GREEN}✓ Container '${TFSTATE_CONTAINER:-$CONTAINER_NAME}' created${NC}"
            fi
            
            echo ""
            echo "========================================="
            echo "Bootstrap Status: Already Complete"
            echo "========================================="
            echo "  Storage Account: $TFSTATE_STORAGE_ACCOUNT"
            echo "  Container: ${TFSTATE_CONTAINER:-$CONTAINER_NAME}"
            echo "  Location: ${TFSTATE_LOCATION:-$LOCATION}"
            echo ""
            echo "Next step: Run './scripts/deploy.sh' to deploy infrastructure"
            echo ""
            exit 0
        else
            echo -e "${YELLOW}⚠️  Configured storage account '$TFSTATE_STORAGE_ACCOUNT' not found${NC}"
            echo "It may have been deleted. Will create a new one."
        fi
    fi
fi

# Generate unique storage account name with prefix
# Format: st<8-char-random>, lowercase alphanumeric
echo ""
echo "Generating unique storage account name..."
attempts=0
while true; do
    attempts=$((attempts + 1))
    RANDOM_SUFFIX=$(head /dev/urandom | tr -dc 'a-z0-9' | head -c 8)
    STORAGE_ACCOUNT="${NAME_PREFIX}${RANDOM_SUFFIX}"

    echo "Checking name availability: $STORAGE_ACCOUNT (attempt $attempts)"
    NAME_AVAILABLE=$(az storage account check-name --name "$STORAGE_ACCOUNT" --query "nameAvailable" -o tsv)

    if [ "$NAME_AVAILABLE" == "true" ]; then
        echo -e "${GREEN}✓ Storage account name is available${NC}"
        break
    fi

    if [ $attempts -ge 5 ]; then
        echo -e "${RED}ERROR: Could not find an available storage account name after $attempts attempts. Try again.${NC}"
        exit 2
    fi
done

# Create storage account
echo ""
echo "========================================="
echo "Creating Azure Storage Account"
echo "========================================="
echo ""
echo "Configuration:"
echo "  Resource Group: $RESOURCE_GROUP"
echo "  Storage Account: $STORAGE_ACCOUNT"
echo "  Location: $LOCATION"
echo "  SKU: $SKU (cheapest option)"
echo "  Container: $CONTAINER_NAME"
echo ""

echo "Creating storage account '$STORAGE_ACCOUNT'..."
az storage account create \
    --name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku "$SKU" \
    --kind StorageV2 \
    --https-only true \
    --min-tls-version TLS1_2 \
    --allow-blob-public-access false \
    --tags ManagedBy=bootstrap Purpose=terragrunt-state Environment=live Project=project Repository=repo \
    --output none

if [ $? -ne 0 ]; then
    echo -e "${RED}ERROR: Failed to create storage account${NC}"
    exit 2
fi

echo -e "${GREEN}✓ Storage account created${NC}"

# Enable blob versioning
echo "Enabling blob versioning..."
az storage account blob-service-properties update \
    --account-name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --enable-versioning true \
    --output none

echo -e "${GREEN}✓ Blob versioning enabled${NC}"

# Create container
echo "Creating blob container '$CONTAINER_NAME'..."
az storage container create \
    --name "$CONTAINER_NAME" \
    --account-name "$STORAGE_ACCOUNT" \
    --public-access off \
    --output none

if [ $? -ne 0 ]; then
    echo -e "${RED}ERROR: Failed to create container${NC}"
    exit 2
fi

echo -e "${GREEN}✓ Container created${NC}"

# Save configuration to file
echo ""
echo "Saving configuration to $CONFIG_FILE..."
cat > "$CONFIG_FILE" << EOF
# Terragrunt Remote State Configuration
# This file is auto-generated by bootstrap.sh
# DO NOT edit manually - it will be overwritten

# Storage account name for Terragrunt remote state
# Must be globally unique across all of Azure
TFSTATE_STORAGE_ACCOUNT="$STORAGE_ACCOUNT"

# Container name for state files
TFSTATE_CONTAINER="$CONTAINER_NAME"

# Resource group containing the storage account
TFSTATE_RESOURCE_GROUP="$RESOURCE_GROUP"

# Location for the storage account
TFSTATE_LOCATION="$LOCATION"
EOF

echo -e "${GREEN}✓ Configuration saved${NC}"

# Success message
echo ""
echo "========================================="
echo "Bootstrap Complete!"
echo "========================================="
echo ""
echo -e "${GREEN}✓ Azure Storage for Terragrunt remote state is ready${NC}"
echo ""
echo "Resources created:"
echo "  Storage Account: $STORAGE_ACCOUNT"
echo "  Container: $CONTAINER_NAME"
echo "  Location: $LOCATION"
echo "  SKU: $SKU"
echo "  Versioning: Enabled"
echo "  Encryption: Enabled (Azure default + PBKDF2 client-side)"
echo ""
echo "Configuration saved to:"
echo "  $CONFIG_FILE"
echo ""
echo "Special tags applied:"
echo "  ManagedBy: bootstrap"
echo "  Purpose: terragrunt-state"
echo ""
echo "========================================="
echo "Next Steps"
echo "========================================="
echo ""
echo "1. Deploy infrastructure:"
echo -e "   ${YELLOW}./scripts/deploy.sh${NC}"
echo ""
echo "2. The deploy script will automatically use this storage account"
echo ""
echo "Note: Keep the PBKDF2 passphrase secure - you'll need it for all Terragrunt operations!"
echo ""
