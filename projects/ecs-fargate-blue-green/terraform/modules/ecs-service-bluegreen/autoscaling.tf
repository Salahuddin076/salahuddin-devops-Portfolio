resource "aws_appautoscaling_target" "service" {
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = "service/${var.cluster_name}/${aws_ecs_service.app.name}"
  min_capacity       = var.min_capacity
  max_capacity       = var.max_capacity
  tags               = local.tags
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "${local.name}-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.service.service_namespace
  scalable_dimension = aws_appautoscaling_target.service.scalable_dimension
  resource_id        = aws_appautoscaling_target.service.resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = var.cpu_target_percent
    scale_in_cooldown  = 300
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

# Requests per target, summed over BOTH target groups. The predefined
# ALBRequestCountPerTarget metric is bound to one target group, and the live
# group alternates between blue and green with every deployment, so a
# policy bound to "blue" would see zero traffic after the next release and
# scale in. FILL(..., 0) keeps the idle group from producing missing data.
resource "aws_appautoscaling_policy" "requests" {
  name               = "${local.name}-requests-per-target"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.service.service_namespace
  scalable_dimension = aws_appautoscaling_target.service.scalable_dimension
  resource_id        = aws_appautoscaling_target.service.resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = var.requests_per_target
    scale_in_cooldown  = 300
    scale_out_cooldown = 60

    customized_metric_specification {
      metrics {
        id          = "requests_per_target"
        label       = "RequestCountPerTarget, blue + green"
        expression  = "FILL(blue, 0) + FILL(green, 0)"
        return_data = true
      }

      dynamic "metrics" {
        for_each = local.colors
        content {
          id          = metrics.value
          return_data = false
          metric_stat {
            stat = "Sum"
            metric {
              namespace   = "AWS/ApplicationELB"
              metric_name = "RequestCountPerTarget"
              dimensions {
                name  = "TargetGroup"
                value = aws_lb_target_group.this[metrics.value].arn_suffix
              }
            }
          }
        }
      }
    }
  }
}
