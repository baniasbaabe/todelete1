# Web App environment configuration

# Include root configuration (remote state, providers, global inputs)
include "root" {
  path = find_in_parent_folders("root.hcl")
}

# Source module from local path
terraform {
  source = "../../modules/web-app"
}

# Dependencies: Requires all other modules
dependency "keyvault" {
  config_path = "../keyvault"
}

dependency "postgres" {
  config_path = "../postgres"
}

dependency "phoenix" {
  config_path = "../phoenix"
}

dependency "acr" {
  config_path = "../acr"
}

dependency "log_analytics" {
  config_path = "../log-analytics"
}

# Module-specific inputs
inputs = {
  # Key Vault
  keyvault_name             = dependency.keyvault.outputs.keyvault_name
  telegram_token_secret_uri = dependency.keyvault.outputs.telegram_token_secret_uri
  groq_key_secret_uri       = dependency.keyvault.outputs.groq_key_secret_uri
  jina_key_secret_uri       = dependency.keyvault.outputs.jina_key_secret_uri
  webhook_secret_uri        = dependency.keyvault.outputs.webhook_secret_uri

  # LLM Configuration (from environment variables)
  llm_model       = get_env("LLM_MODEL", "qwen/qwen3.6-27b")
  llm_temperature = get_env("LLM_TEMPERATURE", "0.2")

  # Mem0 configuration
  jina_embedding_model = get_env("JINA_EMBEDDING_MODEL", "jina-embeddings-v5-text-small")
  mem0_embedding_dims  = get_env("MEM0_EMBEDDING_DIMS", "1024")
  mem0_collection_name = get_env("MEM0_COLLECTION_NAME", "mem0_jina")

  # Webhook Configuration (from environment variables)
  webhook_url = get_env("WEBHOOK_URL", "")

  # PostgreSQL
  postgres_connection_string = dependency.postgres.outputs.habit_tracker_app_connection_string

  # Phoenix
  phoenix_collector_endpoint = dependency.phoenix.outputs.phoenix_collector_endpoint
  phoenix_api_key_secret_uri = dependency.keyvault.outputs.phoenix_api_key_secret_uri

  # Azure Container Registry
  acr_id            = dependency.acr.outputs.acr_id
  acr_login_server  = dependency.acr.outputs.acr_login_server
  docker_image_name = "habit-tracker-bot"
  docker_image_tag  = get_env("BOT_IMAGE_TAG", "latest")

  log_analytics_workspace_id = dependency.log_analytics.outputs.workspace_id
}
