# Organization CloudTrail (management account) delivering to a central,
# Object Lock protected bucket in the log-archive account, plus an
# organization-wide AWS Config aggregator.
#
# Provider aliases:
#   aws.management   the management account (org trail)
#   aws.log_archive  the log-archive account (bucket, KMS key, aggregator)
#
# The aggregator needs the log-archive account registered as delegated
# administrator for config.amazonaws.com (organization module,
# delegated_administrators).

data "aws_partition" "current" {
  provider = aws.log_archive
}

data "aws_caller_identity" "management" {
  provider = aws.management
}

data "aws_caller_identity" "log_archive" {
  provider = aws.log_archive
}

data "aws_region" "management" {
  provider = aws.management
}

locals {
  partition      = data.aws_partition.current.partition
  management_id  = data.aws_caller_identity.management.account_id
  log_archive_id = data.aws_caller_identity.log_archive.account_id
  bucket_arn     = "arn:${local.partition}:s3:::${var.bucket_name}"

  # Built rather than read from the trail, so the key and bucket policies can
  # exist before the trail (CloudTrail validates delivery on creation).
  trail_arn         = "arn:${local.partition}:cloudtrail:${data.aws_region.management.region}:${local.management_id}:trail/${var.trail_name}"
  trail_arn_pattern = "arn:${local.partition}:cloudtrail:*:${local.management_id}:trail/*"
  break_glass_arn   = "arn:${local.partition}:iam::${local.log_archive_id}:role/${var.break_glass_role_name}"
}

# ----------------------------------------------------------------------------- KMS

data "aws_iam_policy_document" "kms" {
  provider = aws.log_archive

  statement {
    sid       = "LogArchiveAccountAdministers"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.log_archive_id}:root"]
    }
  }

  statement {
    sid       = "CloudTrailEncryptsOrgTrail"
    actions   = ["kms:GenerateDataKey*"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.trail_arn]
    }
    condition {
      test     = "StringLike"
      variable = "kms:EncryptionContext:aws:cloudtrail:arn"
      values   = [local.trail_arn_pattern]
    }
  }

  statement {
    sid       = "CloudTrailDescribesKey"
    actions   = ["kms:DescribeKey"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.trail_arn]
    }
  }

  statement {
    sid       = "ConfigEncryptsSnapshotsFromOrg"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceOrgID"
      values   = [var.organization_id]
    }
  }

  statement {
    sid       = "LogArchiveReadersDecrypt"
    actions   = ["kms:Decrypt", "kms:ReEncryptFrom"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.log_archive_id}:root"]
    }
    condition {
      test     = "StringEquals"
      variable = "kms:CallerAccount"
      values   = [local.log_archive_id]
    }
    condition {
      test     = "StringLike"
      variable = "kms:EncryptionContext:aws:cloudtrail:arn"
      values   = [local.trail_arn_pattern]
    }
  }
}

resource "aws_kms_key" "logs" {
  provider = aws.log_archive

  description             = "Organization CloudTrail and Config log encryption"
  enable_key_rotation     = true
  deletion_window_in_days = var.kms_deletion_window_days
  policy                  = data.aws_iam_policy_document.kms.json
  tags                    = var.tags
}

resource "aws_kms_alias" "logs" {
  provider = aws.log_archive

  name          = "alias/lz-org-logs"
  target_key_id = aws_kms_key.logs.key_id
}

# ----------------------------------------------------------------------------- bucket

