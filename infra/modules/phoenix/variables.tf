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

variable "phoenix_connection_string" {
  description = "PostgreSQL connection string for Phoenix (habit_tracker database)"
  type        = string
  sensitive   = true
}

variable "phoenix_secret" {
  description = "Phoenix secret for authentication"
  type        = string
  sensitive   = true
}

variable "phoenix_admin_password" {
  description = "Phoenix admin user password"
  type        = string
  sensitive   = true
}

variable "log_analytics_workspace_id" {
  description = "Resource ID of the shared Log Analytics Workspace"
  type        = string
}
