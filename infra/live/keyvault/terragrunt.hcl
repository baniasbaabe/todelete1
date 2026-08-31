# Key Vault environment configuration

# Include root configuration (remote state, providers, global inputs)
include "root" {
  path = find_in_parent_folders("root.hcl")
}

# Source module from local path
terraform {
  source = "../../modules/keyvault"
}

dependency "log_analytics" {
  config_path = "../log-analytics"
}

# Module-specific inputs
inputs = {
  # These come from environment variables (set in .env or shell)
  telegram_bot_token = get_env("TELEGRAM_BOT_TOKEN")
  groq_api_key       = get_env("GROQ_API_KEY")
  jina_api_key       = get_env("JINA_API_KEY")

  log_analytics_workspace_id = dependency.log_analytics.outputs.workspace_id

  # Comma-separated Azure AD object IDs of operators who need Key Vault access.
  # Set OPERATOR_OBJECT_IDS in the GitHub production environment variables.
  # The bootstrap script prints the deployer's OID for convenience.
  operator_object_ids = compact(split(",", get_env("OPERATOR_OBJECT_IDS", "")))
}
