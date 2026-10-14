# Route 53 failover in front of the two regional ALBs.
#
#   <region>.<record_name>  simple alias per region: what the health checks
#                           probe and what operators curl directly
#   <record_name>           failover pair, PRIMARY + SECONDARY, each with a
#                           deep health check on /healthz/ready
#
# The ALBs are created by the AWS Load Balancer Controller from each region's
# Ingress, so nothing here exists until dns.primary_alb and dns.dr_alb are set
# (phase 2 of the bootstrap, docs/operations.md).
#
# Who owns the failover roles: Terraform sets them once (the primary region is
# PRIMARY). From then on the failover CLI swaps them in one atomic change
# batch, and Terraform ignores the routing policy so a routine apply after a
# failover can't silently send traffic back to the fenced region. Health
# checks alone also move traffic when the primary's health check fails; the
# swap is what keeps it moved once the old primary answers again.

locals {
  dns_enabled = var.dns != null && try(var.dns.primary_alb, null) != null
  dns_regions = local.dns_enabled ? {
    (local.primary_region) = { alb = var.dns.primary_alb, initial_role = "PRIMARY" }
    (local.dr_region)      = { alb = var.dns.dr_alb, initial_role = "SECONDARY" }
  } : {}
}

resource "aws_route53_record" "regional" {
  provider = aws.primary
  for_each = local.dns_regions

  zone_id = var.dns.hosted_zone_id
  name    = "${each.key}.${var.dns.record_name}"
  type    = "A"

  alias {
    name                   = each.value.alb.dns_name
    zone_id                = each.value.alb.zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_health_check" "regional" {
  provider = aws.primary
  for_each = local.dns_regions

  type              = "HTTPS"
  fqdn              = aws_route53_record.regional[each.key].fqdn
  port              = 443
  resource_path     = var.dns.health_check_path
  request_interval  = var.dns.request_interval
  failure_threshold = var.dns.failure_threshold
  enable_sni        = true
  measure_latency   = false

  tags = merge(var.tags, {
    Name   = "${var.name}-${each.key}-ready"
    region = each.key
  })
}

resource "aws_route53_record" "failover" {
  provider = aws.primary
  for_each = local.dns_regions

  zone_id         = var.dns.hosted_zone_id
  name            = var.dns.record_name
  type            = "A"
  set_identifier  = each.key
  health_check_id = aws_route53_health_check.regional[each.key].id

  failover_routing_policy {
    type = each.value.initial_role
  }

  alias {
    name                   = each.value.alb.dns_name
    zone_id                = each.value.alb.zone_id
    evaluate_target_health = true
  }

  lifecycle {
    ignore_changes = [failover_routing_policy]
  }
}

# Route 53 publishes health check metrics only in us-east-1, whatever the zone
# or ALB region. The alarms are created only when the primary provider is in
# us-east-1 (the default); with another primary region, add a us-east-1
# provider for them.
resource "aws_cloudwatch_metric_alarm" "health" {
  provider = aws.primary
  for_each = local.primary_region == "us-east-1" ? local.dns_regions : {}

  alarm_name          = "${var.name}-${each.key}-route53-unhealthy"
  alarm_description   = "Route 53 deep health check for ${each.key} is failing: traffic may already be failing over. Decide planned vs unplanned (runbooks/)."
  namespace           = "AWS/Route53"
  metric_name         = "HealthCheckStatus"
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"

  dimensions = {
    HealthCheckId = aws_route53_health_check.regional[each.key].id
  }

  alarm_actions = var.alarm_topic_arns.primary
  ok_actions    = var.alarm_topic_arns.primary
  tags          = var.tags
}
