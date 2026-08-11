output "workspace_id" {
  description = "Resource ID of the shared Log Analytics Workspace"
  value       = azurerm_log_analytics_workspace.main.id
}

output "workspace_name" {
  description = "Name of the shared Log Analytics Workspace"
  value       = azurerm_log_analytics_workspace.main.name
}
