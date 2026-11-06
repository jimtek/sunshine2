# Read-only role assumed by `fleetops inventory` in each fleet account.
# Grants describe/list on EC2 capacity and read on GPU metrics. No writes.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

variable "role_name" {
  type    = string
  default = "FleetInventoryReadOnly"
}

variable "trusted_principal_arns" {
  description = "IAM role/user ARNs (in the platform account) allowed to assume this role."
  type        = list(string)
}

variable "tags" {
  type    = map(string)
  default = {}
}

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = var.trusted_principal_arns
    }
  }
}

data "aws_iam_policy_document" "read" {
  statement {
    sid = "Ec2CapacityRead"
    actions = [
      "ec2:DescribeInstances",
      "ec2:DescribeInstanceTypes",
      "ec2:DescribeCapacityReservations",
      "ec2:DescribeCapacityBlockOfferings",
      "ec2:DescribeCapacityReservationFleets",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "GpuMetricsRead"
    actions   = ["cloudwatch:GetMetricData", "cloudwatch:ListMetrics"]
    resources = ["*"]
  }
}

resource "aws_iam_role" "this" {
  name                 = var.role_name
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = 3600
  tags                 = merge({ "platform:component" = "fleet-inventory", "platform:phase" = "0" }, var.tags)
}

resource "aws_iam_role_policy" "read" {
  name   = "fleet-inventory-read"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.read.json
}

output "role_arn" {
  value = aws_iam_role.this.arn
}
