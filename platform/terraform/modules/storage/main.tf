# Training storage: an S3 bucket for datasets and checkpoints, and optionally
# an FSx for Lustre file system linked to it for high-throughput reads.
# Size FSx from measured data-loading stalls, not guesses (build plan risk).

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.90" }
  }
}

variable "name" { type = string }
variable "create_fsx" {
  type    = bool
  default = false
}
variable "fsx_subnet_id" {
  description = "Same AZ as the GPU pool it serves."
  type        = string
  default     = null
}
variable "fsx_security_group_ids" {
  type    = list(string)
  default = []
}
variable "fsx_storage_gib" {
  description = "PERSISTENT_2: multiples of 2400 GiB."
  type        = number
  default     = 4800
}
variable "fsx_throughput_per_tib" {
  type    = number
  default = 250
}
variable "checkpoint_retention_days" {
  type    = number
  default = 90
}
variable "tags" {
  type    = map(string)
  default = {}
}

resource "aws_s3_bucket" "ml" {
  bucket = var.name
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "ml" {
  bucket                  = aws_s3_bucket.ml.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ml" {
  bucket = aws_s3_bucket.ml.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "ml" {
  bucket = aws_s3_bucket.ml.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "ml" {
  bucket = aws_s3_bucket.ml.id
  rule {
    id     = "expire-old-checkpoints"
    status = "Enabled"
    filter {
      prefix = "checkpoints/"
    }
    expiration {
      days = var.checkpoint_retention_days
    }
    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 2
    }
  }
}

resource "aws_fsx_lustre_file_system" "this" {
  count                       = var.create_fsx ? 1 : 0
  storage_capacity            = var.fsx_storage_gib
  subnet_ids                  = [var.fsx_subnet_id]
  security_group_ids          = var.fsx_security_group_ids
  deployment_type             = "PERSISTENT_2"
  per_unit_storage_throughput = var.fsx_throughput_per_tib
  data_compression_type       = "LZ4"
  file_system_type_version    = "2.15"
  tags                        = merge(var.tags, { Name = var.name })
}

resource "aws_fsx_data_repository_association" "datasets" {
  count                = var.create_fsx ? 1 : 0
  file_system_id       = aws_fsx_lustre_file_system.this[0].id
  data_repository_path = "s3://${aws_s3_bucket.ml.id}/datasets"
  file_system_path     = "/datasets"
  s3 {
    auto_import_policy {
      events = ["NEW", "CHANGED", "DELETED"]
    }
  }
}

output "bucket" { value = aws_s3_bucket.ml.id }
output "fsx_dns_name" {
  value = var.create_fsx ? aws_fsx_lustre_file_system.this[0].dns_name : null
}
output "fsx_mount_name" {
  value = var.create_fsx ? aws_fsx_lustre_file_system.this[0].mount_name : null
}
