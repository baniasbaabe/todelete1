# Infrastructure Security Hardening Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all identified infrastructure bugs and security issues in the Terragrunt/OpenTofu Azure stack.

**Architecture:** Terragrunt wraps OpenTofu modules for an Azure stack: ACR → Key Vault → PostgreSQL Flexible Server → Phoenix Container App → Linux Web App. Each module lives in `infra/modules/<name>/`, each live environment in `infra/live/<name>/`.

**Tech Stack:** OpenTofu (Terraform-compatible), Terragrunt, Azure (azurerm ~4.0), azurerm random ~3.6.

## Global Constraints

- Never run `terragrunt apply` or `tofu apply` — IaC text changes only.
- All file paths are relative to `/home/banix/Code/ai-habit-bot/`.
- Provider pinned to `azurerm ~> 4.0`, `random ~> 3.6` — do not change version constraints.
- Do not restructure the module/live directory layout.
- `sensitive = true` on every output and variable that carries a secret.

---

## Security Findings Summary

| Severity | Finding | File | Task |
|----------|---------|------|------|
| P1 | DATABASE_URL embeds KV reference — Azure App Service cannot resolve it | web-app/main.tf:69 | 1 |
| P1 | ACR admin credentials stored as plain app settings | web-app/main.tf:52-54 | 2 |
| P1 | Phoenix secrets (connection string, phoenix_secret, admin password) in plain env vars | phoenix/main.tf:51-76 | 3 |
| P1 | webhook_secret stored as plain app setting, not via Key Vault | web-app/main.tf:72 | 4 |
| P2 | `purge_protection_enabled = false` — KV secrets permanently deletable | keyvault/main.tf:24 | 5 |
| P2 | Key Vault uses legacy access policies instead of RBAC | keyvault/main.tf:27 | 5 |
| P3 | Phoenix image pinned to mutable `:latest` tag | phoenix/main.tf:46 | 6 |
| P3 | Bot image tag hardcoded to `latest` | web-app/terragrunt.hcl:59 | 6 |
| Info | F1 tier forces `always_on = false` — webhook bot will drop requests | web-app/main.tf:26 | 7 |
| Info | `random_suffix` local defined but never referenced | root.hcl:24 | 8 |
| Info | Common tags use placeholder values | root.hcl:12-16 | 8 |

---

## File Map

```
infra/
├── root.hcl                          MODIFY — remove unused local, fix tags
├── modules/
│   ├── acr/
│   │   └── main.tf                   MODIFY — disable admin auth
│   ├── keyvault/
│   │   ├── main.tf                   MODIFY — RBAC + purge protection + webhook_secret
│   │   ├── variables.tf              MODIFY — add webhook_secret variable
│   │   └── outputs.tf                MODIFY — add webhook_secret_uri, use versionless IDs
│   ├── phoenix/
│   │   └── main.tf                   MODIFY — wrap secrets with Container App secret blocks, pin image
│   └── web-app/
│       ├── main.tf                   MODIFY — DATABASE_URL via KV secret, ACR RBAC, RBAC KV policy, B1 tier
│       ├── variables.tf              MODIFY — add/remove variables
│       └── outputs.tf                no change
└── live/
    ├── web-app/
    │   └── terragrunt.hcl            MODIFY — wire new/removed inputs
    └── keyvault/
        └── terragrunt.hcl            MODIFY — add webhook_secret env input
```

---

## Task 1: Fix DATABASE_URL — Store full connection string as a Key Vault secret

**Why the bug exists:** Azure App Service resolves `@Microsoft.KeyVault(SecretUri=...)` only when it is the *entire* value of an app setting. The current code embeds it inside a URL string, so the password is the literal text `@Microsoft.KeyVault(...)` at runtime.

**Fix approach:** Create the full connection string as a KV secret inside the web-app module (which already has access to the KV data source), then reference the secret URI in the app setting.

**Files:**
- Modify: `infra/modules/web-app/variables.tf`
- Modify: `infra/modules/web-app/main.tf`
- Modify: `infra/live/web-app/terragrunt.hcl`

**Interfaces:**
- Consumes: `dependency.postgres.outputs.habit_tracker_connection_string` (already a sensitive output in postgres/outputs.tf:26)
- Produces: `DATABASE_URL` app setting that resolves to the full connection string at runtime

- [ ] **Step 1: Add the new variable to web-app module**

In `infra/modules/web-app/variables.tf`, add after the `habit_tracker_db_name` variable block:

