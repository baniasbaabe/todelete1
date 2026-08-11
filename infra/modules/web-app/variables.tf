variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "location" {
  description = "Azure region for resources"
  type        = string
}

variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

# Key Vault configuration

variable "keyvault_name" {
  description = "Name of the Key Vault containing secrets"
  type        = string
}

variable "telegram_token_secret_uri" {
  description = "Key Vault secret URI for Telegram bot token"
  type        = string
}

variable "telegram_token_secret_resource_id" {
  description = "Azure resource ID for the Telegram bot token secret"
  type        = string
}

variable "groq_key_secret_uri" {
  description = "Key Vault secret URI for Groq API key"
  type        = string
}

variable "groq_key_secret_resource_id" {
  description = "Azure resource ID for the Groq API key secret"
  type        = string
}

variable "jina_key_secret_uri" {
  description = "Key Vault secret URI for Jina AI API key"
  type        = string
}

variable "jina_key_secret_resource_id" {
  description = "Azure resource ID for the Jina AI API key secret"
  type        = string
}

variable "webhook_secret_uri" {
  description = "Key Vault secret URI for webhook secret"
  type        = string
}

variable "webhook_secret_resource_id" {
  description = "Azure resource ID for the Telegram webhook secret"
  type        = string
}

variable "postgres_connection_string" {
  description = "Full PostgreSQL connection string (postgresql://user:pass@host/db?sslmode=require)"
  type        = string
  sensitive   = true
}

# LLM Configuration

variable "llm_model" {
  description = "Native Groq model ID"
  type        = string
  default     = "qwen/qwen3.6-27b"
}

variable "llm_temperature" {
  description = "LLM temperature setting"
  type        = string
  default     = "0.2"
}

variable "jina_embedding_model" {
  description = "Jina embedding model used through LangChain"
  type        = string
  default     = "jina-embeddings-v5-text-small"
}

variable "mem0_embedding_dims" {
  description = "Mem0 embedding vector dimensions"
  type        = string
  default     = "1024"
}

variable "mem0_collection_name" {
  description = "Mem0 pgvector collection/table name"
  type        = string
  default     = "mem0_jina"
}

# Webhook Configuration

variable "webhook_url" {
  description = "Optional public HTTPS base URL; defaults to the generated azurewebsites.net URL"
  type        = string
  default     = ""
}

# Phoenix Configuration

variable "phoenix_collector_endpoint" {
  description = "Phoenix OTLP collector endpoint URL"
  type        = string
}

# Azure Container Registry Configuration

variable "acr_id" {
  description = "Resource ID of the Azure Container Registry"
  type        = string
}

variable "acr_login_server" {
  description = "ACR login server URL"
  type        = string
}

variable "docker_image_name" {
  description = "Docker image name in ACR"
  type        = string
  default     = "habit-tracker-bot"
}

variable "docker_image_tag" {
  description = "Docker image tag"
  type        = string
  default     = "latest"
}

variable "log_analytics_workspace_id" {
  description = "Resource ID of the shared Log Analytics Workspace for diagnostic settings"
  type        = string
}
