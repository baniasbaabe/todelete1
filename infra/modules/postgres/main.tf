# Random suffix for globally unique PostgreSQL server name
resource "random_string" "pg_suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_postgresql_flexible_server" "main" {
  name                = "${var.name_prefix}-pg-${random_string.pg_suffix.result}"
  location            = var.location
  resource_group_name = var.resource_group_name

  administrator_login    = var.postgres_admin_user
  administrator_password = var.postgres_admin_password

  sku_name = "B_Standard_B1ms"

  storage_mb   = 32768 # 32 GB
  storage_tier = "P4"

  version = "17"

  # The server keeps a public endpoint, but no firewall rule is created here.
  # Reachability is granted exclusively by the postgres-firewall module, which
  # allowlists the specific App Service and Container App egress addresses.
  public_network_access_enabled = true

  backup_retention_days        = 7
  geo_redundant_backup_enabled = false

  zone = "1"

  tags = var.tags
}

resource "azurerm_postgresql_flexible_server_database" "habit_tracker" {
  name      = "habit_tracker"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# Dedicated database for Phoenix observability data.
#
# Phoenix manages its own schema and must not share a database with the
# application's Alembic-managed tables. The matching least-privilege role
# (phoenix_app) is a data-plane object and is created by
# scripts/bootstrap-db-roles.sh, since ARM/Terraform cannot create SQL roles.
resource "azurerm_postgresql_flexible_server_database" "phoenix" {
  name      = "phoenix"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# NOTE: Firewall rules deliberately live in the separate postgres-firewall
# module. They depend on the App Service and Container App egress addresses,
# which in turn depend on this module's connection string outputs — declaring
# them here would create a dependency cycle.

resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "vector,pg_stat_statements"
}

resource "azurerm_monitor_diagnostic_setting" "postgres" {
  name                       = "${var.name_prefix}-pg-diag"
  target_resource_id         = azurerm_postgresql_flexible_server.main.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category = "PostgreSQLLogs"
  }

  enabled_log {
    category = "PostgreSQLFlexSessions"
  }

}
