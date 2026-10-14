variable "role_name" {
  description = "Name of the deploy role GitHub Actions assumes."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,64}$", var.role_name))
    error_message = "role_name must be 1-64 characters of letters, digits and +=,.@_-."
  }
}

variable "github_repository" {
  description = "The one repository allowed to assume the role, as <org>/<repo>, e.g. example-org/example-site."
  type        = string

  validation {
    # GitHub owner: 1-39 alphanumerics or single hyphens, not leading or
    # trailing. Repository: letters, digits, '.', '_' and '-'.
    condition     = can(regex("^[A-Za-z0-9](?:[A-Za-z0-9]|-[A-Za-z0-9]){0,38}/[A-Za-z0-9._-]{1,100}$", var.github_repository))
    error_message = "github_repository must be <org>/<repo>, e.g. example-org/example-site (no wildcards, no URL, no .git suffix needed)."
  }

  validation {
    condition     = !can(regex("\\*", var.github_repository)) && !endswith(var.github_repository, "/.") && !endswith(var.github_repository, "/..")
    error_message = "github_repository must name exactly one repository: wildcards and '.'/'..' are not allowed."
  }
}

variable "allowed_branches" {
  description = "Branches whose workflow runs may deploy (sub = repo:<org>/<repo>:ref:refs/heads/<branch>). Only applies to jobs WITHOUT a GitHub environment: a job that declares `environment:` gets the environment form of sub instead."
  type        = list(string)
  default     = ["main"]

  validation {
    condition     = alltrue([for b in var.allowed_branches : can(regex("^[A-Za-z0-9._/-]{1,255}$", b)) && !startswith(b, "refs/")])
    error_message = "allowed_branches must be plain branch names such as main (no refs/heads/ prefix, no wildcards)."
  }
}

variable "github_environments" {
  description = "GitHub environments whose jobs may deploy (sub = repo:<org>/<repo>:environment:<name>). Use with environment protection rules (required reviewers, branch restrictions) for a gated production deploy."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for e in var.github_environments : can(regex("^[A-Za-z0-9._ -]{1,255}$", e))])
    error_message = "github_environments must be environment names (letters, digits, space, '.', '_' or '-'; no wildcards)."
  }
}

variable "create_oidc_provider" {
  description = "Create the account's GitHub OIDC provider. There can be only one per URL per account, so set false and pass existing_oidc_provider_arn if another stack already created it."
  type        = bool
  default     = true
}

variable "existing_oidc_provider_arn" {
  description = "ARN of an existing IAM OIDC provider for token.actions.githubusercontent.com. Required when create_oidc_provider = false."
  type        = string
  default     = null

  validation {
    condition     = var.existing_oidc_provider_arn == null ? true : can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:oidc-provider/token\\.actions\\.githubusercontent\\.com$", var.existing_oidc_provider_arn))
    error_message = "existing_oidc_provider_arn must be arn:aws:iam::<account>:oidc-provider/token.actions.githubusercontent.com."
  }

  validation {
    condition     = var.create_oidc_provider || var.existing_oidc_provider_arn != null
    error_message = "Set existing_oidc_provider_arn when create_oidc_provider = false."
  }
}

variable "bucket_arn" {
  description = "ARN of the site's origin bucket (static-site module output bucket_arn)."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:s3:::[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.bucket_arn))
    error_message = "bucket_arn must be an S3 bucket ARN such as arn:aws:s3:::example-site-origin (a bucket, not an object path)."
  }
}

variable "distribution_arn" {
  description = "ARN of the site's CloudFront distribution (static-site module output distribution_arn)."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:cloudfront::[0-9]{12}:distribution/[A-Z0-9]+$", var.distribution_arn))
    error_message = "distribution_arn must look like arn:aws:cloudfront::<account>:distribution/<ID>."
  }
}

variable "kms_key_arn" {
  description = "The origin bucket's KMS key, if it uses SSE-KMS. The role then gets kms:GenerateDataKey and kms:Decrypt on that key only (S3 needs both for uploads). Null for SSE-S3."
  type        = string
  default     = null

  validation {
    condition     = var.kms_key_arn == null ? true : can(regex("^arn:aws[a-z-]*:kms:[a-z0-9-]+:[0-9]{12}:key/[0-9a-f-]{36}$", var.kms_key_arn))
    error_message = "kms_key_arn must be a KMS key ARN, not an alias."
  }
}

variable "max_session_duration" {
  description = "Maximum session length in seconds. A deploy takes minutes; the one-hour minimum is plenty."
  type        = number
  default     = 3600

  validation {
    condition     = var.max_session_duration >= 3600 && var.max_session_duration <= 43200
    error_message = "max_session_duration must be between 3600 and 43200 seconds."
  }
}

variable "permissions_boundary_arn" {
  description = "Optional permissions boundary for the role, where the organisation requires one."
  type        = string
  default     = null
}

variable "tags" {
  description = "Extra tags for every resource."
  type        = map(string)
  default     = {}
}
