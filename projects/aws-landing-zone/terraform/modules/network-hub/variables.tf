variable "name_prefix" {
  description = "Prefix for network resource names."
  type        = string
  default     = "lz"
}

variable "organization_arn" {
  description = "Organization ARN; the Transit Gateway is shared with the whole organization through RAM."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:organizations::[0-9]{12}:organization/o-[a-z0-9]{10,32}$", var.organization_arn))
    error_message = "organization_arn must be an organization ARN (arn:aws:organizations::<account>:organization/o-...)."
  }
}

variable "azs" {
  description = "Availability zones for the egress VPC (2 or 3)."
  type        = list(string)

  validation {
    condition     = length(var.azs) >= 2 && length(var.azs) <= 3
    error_message = "Use 2 or 3 availability zones."
  }
}

variable "egress_vpc_cidr" {
  description = "CIDR of the centralized egress VPC (a reserved block in the address plan)."
  type        = string
  default     = "10.0.0.0/16"

  validation {
    condition     = can(cidrsubnet(var.egress_vpc_cidr, 0, 0)) && try(cidrsubnet(var.egress_vpc_cidr, 0, 0) == var.egress_vpc_cidr, false) && endswith(var.egress_vpc_cidr, "/16")
    error_message = "egress_vpc_cidr must be a /16 network address with no host bits set."
  }
}

variable "spoke_vpcs" {
  description = "IPAM-like address plan: spoke name -> { cidr, environment, account }. The spokes map of policy/cidr-plan.json. Every spoke is a non-overlapping RFC 1918 /16; environment is prod, nonprod or shared and decides the route table."
  type = map(object({
    cidr        = string
    environment = string
    account     = optional(string)
  }))

  validation {
    condition     = alltrue([for v in values(var.spoke_vpcs) : can(cidrsubnet(v.cidr, 0, 0)) && try(cidrsubnet(v.cidr, 0, 0) == v.cidr, false)])
    error_message = "Every spoke cidr must be a valid network address with no host bits set (10.16.0.0/16, not 10.16.1.0/16)."
  }

  validation {
    condition     = alltrue([for v in values(var.spoke_vpcs) : endswith(v.cidr, "/16")])
    error_message = "Every spoke must be a /16."
  }

  validation {
    condition = alltrue([
      for v in values(var.spoke_vpcs) : anytrue([
        for r in ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"] :
        try(tonumber(split("/", v.cidr)[1]) >= tonumber(split("/", r)[1]) && cidrsubnet("${cidrhost(v.cidr, 0)}/${split("/", r)[1]}", 0, 0) == r, false)
      ])
    ])
    error_message = "Every spoke cidr must be inside RFC 1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)."
  }

  validation {
    condition     = alltrue([for v in values(var.spoke_vpcs) : contains(["prod", "nonprod", "shared"], v.environment)])
    error_message = "Spoke environment must be prod, nonprod or shared."
  }
}

variable "spoke_attachment_ids" {
  description = "Spoke name -> Transit Gateway attachment ID, filled in once a spoke account has attached (two-phase: see docs/operations.md). Only these spokes get route table associations and propagations."
  type        = map(string)
  default     = {}

  validation {
    condition     = alltrue([for id in values(var.spoke_attachment_ids) : can(regex("^tgw-attach-[0-9a-f]{8,17}$", id))])
    error_message = "spoke_attachment_ids values must be Transit Gateway attachment IDs (tgw-attach-...)."
  }
}

variable "amazon_side_asn" {
  description = "Private ASN of the Transit Gateway."
  type        = number
  default     = 64512
}

variable "single_nat_gateway" {
  description = "One NAT gateway instead of one per AZ. Cheaper, but an AZ outage takes all egress with it. Fine for nonprod-only hubs."
  type        = bool
  default     = false
}

variable "blackhole_cidrs" {
  description = "Supernets blackholed in every TGW route table. Propagated /16s are more specific and still win; anything else private (including the other environment) is dropped instead of following 0.0.0.0/0 to the egress VPC and hairpinning back."
  type        = list(string)
  default     = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
}

variable "tags" {
  description = "Tags for network resources."
  type        = map(string)
  default     = {}
}