```hcl
variable "postgres_connection_string" {
  description = "Full PostgreSQL connection string (postgresql://user:pass@host/db?sslmode=require)"
  type        = string
  sensitive   = true
}
```

- [ ] **Step 2: Create the KV secret and fix the app setting in web-app/main.tf**

Find the `data "azurerm_key_vault" "main"` block (line ~103). Directly after it, add:

```hcl
resource "azurerm_key_vault_secret" "database_url" {
  name         = "database-url"
  value        = var.postgres_connection_string
  key_vault_id = data.azurerm_key_vault.main.id

  depends_on = [azurerm_key_vault_access_policy.webapp]
}
```

Then replace the `DATABASE_URL` line inside `app_settings` (line ~69):

```hcl
# OLD (broken):
DATABASE_URL = "postgresql://${var.postgres_admin_user}:@Microsoft.KeyVault(SecretUri=${var.postgres_password_secret_uri})@${var.postgres_host}:5432/${var.habit_tracker_db_name}?sslmode=require"

# NEW (correct):
DATABASE_URL = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.database_url.versionless_id})"
```

Also remove the now-unused individual DB variables from `app_settings` (they are only needed to build the URL, which is now pre-built):

```hcl
# REMOVE these three lines from app_settings:
# postgres_host         = dependency.postgres.outputs.postgres_host        (in terragrunt, not app_settings)
# postgres_admin_user   = dependency.postgres.outputs.postgres_admin_user  (in terragrunt, not app_settings)
# habit_tracker_db_name = dependency.postgres.outputs.habit_tracker_db_name (in terragrunt, not app_settings)
```

Note: those three were Terragrunt inputs used to build the URL, not app_settings. The `DATABASE_URL` was the only app setting derived from them. After this change, `postgres_host`, `postgres_admin_user`, and `habit_tracker_db_name` variables in web-app/variables.tf are still used by the `DATABASE_URL` old code. Remove them since `postgres_connection_string` replaces them:

Remove from `web-app/variables.tf`:
- `variable "postgres_host"`
- `variable "postgres_admin_user"`
- `variable "habit_tracker_db_name"`

Also remove `variable "postgres_password_secret_uri"` from `web-app/variables.tf` (no longer needed directly; the secret is now created from `postgres_connection_string`).

- [ ] **Step 3: Wire the new input in web-app/terragrunt.hcl**

In `infra/live/web-app/terragrunt.hcl`, replace the DB-related inputs block:

```hcl
# REMOVE these lines:
postgres_password_secret_uri = dependency.keyvault.outputs.postgres_admin_password_secret_uri
postgres_host         = dependency.postgres.outputs.postgres_host
postgres_admin_user   = dependency.postgres.outputs.postgres_admin_user
habit_tracker_db_name = dependency.postgres.outputs.habit_tracker_db_name

# ADD this line:
postgres_connection_string = dependency.postgres.outputs.habit_tracker_connection_string
```

---

## Task 2: Replace ACR admin credentials with managed identity (AcrPull)

**Why:** ACR admin credentials give full push/pull/delete access to the registry and are stored as visible plain-text app settings. The web app only needs to *pull* images. Azure's AcrPull RBAC role on the web app's SystemAssigned identity provides exactly that, with no credentials required.

**Files:**
- Modify: `infra/modules/acr/main.tf`
- Modify: `infra/modules/web-app/main.tf`
- Modify: `infra/modules/web-app/variables.tf`
- Modify: `infra/live/web-app/terragrunt.hcl`

**Interfaces:**
- Consumes: `dependency.acr.outputs.acr_id` (already output in acr/outputs.tf:1-4)
- Consumes: `dependency.acr.outputs.acr_login_server` (unchanged)
- Produces: `azurerm_role_assignment.acr_pull` — grants AcrPull to the web app identity

- [ ] **Step 1: Disable ACR admin in acr/main.tf**

Change line 19 of `infra/modules/acr/main.tf`:

```hcl
# OLD:
admin_enabled = true    # Enable admin for easier authentication

# NEW:
admin_enabled = false
```

- [ ] **Step 2: Update web-app/variables.tf — remove admin cred variables, add acr_id**

Remove these variable blocks from `infra/modules/web-app/variables.tf`:
- `variable "acr_admin_username"`
- `variable "acr_admin_password"`

Add:

```hcl
variable "acr_id" {
  description = "Resource ID of the Azure Container Registry"
  type        = string
}
```

- [ ] **Step 3: Update web-app/main.tf — remove creds, add role assignment**

