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

# Secrets from user input

variable "telegram_bot_token" {
  description = "Telegram Bot Token (from @BotFather)"
  type        = string
  sensitive   = true
}

variable "groq_api_key" {
  description = "Groq API Key"
  type        = string
  sensitive   = true
}

variable "jina_api_key" {
  description = "Jina AI API Key for LangChain embeddings"
  type        = string
  sensitive   = true
}

variable "log_analytics_workspace_id" {
  description = "Resource ID of the shared Log Analytics Workspace for diagnostic settings"
  type        = string
}

variable "operator_object_ids" {
  description = "Azure AD object IDs of human operators who need portal/CLI access to Key Vault secrets"
  type        = list(string)
  default     = []
}
