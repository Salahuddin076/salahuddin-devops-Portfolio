# ---------------------------------------------------------------------------
# S3 bucket that receives the FOCUS 1.0 billing export
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "exports" {
  count = var.create_data_export ? 1 : 0

  bucket        = local.export_bucket_name
  force_destroy = var.force_destroy_bucket
  tags          = var.tags
}

resource "aws_s3_bucket_ownership_controls" "exports" {
  count  = var.create_data_export ? 1 : 0
  bucket = aws_s3_bucket.exports[0].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "exports" {
  count  = var.create_data_export ? 1 : 0
  bucket = aws_s3_bucket.exports[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# SSE-S3 keeps the billing service's write path simple (no KMS grant needed for
# the export service). Switch to SSE-KMS with a key policy granting
# bcm-data-exports.amazonaws.com if your policy requires customer-managed keys.
resource "aws_s3_bucket_server_side_encryption_configuration" "exports" {
  count  = var.create_data_export ? 1 : 0
  bucket = aws_s3_bucket.exports[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "exports" {
  count  = var.create_data_export ? 1 : 0
  bucket = aws_s3_bucket.exports[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "exports" {
  count  = var.create_data_export ? 1 : 0
  bucket = aws_s3_bucket.exports[0].id

  rule {
    id     = "expire-old-exports"
    status = "Enabled"

    filter {
      prefix = "${var.export_s3_prefix}/"
    }

    expiration {
      days = var.export_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.exports]
}

data "aws_iam_policy_document" "exports_bucket" {
  count = var.create_data_export ? 1 : 0

  statement {
    sid       = "AllowBillingExportDelivery"
    actions   = ["s3:PutObject", "s3:GetBucketPolicy"]
    resources = [aws_s3_bucket.exports[0].arn, "${aws_s3_bucket.exports[0].arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["bcm-data-exports.amazonaws.com", "billingreports.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    # The Billing and Cost Management APIs are served from us-east-1.
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values = [
        "arn:${local.partition}:bcm-data-exports:us-east-1:${local.account_id}:export/*",
        "arn:${local.partition}:cur:us-east-1:${local.account_id}:definition/*",
      ]
    }
  }

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.exports[0].arn, "${aws_s3_bucket.exports[0].arn}/*"]

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

resource "aws_s3_bucket_policy" "exports" {
  count  = var.create_data_export ? 1 : 0
  bucket = aws_s3_bucket.exports[0].id
  policy = data.aws_iam_policy_document.exports_bucket[0].json

  depends_on = [aws_s3_bucket_public_access_block.exports]
}

# ---------------------------------------------------------------------------
# FOCUS 1.0 export (AWS Billing and Cost Management Data Exports)
# The selected columns are the ones the finops toolkit reads.
# ---------------------------------------------------------------------------
resource "aws_bcmdataexports_export" "focus" {
  count = var.create_data_export ? 1 : 0

  export {
    name        = local.export_name
    description = "FOCUS 1.0 cost and usage export consumed by the finops toolkit"

    data_query {
      query_statement = <<-SQL
        SELECT BillingPeriodStart, ChargePeriodStart, ChargePeriodEnd, ServiceName,
               ResourceId, ResourceType, RegionId, ConsumedQuantity, PricingUnit,
               ListCost, BilledCost, EffectiveCost, ChargeCategory, PricingCategory,
               SubAccountId, Tags
        FROM FOCUS_1_0_AWS
      SQL
    }

    destination_configurations {
      s3_destination {
        s3_bucket = aws_s3_bucket.exports[0].bucket
        s3_prefix = var.export_s3_prefix
        s3_region = aws_s3_bucket.exports[0].region

        s3_output_configurations {
          # CSV so the stdlib-only toolkit can read it after gunzip.
          format      = "TEXT_OR_CSV"
          compression = "GZIP"
          output_type = "CUSTOM"
          overwrite   = "OVERWRITE_REPORT"
        }
      }
    }

    refresh_cadence {
      frequency = "SYNCHRONOUS"
    }
  }

  tags = var.tags

  depends_on = [aws_s3_bucket_policy.exports]
}