In `infra/modules/web-app/main.tf`, inside the `application_stack` block, remove the two credential lines:

```hcl
# REMOVE:
docker_registry_username = var.acr_admin_username
docker_registry_password = var.acr_admin_password
```

Keep `docker_registry_url` — Azure uses it to know which registry to authenticate against with the managed identity.

After the `azurerm_key_vault_access_policy "webapp"` resource, add:

```hcl
resource "azurerm_role_assignment" "acr_pull" {
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_linux_web_app.main.identity[0].principal_id
}
```

- [ ] **Step 4: Update live/web-app/terragrunt.hcl**

Remove:
```hcl
acr_admin_username = dependency.acr.outputs.acr_admin_username
acr_admin_password = dependency.acr.outputs.acr_admin_password
```

Add:
```hcl
acr_id = dependency.acr.outputs.acr_id
```

---

## Task 3: Move webhook_secret into Key Vault

**Why:** `WEBHOOK_SECRET` is a sensitive token for validating Telegram webhook requests. It's currently stored as a plain App Service setting visible in the Azure portal.

**Files:**
- Modify: `infra/modules/keyvault/variables.tf`
- Modify: `infra/modules/keyvault/main.tf`
- Modify: `infra/modules/keyvault/outputs.tf`
- Modify: `infra/modules/web-app/variables.tf`
- Modify: `infra/modules/web-app/main.tf`
- Modify: `infra/live/keyvault/terragrunt.hcl`
- Modify: `infra/live/web-app/terragrunt.hcl`

- [ ] **Step 1: Add webhook_secret to keyvault module**

In `infra/modules/keyvault/variables.tf`, add:

```hcl
variable "webhook_secret" {
  description = "Secret token for validating Telegram webhook requests"
  type        = string
  sensitive   = true
}
```

In `infra/modules/keyvault/main.tf`, after the `openai_key` secret resource, add:

```hcl
resource "azurerm_key_vault_secret" "webhook_secret" {
  name         = "webhook-secret"
  value        = var.webhook_secret
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_key_vault_access_policy.terraform]
}
```

In `infra/modules/keyvault/outputs.tf`, add:

```hcl
output "webhook_secret_uri" {
  description = "Key Vault secret URI for webhook secret"
  value       = azurerm_key_vault_secret.webhook_secret.versionless_id
}
```

- [ ] **Step 2: Wire from environment in keyvault/terragrunt.hcl**

In `infra/live/keyvault/terragrunt.hcl`, add to the inputs block:

```hcl
webhook_secret = get_env("WEBHOOK_SECRET")
```

- [ ] **Step 3: Update web-app module to reference the KV secret**

In `infra/modules/web-app/variables.tf`:
- Remove `variable "webhook_secret"` (the plain value)
- Add:

```hcl
variable "webhook_secret_uri" {
  description = "Key Vault secret URI for webhook secret"
  type        = string
}
```

In `infra/modules/web-app/main.tf`, change the `WEBHOOK_SECRET` app setting:

```hcl
# OLD:
WEBHOOK_SECRET = var.webhook_secret

# NEW:
WEBHOOK_SECRET = "@Microsoft.KeyVault(SecretUri=${var.webhook_secret_uri})"
```

- [ ] **Step 4: Update live/web-app/terragrunt.hcl**

Replace:
```hcl
webhook_secret = get_env("WEBHOOK_SECRET", "")
```

With:
```hcl
webhook_secret_uri = dependency.keyvault.outputs.webhook_secret_uri
```

---

## Task 4: Secure Phoenix Container App secrets

**Why:** `PHOENIX_SQL_DATABASE_URL`, `PHOENIX_SECRET`, and `PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD` are currently passed as plain environment variables, visible in the Azure portal. Azure Container Apps support native secrets that store values encrypted and expose them to containers via name reference.

**Files:**
- Modify: `infra/modules/phoenix/main.tf`

- [ ] **Step 1: Replace plain env vars with Container App secrets**

Replace the entire `template { container { ... } }` section in `infra/modules/phoenix/main.tf` with:

```hcl
  template {
    container {
      name   = "phoenix"
      image  = "arizephoenix/phoenix:latest"  # will be pinned in Task 6
      cpu    = 0.5
      memory = "1Gi"

      env {
        name        = "PHOENIX_SQL_DATABASE_URL"
        secret_name = "phoenix-connection-string"
      }

      env {
        name  = "PHOENIX_WORKING_DIR"
        value = "/phoenix"
      }

      env {
        name  = "PHOENIX_ENABLE_AUTH"
        value = "true"
      }

      env {
        name        = "PHOENIX_SECRET"
        secret_name = "phoenix-secret"
      }

      env {
        name        = "PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD"
        secret_name = "phoenix-admin-password"
      }
    }

    min_replicas = 1
    max_replicas = 1
  }
```

