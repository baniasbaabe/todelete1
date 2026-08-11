# Azure Container Registry Module
# Manages ACR for storing Docker images

# Random suffix for globally unique ACR name
resource "random_string" "acr_suffix" {
  length  = 6
  special = false
  upper   = false
  numeric = true
  lower   = true
}

# Azure Container Registry
resource "azurerm_container_registry" "main" {
  name                = "${var.name_prefix}acr${random_string.acr_suffix.result}"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "Basic" # Basic tier is sufficient for single app
  admin_enabled       = false

  tags = var.tags
}
