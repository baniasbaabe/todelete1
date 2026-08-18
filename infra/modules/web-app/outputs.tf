output "web_app_id" {
  description = "ID of the Web App"
  value       = azurerm_linux_web_app.main.id
}

output "web_app_name" {
  description = "Name of the Web App"
  value       = azurerm_linux_web_app.main.name
}

output "web_app_url" {
  description = "Default URL of the Web App"
  value       = "https://${azurerm_linux_web_app.main.default_hostname}"
}

output "web_app_default_hostname" {
  description = "Default hostname of the Web App"
  value       = azurerm_linux_web_app.main.default_hostname
}

output "web_app_identity_principal_id" {
  description = "Principal ID of the Web App managed identity"
  value       = azurerm_linux_web_app.main.identity[0].principal_id
}

# Consumed by the postgres-firewall module to allowlist exactly this app.
#
# possible_outbound_ip_address_list (not outbound_ip_address_list) is the
# correct source: it enumerates every address the app may egress from across
# the scale unit, so the allowlist stays valid if the instance is moved.
output "web_app_possible_outbound_ips" {
  description = "All possible outbound IPv4 addresses of the Web App"
  value       = azurerm_linux_web_app.main.possible_outbound_ip_address_list
}

output "app_service_plan_id" {
  description = "ID of the App Service Plan"
  value       = azurerm_service_plan.main.id
}

output "app_service_plan_name" {
  description = "Name of the App Service Plan"
  value       = azurerm_service_plan.main.name
}
