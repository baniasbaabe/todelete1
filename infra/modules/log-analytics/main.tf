# Log Analytics Workspace Module
# Manages a shared Azure Log Analytics Workspace for centralised diagnostic settings
# across App Service, PostgreSQL, Key Vault, and Container Apps.

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.name_prefix}-logs-${random_string.suffix.result}"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = var.tags
}
