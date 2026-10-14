output "alb_dns_name" {
  description = "Alias target for host_header (e.g. api.example.com)."
  value       = aws_lb.this.dns_name
}

output "alb_zone_id" {
  description = "Hosted zone ID for the alias record."
  value       = aws_lb.this.zone_id
}

output "service_name" {
  description = "ECS service name."
  value       = aws_ecs_service.app.name
}

output "codedeploy_app_name" {
  description = "CodeDeploy application (aws deploy create-deployment --application-name)."
  value       = aws_codedeploy_app.this.name
}

output "codedeploy_deployment_group_name" {
  description = "CodeDeploy deployment group (--deployment-group-name)."
  value       = aws_codedeploy_deployment_group.this.deployment_group_name
}

output "target_group_names" {
  description = "Blue and green target group names."
  value       = { for k, tg in aws_lb_target_group.this : k => tg.name }
}

output "test_listener_url" {
  description = "Where the replacement task set answers before traffic shifts."
  value       = "https://${var.host_header}:${var.test_listener_port}"
}

output "production_url" {
  description = "Production URL for this environment."
  value       = "https://${var.host_header}"
}

output "hook_function_arns" {
  description = "Lambda ARNs for the appspec BeforeAllowTraffic and AfterAllowTraffic hooks."
  value       = { for k, f in aws_lambda_function.hooks : k => f.arn }
}

output "task_definition_family" {
  description = "Task definition family (FAMILY in deploy/values)."
  value       = aws_ecs_task_definition.app.family
}

output "execution_role_arn" {
  description = "EXECUTION_ROLE_ARN for the rendered task definition."
  value       = aws_iam_role.execution.arn
}

output "task_role_arn" {
  description = "TASK_ROLE_ARN for the rendered task definition."
  value       = aws_iam_role.task.arn
}

output "log_group_name" {
  description = "LOG_GROUP for the rendered task definition."
  value       = aws_cloudwatch_log_group.service.name
}

output "secret_arn" {
  description = "DB_SECRET_ARN for the rendered task definition; set its value out of band."
  value       = aws_secretsmanager_secret.app.arn
}

output "alarm_names" {
  description = "Alarms wired into the deployment group."
  value       = aws_codedeploy_deployment_group.this.alarm_configuration[0].alarms
}
