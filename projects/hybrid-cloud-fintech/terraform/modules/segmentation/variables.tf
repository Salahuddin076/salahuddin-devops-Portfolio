variable "name_prefix" {
  description = "Prefix for resource names and tags."
  type        = string
}

variable "vpc_id" {
  description = "VPC the security group and (optional) network ACL belong to."
  type        = string
}

variable "zone" {
  description = <<-EOT
    Which side of the PCI-DSS segmentation boundary this instantiation
    guards: "edge" for customer-facing AWS services (CloudFront/ALB/EKS
    ingress), or "regulated" for the cardholder-data-environment-style zone
    (systems of record, replicated databases, anything that talks to
    on-prem over the private link). The regulated zone is held to a
    stricter rule: nothing in it may be reachable from, or reach out to,
    the open internet (0.0.0.0/0).
  EOT
  type        = string

  validation {
    condition     = contains(["edge", "regulated"], var.zone)
    error_message = "zone must be \"edge\" or \"regulated\"."
  }
}

variable "subnet_ids" {
  description = "Subnets for this zone, associated with the zone's network ACL."
  type        = list(string)
  default     = []
}

variable "zone_cidr_blocks" {
  description = "This zone's own subnet CIDR blocks, used for intra-zone NACL rules."
  type        = list(string)
  default     = []
}

variable "allowed_ingress" {
  description = <<-EOT
    The explicit allow-list of inbound flows into this zone. There is no
    implicit default: a security group with an empty list allows nothing
    in. Each entry must name either cidr_blocks or source_security_group_id,
    never both, and for the "regulated" zone cidr_blocks must never contain
    0.0.0.0/0 (enforced by a plan-time precondition, not just convention).
  EOT
  type = list(object({
    description              = string
    from_port                = number
    to_port                  = number
    protocol                 = string
    cidr_blocks              = optional(list(string))
    source_security_group_id = optional(string)
  }))
  default = []
}

variable "allowed_egress" {
  description = <<-EOT
    The explicit allow-list of outbound flows from this zone. There is no
    default allow-all egress rule in this module (unlike a bare AWS default
    security group): everything not listed here is denied. For the
    "regulated" zone, cidr_blocks must never contain 0.0.0.0/0 -- egress to
    on-prem systems of record goes over the private connectivity module's
    link to a documentation-safe on-prem CIDR, and egress to the SIEM/log
    pipeline goes to the controls zone, never to the open internet.
  EOT
  type = list(object({
    description                   = string
    from_port                     = number
    to_port                       = number
    protocol                      = string
    cidr_blocks                   = optional(list(string))
    destination_security_group_id = optional(string)
  }))
  default = []
}

variable "enable_network_acl" {
  description = "Also create a network ACL for this zone's subnets with explicit numbered allow rules and an explicit deny-all floor. Recommended true for the regulated zone (defense in depth under a PCI-DSS segmentation boundary: a security-group misconfiguration on one instance doesn't open the whole subnet)."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Additional tags merged onto every resource this module creates."
  type        = map(string)
  default     = {}
}
