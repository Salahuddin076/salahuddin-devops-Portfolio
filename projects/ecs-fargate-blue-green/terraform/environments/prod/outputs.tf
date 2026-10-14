output "alb_dns_name" {
  description = "Alias target for this environment's host name."
  value       = module.service.alb_dns_name
}

output "codedeploy_app_name" {
  description = "--application-name for aws deploy create-deployment."
  value       = module.service.codedeploy_app_name
}

output "codedeploy_deployment_group_name" {
  description = "--deployment-group-name for aws deploy create-deployment."
  value       = module.service.codedeploy_deployment_group_name
}

output "test_listener_url" {
  description = "Replacement task set, before traffic shifts."
  value       = module.service.test_listener_url
}

output "production_url" {
  description = "Production URL."
  value       = module.service.production_url
}

output "render_values" {
  description = "Values for scripts/render_appspec.py (add IMAGE and TASK_DEFINITION_ARN per release)."
  value = {
    FAMILY                        = module.service.task_definition_family
    EXECUTION_ROLE_ARN            = module.service.execution_role_arn
    TASK_ROLE_ARN                 = module.service.task_role_arn
    LOG_GROUP                     = module.service.log_group_name
    DB_SECRET_ARN                 = module.service.secret_arn
    BEFORE_ALLOW_TRAFFIC_HOOK_ARN = module.service.hook_function_arns["before"]
    AFTER_ALLOW_TRAFFIC_HOOK_ARN  = module.service.hook_function_arns["after"]
  }
}
