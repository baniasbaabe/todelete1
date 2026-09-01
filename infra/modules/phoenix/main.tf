# Phoenix (Arize) Container App Module
# Manages Azure Container Apps for Phoenix observability platform

# Random suffix for unique names
resource "random_string" "phoenix_suffix" {
  length  = 6
  special = false
  upper   = false
}

# Container App Environment — wired to the shared Log Analytics Workspace.
resource "azurerm_container_app_environment" "phoenix" {
  name                = "${var.name_prefix}-phoenix-env-${random_string.phoenix_suffix.result}"
  location            = var.location
  resource_group_name = var.resource_group_name

  log_analytics_workspace_id = var.log_analytics_workspace_id

  tags = var.tags
}

# Phoenix Container App
resource "azurerm_container_app" "phoenix" {
  name                         = "${var.name_prefix}-phoenix-${random_string.phoenix_suffix.result}"
  container_app_environment_id = azurerm_container_app_environment.phoenix.id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  tags = var.tags

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

  template {
    container {
      name   = "phoenix"
      image  = "arizephoenix/phoenix:version-19.6.0"
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

    # Resource allocation (0.5 vCPU, 1 GiB RAM)
    min_replicas = 1
    max_replicas = 1
  }

  # Ingress configuration
  ingress {
    external_enabled = true
    target_port      = 6006
    transport        = "http"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}
