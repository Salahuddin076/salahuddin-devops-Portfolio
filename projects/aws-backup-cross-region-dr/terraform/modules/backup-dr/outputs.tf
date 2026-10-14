output "primary_vault_arn" {
  description = "Primary backup vault ARN."
  value       = module.primary_vault.vault_arn
}

output "dr_vault_arn" {
  description = "DR backup vault ARN (copy destination, restore-testing source)."
  value       = module.dr_vault.vault_arn
}

output "primary_kms_key_arn" {
  description = "CMK of the primary vault."
  value       = module.primary_vault.kms_key_arn
}

output "dr_kms_key_arn" {
  description = "CMK of the DR vault, in the DR region. Copies are re-encrypted with it."
  value       = module.dr_vault.kms_key_arn
}

output "vault_lock_mode" {
  description = "governance, compliance or disabled (both vaults)."
  value       = module.primary_vault.vault_lock_mode
}

output "backup_plan_ids" {
  description = "Backup plan IDs by tier."
  value       = { for tier, plan in aws_backup_plan.tier : tier => plan.id }
}

output "backup_role_arn" {
  description = "AWS Backup service role used by the plans."
  value       = aws_iam_role.backup.arn
}

output "restore_testing_role_arn" {
  description = "AWS Backup role in the DR account used for restore testing and manual DR restores."
  value       = aws_iam_role.restore_testing.arn
}

output "notification_topic_arns" {
  description = "Encrypted SNS topics receiving vault notifications, job-failure events and alarms."
  value = {
    primary = module.primary_vault.notification_topic_arn
    dr      = module.dr_vault.notification_topic_arn
  }
}

output "restore_testing_plan_arn" {
  description = "Restore testing plan ARN, or null when disabled."
  value       = try(aws_backup_restore_testing_plan.this[0].arn, null)
}

output "restore_validator_function" {
  description = "Restore validator Lambda name, or null when disabled."
  value       = try(aws_lambda_function.validator[0].function_name, null)
}

output "audit_framework_arn" {
  description = "Backup Audit Manager framework ARN, or null when disabled."
  value       = try(aws_backup_framework.this[0].arn, null)
}

output "cross_account" {
  description = "True when aws.dr points at a different account than aws.primary."
  value       = local.cross_account
}
