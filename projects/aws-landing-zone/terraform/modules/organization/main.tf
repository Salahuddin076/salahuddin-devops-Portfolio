# AWS Organization, OU tree and member accounts.
#
# OU tree (keys in brackets are used by every other module and by
# policy/attachments.json):
#
#   Root [root]
#   ├── Security        [security]        log archive, security tooling
#   ├── Infrastructure  [infrastructure]  shared services, network hub
#   ├── Workloads       [workloads]
#   │   ├── Prod        [prod]
#   │   └── NonProd     [nonprod]
#   ├── Sandbox         [sandbox]         experiments, own budget, no hub access
#   └── Suspended       [suspended]       deny-all quarantine before closure
#
# OUs follow policy boundaries, not the org chart: see
# docs/decisions/0001-ou-by-policy-boundary.md.

resource "aws_organizations_organization" "this" {
  feature_set                   = "ALL"
  aws_service_access_principals = var.aws_service_access_principals
  enabled_policy_types = [
    "SERVICE_CONTROL_POLICY",
    "TAG_POLICY",
  ]

  lifecycle {
    # Deleting the organization would orphan every account. Remove this
    # block deliberately, never through a routine apply.
    prevent_destroy = true
  }
}

locals {
  root_id = aws_organizations_organization.this.roots[0].id

  top_level_ous = {
    security       = "Security"
    infrastructure = "Infrastructure"
    workloads      = "Workloads"
    sandbox        = "Sandbox"
    suspended      = "Suspended"
  }

  workload_ous = {
    prod    = "Prod"
    nonprod = "NonProd"
  }
}

resource "aws_organizations_organizational_unit" "top" {
  for_each = local.top_level_ous

  name      = each.value
  parent_id = local.root_id
  tags      = var.tags
}

resource "aws_organizations_organizational_unit" "workloads" {
  for_each = local.workload_ous

  name      = each.value
  parent_id = aws_organizations_organizational_unit.top["workloads"].id
  tags      = var.tags
}

locals {
  ou_ids = merge(
    { root = local.root_id },
    { for k, ou in aws_organizations_organizational_unit.top : k => ou.id },
    { for k, ou in aws_organizations_organizational_unit.workloads : k => ou.id },
  )
}

resource "aws_organizations_account" "this" {
  for_each = var.accounts

  name      = each.value.name
  email     = each.value.email
  parent_id = local.ou_ids[each.value.ou]

  # Removing an account from Terraform must never close it. Closing is a
  # deliberate, manual step after the account has sat in Suspended (see
  # docs/operations.md). With close_on_deletion = false a destroy only
  # removes the account from the organization, and prevent_destroy blocks
  # even that.
  close_on_deletion          = false
  role_name                  = "OrganizationAccountAccessRole"
  iam_user_access_to_billing = "DENY"

  tags = merge(var.tags, { Name = each.value.name })

  lifecycle {
    prevent_destroy = true
    # role_name and iam_user_access_to_billing are only read at creation;
    # AWS does not return them, so imported accounts would show a diff.
    ignore_changes = [role_name, iam_user_access_to_billing]
  }
}

# RAM sharing with the organization, so the network hub can share the
# Transit Gateway with OUs without per-account invitations.
resource "aws_ram_sharing_with_organization" "this" {
  depends_on = [aws_organizations_organization.this]
}

resource "aws_organizations_delegated_administrator" "this" {
  for_each = var.delegated_administrators

  account_id        = aws_organizations_account.this[each.value].id
  service_principal = each.key
}

resource "aws_guardduty_organization_admin_account" "this" {
  count = var.security_tooling_account_key == null ? 0 : 1

  admin_account_id = aws_organizations_account.this[var.security_tooling_account_key].id
  depends_on       = [aws_organizations_organization.this]
}

resource "aws_securityhub_organization_admin_account" "this" {
  count = var.security_tooling_account_key == null ? 0 : 1

  admin_account_id = aws_organizations_account.this[var.security_tooling_account_key].id
  depends_on       = [aws_organizations_organization.this]
}
