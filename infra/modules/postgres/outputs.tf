output "postgres_server_id" {
  description = "ID of the PostgreSQL Flexible Server"
  value       = azurerm_postgresql_flexible_server.main.id
}

output "postgres_server_name" {
  description = "Name of the PostgreSQL Flexible Server"
  value       = azurerm_postgresql_flexible_server.main.name
}

output "postgres_fqdn" {
  description = "Fully qualified domain name of the PostgreSQL server"
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "postgres_admin_user" {
  description = "PostgreSQL administrator username"
  value       = azurerm_postgresql_flexible_server.main.administrator_login
}

output "habit_tracker_db_name" {
  description = "Name of the habit tracker database"
  value       = azurerm_postgresql_flexible_server_database.habit_tracker.name
}

# Connection string for the bot application.
#
# Authenticates as habit_app, not the server admin: the running container gets
# SELECT/INSERT/UPDATE/DELETE on the public schema and no DDL there, so a
# compromise of the bot image cannot drop or rewrite the Alembic-managed
# schema. The role is a data-plane object created by
# scripts/bootstrap-db-roles.sh, which must run before the app starts.
#
# Uses the postgresql+asyncpg:// scheme: the app calls create_async_engine(),
# which resolves the sync psycopg2 dialect for a bare postgresql:// URL and
# fails with "The asyncio extension requires an async driver".
#
# No sslmode query parameter: SQLAlchemy forwards unrecognised query args to
# asyncpg.connect() as keyword arguments, and asyncpg has no sslmode kwarg.
# TLS is configured in code (DatabaseSessionManager) via an ssl.SSLContext
# that performs full certificate and hostname verification.
output "habit_tracker_app_connection_string" {
  description = "asyncpg connection string using the least-privilege habit_app role"
  value       = "postgresql+asyncpg://habit_app:${var.habit_app_db_password}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/${azurerm_postgresql_flexible_server_database.habit_tracker.name}"
  sensitive   = true
}

# No admin connection string is exported. The deploy scripts that need DDL
# (scripts/run-migrations.sh, driven by deploy.sh Phase 3.5 and deploy-bot.sh)
# assemble their own URL from postgres_host, postgres_admin_user and the
# Key Vault secret, so exporting one would only materialize the admin password
# into Terraform state for no consumer.

# Connection string handed to the Phoenix container.
#
# Scoped to the dedicated phoenix database and the least-privilege phoenix_app
# role, so a compromise of the Phoenix image cannot read application data.
output "phoenix_connection_string" {
  description = "Least-privilege connection string for the Phoenix database"
  value       = "postgresql://phoenix_app:${var.phoenix_db_password}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/${azurerm_postgresql_flexible_server_database.phoenix.name}?sslmode=require"
  sensitive   = true
}

output "phoenix_db_name" {
  description = "Name of the Phoenix database"
  value       = azurerm_postgresql_flexible_server_database.phoenix.name
}

output "postgres_host" {
  description = "PostgreSQL server hostname"
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "postgres_port" {
  description = "PostgreSQL server port"
  value       = "5432"
}
