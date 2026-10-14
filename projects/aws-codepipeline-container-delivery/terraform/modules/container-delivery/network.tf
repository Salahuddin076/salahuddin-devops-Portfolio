# The module takes an existing VPC; it only adds security groups.

resource "aws_security_group" "tasks" {
  name        = "${var.name_prefix}-tasks"
  description = "Fargate tasks for ${var.name_prefix} (staging and prod)"
  vpc_id      = var.vpc_id
  tags        = merge(local.tags, { Name = "${var.name_prefix}-tasks" })
}

resource "aws_vpc_security_group_ingress_rule" "tasks_app" {
  for_each = toset(var.ingress_cidr_blocks)

  security_group_id = aws_security_group.tasks.id
  description       = "App port from ${each.key}"
  ip_protocol       = "tcp"
  from_port         = var.container_port
  to_port           = var.container_port
  cidr_ipv4         = each.key
}

# HTTPS out only: ECR, Secrets Manager, CloudWatch Logs (through NAT or VPC
# endpoints). The app itself makes no other outbound calls.
resource "aws_vpc_security_group_egress_rule" "tasks_https" {
  security_group_id = aws_security_group.tasks.id
  description       = "HTTPS to AWS APIs"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_security_group" "codebuild" {
  count = var.codebuild_in_vpc ? 1 : 0

  name        = "${var.name_prefix}-codebuild"
  description = "CodeBuild projects for ${var.name_prefix}"
  vpc_id      = var.vpc_id
  tags        = merge(local.tags, { Name = "${var.name_prefix}-codebuild" })
}

resource "aws_vpc_security_group_egress_rule" "codebuild_https" {
  count = var.codebuild_in_vpc ? 1 : 0

  security_group_id = aws_security_group.codebuild[0].id
  description       = "HTTPS to AWS APIs, GitHub releases and the base image registry"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}
