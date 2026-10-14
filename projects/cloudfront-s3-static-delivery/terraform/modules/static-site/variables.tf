variable "name_prefix" {
  description = "Prefix for resource names, e.g. static-demo. Lowercase letters, digits and hyphens."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,23}$", var.name_prefix))
    error_message = "name_prefix must be 3-24 characters: a lowercase letter followed by lowercase letters, digits or hyphens."
  }
}

variable "bucket_name" {
  description = "Origin bucket name. Leave null to derive <name_prefix>-origin-<account id>-<region>, which is globally unique without guessing."
  type        = string
  default     = null

  validation {
    condition     = var.bucket_name == null ? true : can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.bucket_name))
    error_message = "bucket_name must be a valid S3 bucket name (3-63 lowercase letters, digits, dots or hyphens)."
  }
}

# ----------------------------------------------------------------------------- domain, certificate, DNS

variable "domain_names" {
  description = "Hostnames served by the distribution. The first is the certificate's primary name, the rest are SANs. All must live in the hosted zone given by hosted_zone_id."
  type        = list(string)

  validation {
    condition     = length(var.domain_names) >= 1 && length(var.domain_names) <= 10
    error_message = "domain_names must contain between 1 and 10 hostnames."
  }

  validation {
    condition     = alltrue([for d in var.domain_names : can(regex("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", d))])
    error_message = "Each domain name must be a lowercase hostname such as www.example.com (no wildcards, no trailing dot)."
  }

  validation {
    condition     = length(distinct(var.domain_names)) == length(var.domain_names)
    error_message = "domain_names must not contain duplicates."
  }
}

variable "hosted_zone_id" {
  description = "ID of the existing public Route 53 hosted zone that holds domain_names. The module writes the ACM validation records and the alias records into it."
  type        = string

  validation {
    condition     = can(regex("^Z[A-Z0-9]{1,31}$", var.hosted_zone_id))
    error_message = "hosted_zone_id must be a Route 53 zone ID such as Z0123456789ABCDEFGHIJ."
  }
}

# ----------------------------------------------------------------------------- distribution

variable "price_class" {
  description = "CloudFront price class: PriceClass_100 (North America and Europe edges), PriceClass_200 (adds most of Asia, Middle East, Africa) or PriceClass_All."
  type        = string
  default     = "PriceClass_100"

  validation {
    condition     = contains(["PriceClass_100", "PriceClass_200", "PriceClass_All"], var.price_class)
    error_message = "price_class must be PriceClass_100, PriceClass_200 or PriceClass_All."
  }
}

variable "web_acl_arn" {
  description = "Optional WAFv2 web ACL to attach. It must be CLOUDFRONT scope, which AWS only creates in us-east-1 (ARN contains :us-east-1:...:global/webacl/). The cloud-security-waf-automation project's waf module can create one with scope = \"CLOUDFRONT\"."
  type        = string
  default     = null

  validation {
    condition     = var.web_acl_arn == null ? true : can(regex("^arn:aws[a-z-]*:wafv2:us-east-1:[0-9]{12}:global/webacl/[^/]+/[^/]+$", var.web_acl_arn))
    error_message = "web_acl_arn must be a CLOUDFRONT-scope web ACL ARN in us-east-1: arn:aws:wafv2:us-east-1:<account>:global/webacl/<name>/<id>. A REGIONAL ACL cannot be attached to CloudFront."
  }
}

variable "content_security_policy" {
  description = "Content-Security-Policy sent on every response. The default allows only same-origin resources and no inline script or style, which the demo site is written to respect."
  type        = string
  default     = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests"

  validation {
    condition     = length(var.content_security_policy) > 0 && length(var.content_security_policy) <= 1783
    error_message = "content_security_policy must be non-empty and at most 1783 characters (the CloudFront limit)."
  }
}

variable "hsts_max_age_seconds" {
  description = "Strict-Transport-Security max-age. At least one year (31536000), which is also the HSTS preload list minimum."
  type        = number
  default     = 63072000

  validation {
    condition     = var.hsts_max_age_seconds >= 31536000
    error_message = "hsts_max_age_seconds must be at least 31536000 (one year)."
  }
}

variable "hsts_preload" {
  description = "Add the preload directive to HSTS. Only enable after deciding to submit the domain to hstspreload.org: removal from browser preload lists takes months."
  type        = bool
  default     = false
}

variable "error_caching_min_ttl" {
  description = "Seconds CloudFront caches the 404 page for a missing path. Kept short so a page published moments after someone requested it is not hidden behind a cached 404."
  type        = number
  default     = 10

  validation {
    condition     = var.error_caching_min_ttl >= 0 && var.error_caching_min_ttl <= 3600
    error_message = "error_caching_min_ttl must be between 0 and 3600 seconds."
  }
}

# ----------------------------------------------------------------------------- bucket

variable "kms_key_arn" {
  description = "Optional customer managed KMS key for the origin bucket (SSE-KMS). Null means SSE-S3 (AES256), the default. With a CMK, the KEY POLICY must allow cloudfront.amazonaws.com kms:Decrypt for this distribution (see the kms_key_policy_statement output and docs/operations.md), or every request returns 403."
  type        = string
  default     = null

  validation {
    condition     = var.kms_key_arn == null ? true : can(regex("^arn:aws[a-z-]*:kms:[a-z0-9-]+:[0-9]{12}:key/[0-9a-f-]{36}$", var.kms_key_arn))
    error_message = "kms_key_arn must be a KMS key ARN (arn:aws:kms:<region>:<account>:key/<uuid>), not an alias."
  }
}

variable "noncurrent_version_retention_days" {
  description = "Days a replaced or deleted object version is kept before expiry. This is the rollback window (docs/operations.md)."
  type        = number
  default     = 30

  validation {
    condition     = var.noncurrent_version_retention_days >= 1 && var.noncurrent_version_retention_days <= 3650
    error_message = "noncurrent_version_retention_days must be between 1 and 3650."
  }
}

variable "noncurrent_versions_to_keep" {
  description = "Newest noncurrent versions kept regardless of age, so a rarely changed page still has a version to roll back to."
  type        = number
  default     = 3

  validation {
    condition     = var.noncurrent_versions_to_keep >= 0 && var.noncurrent_versions_to_keep <= 100
    error_message = "noncurrent_versions_to_keep must be between 0 and 100."
  }
}

variable "force_destroy" {
  description = "Allow terraform destroy to delete a non-empty bucket. Keep false outside throwaway environments."
  type        = bool
  default     = false
}

# ----------------------------------------------------------------------------- logging

variable "access_logs" {
  description = <<-EOT
    CloudFront standard logging v2, delivered to a CloudWatch Logs group in
    us-east-1 (see docs/security.md for why not legacy S3 logging). Null
    disables access logging. retention_days must be a CloudWatch-supported
    value.
  EOT
  type = object({
    retention_days = optional(number, 30)
  })
  default = {}

  validation {
    condition = var.access_logs == null ? true : contains(
      [1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653],
      var.access_logs.retention_days
    )
    error_message = "access_logs.retention_days must be a CloudWatch Logs retention value (1, 3, 5, 7, 14, 30, 60, 90, ... 3653)."
  }
}

variable "tags" {
  description = "Extra tags for every resource (on top of the provider's default_tags)."
  type        = map(string)
  default     = {}
}
