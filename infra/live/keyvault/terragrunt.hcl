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
}
