# Private origin bucket. Nothing here is public: no website endpoint, no
# ACLs, all four public-access blocks on. CloudFront reads it through Origin
# Access Control (SigV4-signed requests), and the bucket policy accepts only
# those requests, and only from this one distribution.

resource "aws_s3_bucket" "origin" {
  bucket        = local.bucket_name
  force_destroy = var.force_destroy
  tags          = local.tags
}

resource "aws_s3_bucket_ownership_controls" "origin" {
  bucket = aws_s3_bucket.origin.id

  rule {
    # Disables ACLs entirely; the bucket owner owns every object.
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "origin" {
  bucket = aws_s3_bucket.origin.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "origin" {
  bucket = aws_s3_bucket.origin.id

  versioning_configuration {
    # Versioning is the rollback mechanism: a bad deploy is undone by
    # restoring the previous version of each object (docs/operations.md).
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "origin" {
  bucket = aws_s3_bucket.origin.id

  rule {
    apply_server_side_encryption_by_default {
      # SSE-S3 by default: OAC reads it with no extra grants. SSE-KMS needs a
      # key-policy statement for cloudfront.amazonaws.com (see outputs).
      sse_algorithm     = var.kms_key_arn == null ? "AES256" : "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    # S3 Bucket Keys cut KMS request charges; ignored for SSE-S3.
    bucket_key_enabled = var.kms_key_arn != null
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "origin" {
  bucket = aws_s3_bucket.origin.id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days           = var.noncurrent_version_retention_days
      newer_noncurrent_versions = var.noncurrent_versions_to_keep > 0 ? var.noncurrent_versions_to_keep : null
    }
  }

  rule {
    id     = "clean-up-deploy-leftovers"
    status = "Enabled"

    filter {}

    # Interrupted multipart uploads from a cancelled deploy.
    abort_incomplete_multipart_upload {
      days_after_initiation = 2
    }

    # Delete markers with no versions left behind them.
    expiration {
      expired_object_delete_marker = true
    }
  }

  depends_on = [aws_s3_bucket_versioning.origin]
}

data "aws_iam_policy_document" "origin" {
  statement {
    sid       = "AllowCloudFrontOACRead"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.origin.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    # Pins access to this distribution: another distribution (even in the
    # same account) using OAC cannot read the bucket.
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.this.arn]
    }
  }

  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.origin.arn,
      "${aws_s3_bucket.origin.arn}/*",
    ]

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

resource "aws_s3_bucket_policy" "origin" {
  bucket = aws_s3_bucket.origin.id
  policy = data.aws_iam_policy_document.origin.json

  # The public access block must exist first, so the policy is evaluated
  # against it (it is not public, so it is accepted).
  depends_on = [aws_s3_bucket_public_access_block.origin]
}
