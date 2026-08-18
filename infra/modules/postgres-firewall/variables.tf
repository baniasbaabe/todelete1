variable "postgres_server_id" {
  description = "ID of the PostgreSQL Flexible Server to attach firewall rules to"
  type        = string
}

variable "allowed_ips" {
  description = <<-EOT
    Map of firewall rule name => single IPv4 address permitted to reach the
    server. Rule names must contain only letters, digits and hyphens.
  EOT
  type        = map(string)
  default     = {}
}

variable "deployer_ip" {
  description = <<-EOT
    Optional public IPv4 address of the machine running deployments and
    database bootstrap. Set via the DEPLOYER_IP environment variable. Leave
    empty in CI so no long-lived operator rule is created.
  EOT
  type        = string
  default     = ""

  validation {
    condition     = var.deployer_ip == "" || can(regex("^(\\d{1,3}\\.){3}\\d{1,3}$", var.deployer_ip))
    error_message = "deployer_ip must be empty or a single IPv4 address."
  }
}
