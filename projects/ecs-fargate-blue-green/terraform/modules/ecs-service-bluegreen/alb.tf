# This environment's own ALB. CodeDeploy shifts ECS traffic by rewriting the
# DEFAULT action of the production and test listeners (a weighted forward
# between the two target groups), which is the shape AWS documents. Hence
# one ALB per environment, each listener with a single default forward and
# no listener rules (docs/decisions/0004-alb-per-environment.md).

data "aws_vpc" "this" {
  id = var.vpc_id
}

resource "aws_security_group" "alb" {
  name_prefix = "${local.name}-alb-"
  description = "${local.name} ALB: 443/80 from production_ingress_cidrs, test port from test_listener_cidrs"
  vpc_id      = var.vpc_id
  tags        = merge(local.tags, { Name = "${local.name}-alb" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  for_each = toset(var.production_ingress_cidrs)

  security_group_id = aws_security_group.alb.id
  description       = "Production HTTPS listener"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_ingress_rule" "http_redirect" {
  for_each = toset(var.production_ingress_cidrs)

  security_group_id = aws_security_group.alb.id
  description       = "HTTP, redirected to HTTPS"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_ingress_rule" "test_listener" {
  for_each = toset(var.test_listener_cidrs)

  security_group_id = aws_security_group.alb.id
  description       = "Test listener (replacement task set before traffic shifts)"
  ip_protocol       = "tcp"
  from_port         = var.test_listener_port
  to_port           = var.test_listener_port
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_egress_rule" "alb_to_vpc" {
  security_group_id = aws_security_group.alb.id
  description       = "Traffic and health checks to tasks inside the VPC only"
  ip_protocol       = "tcp"
  from_port         = var.container_port
  to_port           = var.container_port
  cidr_ipv4         = data.aws_vpc.this.cidr_block
}

resource "aws_lb" "this" {
  name                       = "${local.name}-alb"
  load_balancer_type         = "application"
  internal                   = false
  security_groups            = [aws_security_group.alb.id]
  subnets                    = var.public_subnet_ids
  drop_invalid_header_fields = true
  desync_mitigation_mode     = "defensive"
  enable_deletion_protection = var.enable_deletion_protection
  idle_timeout               = 60
  tags                       = local.tags
}

# Two target groups. CodeDeploy alternates which one is live: for the first
# deployment blue is original and green is replacement; the next deployment
# reverses them.
resource "aws_lb_target_group" "this" {
  for_each = local.colors

  name                 = substr("${local.name}-${each.key}", 0, 32)
  port                 = var.container_port
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.vpc_id
  deregistration_delay = var.deregistration_delay_seconds
  tags                 = merge(local.tags, { color = each.key })

  health_check {
    path                = var.health_check_path
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Production listener: one default forward, owned by CodeDeploy after
# creation. DNS for host_header (e.g. api.example.com) aliases this ALB.
resource "aws_lb_listener" "production" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = var.ssl_policy
  certificate_arn   = var.certificate_arn
  tags              = local.tags

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this["blue"].arn
  }

  lifecycle {
    ignore_changes = [default_action]
  }
}

# Test listener: CodeDeploy points it at the replacement target group so
# BeforeAllowTraffic can test green before any production traffic moves.
resource "aws_lb_listener" "test" {
  load_balancer_arn = aws_lb.this.arn
  port              = var.test_listener_port
  protocol          = "HTTPS"
  ssl_policy        = var.ssl_policy
  certificate_arn   = var.certificate_arn
  tags              = local.tags

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this["blue"].arn
  }

  lifecycle {
    ignore_changes = [default_action]
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"
  tags              = local.tags

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
