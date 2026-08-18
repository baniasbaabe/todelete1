output "phoenix_url" {
  description = "Phoenix web interface URL"
  value       = "https://${azurerm_container_app.phoenix.ingress[0].fqdn}"
}

output "phoenix_fqdn" {
  description = "Phoenix FQDN"
  value       = azurerm_container_app.phoenix.ingress[0].fqdn
}

output "phoenix_container_app_id" {
  description = "ID of the Phoenix Container App"
  value       = azurerm_container_app.phoenix.id
}

output "phoenix_container_app_name" {
  description = "Name of the Phoenix Container App"
  value       = azurerm_container_app.phoenix.name
}

# Consumed by the postgres-firewall module.
#
# For a Consumption-only Container App Environment this is the environment's
# static IP. Verify it is also the egress address before relying on it (see
# scripts/verify-egress.sh) — if Phoenix cannot reach PostgreSQL after deploy,
# this is the first thing to check.
output "phoenix_static_ip" {
  description = "Static IP address of the Phoenix Container App Environment"
  value       = azurerm_container_app_environment.phoenix.static_ip_address
}

output "container_app_environment_id" {
  description = "ID of the Container App Environment"
  value       = azurerm_container_app_environment.phoenix.id
}

# For Web App environment variable (COLLECTOR_ENDPOINT)
output "phoenix_collector_endpoint" {
  description = "Phoenix OTLP collector endpoint"
  value       = "https://${azurerm_container_app.phoenix.ingress[0].fqdn}/v1/traces"
}
