# Security group and (optionally) network ACL for one side of the
# PCI-DSS-style segmentation boundary between customer-facing AWS services
# ("edge") and the systems-of-record zone that talks to on-prem over the
# connectivity module's link ("regulated" -- modeled on a cardholder data
# environment, CDE).
#
# Both the security group and the network ACL are deny-by-default: nothing
# is open except what `allowed_ingress` / `allowed_egress` name explicitly.
# aws_security_group intentionally declares zero bare ingress/egress blocks
# beyond the dynamic ones below -- the AWS provider removes the account
# default "allow all egress" rule for any security group where `egress`
# isn't populated, which is exactly the behaviour this module relies on.

resource "aws_security_group" "this" {
  name_prefix = "${var.name_prefix}-${var.zone}-"
  description = "Segmentation boundary: ${var.zone} zone (deny by default, allow-listed flows only)."
  vpc_id      = var.vpc_id

  dynamic "ingress" {
    for_each = var.allowed_ingress
    content {
      description     = ingress.value.description
      from_port       = ingress.value.from_port
      to_port         = ingress.value.to_port
      protocol        = ingress.value.protocol
      cidr_blocks     = try(ingress.value.cidr_blocks, null)
      security_groups = ingress.value.source_security_group_id != null ? [ingress.value.source_security_group_id] : null
    }
  }

  dynamic "egress" {
    for_each = var.allowed_egress
    content {
      description     = egress.value.description
      from_port       = egress.value.from_port
      to_port         = egress.value.to_port
      protocol        = egress.value.protocol
      cidr_blocks     = try(egress.value.cidr_blocks, null)
      security_groups = egress.value.destination_security_group_id != null ? [egress.value.destination_security_group_id] : null
    }
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-${var.zone}-sg"
    Zone = var.zone
  })

  lifecycle {
    create_before_destroy = true

    precondition {
      condition = var.zone != "regulated" || alltrue([
        for rule in var.allowed_ingress : !contains(coalesce(rule.cidr_blocks, []), "0.0.0.0/0")
      ])
      error_message = "The regulated zone (CDE-equivalent) must never allow ingress from 0.0.0.0/0 -- PCI-DSS segmentation requires it to be reachable only from the edge zone or named management ranges, never the open internet."
    }

    precondition {
      condition = var.zone != "regulated" || alltrue([
        for rule in var.allowed_egress : !contains(coalesce(rule.cidr_blocks, []), "0.0.0.0/0")
      ])
      error_message = "The regulated zone (CDE-equivalent) must never allow egress to 0.0.0.0/0 -- outbound traffic must stay on the private connectivity link or go to the named controls zone (SIEM/log shipping), never the open internet."
    }

    precondition {
      condition = alltrue([
        for rule in concat(var.allowed_ingress, var.allowed_egress) :
        (try(rule.cidr_blocks, null) != null) != (try(rule.source_security_group_id, try(rule.destination_security_group_id, null)) != null)
      ])
      error_message = "Each allowed_ingress/allowed_egress entry must set exactly one of cidr_blocks or the security-group reference, never both and never neither."
    }
  }
}

# Defense in depth for the regulated zone: a network ACL is stateless and
# subnet-wide, so even a security-group misconfiguration on one instance in
# the subnet doesn't silently widen what the subnet accepts. Explicit allow
# rules mirror allowed_ingress/allowed_egress; the highest-numbered rule is
# an explicit DENY ALL so the boundary is visible in the rule set itself,
# not just implied by AWS's "deny after the last rule" default.
resource "aws_network_acl" "this" {
  count = var.enable_network_acl ? 1 : 0

  vpc_id     = var.vpc_id
  subnet_ids = var.subnet_ids

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-${var.zone}-nacl"
    Zone = var.zone
  })
}

resource "aws_network_acl_rule" "ingress" {
  for_each = var.enable_network_acl ? { for idx, rule in var.allowed_ingress : idx => rule } : {}

  network_acl_id = aws_network_acl.this[0].id
  rule_number    = 100 + (each.key * 10)
  egress         = false
  protocol       = each.value.protocol == "-1" ? "-1" : (each.value.protocol == "tcp" ? "6" : (each.value.protocol == "udp" ? "17" : each.value.protocol))
  rule_action    = "allow"
  cidr_block     = try(each.value.cidr_blocks[0], "0.0.0.0/32") # NACLs have no SG references; cross-zone allows are modeled by CIDR
  from_port      = each.value.protocol == "-1" ? null : each.value.from_port
  to_port        = each.value.protocol == "-1" ? null : each.value.to_port
}

resource "aws_network_acl_rule" "egress" {
  for_each = var.enable_network_acl ? { for idx, rule in var.allowed_egress : idx => rule } : {}

  network_acl_id = aws_network_acl.this[0].id
  rule_number    = 100 + (each.key * 10)
  egress         = true
  protocol       = each.value.protocol == "-1" ? "-1" : (each.value.protocol == "tcp" ? "6" : (each.value.protocol == "udp" ? "17" : each.value.protocol))
  rule_action    = "allow"
  cidr_block     = try(each.value.cidr_blocks[0], "0.0.0.0/32")
  from_port      = each.value.protocol == "-1" ? null : each.value.from_port
  to_port        = each.value.protocol == "-1" ? null : each.value.to_port
}

# Ephemeral-port return traffic for connections this zone initiated or
# accepted. Scoped to the zone's own subnets plus 0.0.0.0/0 would defeat the
# point of a NACL here, so it is scoped to the zone's own CIDR blocks only;
# cross-zone return traffic for stateful-looking flows is handled by the
# fact that NACLs are stateless and the peer zone's own NACL allows its side
# explicitly -- see docs/architecture.md for the full rule table.
resource "aws_network_acl_rule" "ephemeral_return" {
  count = var.enable_network_acl && length(var.zone_cidr_blocks) > 0 ? 1 : 0

  network_acl_id = aws_network_acl.this[0].id
  rule_number    = 900
  egress         = false
  protocol       = "6"
  rule_action    = "allow"
  cidr_block     = var.zone_cidr_blocks[0]
  from_port      = 1024
  to_port        = 65535
}

# Explicit deny-all floor. AWS already denies anything past the last rule
# in a custom NACL, but writing it out makes the boundary auditable from
# the rule set alone, and `terraform plan` on a future change that
# accidentally widens the allow-list still shows this rule unchanged.
resource "aws_network_acl_rule" "deny_all_ingress" {
  count = var.enable_network_acl ? 1 : 0

  network_acl_id = aws_network_acl.this[0].id
  rule_number    = 32766
  egress         = false
  protocol       = "-1"
  rule_action    = "deny"
  cidr_block     = "0.0.0.0/0"
}

resource "aws_network_acl_rule" "deny_all_egress" {
  count = var.enable_network_acl ? 1 : 0

  network_acl_id = aws_network_acl.this[0].id
  rule_number    = 32766
  egress         = true
  protocol       = "-1"
  rule_action    = "deny"
  cidr_block     = "0.0.0.0/0"
}
