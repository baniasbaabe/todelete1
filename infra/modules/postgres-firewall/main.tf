# PostgreSQL Firewall Module
#
# Firewall rules are separated from the postgres module to break a dependency
# cycle: the rules need the egress IP addresses of the App Service and the
# Phoenix Container App, but both of those consume connection strings produced
# by the postgres module.
#
# This module deliberately does NOT create the "AllowAzureServices" rule
# (0.0.0.0-0.0.0.0). Despite looking like a single host, that range is an Azure
# special value meaning "any Azure-hosted resource", which includes virtual
# machines in other customers' tenants.

locals {
  deployer_rule = var.deployer_ip == "" ? {} : {
    "deployer-${replace(var.deployer_ip, ".", "-")}" = var.deployer_ip
  }

  rules = merge(var.allowed_ips, local.deployer_rule)
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allowed" {
  for_each = local.rules

  name             = each.key
  server_id        = var.postgres_server_id
  start_ip_address = each.value
  end_ip_address   = each.value
}
