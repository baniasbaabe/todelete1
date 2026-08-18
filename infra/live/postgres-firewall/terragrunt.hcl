# PostgreSQL firewall rules
#
# Applied last: it depends on the egress addresses of every workload that needs
# database access. Until this unit is applied the bot will crash-loop on
# "alembic upgrade head", which is expected and self-heals once the rules land.

include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../modules/postgres-firewall"
}

dependency "postgres" {
  config_path = "../postgres"
}

dependency "web_app" {
  config_path = "../web-app"
}

dependency "phoenix" {
  config_path = "../phoenix"
}

inputs = {
  postgres_server_id = dependency.postgres.outputs.postgres_server_id

  allowed_ips = merge(
    {
      for ip in dependency.web_app.outputs.web_app_possible_outbound_ips :
      "webapp-${replace(ip, ".", "-")}" => ip
    },
    {
      "phoenix-${replace(dependency.phoenix.outputs.phoenix_static_ip, ".", "-")}" = dependency.phoenix.outputs.phoenix_static_ip
    },
  )

  # Operator access is owned by the postgres-firewall-deployer unit.
  deployer_ip = ""
}
