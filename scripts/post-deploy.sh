#!/bin/bash
set -e

echo "========================================="
echo "AI Habit Tracker - Post-Deployment Configuration"
echo "========================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Check Azure CLI login
if ! az account show &> /dev/null; then
    echo -e "${RED}ERROR: Not logged in to Azure CLI. Run 'az login' first.${NC}"
    exit 1
fi

# Resource group selected by the operator.
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-}"
if [ -z "$RESOURCE_GROUP" ]; then
    echo -e "${RED}ERROR: AZURE_RESOURCE_GROUP is required.${NC}"
    exit 1
fi

echo ""
echo "Retrieving deployment information from Azure..."
echo ""

# Find Key Vault (starts with name prefix)
KV_NAME=$(az keyvault list --resource-group "$RESOURCE_GROUP" --query "[0].name" -o tsv 2>/dev/null)

# Find Phoenix Container App
PHOENIX_APP=$(az containerapp list --resource-group "$RESOURCE_GROUP" --query "[?contains(name, 'phoenix')].name | [0]" -o tsv 2>/dev/null)

# Find Web App
WEBAPP_NAME=$(az webapp list --resource-group "$RESOURCE_GROUP" --query "[0].name" -o tsv 2>/dev/null)

if [ -z "$KV_NAME" ]; then
    echo -e "${RED}ERROR: Could not find Key Vault in resource group $RESOURCE_GROUP${NC}"
    echo "Please run deploy.sh first to deploy the infrastructure."
    exit 1
fi

if [ -z "$PHOENIX_APP" ]; then
    echo -e "${YELLOW}WARNING: Phoenix not found. Skipping Phoenix configuration.${NC}"
    SKIP_PHOENIX=true
else
    # Get Phoenix URL
    PHOENIX_URL=$(az containerapp show --name "$PHOENIX_APP" --resource-group "$RESOURCE_GROUP" --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null)
    PHOENIX_URL="https://$PHOENIX_URL"
fi

echo -e "${GREEN}✓ Found Key Vault: $KV_NAME${NC}"
if [ "$SKIP_PHOENIX" != "true" ]; then
    echo -e "${GREEN}✓ Found Phoenix: $PHOENIX_URL${NC}"
fi
if [ -n "$WEBAPP_NAME" ]; then
    echo -e "${GREEN}✓ Found Web App: $WEBAPP_NAME${NC}"
fi
echo ""

# Ensure the current operator has Key Vault access. The Terragrunt module
# grants it via OPERATOR_OBJECT_IDS, but on first deploy that variable may
# not be set yet. Self-heal by granting the role if a probe read fails.
echo "Checking Key Vault access..."
if ! az keyvault secret show --vault-name "$KV_NAME" --name "phoenix-admin-password" --query "value" -o tsv &>/dev/null; then
    echo -e "${YELLOW}No Key Vault access. Granting Key Vault Secrets Officer to your account...${NC}"
    USER_OID=$(az ad signed-in-user show --query id -o tsv)
    KV_ID=$(az keyvault show --name "$KV_NAME" --query id -o tsv)
    az role assignment create \
        --assignee-object-id "$USER_OID" \
        --assignee-principal-type User \
        --role "Key Vault Secrets Officer" \
        --scope "$KV_ID" \
        --output none
    echo "Waiting for RBAC propagation..."
    sleep 30
    echo -e "${GREEN}✓ Key Vault access granted${NC}"
else
    echo -e "${GREEN}✓ Key Vault access confirmed${NC}"
fi
echo ""

if [ "$SKIP_PHOENIX" == "true" ]; then
    echo -e "${YELLOW}Phoenix not deployed. Skipping Phoenix configuration.${NC}"
    echo ""
