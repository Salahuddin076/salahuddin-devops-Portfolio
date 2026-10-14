variable "region" {
  description = "Region of the network hub (must be in the SCP region allow-list)."
  type        = string
  default     = "us-east-1"
}

variable "network_role_arn" {
  description = "Deployer role in the shared-services account."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:role/.+$", var.network_role_arn))
    error_message = "network_role_arn must be an IAM role ARN."
  }
}

variable "organization_arn" {
  description = "Organization ARN (management environment output organization_arn)."
  type        = string
}

variable "azs" {
  description = "Availability zones for the egress VPC."
  type        = list(string)
}

variable "spoke_attachment_ids" {
  description = "Spoke name -> TGW attachment ID, added after each spoke attaches."
  type        = map(string)
  default     = {}
}

variable "single_nat_gateway" {
  description = "One NAT gateway for all AZs (cheaper, less resilient)."
  type        = bool
  default     = false
}

variable "cost_center" {
  description = "CostCenter tag (one of the tag policy values)."
  type        = string
  default     = "CC-9000"
}
