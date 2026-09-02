output "keyvault_id" {
  description = "ID of the Key Vault"
  value       = azurerm_key_vault.main.id
}

output "keyvault_name" {
  description = "Name of the Key Vault"
  value       = azurerm_key_vault.main.name
}

output "keyvault_uri" {
  description = "URI of the Key Vault"
  value       = azurerm_key_vault.main.vault_uri
}

# Secret IDs for Web App Key Vault references
# Format: @Microsoft.KeyVault(SecretUri=...)

output "postgres_admin_password" {
  description = "PostgreSQL admin password (sensitive)"
  value       = random_password.postgres_admin.result
  sensitive   = true
}

output "postgres_admin_password_secret_uri" {
  description = "Key Vault secret URI for PostgreSQL admin password"
  value       = azurerm_key_vault_secret.postgres_admin_password.versionless_id
}

output "phoenix_db_password" {
  description = "Password for the least-privilege Phoenix database role (sensitive)"
  value       = random_password.phoenix_db.result
  sensitive   = true
}

output "phoenix_db_password_secret_uri" {
  description = "Key Vault secret URI for the Phoenix database role password"
  value       = azurerm_key_vault_secret.phoenix_db_password.versionless_id
}

output "habit_app_db_password" {
  description = "Password for the least-privilege habit_app database role (sensitive)"
  value       = random_password.habit_app.result
  sensitive   = true
}

output "habit_app_db_password_secret_uri" {
  description = "Key Vault secret URI for the habit_app database role password"
  value       = azurerm_key_vault_secret.habit_app_db_password.versionless_id
}

output "telegram_token_secret_uri" {
  description = "Key Vault secret URI for Telegram bot token"
  value       = azurerm_key_vault_secret.telegram_token.versionless_id
}

output "groq_key_secret_uri" {
  description = "Key Vault secret URI for Groq API key"
  value       = azurerm_key_vault_secret.groq_key.versionless_id
}

output "jina_key_secret_uri" {
  description = "Key Vault secret URI for Jina AI API key"
  value       = azurerm_key_vault_secret.jina_key.versionless_id
}

output "webhook_secret_uri" {
  description = "Key Vault secret URI for webhook secret"
  value       = azurerm_key_vault_secret.webhook_secret.versionless_id
}

output "phoenix_api_key_secret_uri" {
  description = "Key Vault secret URI for Phoenix API key"
  value       = azurerm_key_vault_secret.phoenix_api_key.versionless_id
}

output "phoenix_secret_value" {
  description = "Phoenix secret value (sensitive)"
  value       = random_password.phoenix_secret.result
  sensitive   = true
}

output "phoenix_secret_uri" {
  description = "Key Vault secret URI for Phoenix secret"
  value       = azurerm_key_vault_secret.phoenix_secret.versionless_id
}

output "phoenix_admin_password_secret_uri" {
  description = "Key Vault secret URI for Phoenix admin password"
  value       = azurerm_key_vault_secret.phoenix_admin_password.versionless_id
}

output "phoenix_admin_password_value" {
  description = "Phoenix admin password (sensitive)"
  value       = random_password.phoenix_admin.result
  sensitive   = true
}
