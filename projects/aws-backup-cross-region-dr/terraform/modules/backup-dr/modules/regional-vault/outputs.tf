output "vault_name" {
  description = "Backup vault name."
  value       = aws_backup_vault.this.name
}

output "vault_arn" {
  description = "Backup vault ARN."
  value       = aws_backup_vault.this.arn
}

output "kms_key_arn" {
  description = "Vault CMK ARN."
  value       = aws_kms_key.vault.arn
}

output "notification_topic_arn" {
  description = "Encrypted SNS topic for vault notifications, job-failure events and alarms in this region."
  value       = aws_sns_topic.notify.arn
}

output "notification_key_arn" {
  description = "CMK encrypting the notification topic."
  value       = aws_kms_key.notify.arn
}

output "vault_lock_mode" {
  description = "governance, compliance, or disabled."
  value       = !var.vault_lock.enabled ? "disabled" : (var.vault_lock.changeable_for_days == null ? "governance" : "compliance")
}

output "account_id" {
  description = "Account that owns this vault."
  value       = local.account_id
}

output "region" {
  description = "Region of this vault."
  value       = local.region
}
