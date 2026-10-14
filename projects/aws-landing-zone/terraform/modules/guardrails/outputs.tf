output "scp_ids" {
  description = "SCP name -> policy ID."
  value       = { for k, p in aws_organizations_policy.scp : k => p.id }
}

output "scp_sizes" {
  description = "SCP name -> minified size in characters (limit 5,120)."
  value       = { for k, doc in local.scp_documents : k => length(doc) }
}

output "attachments" {
  description = "Managed SCP attachments as target/policy keys (FullAWSAccess excluded)."
  value       = sort(keys(aws_organizations_policy_attachment.scp))
}

output "tag_policy_id" {
  description = "Required-tags tag policy ID."
  value       = aws_organizations_policy.required_tags.id
}
