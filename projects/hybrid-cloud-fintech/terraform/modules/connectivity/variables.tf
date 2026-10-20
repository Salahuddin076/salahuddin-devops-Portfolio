variable "name_prefix" {
  description = "Prefix for connectivity resource names and tags."
  type        = string
}

variable "vpc_id" {
  description = "VPC the AWS Virtual Private Gateway attaches to."
  type        = string
}

variable "amazon_side_asn" {
  description = "BGP ASN on the AWS side of the Virtual Private Gateway. Must be a private-use ASN (not the default 64512) when an on-prem device also uses 64512."
  type        = number
  default     = 64512
}

variable "on_prem_gateways" {
  description = <<-EOT
    The on-premises edge of each redundant tunnel. Two entries are required
    (two independent on-prem devices, e.g. a pair of firewalls/routers in
    different racks or sites) so the loss of one device or one ISP uplink
    does not take down private connectivity. Every IP here must be a
    documentation-safe address (TEST-NET range) -- this project never
    points at a real on-prem device.
  EOT
  type = list(object({
    name               = string
    bgp_asn            = number
    ip_address         = string
    on_prem_cidr_block = string
  }))

  validation {
    condition     = length(var.on_prem_gateways) >= 2
    error_message = "on_prem_gateways must list at least 2 devices: a single customer gateway is a single point of failure for the hybrid link."
  }

  validation {
    condition = alltrue([
      for g in var.on_prem_gateways :
      can(regex("^(192\\.0\\.2\\.|198\\.51\\.100\\.|203\\.0\\.113\\.)", g.ip_address))
    ])
    error_message = "on_prem_gateways[*].ip_address must be in a TEST-NET documentation range (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) -- no real public IPs in this repository."
  }

  validation {
    condition     = length(distinct([for g in var.on_prem_gateways : g.ip_address])) == length(var.on_prem_gateways)
    error_message = "on_prem_gateways[*].ip_address must be unique: redundant tunnels terminate on distinct on-prem devices."
  }
}

variable "static_routes_only" {
  description = "Use static routing instead of BGP for the VPN connections. Static routing is simpler to validate here; a real deployment with dynamic on-prem routers typically prefers BGP for faster failover."
  type        = bool
  default     = false
}

variable "route_table_ids" {
  description = "Route tables that should learn on-prem routes via the Virtual Private Gateway (propagation). Typically the route tables for the 'regulated' subnets that talk to on-prem systems of record."
  type        = list(string)
  default     = []
}

variable "tunnel_inside_cidr_blocks" {
  description = <<-EOT
    Optional /30 CIDR blocks (from the 169.254.0.0/16 APIPA range, excluding
    the AWS-reserved ones) for each of the 4 tunnels (2 per VPN connection).
    Leave empty to let AWS assign them. Set explicitly to make the tunnel
    topology reproducible across applies, which some change-control
    processes require.
  EOT
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Additional tags merged onto every resource this module creates."
  type        = map(string)
  default     = {}
}
