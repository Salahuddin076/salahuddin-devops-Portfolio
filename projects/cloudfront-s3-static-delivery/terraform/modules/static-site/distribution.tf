# CloudFront in front of the private bucket.
#
# Request path: viewer -> viewer-request function (URI rewrite / redirect)
# -> cache (key from the managed CachingOptimized policy) -> on a miss, OAC
# signs the origin request with SigV4 -> S3 checks the bucket policy's
# AWS:SourceArn. Responses get the security headers policy on the way out.

# AWS managed policies are looked up by name, never by a pasted ID.
data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

resource "aws_cloudfront_origin_access_control" "this" {
  name                              = "${var.name_prefix}-oac"
  description                       = "SigV4 access from ${var.name_prefix} distribution to its private origin bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_function" "uri_rewrite" {
  name    = "${var.name_prefix}-uri-rewrite"
  runtime = "cloudfront-js-2.0"
  comment = "Directory index rewrite and trailing-slash redirect; spec is scripts/rewrite.py"
  publish = true
  code    = file("${path.module}/functions/uri-rewrite.js")
}

resource "aws_cloudfront_response_headers_policy" "security" {
  name    = "${var.name_prefix}-security-headers"
  comment = "HSTS, CSP, nosniff, frame and referrer policy for ${var.name_prefix}"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = var.hsts_max_age_seconds
      include_subdomains         = true
      preload                    = var.hsts_preload
      override                   = true
    }

    content_security_policy {
      content_security_policy = var.content_security_policy
      override                = true
    }

    content_type_options {
      override = true
    }

    frame_options {
      frame_option = "DENY"
      override     = true
    }

    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }

  custom_headers_config {
    items {
      header   = "Permissions-Policy"
      value    = "camera=(), microphone=(), geolocation=(), payment=()"
      override = true
    }
  }

  # S3 adds these on every object; they tell a viewer nothing useful.
  remove_headers_config {
    items {
      header = "x-amz-server-side-encryption"
    }
    items {
      header = "x-amz-version-id"
    }
  }
}

resource "aws_cloudfront_distribution" "this" {
  enabled             = true
  comment             = "${var.name_prefix} static site"
  aliases             = var.domain_names
  default_root_object = "index.html"
  is_ipv6_enabled     = true
  http_version        = "http2and3"
  price_class         = var.price_class
  web_acl_id          = var.web_acl_arn

  origin {
    origin_id                = "s3-origin"
    domain_name              = aws_s3_bucket.origin.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.this.id
    # No s3_origin_config / origin_access_identity: that is the legacy OAI
    # path. OAC replaces it (docs/decisions/0001-oac-over-oai.md).
  }

  default_cache_behavior {
    target_origin_id       = "s3-origin"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.uri_rewrite.arn
    }
  }

  # Without s3:ListBucket, S3 answers a missing key with 403, not 404. Both
  # map to the site's 404 page with a real 404 status, so crawlers and
  # monitors see the truth and nobody learns whether a key exists.
  custom_error_response {
    error_code            = 403
    response_code         = 404
    response_page_path    = "/404.html"
    error_caching_min_ttl = var.error_caching_min_ttl
  }

  custom_error_response {
    error_code            = 404
    response_code         = 404
    response_page_path    = "/404.html"
    error_caching_min_ttl = var.error_caching_min_ttl
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    # The validation resource's ARN, not the certificate's: this makes the
    # distribution wait until the certificate is ISSUED.
    acm_certificate_arn      = aws_acm_certificate_validation.this.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = local.tags
}
