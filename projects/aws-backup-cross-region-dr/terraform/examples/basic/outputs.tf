output "primary_vault_arn" {
  description = "Primary backup vault ARN."
  value       = module.backup_dr.primary_vault_arn
}

output "dr_vault_arn" {
  description = "DR backup vault ARN."
  value       = module.backup_dr.dr_vault_arn
}

output "vault_lock_mode" {
  description = "Vault Lock mode applied to both vaults."
  value       = module.backup_dr.vault_lock_mode
}

output "backup_plan_ids" {
  description = "Backup plan IDs by tier."
  value       = module.backup_dr.backup_plan_ids
}

output "notification_topic_arns" {
  description = "Notification topics per region."
  value       = module.backup_dr.notification_topic_arns
}

output "restore_testing_plan_arn" {
  description = "Restore testing plan ARN."
  value       = module.backup_dr.restore_testing_plan_arn
}

output "restore_validator_function" {
  description = "Restore validator Lambda name."
  value       = module.backup_dr.restore_validator_function
}
