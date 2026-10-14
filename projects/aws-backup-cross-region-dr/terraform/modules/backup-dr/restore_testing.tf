# AWS Backup native restore testing in the DR region, against the DR vault:
# the test proves the copy a regional failover would actually use. AWS
# Backup restores the latest recovery point inside the selection window,
# waits up to validation_window_hours for a validation result, then deletes
# the restored resource itself.

resource "aws_backup_restore_testing_plan" "this" {
  provider = aws.dr
  count    = var.restore_testing.enabled ? 1 : 0

  # Restore testing names allow letters, digits and underscores only.
  name                         = "${local.name_us}_restore_tests"
  schedule_expression          = var.restore_testing.schedule
  schedule_expression_timezone = var.schedule_timezone
  start_window_hours           = var.restore_testing.start_window_hours

  recovery_point_selection {
    algorithm             = "LATEST_WITHIN_WINDOW"
    include_vaults        = [module.dr_vault.vault_arn]
    recovery_point_types  = ["SNAPSHOT"]
    selection_window_days = var.restore_testing.selection_window_days
  }

  tags = var.tags
}

resource "aws_backup_restore_testing_selection" "this" {
  provider = aws.dr
  for_each = var.restore_testing.enabled ? var.restore_testing.selections : {}

  name                      = each.key
  restore_testing_plan_name = aws_backup_restore_testing_plan.this[0].name
  protected_resource_type   = each.value.resource_type
  iam_role_arn              = aws_iam_role.restore_testing.arn
  validation_window_hours   = each.value.validation_window_hours
  # e.g. RDS: dbsubnetgroupname and vpcsecuritygroupids for an isolated test
  # subnet, so a restored database is never reachable from production.
  restore_metadata_overrides = each.value.restore_metadata_overrides

  # Tag conditions select the protected resources (the provider accepts
  # either conditions or explicit ARNs, not both).
  protected_resource_conditions {
    string_equals {
      key   = "aws:ResourceTag/${var.selection_tag_key}"
      value = each.value.tier
    }
  }
}
