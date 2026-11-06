# platform-test account: the Phase 1 pilot cluster.
#
# Cost controls (build plan, Phase 1):
#  - GPU pools default to 0 nodes; set dev_gpu_nodes=1 or 2 for the week-9
#    smoke test, then back to 0 (or `terraform destroy`).
#  - Every resource carries platform:expires-at; review and destroy after it.
#  - AWS budget alert on the account.
#  - Confirm the On-Demand P instance quota before week 9.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.90" }
  }
  # backend "s3" {}   # configure once the platform state bucket exists
}

variable "region" {
  type    = string
  default = "us-east-1"
}
variable "azs" {
  description = "First AZ hosts the GPU pools; pick one where p5 capacity is available."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}
variable "cluster_name" {
  type    = string
  default = "gpu-pilot"
}
variable "admin_role_arns" { type = list(string) }
variable "researcher_role_arns" {
  type    = map(string)
  default = {}
}
variable "public_endpoint_cidrs" {
  type    = list(string)
  default = []
}
variable "expires_at" {
  description = "Date after which this stack should be destroyed (YYYY-MM-DD)."
  type        = string
}
variable "dev_gpu_nodes" {
  description = "p5.4xlarge (1 GPU) nodes for the smoke test. Keep 0 unless testing."
  type        = number
  default     = 0
}
variable "reserved_capacity_reservation_id" {
  description = "Existing ODCR to test multi-node on (weeks 10-12). Null = no reserved pool."
  type        = string
  default     = null
}
variable "reserved_nodes" {
  type    = number
  default = 0
}
variable "budget_monthly_usd" {
  type    = number
  default = 5000
}
variable "budget_alert_emails" { type = list(string) }

locals {
  tags = {
    "platform:owner"      = "gpu-platform"
    "platform:account"    = "platform-test"
    "platform:phase"      = "1"
    "platform:expires-at" = var.expires_at
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = local.tags }
}

module "network" {
  source = "../../modules/network"
  name   = var.cluster_name
  azs    = var.azs
  tags   = local.tags
}

module "eks" {
  source                = "../../modules/eks-cluster"
  name                  = var.cluster_name
  vpc_id                = module.network.vpc_id
  subnet_ids            = module.network.private_subnet_ids
  admin_role_arns       = var.admin_role_arns
  researcher_role_arns  = var.researcher_role_arns
  public_endpoint_cidrs = var.public_endpoint_cidrs
  tags                  = local.tags
}

module "pool_dev" {
  source             = "../../modules/gpu-nodegroup"
  cluster_name       = module.eks.cluster_name
  pool               = "dev"
  instance_type      = "p5.4xlarge"
  node_count         = var.dev_gpu_nodes
  subnet_id          = module.network.private_subnets_by_az[var.azs[0]]
  node_role_arn      = module.eks.gpu_node_role_arn
  security_group_ids = [module.eks.node_security_group_id]
  capacity           = "on-demand"
  tags               = local.tags
}

module "pool_reserved" {
  count                   = var.reserved_capacity_reservation_id == null ? 0 : 1
  source                  = "../../modules/gpu-nodegroup"
  cluster_name            = module.eks.cluster_name
  pool                    = "reserved"
  instance_type           = "p5en.48xlarge"
  node_count              = var.reserved_nodes
  subnet_id               = module.network.private_subnets_by_az[var.azs[0]]
  node_role_arn           = module.eks.gpu_node_role_arn
  security_group_ids      = [module.eks.node_security_group_id]
  capacity                = "odcr"
  capacity_reservation_id = var.reserved_capacity_reservation_id
  efa_interfaces          = 16
  tags                    = local.tags
}

module "storage" {
  source = "../../modules/storage"
  name   = "${var.cluster_name}-ml-${data.aws_caller_identity.current.account_id}"
  tags   = local.tags
}

data "aws_caller_identity" "current" {}

resource "aws_budgets_budget" "account" {
  name         = "${var.cluster_name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_monthly_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.budget_alert_emails
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 90
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.budget_alert_emails
  }
}

output "cluster_name" { value = module.eks.cluster_name }
output "ml_bucket" { value = module.storage.bucket }
output "kubeconfig_command" {
  value = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}
