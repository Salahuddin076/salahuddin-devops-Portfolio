output "organization_id" {
  description = "Organization ID (o-...). Used for aws:PrincipalOrgID and aws:SourceOrgID conditions."
  value       = aws_organizations_organization.this.id
}

output "organization_arn" {
  description = "Organization ARN, the RAM principal for org-wide shares."
  value       = aws_organizations_organization.this.arn
}

output "management_account_id" {
  description = "Management account ID."
  value       = aws_organizations_organization.this.master_account_id
}

output "root_id" {
  description = "Organization root ID (r-...)."
  value       = local.root_id
}

output "ou_ids" {
  description = "OU key -> ID, including root. Keys match policy/attachments.json."
  value       = local.ou_ids
}

output "account_ids" {
  description = "Account key -> account ID."
  value       = { for k, a in aws_organizations_account.this : k => a.id }
}
