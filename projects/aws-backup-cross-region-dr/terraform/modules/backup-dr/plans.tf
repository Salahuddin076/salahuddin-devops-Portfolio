# One plan per tier. Rules, lifecycles and copy settings come from
# policy/backup-policy.json through var.backup_plans, so CI's policy check
# and Terraform read the same numbers.

resource "aws_backup_plan" "tier" {
  provider = aws.primary
  for_each = var.backup_plans

  name = "${var.name_prefix}-${each.key}"

  dynamic "rule" {
    for_each = { for r in each.value.rules : r.name => r }

    content {
      rule_name                    = "${each.key}-${rule.key}"
      target_vault_name            = module.primary_vault.vault_name
      schedule                     = rule.value.schedule
      schedule_expression_timezone = var.schedule_timezone
      start_window                 = rule.value.start_window_minutes
      completion_window            = rule.value.completion_window_minutes
      # PITR for supported types; AWS Backup takes snapshots for the rest.
      enable_continuous_backup = var.enable_continuous_backup && rule.value.continuous

      recovery_point_tags = merge(var.tags, {
        (var.selection_tag_key) = each.key
        backup-rule             = rule.key
      })

      # Cold storage only applies to types that support it (for example
      # EFS, DynamoDB with advanced features, EBS archive); the others ignore it.
      lifecycle {
        cold_storage_after = rule.value.cold_storage_after_days
        delete_after       = rule.value.delete_after_days
      }

      # The copy lands in the DR vault and is re-encrypted with the DR
      # vault's key. It has its own lifecycle, which may differ from the
      # primary's (for example longer, if DR is also the archive).
      dynamic "copy_action" {
        for_each = rule.value.copy_to_dr ? [1] : []

        content {
          destination_vault_arn = module.dr_vault.vault_arn

          lifecycle {
            cold_storage_after = rule.value.dr_cold_storage_after_days
            delete_after       = rule.value.dr_delete_after_days
          }
        }
      }
    }
  }

  tags = merge(var.tags, { (var.selection_tag_key) = each.key })
}

# Tier membership by tag. Conditions are ANDed (selection_tag entries are
# ORed), which is what "tier = gold AND not excluded" needs. resources = ["*"]
# scopes the conditions to every supported resource in the account and region.
resource "aws_backup_selection" "tier" {
  provider = aws.primary
  for_each = var.backup_plans

  name         = "${var.name_prefix}-${each.key}"
  plan_id      = aws_backup_plan.tier[each.key].id
  iam_role_arn = aws_iam_role.backup.arn
  resources    = ["*"]

  condition {
    string_equals {
      key   = "aws:ResourceTag/${var.selection_tag_key}"
      value = each.key
    }

    string_not_equals {
      key   = "aws:ResourceTag/${var.exclude_tag_key}"
      value = "true"
    }
  }
}