Add a `secret` block to `azurerm_container_app.phoenix`, directly before the `template` block:

```hcl
  secret {
    name  = "phoenix-connection-string"
    value = var.phoenix_connection_string
  }

  secret {
    name  = "phoenix-secret"
    value = var.phoenix_secret
  }

  secret {
    name  = "phoenix-admin-password"
    value = var.phoenix_admin_password
  }
```

---

## Task 5: Harden Key Vault — purge protection + RBAC

**Why:**
- `purge_protection_enabled = false` means accidental KV deletion permanently loses all secrets (Telegram token, OpenAI key, DB password) after the 7-day soft-delete window.
- Access policies are the legacy authorization model. RBAC provides finer-grained control, audit logs, and is the Azure-recommended approach for new deployments.

**Files:**
- Modify: `infra/modules/keyvault/main.tf`
- Modify: `infra/modules/web-app/main.tf`

### 5a: Enable purge protection

- [ ] **Step 1: Set purge_protection_enabled = true in keyvault/main.tf**

Change line 24 of `infra/modules/keyvault/main.tf`:

```hcl
# OLD:
purge_protection_enabled   = false # Set to true for production

# NEW:
purge_protection_enabled   = true
```

**Note:** Once applied to a live vault, this setting cannot be reverted. That is the intent — it prevents anyone (including Terraform) from permanently deleting the vault.

### 5b: Migrate to RBAC authorization

- [ ] **Step 2: Switch to RBAC in keyvault/main.tf**

Change line 27:

```hcl
# OLD:
enable_rbac_authorization = false # Using access policies for simplicity

# NEW:
enable_rbac_authorization = true
```

- [ ] **Step 3: Replace the Terraform access policy with an RBAC role assignment**

In `infra/modules/keyvault/main.tf`, remove the `azurerm_key_vault_access_policy "terraform"` resource block entirely (lines 33-46).

Add in its place:

```hcl
resource "azurerm_role_assignment" "terraform_kv_admin" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}
```

Update every secret resource's `depends_on` to use the new role assignment. Change all occurrences of:

```hcl
depends_on = [azurerm_key_vault_access_policy.terraform]
```

To:

```hcl
depends_on = [azurerm_role_assignment.terraform_kv_admin]
```

(There are 5 occurrences: `postgres_admin_password`, `telegram_token`, `openai_key`, `phoenix_secret`, `phoenix_admin_password`, plus `webhook_secret` added in Task 3.)

- [ ] **Step 4: Replace the webapp access policy with an RBAC role assignment in web-app/main.tf**

Remove the `azurerm_key_vault_access_policy "webapp"` resource block (lines 108-117).

Add in its place:

```hcl
resource "azurerm_role_assignment" "webapp_kv_reader" {
  scope                = data.azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_web_app.main.identity[0].principal_id
}
```

Update `azurerm_key_vault_secret.database_url` (added in Task 1) to depend on the new role:

```hcl
depends_on = [azurerm_role_assignment.webapp_kv_reader]
```

Also remove `data "azurerm_client_config" "current"` from `infra/modules/web-app/main.tf` — it is no longer used after removing the access policy (which used `current.tenant_id` and `current.object_id`).

---

## Task 6: Pin container image versions

**Why:** `:latest` is a mutable tag — a new image pushed to `arizephoenix/phoenix:latest` or to your ACR `habit-tracker-bot:latest` will silently replace what's running on next container restart with no audit trail.

**Files:**
- Modify: `infra/modules/phoenix/main.tf`
- Modify: `infra/modules/web-app/variables.tf` (already has `docker_image_tag` variable)
- Modify: `infra/live/web-app/terragrunt.hcl`
- Modify: `docker-compose.yaml`

- [ ] **Step 1: Pin Phoenix image**

1. Check Docker Hub for the latest stable Phoenix release tag (e.g. `version4.x.x` — do not use `:latest`).
2. In `infra/modules/phoenix/main.tf`, change:

```hcl
# OLD:
image  = "arizephoenix/phoenix:latest"

# NEW (use the actual latest stable version tag from Docker Hub):
image  = "arizephoenix/phoenix:<VERSION>"
```

3. In `docker-compose.yaml` line 2, apply the same version tag:

