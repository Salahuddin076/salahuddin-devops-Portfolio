output "instance_arn" {
  description = "IAM Identity Center instance ARN."
  value       = local.instance_arn
}

output "permission_set_arns" {
  description = "Permission set name -> ARN."
  value       = { for k, ps in aws_ssoadmin_permission_set.this : k => ps.arn }
}

output "assignments" {
  description = "Created assignments as group/account/permission-set keys."
  value       = sort(keys(aws_ssoadmin_account_assignment.this))
}
