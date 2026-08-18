# Key Vault Module
# Manages Azure Key Vault and secrets for the AI Habit Tracker application

# Get current Azure client configuration
data "azurerm_client_config" "current" {}

# Random suffix for globally unique Key Vault name
resource "random_string" "kv_suffix" {
  length  = 6
  special = false
  upper   = false
}

# Azure Key Vault
resource "azurerm_key_vault" "main" {
  name                = "${var.name_prefix}-kv-${random_string.kv_suffix.result}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  # Enable soft delete and purge protection
  soft_delete_retention_days = 7
  purge_protection_enabled   = true

  # Enable RBAC for access (modern approach)
  rbac_authorization_enabled = true

  tags = var.tags
}

# RBAC role assignment for Terraform service principal (Key Vault Secrets Officer)
resource "azurerm_role_assignment" "terraform_kv_admin" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Generate random password for PostgreSQL admin
#
# override_special is restricted to RFC 3986 "unreserved" characters. These
# passwords are embedded in postgresql:// connection strings, and any reserved
# character (@ : / ? # & =) would corrupt URL parsing on the consuming side.
resource "random_password" "postgres_admin" {
  length           = 40
  special          = true
  override_special = "-_.~"
}

# Generate random password for the least-privilege Phoenix database role.
# Phoenix gets its own role and database rather than the server admin
# credential, so a compromise of the Phoenix container cannot reach the
# habit_tracker application data.
resource "random_password" "phoenix_db" {
  length           = 40
  special          = true
  override_special = "-_.~"
}

# Generate random password for the least-privilege application database role.
# The bot container authenticates as habit_app, which holds CRUD rights on the
# public schema and no DDL there, so a compromise of the bot image cannot alter
# the Alembic-managed schema. The server admin credential stays with migrations.
resource "random_password" "habit_app" {
  length           = 40
  special          = true
  override_special = "-_.~"
}

# Generate the Telegram webhook verification secret. It is shared only between
# Telegram and the bot, so operators never need to create or handle it.
resource "random_password" "webhook_secret" {
  length  = 64
  special = false
}

# Generate random secret for Phoenix
resource "random_password" "phoenix_secret" {
  length  = 64
  special = false
}

# Generate random password for Phoenix admin user
resource "random_password" "phoenix_admin" {
  length  = 24
  special = true
}

# Store PostgreSQL admin password in Key Vault
resource "azurerm_key_vault_secret" "postgres_admin_password" {
  name         = "postgres-admin-password"
  value        = random_password.postgres_admin.result
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.terraform_kv_admin]
}

# Store the Phoenix database role password in Key Vault
resource "azurerm_key_vault_secret" "phoenix_db_password" {
  name         = "phoenix-db-password"
  value        = random_password.phoenix_db.result
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.terraform_kv_admin]
}

# Store the least-privilege application role password in Key Vault
resource "azurerm_key_vault_secret" "habit_app_db_password" {
  name         = "habit-app-db-password"
  value        = random_password.habit_app.result
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.terraform_kv_admin]
}

# Store Telegram bot token in Key Vault (from variable)
resource "azurerm_key_vault_secret" "telegram_token" {
  name         = "telegram-bot-token"
  value        = var.telegram_bot_token
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.terraform_kv_admin]
}

# Store the Groq API key.
resource "azurerm_key_vault_secret" "groq_key" {
  name         = "groq-api-key"
  value        = var.groq_api_key
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.terraform_kv_admin]
}

# Store the Jina API key used by the LangChain embedder.
resource "azurerm_key_vault_secret" "jina_key" {
  name         = "jina-api-key"
  value        = var.jina_api_key
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.terraform_kv_admin]
}

# Store the generated webhook secret in Key Vault.
resource "azurerm_key_vault_secret" "webhook_secret" {
  name         = "webhook-secret"
  value        = random_password.webhook_secret.result
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.terraform_kv_admin]
}

# Store Phoenix secret in Key Vault
resource "azurerm_key_vault_secret" "phoenix_secret" {
  name         = "phoenix-secret"
  value        = random_password.phoenix_secret.result
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.terraform_kv_admin]
}

# Store Phoenix admin password in Key Vault
resource "azurerm_key_vault_secret" "phoenix_admin_password" {
  name         = "phoenix-admin-password"
  value        = random_password.phoenix_admin.result
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.terraform_kv_admin]
}

# Note: phoenix-api-key will be created manually after Phoenix deployment
# via post-deploy.sh script

resource "azurerm_monitor_diagnostic_setting" "keyvault" {
  name                       = "${var.name_prefix}-kv-diag"
  target_resource_id         = azurerm_key_vault.main.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category = "AuditEvent"
  }

}
