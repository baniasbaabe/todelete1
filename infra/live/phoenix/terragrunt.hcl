# Phoenix Container App environment configuration

# Include root configuration (remote state, providers, global inputs)
include "root" {
  path = find_in_parent_folders("root.hcl")
}

# Source module from local path
terraform {
  source = "../../modules/phoenix"
}

# Dependencies: Requires PostgreSQL, Key Vault, and shared Log Analytics Workspace
dependency "postgres" {
  config_path = "../postgres"
}

dependency "keyvault" {
  config_path = "../keyvault"
}

dependency "log_analytics" {
  config_path = "../log-analytics"
}

# Module-specific inputs
inputs = {
  # Least-privilege: the dedicated phoenix database and phoenix_app role, not
  # the server administrator credential for the application database.
  phoenix_connection_string = dependency.postgres.outputs.phoenix_connection_string
  phoenix_secret            = dependency.keyvault.outputs.phoenix_secret_value
  phoenix_admin_password    = dependency.keyvault.outputs.phoenix_admin_password_value

  log_analytics_workspace_id = dependency.log_analytics.outputs.workspace_id
}
