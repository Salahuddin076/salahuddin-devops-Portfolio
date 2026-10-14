# One bucket per region, versioned, SSE-KMS with that region's key, private,
# TLS-only. Cross-Region Replication primary -> DR, and optionally DR ->
# primary with replica modification sync so the pair stays two-way after a
# failover. Replication is asynchronous: objects written in the last minutes
# before a regional loss may be missing in DR (RTC bounds that to 15 minutes
# for 99.99% of objects when enabled).

locals {
  buckets = {
    primary = { name = var.primary_bucket_name, kms = var.primary.kms_key_arn, region = local.primary_region }
    dr      = { name = var.dr_bucket_name, kms = var.dr.kms_key_arn, region = local.dr_region }
  }
}

# --- primary bucket --------------------------------------------------------------

resource "aws_s3_bucket" "primary" {
  provider = aws.primary
  bucket   = var.primary_bucket_name
  tags     = merge(var.tags, { Name = var.primary_bucket_name })
}

resource "aws_s3_bucket_versioning" "primary" {
  provider = aws.primary
  bucket   = aws_s3_bucket.primary.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "primary" {
  provider = aws.primary
  bucket   = aws_s3_bucket.primary.id

  rule {
    bucket_key_enabled = true

    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.primary.kms_key_arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "primary" {
  provider                = aws.primary
  bucket                  = aws_s3_bucket.primary.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "primary" {
  provider = aws.primary
  bucket   = aws_s3_bucket.primary.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "primary" {
  provider = aws.primary
  bucket   = aws_s3_bucket.primary.id

  rule {
    id     = "expire-noncurrent"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_expiration_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.primary]
}

resource "aws_s3_bucket_policy" "primary" {
  provider = aws.primary
  bucket   = aws_s3_bucket.primary.id
  policy   = data.aws_iam_policy_document.tls_only["primary"].json

  depends_on = [aws_s3_bucket_public_access_block.primary]
}

# --- DR bucket -------------------------------------------------------------------

resource "aws_s3_bucket" "dr" {
  provider = aws.dr
  bucket   = var.dr_bucket_name
  tags     = merge(var.tags, { Name = var.dr_bucket_name })
}

resource "aws_s3_bucket_versioning" "dr" {
  provider = aws.dr
  bucket   = aws_s3_bucket.dr.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "dr" {
  provider = aws.dr
  bucket   = aws_s3_bucket.dr.id

  rule {
    bucket_key_enabled = true

    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.dr.kms_key_arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "dr" {
  provider                = aws.dr
  bucket                  = aws_s3_bucket.dr.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "dr" {
  provider = aws.dr
  bucket   = aws_s3_bucket.dr.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "dr" {
  provider = aws.dr
  bucket   = aws_s3_bucket.dr.id

  rule {
    id     = "expire-noncurrent"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_expiration_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.dr]
}

resource "aws_s3_bucket_policy" "dr" {
  provider = aws.dr
  bucket   = aws_s3_bucket.dr.id
  policy   = data.aws_iam_policy_document.tls_only["dr"].json

  depends_on = [aws_s3_bucket_public_access_block.dr]
}

data "aws_iam_policy_document" "tls_only" {
  for_each = local.buckets

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = ["arn:aws:s3:::${each.value.name}", "arn:aws:s3:::${each.value.name}/*"]

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
}

# --- replication role (IAM is global; created through the primary provider) -----

data "aws_iam_policy_document" "replication_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "replication" {
  statement {
    sid       = "ReadReplicationConfig"
    actions   = ["s3:GetReplicationConfiguration", "s3:ListBucket"]
    resources = [aws_s3_bucket.primary.arn, aws_s3_bucket.dr.arn]
  }

  statement {
    sid = "ReadSourceVersions"
    actions = [
      "s3:GetObjectVersionForReplication",
      "s3:GetObjectVersionAcl",
      "s3:GetObjectVersionTagging",
    ]
    resources = ["${aws_s3_bucket.primary.arn}/*", "${aws_s3_bucket.dr.arn}/*"]
  }

  statement {
    sid       = "WriteReplicas"
    actions   = ["s3:ReplicateObject", "s3:ReplicateDelete", "s3:ReplicateTags", "s3:ObjectOwnerOverrideToBucketOwner"]
    resources = ["${aws_s3_bucket.primary.arn}/*", "${aws_s3_bucket.dr.arn}/*"]
  }

  dynamic "statement" {
    for_each = local.buckets

    content {
      sid       = "UseKey${title(statement.key)}"
      actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
      resources = [statement.value.kms]

      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = ["s3.${statement.value.region}.amazonaws.com"]
      }

      condition {
        test     = "StringLike"
        variable = "kms:EncryptionContext:aws:s3:arn"
        values   = ["arn:aws:s3:::${statement.value.name}/*"]
      }
    }
  }
}

resource "aws_iam_role" "replication" {
  provider           = aws.primary
  name               = "${var.name}-s3-replication"
  assume_role_policy = data.aws_iam_policy_document.replication_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "replication" {
  provider = aws.primary
  name     = "s3-crr"
  role     = aws_iam_role.replication.id
  policy   = data.aws_iam_policy_document.replication.json
}

# --- replication rules -----------------------------------------------------------

resource "aws_s3_bucket_replication_configuration" "primary_to_dr" {
  provider = aws.primary
  role     = aws_iam_role.replication.arn
  bucket   = aws_s3_bucket.primary.id

  rule {
    id     = "to-${local.dr_region}"
    status = "Enabled"
    filter {}

    delete_marker_replication {
      status = "Enabled"
    }

    source_selection_criteria {
      sse_kms_encrypted_objects {
        status = "Enabled"
      }
      replica_modifications {
        status = "Enabled"
      }
    }

    destination {
      bucket        = aws_s3_bucket.dr.arn
      storage_class = "STANDARD"

      encryption_configuration {
        replica_kms_key_id = var.dr.kms_key_arn
      }

      dynamic "replication_time" {
        for_each = var.s3_replication_time_control ? [1] : []
        content {
          status = "Enabled"
          time {
            minutes = 15
          }
        }
      }

      # RTC requires replication metrics, so they are enabled together.
      dynamic "metrics" {
        for_each = var.s3_replication_time_control ? [1] : []
        content {
          status = "Enabled"
          event_threshold {
            minutes = 15
          }
        }
      }
    }
  }

  depends_on = [aws_s3_bucket_versioning.primary, aws_s3_bucket_versioning.dr]
}

resource "aws_s3_bucket_replication_configuration" "dr_to_primary" {
  provider = aws.dr
  count    = var.s3_bidirectional_replication ? 1 : 0

  role   = aws_iam_role.replication.arn
  bucket = aws_s3_bucket.dr.id

  rule {
    id     = "to-${local.primary_region}"
    status = "Enabled"
    filter {}

    delete_marker_replication {
      status = "Enabled"
    }

    source_selection_criteria {
      sse_kms_encrypted_objects {
        status = "Enabled"
      }
      replica_modifications {
        status = "Enabled"
      }
    }

    destination {
      bucket        = aws_s3_bucket.primary.arn
      storage_class = "STANDARD"

      encryption_configuration {
        replica_kms_key_id = var.primary.kms_key_arn
      }

      dynamic "replication_time" {
        for_each = var.s3_replication_time_control ? [1] : []
        content {
          status = "Enabled"
          time {
            minutes = 15
          }
        }
      }

      dynamic "metrics" {
        for_each = var.s3_replication_time_control ? [1] : []
        content {
          status = "Enabled"
          event_threshold {
            minutes = 15
          }
        }
      }
    }
  }

  depends_on = [aws_s3_bucket_versioning.primary, aws_s3_bucket_versioning.dr]
}
