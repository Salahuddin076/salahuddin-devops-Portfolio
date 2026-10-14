# The n8n pod security group (attached by the chart's SecurityGroupPolicy when
# security groups for pods are on). Postgres and Redis accept only this group
# plus any extra client groups, never a CIDR.

resource "aws_security_group" "n8n_pods" {
  name        = "${var.name}-pods"
  description = "n8n main, webhook and worker pods"
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name}-pods" })
}

resource "aws_vpc_security_group_ingress_rule" "pods_http_from_vpc" {
  security_group_id = aws_security_group.n8n_pods.id
  description       = "n8n HTTP from the ALB (target-type ip) and kubelet probes"
  ip_protocol       = "tcp"
  from_port         = 5678
  to_port           = 5678
  cidr_ipv4         = data.aws_vpc.this.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "pods_dns" {
  for_each = toset(["tcp", "udp"])

  security_group_id = aws_security_group.n8n_pods.id
  description       = "Cluster DNS (${each.key})"
  ip_protocol       = each.key
  from_port         = 53
  to_port           = 53
  cidr_ipv4         = data.aws_vpc.this.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "pods_to_db" {
  security_group_id            = aws_security_group.n8n_pods.id
  description                  = "Postgres"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.db.id
}

resource "aws_vpc_security_group_egress_rule" "pods_to_cache" {
  security_group_id            = aws_security_group.n8n_pods.id
  description                  = "Valkey"
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
  referenced_security_group_id = aws_security_group.cache.id
}

resource "aws_vpc_security_group_egress_rule" "pods_https" {
  security_group_id = aws_security_group.n8n_pods.id
  description       = "HTTPS to third-party APIs called by workflows"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_security_group" "db" {
  name        = "${var.name}-db"
  description = "n8n Postgres: only from n8n clients"
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name}-db" })
}

resource "aws_vpc_security_group_ingress_rule" "db_from_clients" {
  count = length(local.client_security_group_ids)

  security_group_id            = aws_security_group.db.id
  description                  = "Postgres from n8n clients"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = local.client_security_group_ids[count.index]
}

resource "aws_security_group" "cache" {
  name        = "${var.name}-cache"
  description = "n8n Valkey: only from n8n clients"
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name}-cache" })
}

resource "aws_vpc_security_group_ingress_rule" "cache_from_clients" {
  count = length(local.client_security_group_ids)

  security_group_id            = aws_security_group.cache.id
  description                  = "Valkey from n8n clients"
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
  referenced_security_group_id = local.client_security_group_ids[count.index]
}

# KEDA's operator polls the wait list from its own pods. Without security
# groups for pods it uses the node security group (pass it in
# additional_client_security_group_ids); otherwise give it its own policy.
