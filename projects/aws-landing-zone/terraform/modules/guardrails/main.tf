# Service control policies and the tag policy, attached per OU.
#
# Policies are JSON files under policies/. Static files are loaded with
# file(); *.json.tftpl files are rendered with templatefile(). Every document
# is minified with jsonencode(jsondecode(...)), so the size AWS counts is the
# minified size, which is also what policy/check_scps.py measures.
#
# Limits that shape the layout (AWS Organizations quotas):
#   - an SCP document is at most 5,120 characters;
#   - at most 5 SCPs are attached directly to one root, OU or account, and
#     the AWS-managed FullAWSAccess counts toward the 5.
# SCPs never restrict the management account or service-linked roles.

locals {
  scp_dir = "${path.module}/policies/scp"

  template_vars = {
    allowed_regions       = var.allowed_regions
    exempt_principal_arns = var.exempt_principal_arns
  }

  scp_documents = merge(
    {
      for f in fileset(local.scp_dir, "*.json") :
      trimsuffix(f, ".json") => jsonencode(jsondecode(file("${local.scp_dir}/${f}")))
    },
    {
      for f in fileset(local.scp_dir, "*.json.tftpl") :
      trimsuffix(f, ".json.tftpl") => jsonencode(jsondecode(templatefile("${local.scp_dir}/${f}", local.template_vars)))
    },
  )

  scp_descriptions = {
    "deny-all"                       = "Suspended OU: deny every action."
    "deny-leave-organization"        = "Deny organizations:LeaveOrganization."
    "deny-root-user"                 = "Deny all actions by the account root user."
    "protect-s3-public-access-block" = "Deny changes to the account-level S3 public access block (break-glass excepted)."
    "protect-security-services"      = "Deny disabling or deleting CloudTrail, GuardDuty, Config and Security Hub."
    "region-allowlist"               = "Deny regional services outside the allowed regions; global services exempt."
    "require-imdsv2"                 = "Require IMDSv2 on ec2:RunInstances and lock metadata options."
    "require-tags-on-create"         = "Deny EC2 and RDS creation without CostCenter, Owner and Environment tags."
  }

  # One attachment per (target, policy), skipping the AWS-managed policy.
  scp_attachments = {
    for pair in flatten([
      for target, policies in var.attachments : [
        for p in policies : { target = target, policy = p } if p != "FullAWSAccess"
      ]
    ]) : "${pair.target}/${pair.policy}" => pair
  }
}

resource "aws_organizations_policy" "scp" {
  for_each = local.scp_documents

  name        = "${var.name_prefix}-${each.key}"
  description = lookup(local.scp_descriptions, each.key, "Landing zone guardrail ${each.key}.")
  type        = "SERVICE_CONTROL_POLICY"
  content     = each.value
  tags        = var.tags

  lifecycle {
    precondition {
      condition     = length(each.value) <= 5120
      error_message = "SCP ${each.key} is ${length(each.value)} characters minified; the AWS limit is 5,120."
    }
  }
}

resource "aws_organizations_policy_attachment" "scp" {
  for_each = local.scp_attachments

  policy_id = aws_organizations_policy.scp[each.value.policy].id
  target_id = var.target_ids[each.value.target]

  lifecycle {
    precondition {
      condition     = contains(keys(var.target_ids), each.value.target) && contains(keys(local.scp_documents), each.value.policy)
      error_message = "Attachment ${each.key}: unknown target or policy name."
    }
  }
}

# Tag policy: standardizes the keys and allowed values of CostCenter, Owner
# and Environment, and blocks non-compliant values for the listed resource
# types. A tag policy cannot require a tag to be present; the
# require-tags-on-create SCP does that for EC2 and RDS in Workloads.
resource "aws_organizations_policy" "required_tags" {
  name        = "${var.name_prefix}-required-tags"
  description = "Allowed values for CostCenter, Owner and Environment."
  type        = "TAG_POLICY"
  content     = jsonencode(jsondecode(file("${path.module}/policies/tag/required-tags.json")))
  tags        = var.tags
}

resource "aws_organizations_policy_attachment" "required_tags" {
  for_each = toset(var.tag_policy_targets)

  policy_id = aws_organizations_policy.required_tags.id
  target_id = var.target_ids[each.value]
}