resource "aws_s3_bucket" "logs" {
  provider = aws.log_archive

  bucket = var.bucket_name
  # Object Lock can only be turned on at creation.
  object_lock_enabled = true
  tags                = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_ownership_controls" "logs" {
  provider = aws.log_archive

  bucket = aws_s3_bucket.logs.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "logs" {
  provider = aws.log_archive

  bucket                  = aws_s3_bucket.logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "logs" {
  provider = aws.log_archive

  bucket = aws_s3_bucket.logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "logs" {
  provider = aws.log_archive

  bucket = aws_s3_bucket.logs.id
  rule {
    default_retention {
      mode = var.object_lock_mode
      days = var.object_lock_retention_days
    }
  }

  depends_on = [aws_s3_bucket_versioning.logs]
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  provider = aws.log_archive

  bucket = aws_s3_bucket.logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.logs.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  provider = aws.log_archive

  bucket = aws_s3_bucket.logs.id

  rule {
    id     = "archive-then-expire"
    status = "Enabled"

    filter {
      prefix = ""
    }

    transition {
      days          = var.glacier_transition_days
      storage_class = "GLACIER"
    }

    expiration {
      days = var.log_expiration_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.logs]

  lifecycle {
    precondition {
      condition     = var.log_expiration_days > var.object_lock_retention_days && var.log_expiration_days > var.glacier_transition_days
      error_message = "log_expiration_days must exceed object_lock_retention_days and glacier_transition_days."
    }
  }
}

data "aws_iam_policy_document" "bucket" {
  provider = aws.log_archive

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [local.bucket_arn, "${local.bucket_arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid       = "DenyGovernanceBypassExceptBreakGlass"
    effect    = "Deny"
    actions   = ["s3:BypassGovernanceRetention", "s3:PutBucketObjectLockConfiguration", "s3:DeleteBucket"]
    resources = [local.bucket_arn, "${local.bucket_arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "ArnNotLike"
      variable = "aws:PrincipalArn"
      values   = [local.break_glass_arn]
    }
  }

  statement {
    sid       = "CloudTrailAclCheck"
    actions   = ["s3:GetBucketAcl"]
    resources = [local.bucket_arn]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.trail_arn]
    }
  }

  statement {
    sid     = "CloudTrailWriteOrgTrail"
    actions = ["s3:PutObject"]
    # Org trails write the management account's own events under its account
    # ID and every member account's events under the organization ID.
    resources = [
      "${local.bucket_arn}/AWSLogs/${local.management_id}/*",
      "${local.bucket_arn}/AWSLogs/${var.organization_id}/*",
    ]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.trail_arn]
    }
  }

  # Config delivery channels in every member account write here. Their
  # source ARNs differ per account, so the scope is the organization.
  statement {
    sid       = "ConfigBucketCheckFromOrg"
    actions   = ["s3:GetBucketAcl", "s3:ListBucket"]
    resources = [local.bucket_arn]
    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceOrgID"
      values   = [var.organization_id]
    }
  }

  statement {
    sid       = "ConfigWriteFromOrg"
    actions   = ["s3:PutObject"]
    resources = ["${local.bucket_arn}/AWSLogs/*/Config/*"]
    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceOrgID"
      values   = [var.organization_id]
    }
  }
}

resource "aws_s3_bucket_policy" "logs" {
  provider = aws.log_archive

  bucket = aws_s3_bucket.logs.id
  policy = data.aws_iam_policy_document.bucket.json

  depends_on = [aws_s3_bucket_public_access_block.logs]
}

# ----------------------------------------------------------------------------- org trail

resource "aws_cloudtrail" "org" {
  provider = aws.management

  name                          = var.trail_name
  s3_bucket_name                = aws_s3_bucket.logs.id
  kms_key_id                    = aws_kms_key.logs.arn
  is_organization_trail         = true
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  tags                          = var.tags

  # CloudTrail checks bucket and key access when the trail is created.
  depends_on = [
    aws_s3_bucket_policy.logs,
    aws_s3_bucket_server_side_encryption_configuration.logs,
    aws_s3_bucket_object_lock_configuration.logs,
  ]
}

# ----------------------------------------------------------------------------- Config aggregator

data "aws_iam_policy_document" "aggregator_trust" {
  provider = aws.log_archive

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.log_archive_id]
    }
  }
}

resource "aws_iam_role" "aggregator" {
  provider = aws.log_archive

  name               = "lz-config-org-aggregator"
  assume_role_policy = data.aws_iam_policy_document.aggregator_trust.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "aggregator" {
  provider = aws.log_archive

  role       = aws_iam_role.aggregator.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSConfigRoleForOrganizations"
}

resource "aws_config_configuration_aggregator" "org" {
  provider = aws.log_archive

  name = var.config_aggregator_name

  organization_aggregation_source {
    all_regions = true
    role_arn    = aws_iam_role.aggregator.arn
  }

  tags       = var.tags
  depends_on = [aws_iam_role_policy_attachment.aggregator]
}
