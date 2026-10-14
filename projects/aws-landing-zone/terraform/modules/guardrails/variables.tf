variable "name_prefix" {
  description = "Prefix for policy names."
  type        = string
  default     = "lz"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.name_prefix))
    error_message = "name_prefix must be 2-21 lower-case letters, digits or hyphens, starting with a letter."
  }
}

variable "target_ids" {
  description = "Target key -> root or OU ID (the organization module's ou_ids output)."
  type        = map(string)
}

variable "attachments" {
  description = "Target key -> SCP names attached directly to it, the 'attachments' object of policy/attachments.json. FullAWSAccess is AWS-managed and already attached, so it is listed for the 5-per-target count but not managed here."
  type        = map(list(string))

  validation {
    condition     = alltrue([for t, ps in var.attachments : length(ps) <= 5])
    error_message = "AWS allows at most 5 SCPs directly attached to a target, and FullAWSAccess counts toward the 5."
  }

  validation {
    condition     = alltrue([for t, ps in var.attachments : contains(ps, "FullAWSAccess")])
    error_message = "List FullAWSAccess on every target: without an Allow at every level of the OU path, everything below is implicitly denied."
  }
}

variable "allowed_regions" {
  description = "Regions the region allow-list SCP permits for regional services."
  type        = list(string)

  validation {
    condition     = length(var.allowed_regions) > 0 && alltrue([for r in var.allowed_regions : can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", r))])
    error_message = "allowed_regions must be a non-empty list of region names such as eu-west-1."
  }
}

variable "exempt_principal_arns" {
  description = "Principal ARN patterns exempt from the region allow-list (break-glass and security automation roles)."
  type        = list(string)

  validation {
    condition     = alltrue([for a in var.exempt_principal_arns : startswith(a, "arn:aws:iam::")])
    error_message = "exempt_principal_arns must be IAM ARN patterns (arn:aws:iam::...)."
  }
}

variable "tag_policy_targets" {
  description = "Target keys the required-tags tag policy is attached to."
  type        = list(string)
  default     = ["root"]
}

variable "tags" {
  description = "Tags for the policies."
  type        = map(string)
  default     = {}
}
