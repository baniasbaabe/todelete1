include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../modules/postgres"
}

dependency "keyvault" {
  config_path = "../keyvault"
}

dependency "log_analytics" {
  config_path = "../log-analytics"
}

inputs = {
  postgres_admin_user     = "phoenixadmin"
  postgres_admin_password = dependency.keyvault.outputs.postgres_admin_password
  phoenix_db_password     = dependency.keyvault.outputs.phoenix_db_password
  habit_app_db_password   = dependency.keyvault.outputs.habit_app_db_password

  log_analytics_workspace_id = dependency.log_analytics.outputs.workspace_id
}
