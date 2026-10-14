# Network hub in the shared-services (network) account:
#   - a Transit Gateway shared with the organization through RAM;
#   - one TGW route table per environment (prod, nonprod, shared);
#   - a centralized egress VPC with NAT gateways.
#
# Isolation model: prod and nonprod never route to each other.
#   * Each spoke attachment is ASSOCIATED with the route table of its own
#     environment: that table decides where its traffic can go.
#   * Each spoke PROPAGATES its CIDR only into the tables listed in
#     local.propagate_into. The prod table never learns nonprod CIDRs and
#     vice versa; the shared table learns everyone (shared services and the
#     egress VPC must reply to all spokes).
#   * Every table sends 0.0.0.0/0 to the egress VPC, and blackholes the
#     RFC 1918 supernets. Without the blackholes, prod -> nonprod traffic
#     would match 0.0.0.0/0, reach the egress VPC, and be routed back
#     through the shared table into nonprod: the classic hairpin leak.

locals {
  environments = toset(["prod", "nonprod", "shared"])

  # Route-table isolation matrix. Key: the environment of the attachment.
  # Value: the route tables that attachment's CIDR is propagated into.
  propagate_into = {
    prod    = ["prod", "shared"]
    nonprod = ["nonprod", "shared"]
    shared  = ["prod", "nonprod", "shared"]
  }

  # Overlap check across spokes and the egress VPC. Two networks overlap
  # when they are equal after truncating both to the shorter prefix.
  all_cidrs = merge({ egress = var.egress_vpc_cidr }, { for k, v in var.spoke_vpcs : k => v.cidr })
  cidr_keys = keys(local.all_cidrs)
  overlapping_pairs = flatten([
    for i, a in local.cidr_keys : [
      for j, b in local.cidr_keys : "${a} (${local.all_cidrs[a]}) overlaps ${b} (${local.all_cidrs[b]})"
      if j > i && try(
        cidrsubnet("${cidrhost(local.all_cidrs[a], 0)}/${min(tonumber(split("/", local.all_cidrs[a])[1]), tonumber(split("/", local.all_cidrs[b])[1]))}", 0, 0)
        == cidrsubnet("${cidrhost(local.all_cidrs[b], 0)}/${min(tonumber(split("/", local.all_cidrs[a])[1]), tonumber(split("/", local.all_cidrs[b])[1]))}", 0, 0),
        false
      )
    ]
  ])

  nat_count = var.single_nat_gateway ? 1 : length(var.azs)

  spoke_propagations = {
    for p in flatten([
      for name, attachment_id in var.spoke_attachment_ids : [
        for rt in local.propagate_into[var.spoke_vpcs[name].environment] : {
          key           = "${name}->${rt}"
          attachment_id = attachment_id
          route_table   = rt
        }
      ]
    ]) : p.key => p
  }

  blackholes = {
    for p in setproduct(local.environments, var.blackhole_cidrs) : "${p[0]}:${p[1]}" => { route_table = p[0], cidr = p[1] }
  }
}

check "address_plan_has_no_overlaps" {
  assert {
    condition     = length(local.overlapping_pairs) == 0
    error_message = "Address plan overlaps: ${join("; ", local.overlapping_pairs)}"
  }
}

# ----------------------------------------------------------------------------- transit gateway

resource "aws_ec2_transit_gateway" "this" {
  description     = "${var.name_prefix} landing zone hub"
  amazon_side_asn = var.amazon_side_asn

  # No default table: an attachment that nobody associated routes nowhere.
  # This is what makes auto-accept safe for org-shared attachments.
  default_route_table_association = "disable"
  default_route_table_propagation = "disable"
  auto_accept_shared_attachments  = "enable"
  dns_support                     = "enable"
  vpn_ecmp_support                = "enable"

  tags = merge(var.tags, { Name = "${var.name_prefix}-tgw" })

  lifecycle {
    precondition {
      condition     = length(local.overlapping_pairs) == 0
      error_message = "Address plan overlaps: ${join("; ", local.overlapping_pairs)}"
    }
  }
}

resource "aws_ram_resource_share" "tgw" {
  name                      = "${var.name_prefix}-tgw"
  allow_external_principals = false
  tags                      = var.tags
}

resource "aws_ram_resource_association" "tgw" {
  resource_arn       = aws_ec2_transit_gateway.this.arn
  resource_share_arn = aws_ram_resource_share.tgw.arn
}

resource "aws_ram_principal_association" "org" {
  principal          = var.organization_arn
  resource_share_arn = aws_ram_resource_share.tgw.arn
}

resource "aws_ec2_transit_gateway_route_table" "this" {
  for_each = local.environments

  transit_gateway_id = aws_ec2_transit_gateway.this.id
  tags               = merge(var.tags, { Name = "${var.name_prefix}-tgw-rt-${each.key}" })
}

# ----------------------------------------------------------------------------- egress VPC

