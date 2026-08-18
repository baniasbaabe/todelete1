output "resource_group_name" {
  description = "Name of the resource group"
  value       = data.azurerm_resource_group.main.name
  # If creating new RG, change to: azurerm_resource_group.main.name
}

output "resource_group_id" {
  description = "ID of the resource group"
  value       = data.azurerm_resource_group.main.id
  # If creating new RG, change to: azurerm_resource_group.main.id
}

output "location" {
  description = "Location of the resource group"
  value       = data.azurerm_resource_group.main.location
  # If creating new RG, change to: azurerm_resource_group.main.location
}
