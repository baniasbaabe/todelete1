#!/usr/bin/env bash
set -euo pipefail

# Creates the small Azure bootstrap layer that cannot live in the main
# Terragrunt stack: the resource group, remote-state storage, and the
# GitHub Actions OIDC identity.

repository="${1:-${GITHUB_REPOSITORY:-}}"
resource_group="${2:-${AZURE_RESOURCE_GROUP:-}}"
location="${AZURE_LOCATION:-swedencentral}"
github_environment="${GITHUB_ENVIRONMENT:-production}"

if [[ ! "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    echo "Usage: $0 <github-owner/repository> <azure-resource-group>" >&2
    echo "Example: $0 octocat/ai-habit-bot my-habit-bot" >&2
    exit 1
fi

if [[ -z "$resource_group" ]]; then
    echo "Pass a resource-group name as the second argument or set AZURE_RESOURCE_GROUP." >&2
    exit 1
fi

if ! command -v az >/dev/null 2>&1; then
    echo "Azure CLI is required: https://learn.microsoft.com/cli/azure/install-azure-cli" >&2
    exit 1
fi

if ! az account show >/dev/null 2>&1; then
    echo "Log in first with: az login" >&2
    exit 1
fi

subscription_id=$(az account show --query id -o tsv)
tenant_id=$(az account show --query tenantId -o tsv)
repository_slug=$(tr '/_' '--' <<< "$repository" | tr '[:upper:]' '[:lower:]')
application_name="github-${repository_slug}-deploy"
federated_name="github-${github_environment}"

echo "Registering Azure resource providers used by the project..."
providers=(
    Microsoft.App
    Microsoft.ContainerRegistry
    Microsoft.DBforPostgreSQL
    Microsoft.Insights
    Microsoft.KeyVault
    Microsoft.OperationalInsights
    Microsoft.Storage
    Microsoft.Web
)
for provider in "${providers[@]}"; do
    az provider register --namespace "$provider" --wait
done

echo "Creating resource group '$resource_group' when needed..."
az group create --name "$resource_group" --location "$location" --output none

application_id=$(az ad app list --display-name "$application_name" --query '[0].appId' -o tsv)
if [[ -z "$application_id" ]]; then
    echo "Creating Microsoft Entra application '$application_name'..."
    application_id=$(az ad app create --display-name "$application_name" --query appId -o tsv)
else
    echo "Using existing Microsoft Entra application '$application_name'."
fi

service_principal_id=$(az ad sp show --id "$application_id" --query id -o tsv 2>/dev/null || true)
if [[ -z "$service_principal_id" ]]; then
    echo "Creating service principal..."
    service_principal_id=$(az ad sp create --id "$application_id" --query id -o tsv)
fi

scope="/subscriptions/${subscription_id}/resourceGroups/${resource_group}"
echo "Granting deployment permissions within '$resource_group'..."
az role assignment create \
    --assignee-object-id "$service_principal_id" \
    --assignee-principal-type ServicePrincipal \
    --role Contributor \
    --scope "$scope" \
    --output none
az role assignment create \
    --assignee-object-id "$service_principal_id" \
    --assignee-principal-type ServicePrincipal \
    --role "User Access Administrator" \
    --scope "$scope" \
    --output none

# GitHub OIDC tokens include numeric owner and repo IDs in the subject claim
# (e.g. repo:owner@123/repo@456:environment:production). Fetch them so the
# federated credential matches what GitHub Actions actually sends.
if ! command -v gh >/dev/null 2>&1; then
    echo "GitHub CLI (gh) is required: https://cli.github.com/" >&2
    exit 1
fi

owner="${repository%%/*}"
repo_name="${repository##*/}"
owner_id=$(gh api "users/${owner}" --jq '.id')
repo_id=$(gh api "repos/${repository}" --jq '.id')
oidc_subject="repo:${owner}@${owner_id}/${repo_name}@${repo_id}:environment:${github_environment}"

credential_count=$(az ad app federated-credential list \
    --id "$application_id" \
    --query "[?name=='${federated_name}'] | length(@)" \
    -o tsv)

if [[ "$credential_count" == "0" ]]; then
    credential_file=$(mktemp)
    trap 'rm -f "$credential_file"' EXIT
    cat > "$credential_file" <<EOF
{
  "name": "${federated_name}",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "${oidc_subject}",
  "description": "GitHub Actions ${github_environment} environment",
  "audiences": ["api://AzureADTokenExchange"]
}
EOF
    echo "Creating GitHub Actions federated credential..."
    az ad app federated-credential create \
        --id "$application_id" \
        --parameters "$credential_file" \
        --output none
else
    echo "GitHub Actions federated credential already exists."
    echo "Updating subject to match current GitHub OIDC format..."
    credential_id=$(az ad app federated-credential list \
        --id "$application_id" \
        --query "[?name=='${federated_name}'].id | [0]" \
        -o tsv)
    update_file=$(mktemp)
    trap 'rm -f "$update_file"' EXIT
    cat > "$update_file" <<EOF
{
  "subject": "${oidc_subject}"
}
EOF
    az ad app federated-credential update \
        --id "$application_id" \
        --federated-credential-id "$credential_id" \
        --parameters "$update_file" \
        --output none
fi

export AZURE_RESOURCE_GROUP="$resource_group"
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# Invoke via `bash` so a missing +x bit on bootstrap.sh (which would otherwise
# fail with "Permission denied") never halts the bootstrap mid-way. The Azure
# identity pieces created before this point are idempotent, so re-running the
# whole script after fixing permissions resumes cleanly.
bash "$script_dir/bootstrap.sh"

project_root=$(cd "$script_dir/.." && pwd)
# shellcheck disable=SC1091
source "$project_root/.tfstate-config"

echo ""
echo "Azure bootstrap complete. Configure the GitHub '$github_environment' environment with:"
echo ""
echo "Secrets:"
echo "  AZURE_CLIENT_ID=$application_id"
echo "  AZURE_TENANT_ID=$tenant_id"
echo "  AZURE_SUBSCRIPTION_ID=$subscription_id"
echo "  PBKDF2_PASSPHRASE=<store one strong passphrase>"
echo "  TELEGRAM_BOT_TOKEN=<from BotFather>"
echo "  GROQ_API_KEY=<from Groq; required for all LLM calls>"
echo "  JINA_API_KEY=<from Jina; required for LangChain embeddings>"
echo ""
echo "Variables:"
echo "  AZURE_RESOURCE_GROUP=$resource_group"
echo "  TFSTATE_STORAGE_ACCOUNT=$TFSTATE_STORAGE_ACCOUNT"
echo "  TFSTATE_CONTAINER=${TFSTATE_CONTAINER:-tofu-state}"
echo "  LLM_MODEL=qwen/qwen3.6-27b"
echo "  LLM_TEMPERATURE=0.2"
echo "  JINA_EMBEDDING_MODEL=jina-embeddings-v5-text-small"
echo "  MEM0_EMBEDDING_DIMS=1024"
echo "  MEM0_COLLECTION_NAME=memories"
echo ""
echo "Then run the Deploy workflow manually with both options enabled."
