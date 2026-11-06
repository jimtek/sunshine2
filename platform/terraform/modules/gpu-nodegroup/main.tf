# One GPU capacity pool = one EKS managed node group.
#
# - EKS-optimized AL2023 NVIDIA AMI, pinned by release version (driver and
#   container toolkit come with the AMI; the GPU Operator runs with its driver
#   and toolkit disabled, see cluster/addons/).
# - EFA interfaces for multi-node training (one per network card).
# - Label and taint `platform.gpu/pool=<pool>`; these must match the Kueue
#   ResourceFlavor rendered from config/platform.yaml.
# - Capacity Blocks or On-Demand Capacity Reservations via the launch template.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.90" }
  }
}

variable "cluster_name" { type = string }
variable "pool" {
  description = "Pool name from config/platform.yaml (capacity-block | reserved | dev)."
  type        = string
}
variable "instance_type" { type = string }
variable "node_count" {
  description = "Fixed size. Reserved capacity is paid for anyway, so the pool doesn't autoscale."
  type        = number
}
variable "subnet_id" {
  description = "One subnet: the AZ the reservation lives in."
  type        = string
}
variable "node_role_arn" { type = string }
variable "security_group_ids" { type = list(string) }
variable "ami_release_version" {
  description = "Pinned EKS AMI release (e.g. 1.31.4-20250123). Upgrades are rolled on the pilot pool first."
  type        = string
  default     = null
}
variable "capacity" {
  description = "on-demand | odcr | capacity-block"
  type        = string
  default     = "on-demand"
  validation {
    condition     = contains(["on-demand", "odcr", "capacity-block"], var.capacity)
    error_message = "capacity must be on-demand, odcr or capacity-block"
  }
}
variable "capacity_reservation_id" {
  description = "Reservation or Capacity Block ID when capacity is odcr or capacity-block."
  type        = string
  default     = null
}
variable "efa_interfaces" {
  description = "EFA interfaces per node: 32 for p5.48xlarge, 16 for p5en.48xlarge, 0 to disable."
  type        = number
  default     = 0
}
variable "root_volume_gb" {
  type    = number
  default = 500
}
variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  name = "${var.cluster_name}-${var.pool}"

  # AL2023 nodeadm: stripe instance-store NVMe into one RAID0 volume for
  # container images and scratch.
  user_data = <<-EOT
    MIME-Version: 1.0
    Content-Type: multipart/mixed; boundary="BOUNDARY"

    --BOUNDARY
    Content-Type: application/node.eks.aws

    apiVersion: node.eks.aws/v1alpha1
    kind: NodeConfig
    spec:
      instance:
        localStorage:
          strategy: RAID0

    --BOUNDARY--
  EOT
}

resource "aws_placement_group" "this" {
  count    = var.capacity == "odcr" && var.efa_interfaces > 0 ? 1 : 0
  name     = local.name
  strategy = "cluster"
  tags     = var.tags
}

resource "aws_launch_template" "this" {
  name_prefix = "${local.name}-"
  user_data   = base64encode(local.user_data)

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = var.root_volume_gb
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  dynamic "network_interfaces" {
    for_each = range(var.efa_interfaces)
    content {
      device_index          = network_interfaces.value == 0 ? 0 : 1
      network_card_index    = network_interfaces.value
      interface_type        = network_interfaces.value == 0 ? "efa" : "efa-only"
      security_groups       = var.security_group_ids
      delete_on_termination = true
    }
  }

  vpc_security_group_ids = var.efa_interfaces > 0 ? null : var.security_group_ids

  dynamic "placement" {
    for_each = aws_placement_group.this
    content {
      group_name = placement.value.name
    }
  }

  dynamic "instance_market_options" {
    for_each = var.capacity == "capacity-block" ? [1] : []
    content {
      market_type = "capacity-block"
    }
  }

  dynamic "capacity_reservation_specification" {
    for_each = var.capacity_reservation_id == null ? [] : [1]
    content {
      capacity_reservation_target {
        capacity_reservation_id = var.capacity_reservation_id
      }
    }
  }

  tag_specifications {
    resource_type = "instance"
    tags          = merge(var.tags, { Name = local.name, "platform.gpu/pool" = var.pool })
  }
}

resource "aws_eks_node_group" "this" {
  cluster_name    = var.cluster_name
  node_group_name = local.name
  node_role_arn   = var.node_role_arn
  subnet_ids      = [var.subnet_id]
  ami_type        = "AL2023_x86_64_NVIDIA"
  release_version = var.ami_release_version
  instance_types  = [var.instance_type]
  capacity_type   = var.capacity == "capacity-block" ? "CAPACITY_BLOCK" : "ON_DEMAND"

  launch_template {
    id      = aws_launch_template.this.id
    version = aws_launch_template.this.latest_version
  }

  scaling_config {
    desired_size = var.node_count
    min_size     = 0
    max_size     = max(var.node_count, 1)
  }

  update_config {
    max_unavailable = 1
  }

  # Node auto repair stays off: the platform's remediation controller
  # (Phase 2) quarantines and replaces nodes with rate limits, so one bad
  # signal can't drain a reserved pool.
  node_repair_config {
    enabled = false
  }

  labels = {
    "platform.gpu/pool" = var.pool
  }

  taint {
    key    = "platform.gpu/pool"
    value  = var.pool
    effect = "NO_SCHEDULE"
  }
  taint {
    key    = "nvidia.com/gpu"
    value  = "present"
    effect = "NO_SCHEDULE"
  }

  tags = var.tags

  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }
}

output "node_group_name" { value = aws_eks_node_group.this.node_group_name }
