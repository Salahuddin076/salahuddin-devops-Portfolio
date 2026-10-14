resource "aws_security_group" "tasks" {
  name_prefix = "${local.name}-tasks-"
  description = "${local.name} tasks: container port from the ALB only"
  vpc_id      = var.vpc_id
  tags        = merge(local.tags, { Name = "${local.name}-tasks" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "tasks_from_alb" {
  security_group_id            = aws_security_group.tasks.id
  description                  = "Traffic and health checks from this environment's ALB"
  ip_protocol                  = "tcp"
  from_port                    = var.container_port
  to_port                      = var.container_port
  referenced_security_group_id = aws_security_group.alb.id
}

# HTTPS out for ECR, Secrets Manager and CloudWatch Logs (through NAT or
# interface endpoints).
resource "aws_vpc_security_group_egress_rule" "tasks_https" {
  security_group_id = aws_security_group.tasks.id
  description       = "HTTPS to AWS APIs"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_security_group" "hooks" {
  name_prefix = "${local.name}-hooks-"
  description = "${local.name} lifecycle hook Lambdas: outbound HTTPS only"
  vpc_id      = var.vpc_id
  tags        = merge(local.tags, { Name = "${local.name}-hooks" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_egress_rule" "hooks_https" {
  security_group_id = aws_security_group.hooks.id
  description       = "Production listener and AWS APIs"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "hooks_test_listener" {
  security_group_id = aws_security_group.hooks.id
  description       = "Test listener"
  ip_protocol       = "tcp"
  from_port         = var.test_listener_port
  to_port           = var.test_listener_port
  cidr_ipv4         = "0.0.0.0/0"
}
