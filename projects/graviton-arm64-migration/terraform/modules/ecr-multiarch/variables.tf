variable "name" {
  description = "ECR repository name, for example \"example/checkout-api\". One repository holds one multi-arch manifest list per tag: `docker buildx build --platform linux/amd64,linux/arm64 --push` publishes a single tag that resolves to the right image per node architecture."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$", var.name))
    error_message = "name must be a valid ECR repository name (lowercase alphanumerics, and ._-/ as separators)."
  }
}

variable "image_tag_mutability" {
  description = "IMMUTABLE prevents a tag (and therefore a manifest list) from being overwritten after push, which is what makes \"rollback = remove the ARM64 affinity\" safe: the tag workloads already run never changes shape."
  type        = string
  default     = "IMMUTABLE"

  validation {
    condition     = contains(["IMMUTABLE", "MUTABLE"], var.image_tag_mutability)
    error_message = "image_tag_mutability must be IMMUTABLE or MUTABLE."
  }
}

variable "scan_on_push" {
  description = "Enable basic image scanning on every push. Each platform's layer is scanned independently (see docs/compatibility-checklist.md): an arm64-only CVE in a base image package would be invisible if only the amd64 digest were scanned."
  type        = bool
  default     = true
}

variable "enhanced_scanning" {
  description = "Use Amazon Inspector enhanced scanning (continuous, OS + language package CVEs) instead of the basic one-time scan. Costs more; worth it during an active migration when both architectures are being pushed frequently."
  type        = bool
  default     = false
}

variable "untagged_image_expiry_days" {
  description = "Lifecycle policy: expire untagged images (dangling manifest-list layers left behind by buildx) after this many days. 0 disables the rule."
  type        = number
  default     = 14

  validation {
    condition     = var.untagged_image_expiry_days >= 0
    error_message = "untagged_image_expiry_days must be 0 or greater."
  }
}

variable "kms_key_arn" {
  description = "Existing KMS key for repository encryption. null uses AES256 (ECR-managed) encryption instead of a CMK."
  type        = string
  default     = null

  validation {
    condition     = var.kms_key_arn == null || can(regex("^arn:aws[a-z-]*:kms:[a-z0-9-]+:[0-9]{12}:key/[a-zA-Z0-9-]+$", var.kms_key_arn))
    error_message = "kms_key_arn must be a KMS key ARN, or null."
  }
}

variable "tags" {
  description = "Extra tags for the repository (on top of the provider's default_tags)."
  type        = map(string)
  default     = {}
}
