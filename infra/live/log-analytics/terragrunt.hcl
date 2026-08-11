# Log Analytics Workspace — shared across all modules for diagnostic settings.
# No dependencies: must be deployed before keyvault, postgres, phoenix, web-app.

# Include root configuration (remote state, providers, global inputs)
include "root" {
  path = find_in_parent_folders("root.hcl")
}

# Source module from local path
terraform {
  source = "../../modules/log-analytics"
}
