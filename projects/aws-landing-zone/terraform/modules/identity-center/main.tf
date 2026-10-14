# IAM Identity Center permission sets and group-to-account assignments.
#
# Runs in the management account (or the Identity Center delegated
# administrator). Access is granted to groups only, never to users, so
# joiners and leavers are handled in the identity provider.

data "aws_ssoadmin_instances" "this" {}

data "aws_partition" "current" {}

locals {
  instance_arn = tolist(data.aws_ssoadmin_instances.this.arns)[0]
  partition    = data.aws_partition.current.partition

  permission_sets = {
    AdministratorAccess = {
      description      = "Full administrator. Short session; use for break-fix, not daily work."
      managed_policies = ["arn:${local.partition}:iam::aws:policy/AdministratorAccess"]
    }
    PowerUserAccess = {
      description      = "Build and operate workloads; no IAM, Organizations or account changes."
      managed_policies = ["arn:${local.partition}:iam::aws:policy/PowerUserAccess"]
    }
    ReadOnlyAccess = {
      description      = "Read-only access for investigation and audit."
      managed_policies = ["arn:${local.partition}:iam::aws:policy/ReadOnlyAccess"]
    }
    BillingAccess = {
      description      = "Billing, cost and budget management."
      managed_policies = ["arn:${local.partition}:iam::aws:policy/job-function/Billing"]
    }
  }

  managed_policy_attachments = {
    for pair in flatten([
      for ps, cfg in local.permission_sets : [
        for arn in cfg.managed_policies : { permission_set = ps, policy_arn = arn }
      ]
    ]) : "${pair.permission_set}/${basename(pair.policy_arn)}" => pair
  }

  # group/account/permission-set triples.
  account_assignments = {
    for a in flatten([
      for group, accounts in var.assignments : [
        for account, sets in accounts : [
          for ps in sets : { group = group, account = account, permission_set = ps }
        ]
      ]
    ]) : "${a.group}/${a.account}/${a.permission_set}" => a
  }
}

resource "aws_ssoadmin_permission_set" "this" {
  for_each = local.permission_sets

  name             = each.key
  description      = each.value.description
  instance_arn     = local.instance_arn
  session_duration = var.session_durations[each.key]
  tags             = var.tags
}

resource "aws_ssoadmin_managed_policy_attachment" "this" {
  for_each = local.managed_policy_attachments

  instance_arn       = local.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.this[each.value.permission_set].arn
  managed_policy_arn = each.value.policy_arn
}

# PowerUserAccess already excludes most of IAM and Organizations; this makes
# the boundary explicit. IAM writes are denied except on service-linked
# roles (services create them on first use); reads and iam:PassRole stay, so
# workloads can still be deployed with existing roles.
data "aws_iam_policy_document" "power_user_deny" {
  statement {
    sid    = "DenyIamWrites"
    effect = "Deny"
    actions = [
      "iam:Add*",
      "iam:Attach*",
      "iam:Create*",
      "iam:Delete*",
      "iam:Detach*",
      "iam:Put*",
      "iam:Remove*",
      "iam:Tag*",
      "iam:Untag*",
      "iam:Update*",
    ]
    not_resources = ["arn:${local.partition}:iam::*:role/aws-service-role/*"]
  }

  statement {
    sid       = "DenyOrganizationsAndAccount"
    effect    = "Deny"
    actions   = ["organizations:*", "account:*", "sso:*", "identitystore:*"]
    resources = ["*"]
  }
}

resource "aws_ssoadmin_permission_set_inline_policy" "power_user" {
  instance_arn       = local.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.this["PowerUserAccess"].arn
  inline_policy      = data.aws_iam_policy_document.power_user_deny.json
}

resource "aws_ssoadmin_account_assignment" "this" {
  for_each = local.account_assignments

  instance_arn       = local.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.this[each.value.permission_set].arn
  principal_type     = "GROUP"
  principal_id       = var.group_ids[each.value.group]
  target_type        = "AWS_ACCOUNT"
  target_id          = var.account_ids[each.value.account]

  lifecycle {
    precondition {
      condition     = contains(keys(var.group_ids), each.value.group) && contains(keys(var.account_ids), each.value.account)
      error_message = "Assignment ${each.key}: unknown group or account key."
    }
  }
}
