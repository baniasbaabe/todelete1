# Azure Deployment Guide

## Prerequisites

Install these tools before starting:

- [`az`](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) — Azure CLI
- [`tofu`](https://opentofu.org/docs/intro/install/) — OpenTofu (open-source Terraform)
- [`terragrunt`](https://terragrunt.gruntwork.io/docs/getting-started/install/) — Terragrunt wrapper
- [`docker`](https://docs.docker.com/engine/install/) — to build and push the container image
- [`gh`](https://cli.github.com/) — GitHub CLI (used by bootstrap to fetch repo/owner IDs for OIDC)
- [`psql`](https://www.postgresql.org/download/) — used by `bootstrap-db-roles.sh`
- [`uv`](https://docs.astral.sh/uv/) — Python package manager (already required for local dev)
- An Azure subscription with permission to create resource groups and Microsoft Entra applications
- A GitHub repository with a `production` environment

---

## Phase 0 — One-time bootstrap

Run once per environment. Creates the Azure identity, resource group, and remote-state storage that every subsequent step depends on.

```bash
az login
az account set --subscription "<subscription ID or name>"
./scripts/bootstrap-azure-github.sh <owner>/<repository> <resource-group>
```

The script:
1. Creates the resource group and registers required Azure resource providers
2. Creates a Microsoft Entra app and service principal with Contributor + User Access Admin roles
3. Creates an OIDC federated credential so GitHub Actions can authenticate without a client secret
4. Creates a Storage Account and blob container for Terragrunt remote state
5. Prints all GitHub secrets and variables you need to add

### Add to GitHub → Settings → Environments → `production`

**Secrets** (sensitive — stored encrypted):

| Name | Where to get it |
|------|-----------------|
| `AZURE_CLIENT_ID` | printed by bootstrap |
| `AZURE_TENANT_ID` | printed by bootstrap |
| `AZURE_SUBSCRIPTION_ID` | printed by bootstrap |
| `PBKDF2_PASSPHRASE` | choose a strong passphrase; keep it safe — losing it means rotating all KV secrets |
| `TELEGRAM_BOT_TOKEN` | from [BotFather](https://t.me/botfather) |
| `GROQ_API_KEY` | from [Groq console](https://console.groq.com/) |
| `JINA_API_KEY` | from [Jina AI](https://jina.ai/) |

**Variables** (non-sensitive — stored in plain text):

| Name | Value |
|------|-------|
| `AZURE_RESOURCE_GROUP` | printed by bootstrap |
| `TFSTATE_STORAGE_ACCOUNT` | printed by bootstrap |
| `TFSTATE_CONTAINER` | `tofu-state` |
| `LLM_MODEL` | `qwen/qwen3.6-27b` |
| `LLM_TEMPERATURE` | `0.2` |
| `JINA_EMBEDDING_MODEL` | `jina-embeddings-v5-text-small` |
| `MEM0_EMBEDDING_DIMS` | `1024` |
| `MEM0_COLLECTION_NAME` | `memories` |

---

## Phase 1 — Deploy infrastructure

Go to **Actions → Deploy → Run workflow** and enable both deployment options, or push to `main` (the workflow runs automatically on push).

Terragrunt creates these resources in order: ACR → log-analytics → keyvault → postgres → postgres-firewall → phoenix → web-app. The workflow also bootstraps least-privilege database roles (`bootstrap-db-roles.sh`) and runs Alembic migrations.

To run locally instead:

```bash
export AZURE_RESOURCE_GROUP=<resource-group>
./scripts/deploy.sh
```

The script prompts for `PBKDF2_PASSPHRASE` and runs the same steps.

---

## Phase 2 — Enable Phoenix tracing (run once after first infra deploy)

Phoenix is deployed but tracing is disabled until you create an API key and store it in Key Vault.

```bash
export AZURE_RESOURCE_GROUP=<resource-group>
./scripts/post-deploy.sh
```

The script:
1. Retrieves the Phoenix admin password from Key Vault
2. Tells you to log in at the Phoenix URL with those credentials
3. Prompts you to create an API key in Phoenix (**Settings → API Keys**)
4. Stores the key in Key Vault
5. Sets `ENABLE_TRACING=true` and `PHOENIX_API_KEY` on the Web App

Without this step the bot runs fine but sends no traces to Phoenix.

---

## Phase 3 — Deploy the application

Happens automatically as part of the Deploy workflow (the `deploy-app` job). Manually:

```bash
./scripts/deploy-bot.sh
```

Builds the Docker image, pushes it to ACR, opens a temporary firewall rule for your IP, runs migrations, updates the Web App container, then removes the firewall rule.

---

## Subsequent deployments

Push to `main`. Path filters in `.github/workflows/deploy.yml` decide what runs:

- Changes under `infra/**` → infrastructure apply only
- Changes under `src/**`, `alembic/**`, `Dockerfile`, `pyproject.toml` → app deploy only
- Both changed → both jobs run in the correct order

To force a full redeploy without a code change, trigger the workflow manually from Actions.

---

## Tearing down

```bash
export AZURE_RESOURCE_GROUP=<resource-group>
./scripts/destroy.sh
```

Destroys all Terragrunt-managed resources. The resource group itself is not deleted (remove it manually with `az group delete` if needed).

---

## Troubleshooting

**Bot refuses to start (`migration mismatch`)**: The container checks that the running Alembic revision matches the image head. Run `./scripts/run-migrations.sh` with the admin `DATABASE_URL`, or trigger the Deploy workflow to re-run migrations.

**Tracing not appearing in Phoenix**: Check that `ENABLE_TRACING=true` and `PHOENIX_API_KEY` are set as Web App application settings. Re-run `./scripts/post-deploy.sh` if needed.

**`bootstrap-db-roles.sh` fails with permission denied**: It must run as the PostgreSQL server admin (the credential in `DATABASE_URL`), not the `habit_app` runtime role.

**Firewall blocks local `deploy-bot.sh`**: The script opens a firewall rule for your current public IP automatically, but corporate VPNs may change your IP mid-run. Disconnect from the VPN or run from a static IP.

**Azure login fails with `AADSTS700213: No matching federated identity record`**: GitHub changed their OIDC token format to include numeric owner and repo IDs in the subject claim (e.g. `repo:owner@123/repo@456:environment:production`). Re-run `./scripts/bootstrap-azure-github.sh` -- it now fetches the IDs from the GitHub API and updates the existing federated credential automatically.

**`bootstrap-azure-github.sh` fails with `Permission denied` on `bootstrap.sh`**: `bootstrap-azure-github.sh` shells out to `scripts/bootstrap.sh` to create the Terragrunt state storage account. If `bootstrap.sh` was checked in without the execute bit (common on Windows clones or fresh checkouts), the outer script aborts *after* creating the Entra app, federated credential, and role assignments but *before* creating the storage account. Fix with `chmod +x scripts/bootstrap.sh` and re-run. The script is now invoked via `bash` so a missing `+x` bit won't block the bootstrap. The Azure identity pieces are idempotent — re-running picks up where it left off, and `bootstrap.sh` itself detects an existing storage account and skips re-creation.
