variable "region" {
  description = "AWS region for the reference wiring."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix for every resource name and tag."
  type        = string
  default     = "hcf-ref"
}

variable "vpc_cidr_block" {
  description = "CIDR block for the reference VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "edge_subnet_cidr_block" {
  description = "Subnet CIDR for the edge zone (EKS customer-facing services)."
  type        = string
  default     = "10.42.0.0/24"
}

variable "regulated_subnet_cidr_block" {
  description = "Subnet CIDR for the regulated zone (systems of record, replicated databases)."
  type        = string
  default     = "10.42.1.0/24"
}

variable "on_prem_gateways" {
  description = "Two documentation-safe (TEST-NET) on-prem device descriptors for the redundant VPN connections."
  type = list(object({
    name               = string
    bgp_asn            = number
    ip_address         = string
    on_prem_cidr_block = string
  }))
  default = [
    {
      name               = "onprem-dc1-fw"
      bgp_asn            = 65000
      ip_address         = "203.0.113.10"
      on_prem_cidr_block = "198.51.100.0/24"
    },
    {
      name               = "onprem-dc2-fw"
      bgp_asn            = 65000
      ip_address         = "203.0.113.11"
      on_prem_cidr_block = "198.51.100.0/24"
    },
  ]
}
