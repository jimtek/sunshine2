# EKS control plane, a small system node group for platform controllers
# (Kueue, GPU Operator, monitoring), core add-ons including the EKS node
# monitoring agent, and access entries for operators and researchers.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.90" }
  }
}

variable "name" { type = string }
variable "kubernetes_version" {
  type    = string
  default = "1.31"
}
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "public_endpoint_cidrs" {
  description = "CIDRs allowed to reach the public API endpoint. Empty = private endpoint only."
  type        = list(string)
  default     = []
}
variable "admin_role_arns" {
  description = "IAM roles with cluster-admin (platform team)."
  type        = list(string)
}
variable "researcher_role_arns" {
  description = "IAM role per team -> Kubernetes group of the same name (bound in cluster/rbac)."
  type        = map(string)
  default     = {}
}
variable "system_instance_type" {
  type    = string
  default = "m7i.2xlarge"
}
variable "tags" {
  type    = map(string)
  default = {}
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.31"

  cluster_name    = var.name
  cluster_version = var.kubernetes_version
  vpc_id          = var.vpc_id
  subnet_ids      = var.subnet_ids

  cluster_endpoint_private_access      = true
  cluster_endpoint_public_access       = length(var.public_endpoint_cidrs) > 0
  cluster_endpoint_public_access_cidrs = var.public_endpoint_cidrs

  authentication_mode                      = "API"
  enable_cluster_creator_admin_permissions = false

  cluster_addons = {
    coredns                   = { most_recent = false }
    kube-proxy                = { most_recent = false }
    vpc-cni                   = { most_recent = false, before_compute = true }
    eks-pod-identity-agent    = { most_recent = false, before_compute = true }
    eks-node-monitoring-agent = { most_recent = false }
  }

  eks_managed_node_groups = {
    system = {
      instance_types = [var.system_instance_type]
      ami_type       = "AL2023_x86_64_STANDARD"
      min_size       = 2
      max_size       = 4
      desired_size   = 3
      labels         = { "platform.gpu/role" = "system" }
    }
  }

  access_entries = merge(
    { for i, arn in var.admin_role_arns : "admin-${i}" => {
      principal_arn       = arn
      policy_associations = {
        admin = {
          policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = { type = "cluster" }
        }
      }
    } },
    { for team, arn in var.researcher_role_arns : "team-${team}" => {
      principal_arn     = arn
      kubernetes_groups = [team]
    } },
  )

  tags = var.tags
}

output "cluster_name" { value = module.eks.cluster_name }
output "cluster_endpoint" { value = module.eks.cluster_endpoint }
output "cluster_ca" { value = module.eks.cluster_certificate_authority_data }
output "node_security_group_id" { value = module.eks.node_security_group_id }
output "cluster_security_group_id" { value = module.eks.cluster_security_group_id }
output "oidc_provider_arn" { value = module.eks.oidc_provider_arn }

# Node role shared by the GPU node groups (EKS adds their access entries).
resource "aws_iam_role" "gpu_nodes" {
  name               = "${var.name}-gpu-nodes"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "gpu_nodes" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
  ])
  role       = aws_iam_role.gpu_nodes.name
  policy_arn = each.value
}

output "gpu_node_role_arn" { value = aws_iam_role.gpu_nodes.arn }
