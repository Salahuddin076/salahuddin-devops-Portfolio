# Optional AWS Backup Audit Manager framework. It evaluates continuously
# through AWS Config, so Config must be recording in the primary region.

resource "aws_backup_framework" "this" {
  provider = aws.primary
  count    = var.audit_framework.enabled ? 1 : 0

  # Framework names allow letters, digits and underscores, starting with a letter.
  name        = "${local.name_us}_backup_controls"
  description = "Backup frequency and retention, encrypted recovery points, cross-region copies for gold."

  control {
    name = "BACKUP_PLAN_MIN_FREQUENCY_AND_MIN_RETENTION_CHECK"

    input_parameter {
      name  = "requiredFrequencyUnit"
      value = "days"
    }

    input_parameter {
      name  = "requiredFrequencyValue"
      value = tostring(var.audit_framework.required_frequency_days)
    }

    input_parameter {
      name  = "requiredRetentionDays"
      value = tostring(var.audit_framework.required_retention_days)
    }
  }

  control {
    name = "BACKUP_RECOVERY_POINT_ENCRYPTED"
  }

  control {
    name = "BACKUP_RESOURCES_PROTECTED_BY_CROSS_REGION"

    input_parameter {
      name  = "crossRegionList"
      value = local.dr_region
    }

    scope {
      tags = { (var.selection_tag_key) = "gold" }
    }
  }

  tags = var.tags
}
