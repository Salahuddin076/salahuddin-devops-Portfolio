resource "aws_codedeploy_app" "this" {
  name             = local.name
  compute_platform = "ECS"
  tags             = local.tags
}

resource "aws_codedeploy_deployment_group" "this" {
  app_name               = aws_codedeploy_app.this.name
  deployment_group_name  = local.name
  service_role_arn       = aws_iam_role.codedeploy.arn
  deployment_config_name = var.deployment_config_name
  tags                   = local.tags

  deployment_style {
    deployment_type   = "BLUE_GREEN"
    deployment_option = "WITH_TRAFFIC_CONTROL"
  }

  auto_rollback_configuration {
    enabled = true
    events  = var.auto_rollback_events
  }

  alarm_configuration {
    enabled = var.alarms_enabled
    alarms = var.alarms_enabled ? concat(
      [for a in aws_cloudwatch_metric_alarm.target_5xx : a.alarm_name],
      [for a in aws_cloudwatch_metric_alarm.p95_latency : a.alarm_name],
    ) : []
    # If CodeDeploy can't read an alarm, fail the deployment rather than
    # carry on unguarded.
    ignore_poll_alarm_failure = false
  }

  blue_green_deployment_config {
    # manual_reroute = true: green is started and reachable on the test
    # listener, then CodeDeploy waits up to reroute_wait_minutes for
    # `aws deploy continue-deployment --deployment-wait-type READY_WAIT`;
    # without it the deployment is stopped and production never moves.
    deployment_ready_option {
      action_on_timeout    = var.manual_reroute ? "STOP_DEPLOYMENT" : "CONTINUE_DEPLOYMENT"
      wait_time_in_minutes = var.manual_reroute ? var.reroute_wait_minutes : 0
    }

    # Blue stays up for the termination wait: the rollback window.
    terminate_blue_instances_on_deployment_success {
      action                           = "TERMINATE"
      termination_wait_time_in_minutes = var.termination_wait_minutes
    }
  }

  ecs_service {
    cluster_name = var.cluster_name
    service_name = aws_ecs_service.app.name
  }

  load_balancer_info {
    target_group_pair_info {
      prod_traffic_route {
        listener_arns = [aws_lb_listener.production.arn]
      }

      test_traffic_route {
        listener_arns = [aws_lb_listener.test.arn]
      }

      target_group {
        name = aws_lb_target_group.this["blue"].name
      }

      target_group {
        name = aws_lb_target_group.this["green"].name
      }
    }
  }
}
