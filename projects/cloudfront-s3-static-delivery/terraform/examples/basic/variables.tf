variable "region" {
  description = "Region for the origin bucket. CloudFront is global; its certificate and logs go to us-east-1 regardless."
  type        = string
  default     = "eu-west-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.region))
    error_message = "region must look like an AWS region code, e.g. eu-west-1."
  }
}

variable "project" {
  description = "Value for the project default tag."
  type        = string
  default     = "cloudfront-s3-static-delivery"
}

variable "owner" {
  description = "Value for the owner default tag (team accountable for the stack)."
  type        = string
  default     = "web-platform"
}

variable "name_prefix" {
  description = "Prefix for resource names."
  type        = string
  default     = "static-demo"
}

variable "domain_names" {
  description = "Hostnames to serve. The module validates the format."
  type        = list(string)
  default     = ["example.com", "www.example.com"]
}

variable "hosted_zone_id" {
  description = "Existing public hosted zone for domain_names."
  type        = string
  default     = "Z0123456789EXAMPLE0AB"
}

variable "price_class" {
  description = "CloudFront price class (validated in the module)."
  type        = string
  default     = "PriceClass_100"
}

variable "web_acl_arn" {
  description = "Optional CLOUDFRONT-scope WAF web ACL ARN (us-east-1)."
  type        = string
  default     = null
}

variable "github_repository" {
  description = "<org>/<repo> allowed to deploy."
  type        = string
  default     = "example-org/example-site"
}

variable "github_environments" {
  description = "GitHub environments allowed to deploy. The workflow's deploy job uses `environment: production`, so its token's sub is the environment form."
  type        = list(string)
  default     = ["production"]
}

variable "existing_oidc_provider_arn" {
  description = "Existing GitHub OIDC provider ARN, if another stack in the account already created it. Null creates one."
  type        = string
  default     = null
}
