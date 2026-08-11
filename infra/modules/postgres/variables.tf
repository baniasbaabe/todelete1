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

variable "postgres_admin_user" {
  description = "PostgreSQL administrator username"
  type        = string
  default     = "phoenixadmin"
}

variable "postgres_admin_password" {
  description = "PostgreSQL administrator password (from Key Vault)"
  type        = string
  sensitive   = true
}

variable "phoenix_db_password" {
  description = "Password for the least-privilege phoenix_app role (from Key Vault)"
  type        = string
  sensitive   = true
}

variable "habit_app_db_password" {
  description = "Password for the least-privilege habit_app role (from Key Vault)"
  type        = string
  sensitive   = true
}

variable "log_analytics_workspace_id" {
  description = "Resource ID of the shared Log Analytics Workspace for diagnostic settings"
  type        = string
}
