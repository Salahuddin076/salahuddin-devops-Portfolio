output "budget_topic_arn" {
  description = "SNS topic receiving budget alerts."
  value       = aws_sns_topic.budget.arn
}

output "access_analyzer_arn" {
  description = "IAM Access Analyzer ARN."
  value       = aws_accessanalyzer_analyzer.this.arn
}

output "budget_name" {
  description = "Monthly cost budget name."
  value       = aws_budgets_budget.monthly.name
}