```yaml
# OLD:
image: arizephoenix/phoenix:latest

# NEW:
image: arizephoenix/phoenix:<VERSION>
```

- [ ] **Step 2: Stop using `latest` for the bot image**

The `docker_image_tag` variable in web-app/variables.tf already exists with `default = "latest"`. The fix is to pass a specific tag at deploy time. Update `infra/live/web-app/terragrunt.hcl` to remove the hardcoded `latest` default and require it from the environment:

```hcl
# OLD:
docker_image_tag   = "latest"

# NEW:
docker_image_tag = get_env("BOT_IMAGE_TAG", "latest")
```

This ensures CI/CD can pass the git SHA tag; `latest` stays as a fallback for manual deploys.

---

## Task 7: Upgrade App Service to B1 tier with always_on

**Why:** The F1 (Free) tier puts the app to sleep after inactivity. Telegram delivers webhook requests to the app URL — if the app is sleeping, the first request times out and the message is lost. The B1 tier is the lowest paid tier that supports `always_on`.

**Files:**
- Modify: `infra/modules/web-app/main.tf`

- [ ] **Step 1: Change SKU and enable always_on in web-app/main.tf**

Change `azurerm_service_plan.main`:

```hcl
# OLD:
sku_name = "F1" # Free tier - upgrade to B1+ for production

# NEW:
sku_name = "B1"
```

Change `azurerm_linux_web_app.main` `site_config`:

```hcl
# OLD:
always_on = false # F1 tier doesn't support always_on

# NEW:
always_on = true
```

---

## Task 8: Cleanup — remove unused locals, fix placeholder tags

**Files:**
- Modify: `infra/root.hcl`

- [ ] **Step 1: Remove unused random_suffix local from root.hcl**

Remove line 24 of `infra/root.hcl`:

```hcl
# REMOVE:
random_suffix = get_env("RANDOM_SUFFIX", "")
```

- [ ] **Step 2: Fix placeholder common_tags**

Replace the `common_tags` block in `infra/root.hcl`:

```hcl
# OLD:
common_tags = {
  Environment = "live"
  ManagedBy   = "terragrunt"
  Project     = "project"
  Repository  = "repo"
}

# NEW:
common_tags = {
  Environment = "live"
  ManagedBy   = "terragrunt"
  Project     = "kiri-habit-bot"
  Repository  = "ai-habit-bot"
}
```

- [ ] **Step 3: Use versionless secret IDs in keyvault/outputs.tf**

Update all `azurerm_key_vault_secret.<name>.id` references in `infra/modules/keyvault/outputs.tf` to `.versionless_id` so that App Service KV references always pick up the latest secret version:

```hcl
# Change every output that has:
value = azurerm_key_vault_secret.<name>.id

# To:
value = azurerm_key_vault_secret.<name>.versionless_id
```

Affected outputs: `postgres_admin_password_secret_uri`, `telegram_token_secret_uri`, `openai_key_secret_uri`, `phoenix_secret_uri`, `phoenix_admin_password_secret_uri`, and `webhook_secret_uri` (from Task 3).

---

## Self-Review

**Spec coverage check:**
- DATABASE_URL KV bug → Task 1 ✓
- ACR admin creds → Task 2 ✓
- Phoenix plain secrets → Task 4 ✓
- webhook_secret plain → Task 3 ✓
- purge_protection → Task 5a ✓
- RBAC migration → Task 5b ✓
- Image pinning → Task 6 ✓
- always_on / B1 tier → Task 7 ✓
- Unused random_suffix → Task 8 ✓
- Placeholder tags → Task 8 ✓
- Versionless KV IDs → Task 8 ✓

**Dependency order:** Tasks must be applied in order 1→8. Tasks 1, 2, 3 share web-app files — apply in the order shown (each step modifies a distinct section). Task 5b must follow Task 3 (so `depends_on` for webhook_secret uses the RBAC name, not the access policy name).

**Circular dependency check:** Task 1 creates a KV secret in the web-app module. The Terraform principal's write permission (Key Vault Secrets Officer after Task 5b) lives in the keyvault module state, which is applied before web-app (per Terragrunt dependency chain). No circular dependency. ✓

**Removed variables in web-app:**
- `postgres_host`, `postgres_admin_user`, `habit_tracker_db_name`, `postgres_password_secret_uri` → replaced by `postgres_connection_string`
- `acr_admin_username`, `acr_admin_password` → replaced by `acr_id`
- `webhook_secret` (plain value) → replaced by `webhook_secret_uri`
