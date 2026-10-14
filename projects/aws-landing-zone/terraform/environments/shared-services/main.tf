# Shared-services composition: the network hub. The address plan is read
# from policy/cidr-plan.json, the same file policy/cidr_plan.py checks.

locals {
  cidr_plan = jsondecode(file("${path.module}/../../../policy/cidr-plan.json"))
}

module "network_hub" {
  source = "../../modules/network-hub"

  organization_arn     = var.organization_arn
  azs                  = var.azs
  egress_vpc_cidr      = local.cidr_plan.reserved.egress
  spoke_vpcs           = local.cidr_plan.spokes
  spoke_attachment_ids = var.spoke_attachment_ids
  single_nat_gateway   = var.single_nat_gateway
}
