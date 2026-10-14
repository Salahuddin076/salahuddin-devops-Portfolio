# Workload account composition: the account baseline, plus a spoke VPC
# attached to the shared Transit Gateway when spoke_name is set.

locals {
  cidr_plan = jsondecode(file("${path.module}/../../../policy/cidr-plan.json"))
}

module "baseline" {
  source = "../../modules/account-baseline"

  monthly_budget_usd  = var.monthly_budget_usd
  budget_alert_emails = var.budget_alert_emails
}

module "spoke_vpc" {
  source = "../../modules/spoke-vpc"
  count  = var.spoke_name == null ? 0 : 1

  name               = var.spoke_name
  cidr_plan          = local.cidr_plan.spokes
  reserved_cidrs     = local.cidr_plan.reserved
  azs                = var.azs
  transit_gateway_id = var.transit_gateway_id
}

check "spoke_needs_transit_gateway" {
  assert {
    condition     = var.spoke_name == null || var.transit_gateway_id != null
    error_message = "transit_gateway_id is required when spoke_name is set."
  }
}
