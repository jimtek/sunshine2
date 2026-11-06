# Phase 0: deploy the inventory role into one fleet account.
# Apply once per account (research, partner, platform-test), e.g. with
# separate workspaces or per-account provider profiles.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  # backend "s3" {}   # configure once the platform state bucket exists
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "account_name" {
  description = "research | partner | platform-test"
  type        = string
}

variable "inventory_runner_arns" {
  description = "Principals in the platform account that run fleetops."
  type        = list(string)
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { "platform:owner" = "gpu-platform", "platform:account" = var.account_name }
  }
}

module "inventory_role" {
  source                 = "../../modules/inventory-readonly-role"
  trusted_principal_arns = var.inventory_runner_arns
}

output "inventory_role_arn" {
  value = module.inventory_role.role_arn
}
