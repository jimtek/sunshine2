# VPC for one platform cluster: large private subnets (pods use VPC IPs via
# the VPC CNI), small public subnets for NAT/load balancers, and an S3 gateway
# endpoint so dataset and checkpoint traffic skips NAT.
#
# If EA central infrastructure provides the VPC instead, skip this module and
# pass their subnet IDs to eks-cluster directly (see ADR 0002).

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.90" }
  }
}

variable "name" { type = string }
variable "cidr" {
  type    = string
  default = "10.40.0.0/16"
}
variable "azs" {
  description = "Availability zones. GPU nodes for one pool should share an AZ; list the reservation AZ first."
  type        = list(string)
}
variable "single_nat_gateway" {
  description = "One NAT for the VPC (cheaper; fine for test). Set false in production for per-AZ NAT."
  type        = bool
  default     = true
}
variable "tags" {
  type    = map(string)
  default = {}
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.16"

  name = var.name
  cidr = var.cidr
  azs  = var.azs

  # /18 private per AZ (~16k IPs each); /24 public.
  private_subnets = [for i, _ in var.azs : cidrsubnet(var.cidr, 2, i)]
  public_subnets  = [for i, _ in var.azs : cidrsubnet(var.cidr, 8, 240 + i)]

  enable_nat_gateway   = true
  single_nat_gateway   = var.single_nat_gateway
  enable_dns_hostnames = true

  private_subnet_tags = { "kubernetes.io/role/internal-elb" = "1" }
  public_subnet_tags  = { "kubernetes.io/role/elb" = "1" }
  tags                = var.tags
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.${data.aws_region.current.name}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = module.vpc.private_route_table_ids
  tags              = merge(var.tags, { Name = "${var.name}-s3" })
}

data "aws_region" "current" {}

output "vpc_id" { value = module.vpc.vpc_id }
output "private_subnet_ids" { value = module.vpc.private_subnets }
output "private_subnets_by_az" {
  value = zipmap(var.azs, module.vpc.private_subnets)
}
output "vpc_cidr" { value = var.cidr }
