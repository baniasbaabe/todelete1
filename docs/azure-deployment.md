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
| `OPERATOR_OBJECT_IDS` | printed by bootstrap (your Azure AD object ID; comma-separate for multiple operators) |
| `NAME_PREFIX` | short slug used to name all Azure resources (default: `habitbot`). **Every resource is prefixed with this value** — changing it after the first deploy creates duplicate resources instead of updating existing ones. Pick a value before the first deploy and keep it. |

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
1. Checks Key Vault access and auto-grants `Key Vault Secrets Officer` to your Azure account if needed
2. Retrieves the Phoenix admin password from Key Vault
3. Tells you to log in at the Phoenix URL with those credentials
4. Prompts you to create an API key in Phoenix (**Settings → API Keys**)
5. Stores the key in Key Vault
6. Sets `ENABLE_TRACING=true` and `PHOENIX_API_KEY` on the Web App

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

### Destroy the application resources

```bash
export AZURE_RESOURCE_GROUP=<resource-group>
./scripts/destroy.sh
```

Destroys all Terragrunt-managed resources (ACR, Key Vault, PostgreSQL, Phoenix, Web App, App Service Plan, Log Analytics).

### Delete the resource group (catches anything Terragrunt missed)

```bash
az group delete --name "$AZURE_RESOURCE_GROUP" --yes --no-wait
```

### Clean up the GitHub side (optional — only if you want a full reset)

1. **Settings → Environments → production → Delete environment.** Removes every GitHub secret and variable at once.
2. **Microsoft Entra → App registrations → delete the `<repo>-github-deploy` app.** Removes the OIDC identity and federated credential.
3. **Storage account** holding the Terragrunt state: `az storage account delete --name <account> --resource-group <state-rg> --yes`.

If you only deleted the application resources but kept the environment and OIDC identity, you can redeploy without re-running `./scripts/bootstrap-azure-github.sh`. If you deleted everything, follow Phase 0 again.

---

## Troubleshooting

**Bot refuses to start (`migration mismatch`)**: The container checks that the running Alembic revision matches the image head. Run `./scripts/run-migrations.sh` with the admin `DATABASE_URL`, or trigger the Deploy workflow to re-run migrations.

**Tracing not appearing in Phoenix**: Check that `ENABLE_TRACING=true` and `PHOENIX_API_KEY` are set as Web App application settings. Re-run `./scripts/post-deploy.sh` if needed.

**Phoenix crashes with `PhoenixMigrationError` on first deploy**: The infra job creates the Phoenix Container App before `bootstrap-db-roles.sh` has created the `phoenix_app` database role. Trigger the Deploy workflow with "Build, migrate, and deploy the bot" checked — the deploy-app job creates the roles and restarts Phoenix automatically.

**Phoenix crashes with `TimeoutError` connecting to PostgreSQL**: The Container App's egress IP may not match the firewall rule. As a workaround, add `AllowAzureServices` (`0.0.0.0-0.0.0.0`) via the Azure portal or CLI: `az postgres flexible-server firewall-rule create -g <rg> -s <server> --name AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0`. For production, use VNet integration instead.

**`bootstrap-db-roles.sh` fails with permission denied**: It must run as the PostgreSQL server admin (the credential in `DATABASE_URL`), not the `habit_app` runtime role.

**Firewall blocks local `deploy-bot.sh`**: The script opens a firewall rule for your current public IP automatically, but corporate VPNs may change your IP mid-run. Disconnect from the VPN or run from a static IP.

**Azure login fails with `AADSTS700213: No matching federated identity record`**: GitHub changed their OIDC token format to include numeric owner and repo IDs in the subject claim (e.g. `repo:owner@123/repo@456:environment:production`). Re-run `./scripts/bootstrap-azure-github.sh` -- it now fetches the IDs from the GitHub API and updates the existing federated credential automatically.

**Lost `PBKDF2_PASSPHRASE`**: CI still works (the secret is set in GitHub), but you cannot run Terragrunt locally. Generate a new passphrase, update the GitHub secret, and run a full infra deploy to re-encrypt state. Store the passphrase in a password manager.

**Alembic/psycopg2 fails with `SSL error: certificate verify failed`**: `psycopg2-binary` bundles its own libpq and does not honour `PGSSLROOTCERT=system`. Set `export PGSSLROOTCERT=/etc/ssl/certs/ca-certificates.crt` (Debian/Ubuntu path) before running migrations. The deploy scripts now do this automatically.

**`psql` ALTER ROLE fails with syntax error (`:variable`)**: psql's `:'var'` interpolation only works when reading from stdin, not with `--command`/`-c`. Use a heredoc instead.

**`bootstrap-azure-github.sh` fails with `Permission denied` on `bootstrap.sh`**: `bootstrap-azure-github.sh` shells out to `scripts/bootstrap.sh` to create the Terragrunt state storage account. If `bootstrap.sh` was checked in without the execute bit (common on Windows clones or fresh checkouts), the outer script aborts *after* creating the Entra app, federated credential, and role assignments but *before* creating the storage account. Fix with `chmod +x scripts/bootstrap.sh` and re-run. The script is now invoked via `bash` so a missing `+x` bit won't block the bootstrap. The Azure identity pieces are idempotent — re-running picks up where it left off, and `bootstrap.sh` itself detects an existing storage account and skips re-creation.
