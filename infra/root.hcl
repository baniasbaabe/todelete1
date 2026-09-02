# Global Terragrunt configuration
# This file defines shared variables and configurations used across all modules

locals {
  # Azure configuration
  location       = "swedencentral"
  resource_group = get_env("AZURE_RESOURCE_GROUP")
  environment    = "live"

  # Common tags applied to all resources
  common_tags = {
    Environment = "live"
    ManagedBy   = "terragrunt"
    Project     = "kiri-habit-bot"
    Repository  = "ai-habit-bot"
  }

  # Naming convention: override with NAME_PREFIX env var (defaults to "habitbot")
  name_prefix = get_env("NAME_PREFIX", "habitbot")
}

# Remote state configuration with PBKDF2 encryption
remote_state {
  backend = "azurerm"
  
  config = {
    resource_group_name  = local.resource_group
    storage_account_name = get_env("TFSTATE_STORAGE_ACCOUNT")
    container_name       = get_env("TFSTATE_CONTAINER", "tofu-state")
    key                  = "${path_relative_to_include()}/tofu.tfstate"
  }

  encryption = {
    key_provider = "pbkdf2"
    passphrase   = get_env("PBKDF2_PASSPHRASE")
  }
  
  generate = {
    path      = "backend.tf"
    if_exists = "overwrite_terragrunt"
  }
}

# Generate provider configuration for all modules
# This eliminates the need for provider blocks in each module
generate "versions" {
  path      = "versions.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  # Resource providers are registered once by bootstrap-azure-github.sh. The
  # GitHub identity is deliberately scoped to one resource group and therefore
  # cannot register providers at subscription scope during every plan/apply.
  resource_provider_registrations = "none"
  features {}
}

provider "random" {}
EOF
}

# Configure OpenTofu/Terraform settings
terraform {
  # Use the OpenTofu CLI (not Terraform)
  extra_arguments "tofu" {
    commands = get_terraform_commands_that_need_vars()
  }
}

# Global inputs available to all child modules
inputs = {
  location            = local.location
  resource_group_name = local.resource_group
  environment         = local.environment
  tags                = local.common_tags
  name_prefix         = local.name_prefix
}
