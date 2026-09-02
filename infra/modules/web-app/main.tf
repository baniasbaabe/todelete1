# Web App Module
# Manages Azure App Service (Linux) for the AI Habit Tracker Telegram bot
#
# App Service Plan — B1 Basic tier with always_on enabled

locals {
  web_app_name = "${var.name_prefix}-bot-${random_string.app_suffix.result}"
  webhook_url = trimspace(var.webhook_url) != "" ? trimsuffix(var.webhook_url, "/") : (
    "https://${local.web_app_name}.azurewebsites.net"
  )
}

# Random suffix for unique names
resource "random_string" "app_suffix" {
  length  = 6
  special = false
  upper   = false
}

# App Service Plan (B1 Basic tier)
resource "azurerm_service_plan" "main" {
  name                = "${var.name_prefix}-plan-${random_string.app_suffix.result}"
  location            = var.location
  resource_group_name = var.resource_group_name
  os_type             = "Linux"
  sku_name            = "B1"

  tags = var.tags
}

# Linux Web App
resource "azurerm_linux_web_app" "main" {
  name                = local.web_app_name
  location            = var.location
  resource_group_name = var.resource_group_name
  service_plan_id     = azurerm_service_plan.main.id

  # Reject plaintext HTTP. The Telegram webhook authenticates callers with the
  # X-Telegram-Bot-Api-Secret-Token header, which must never traverse cleartext.
  https_only = true

  # Enable system-assigned managed identity for Key Vault access
  identity {
    type = "SystemAssigned"
  }

  site_config {
    always_on                               = true
    container_registry_use_managed_identity = true

    # Deployment is container-pull from ACR, so the FTP publishing endpoint is
    # unused surface. The provider default is "AllAllowed", which leaves the
    # plaintext FTP listener enabled alongside FTPS.
    ftps_state          = "Disabled"
    minimum_tls_version = "1.2"

    # Container configuration - pull from ACR
    application_stack {
      docker_image_name   = "${var.docker_image_name}:${var.docker_image_tag}"
      docker_registry_url = "https://${var.acr_login_server}"
    }

    http2_enabled = true
  }

  # Application settings (environment variables)
  app_settings = {

    # Telegram Bot Configuration
    TELEGRAM_BOT_TOKEN = "@Microsoft.KeyVault(SecretUri=${var.telegram_token_secret_uri})"
    GROQ_API_KEY       = "@Microsoft.KeyVault(SecretUri=${var.groq_key_secret_uri})"
    JINA_API_KEY       = "@Microsoft.KeyVault(SecretUri=${var.jina_key_secret_uri})"

    # LLM Configuration
    LLM_MODEL       = var.llm_model
    LLM_TEMPERATURE = var.llm_temperature

    # Mem0 configuration
    JINA_EMBEDDING_MODEL = var.jina_embedding_model
    MEM0_EMBEDDING_DIMS  = var.mem0_embedding_dims
    MEM0_COLLECTION_NAME = var.mem0_collection_name
    MEM0_TELEMETRY       = "false"

    # Database Configuration
    DATABASE_URL = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.database_url.versionless_id})"

    # Webhook Configuration (required for Azure App Service deployment)
    WEBHOOK_URL    = local.webhook_url
    WEBHOOK_SECRET = "@Microsoft.KeyVault(SecretUri=${var.webhook_secret_uri})"

    # Phoenix / Observability Configuration
    COLLECTOR_ENDPOINT = var.phoenix_collector_endpoint
    ENABLE_TRACING     = var.enable_tracing
    PHOENIX_API_KEY    = "@Microsoft.KeyVault(SecretUri=${var.phoenix_api_key_secret_uri})"

    # Python Configuration
    PYTHONUNBUFFERED = "1"

    # Docker/Container Configuration - port 8443 for webhook
    WEBSITES_PORT                       = "8443"
    WEBSITES_ENABLE_APP_SERVICE_STORAGE = "false"
  }

  # Logs configuration
  logs {
    detailed_error_messages = true
    failed_request_tracing  = true

    http_logs {
      file_system {
        retention_in_days = 7
        retention_in_mb   = 35
      }
    }
  }

  tags = var.tags
}

# Grant Web App managed identity access to Key Vault
data "azurerm_key_vault" "main" {
  name                = var.keyvault_name
  resource_group_name = var.resource_group_name
}

resource "azurerm_key_vault_secret" "database_url" {
  name         = "database-url"
  value        = var.postgres_connection_string
  key_vault_id = data.azurerm_key_vault.main.id
}

# Grant the Web App read access to all secrets in the vault. post-deploy.sh
# adds phoenix-api-key after the initial infra deploy, so per-secret scopes
# would miss it and cause AccessToKeyVaultDenied at runtime.
resource "azurerm_role_assignment" "webapp_secret_reader" {
  scope                = data.azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_web_app.main.identity[0].principal_id
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_linux_web_app.main.identity[0].principal_id
}

resource "azurerm_monitor_diagnostic_setting" "webapp" {
  name                       = "${var.name_prefix}-webapp-diag"
  target_resource_id         = azurerm_linux_web_app.main.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category = "AppServiceConsoleLogs"
  }

  enabled_log {
    category = "AppServiceHTTPLogs"
  }

  enabled_log {
    category = "AppServicePlatformLogs"
  }

}
