# Operator access to PostgreSQL.
#
# Applied immediately after the postgres unit so that scripts/bootstrap-db-roles.sh
# and the initial Alembic migration can reach the server. Kept separate from the
# postgres-firewall unit because that one depends on the web-app and phoenix
# units, which are not deployed yet at bootstrap time.
#
# Set DEPLOYER_IP to your public IPv4 address. Leaving it unset creates no rule.

include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../modules/postgres-firewall"
}

dependency "postgres" {
  config_path = "../postgres"
}

inputs = {
  postgres_server_id = dependency.postgres.outputs.postgres_server_id
  allowed_ips        = {}
  deployer_ip        = get_env("DEPLOYER_IP", "")
}
