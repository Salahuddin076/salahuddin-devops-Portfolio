variable "name" {
  description = "Spoke name: a key of cidr_plan. The CIDR is looked up, never typed twice."
  type        = string
}

variable "cidr_plan" {
  description = "The whole address plan (spokes map of policy/cidr-plan.json). Passing the whole plan lets this module refuse to build a VPC from an overlapping plan."
  type = map(object({
    cidr        = string
    environment = string
    account     = optional(string)
  }))

  validation {
    condition     = alltrue([for v in values(var.cidr_plan) : can(cidrsubnet(v.cidr, 0, 0)) && try(cidrsubnet(v.cidr, 0, 0) == v.cidr, false) && endswith(v.cidr, "/16")])
    error_message = "Every plan entry must be a /16 network address with no host bits set."
  }

  validation {
    condition = alltrue([
      for v in values(var.cidr_plan) : anytrue([
        for r in ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"] :
        try(tonumber(split("/", v.cidr)[1]) >= tonumber(split("/", r)[1]) && cidrsubnet("${cidrhost(v.cidr, 0)}/${split("/", r)[1]}", 0, 0) == r, false)
      ])
    ])
    error_message = "Every plan entry must be inside RFC 1918."
  }

  validation {
    # All entries are canonical /16s (checked above), so two entries overlap
    # exactly when their network addresses are equal.
    condition     = length(distinct([for v in values(var.cidr_plan) : v.cidr])) == length(var.cidr_plan)
    error_message = "The address plan contains overlapping /16s."
  }
}

variable "reserved_cidrs" {
  description = "Blocks no spoke may use (egress VPC, on-premises), the reserved map of policy/cidr-plan.json."
  type        = map(string)
  default     = {}
}

variable "azs" {
  description = "Availability zones (2 or 3)."
  type        = list(string)

  validation {
    condition     = length(var.azs) >= 2 && length(var.azs) <= 3
    error_message = "Use 2 or 3 availability zones."
  }
}

variable "transit_gateway_id" {
  description = "Shared Transit Gateway ID (from the network hub, visible through RAM)."
  type        = string

  validation {
    condition     = can(regex("^tgw-[0-9a-f]{8,17}$", var.transit_gateway_id))
    error_message = "transit_gateway_id must look like tgw-0123456789abcdef0."
  }
}

variable "tags" {
  description = "Tags for spoke resources."
  type        = map(string)
  default     = {}
}