resource "aws_vpc" "egress" {
  cidr_block           = var.egress_vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(var.tags, { Name = "${var.name_prefix}-egress" })
}

resource "aws_internet_gateway" "egress" {
  vpc_id = aws_vpc.egress.id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-egress-igw" })
}

resource "aws_subnet" "public" {
  count = length(var.azs)

  vpc_id            = aws_vpc.egress.id
  availability_zone = var.azs[count.index]
  cidr_block        = cidrsubnet(var.egress_vpc_cidr, 4, count.index)
  tags              = merge(var.tags, { Name = "${var.name_prefix}-egress-public-${var.azs[count.index]}" })
}

resource "aws_subnet" "tgw" {
  count = length(var.azs)

  vpc_id            = aws_vpc.egress.id
  availability_zone = var.azs[count.index]
  # Small /28s at the top of the range, one per AZ, for the TGW ENIs only.
  cidr_block = cidrsubnet(var.egress_vpc_cidr, 12, 4095 - count.index)
  tags       = merge(var.tags, { Name = "${var.name_prefix}-egress-tgw-${var.azs[count.index]}" })
}

resource "aws_eip" "nat" {
  count = local.nat_count

  domain = "vpc"
  tags   = merge(var.tags, { Name = "${var.name_prefix}-egress-nat-${count.index}" })
}

resource "aws_nat_gateway" "egress" {
  count = local.nat_count

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  tags          = merge(var.tags, { Name = "${var.name_prefix}-egress-nat-${var.azs[count.index]}" })

  depends_on = [aws_internet_gateway.egress]
}

resource "aws_ec2_transit_gateway_vpc_attachment" "egress" {
  transit_gateway_id = aws_ec2_transit_gateway.this.id
  vpc_id             = aws_vpc.egress.id
  subnet_ids         = aws_subnet.tgw[*].id

  # Keeps both directions of a flow in the same AZ, so stateful NAT works.
  appliance_mode_support                          = "enable"
  transit_gateway_default_route_table_association = false
  transit_gateway_default_route_table_propagation = false

  tags = merge(var.tags, { Name = "${var.name_prefix}-egress-attachment" })
}

# Public subnets: internet via the IGW, private ranges back to the TGW.
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.egress.id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-egress-public" })
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.egress.id
}

resource "aws_route" "public_to_tgw" {
  for_each = toset(var.blackhole_cidrs)

  route_table_id         = aws_route_table.public.id
  destination_cidr_block = each.value
  transit_gateway_id     = aws_ec2_transit_gateway.this.id

  depends_on = [aws_ec2_transit_gateway_vpc_attachment.egress]
}

resource "aws_route_table_association" "public" {
  count = length(var.azs)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# TGW subnets: everything to the NAT gateway in the same AZ.
resource "aws_route_table" "tgw" {
  count = length(var.azs)

  vpc_id = aws_vpc.egress.id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-egress-tgw-${var.azs[count.index]}" })
}

resource "aws_route" "tgw_to_nat" {
  count = length(var.azs)

  route_table_id         = aws_route_table.tgw[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.egress[var.single_nat_gateway ? 0 : count.index].id
}

resource "aws_route_table_association" "tgw" {
  count = length(var.azs)

  subnet_id      = aws_subnet.tgw[count.index].id
  route_table_id = aws_route_table.tgw[count.index].id
}

# ----------------------------------------------------------------------------- TGW routing

# The egress VPC is associated with the shared table, which knows every
# spoke, so replies from the internet find their way back.
resource "aws_ec2_transit_gateway_route_table_association" "egress" {
  transit_gateway_attachment_id  = aws_ec2_transit_gateway_vpc_attachment.egress.id
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.this["shared"].id
}

resource "aws_ec2_transit_gateway_route_table_association" "spoke" {
  for_each = var.spoke_attachment_ids

  transit_gateway_attachment_id  = each.value
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.this[var.spoke_vpcs[each.key].environment].id

  lifecycle {
    precondition {
      condition     = contains(keys(var.spoke_vpcs), each.key)
      error_message = "spoke_attachment_ids key ${each.key} is not in spoke_vpcs (the address plan)."
    }
  }
}

resource "aws_ec2_transit_gateway_route_table_propagation" "spoke" {
  for_each = local.spoke_propagations

  transit_gateway_attachment_id  = each.value.attachment_id
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.this[each.value.route_table].id
}

resource "aws_ec2_transit_gateway_route" "default_to_egress" {
  for_each = local.environments

  destination_cidr_block         = "0.0.0.0/0"
  transit_gateway_attachment_id  = aws_ec2_transit_gateway_vpc_attachment.egress.id
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.this[each.key].id
}

resource "aws_ec2_transit_gateway_route" "blackhole" {
  for_each = local.blackholes

  destination_cidr_block         = each.value.cidr
  blackhole                      = true
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.this[each.value.route_table].id
}
