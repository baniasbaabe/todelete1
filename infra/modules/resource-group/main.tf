# Resource Group Module
# Looks up an existing resource group, named by var.resource_group_name
# (AZURE_RESOURCE_GROUP in the deploy scripts).
# Code for creating a new resource group is commented out for reference

# Use existing resource group (current approach)
data "azurerm_resource_group" "main" {
  name = var.resource_group_name
}

# Option to create a new resource group (commented out)
# Uncomment this if you want to create a new resource group instead

# resource "azurerm_resource_group" "main" {
#   name     = var.resource_group_name
#   location = var.location
#   tags     = var.tags
# }
