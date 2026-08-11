output "allowed_rule_names" {
  description = "Names of the firewall rules created on the PostgreSQL server"
  value       = sort(keys(local.rules))
}

output "allowed_ip_count" {
  description = "Number of individual IPv4 addresses permitted to reach the server"
  value       = length(local.rules)
}
