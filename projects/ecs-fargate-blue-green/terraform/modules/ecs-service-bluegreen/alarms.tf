# Deployment alarms. The task asked for alarms on the green (replacement)
# target group; because CodeDeploy alternates the replacement group between
# blue and green on every deployment, the same pair of alarms exists for
# both groups and all four are wired into the deployment group. Any of them
# in ALARM during a deployment stops it and rolls back
# (DEPLOYMENT_STOP_ON_ALARM).
resource "aws_cloudwatch_metric_alarm" "target_5xx" {
  for_each = var.alarms_enabled ? local.colors : toset([])

  alarm_name          = "${local.name}-${each.key}-target-5xx"
  alarm_description   = "${local.name}: 5xx responses from ${each.key} targets. Stops and rolls back a CodeDeploy deployment."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = var.alarm_evaluation_periods
  datapoints_to_alarm = var.alarm_evaluation_periods
  threshold           = var.target_5xx_threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  tags                = local.tags

  dimensions = {
    LoadBalancer = aws_lb.this.arn_suffix
    TargetGroup  = aws_lb_target_group.this[each.key].arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "p95_latency" {
  for_each = var.alarms_enabled ? local.colors : toset([])

  alarm_name          = "${local.name}-${each.key}-p95-latency"
  alarm_description   = "${local.name}: p95 TargetResponseTime of ${each.key} targets. Stops and rolls back a CodeDeploy deployment."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  extended_statistic  = "p95"
  period              = 60
  evaluation_periods  = var.alarm_evaluation_periods
  datapoints_to_alarm = var.alarm_evaluation_periods
  threshold           = var.p95_latency_threshold_seconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  tags                = local.tags

  dimensions = {
    LoadBalancer = aws_lb.this.arn_suffix
    TargetGroup  = aws_lb_target_group.this[each.key].arn_suffix
  }
}