else
    echo ""
    echo "========================================="
    echo "Step 1: Phoenix Initial Setup"
    echo "========================================="
    echo ""
    echo "Phoenix is deployed with authentication enabled."
    echo ""
    echo "To complete setup:"
    echo ""
    echo "1. Open Phoenix in your browser:"
    echo -e "   ${YELLOW}$PHOENIX_URL${NC}"
    echo ""
    echo "2. Log in with default admin credentials:"
    echo -e "   Username: ${YELLOW}admin@localhost${NC}"
    echo "   Password: (retrieve from Key Vault)"
    echo ""
    echo "Retrieving Phoenix admin password from Key Vault..."
    
    PHOENIX_ADMIN_PASSWORD=$(az keyvault secret show \
        --vault-name "$KV_NAME" \
        --name "phoenix-admin-password" \
        --query "value" -o tsv 2>/dev/null)
    
    if [ -z "$PHOENIX_ADMIN_PASSWORD" ]; then
        echo -e "${RED}ERROR: Could not retrieve phoenix-admin-password from Key Vault${NC}"
        exit 1
    fi
    
    echo ""
    echo -e "${GREEN}Phoenix Admin Credentials:${NC}"
    echo -e "  URL:      ${YELLOW}$PHOENIX_URL${NC}"
    echo -e "  Username: ${YELLOW}admin@localhost${NC}"
    echo -e "  Password: ${YELLOW}$PHOENIX_ADMIN_PASSWORD${NC}"
    echo ""
    
    read -p "Press Enter after you've logged into Phoenix and are ready to create an API key..."
    
    echo ""
    echo "========================================="
    echo "Step 2: Create Phoenix API Key"
    echo "========================================="
    echo ""
    echo "In the Phoenix UI:"
    echo "1. Navigate to Settings or API Keys section"
    echo "2. Create a new API key"
    echo "3. Copy the generated API key"
    echo ""
    
    read -p "Enter the Phoenix API key: " PHOENIX_API_KEY
    
    if [ -z "$PHOENIX_API_KEY" ]; then
        echo -e "${RED}ERROR: No API key provided${NC}"
        exit 1
    fi
    
    echo ""
    echo "Storing Phoenix API key in Key Vault..."
    
    az keyvault secret set \
        --vault-name "$KV_NAME" \
        --name "phoenix-api-key" \
        --value "$PHOENIX_API_KEY" \
        --output none

    if [ -n "$WEBAPP_NAME" ]; then
        echo "Web App picks up PHOENIX_API_KEY and ENABLE_TRACING from Terraform."
        echo "The KV secret was just updated; restarting the Web App to resolve it."
    fi
    
    echo -e "${GREEN}✓ Phoenix API key stored in Key Vault${NC}"
fi

echo ""
echo "========================================="
echo "Step 3: Restart Web App (if deployed)"
echo "========================================="
echo ""

if [ -n "$WEBAPP_NAME" ]; then
    echo "Restarting Web App to pick up new configuration..."
    az webapp restart \
        --name "$WEBAPP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --output none
    echo -e "${GREEN}✓ Web App restarted${NC}"
else
    echo -e "${YELLOW}Note: Web App not yet deployed.${NC}"
fi

echo ""
echo "========================================="
echo "Post-Deployment Configuration Complete"
echo "========================================="
echo ""

if [ "$SKIP_PHOENIX" != "true" ]; then
    echo -e "${GREEN}✓ Phoenix authentication configured${NC}"
    echo -e "${GREEN}✓ Phoenix API key stored in Key Vault${NC}"
    if [ -n "$WEBAPP_NAME" ]; then
        echo -e "${GREEN}✓ Authenticated tracing enabled on the Web App${NC}"
    fi
fi

if [ -n "$WEBAPP_NAME" ]; then
    echo -e "${GREEN}✓ Web App restarted${NC}"
fi

echo ""
echo "Deployment Summary:"
echo -e "  Resource Group: ${YELLOW}$RESOURCE_GROUP${NC}"
echo -e "  Key Vault:      ${YELLOW}$KV_NAME${NC}"

if [ "$SKIP_PHOENIX" != "true" ]; then
    echo -e "  Phoenix URL:    ${YELLOW}$PHOENIX_URL${NC}"
fi

if [ -n "$WEBAPP_NAME" ]; then
    WEBAPP_URL=$(az webapp show --name "$WEBAPP_NAME" --resource-group "$RESOURCE_GROUP" --query "defaultHostName" -o tsv 2>/dev/null)
    echo -e "  Web App URL:    ${YELLOW}https://$WEBAPP_URL${NC}"
fi

echo ""
echo "Your Telegram bot should now be running!"
echo ""
