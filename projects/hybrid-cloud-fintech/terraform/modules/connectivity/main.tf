# Redundant Site-to-Site VPN connectivity between the AWS edge VPC and the
# on-premises VMware environment.
#
# Redundancy comes from two independent layers, both required:
#   1. Two Customer Gateways (two physical/virtual on-prem devices), each
#      with its own VPN Connection. Losing one device or one upstream ISP
#      still leaves a working path.
#   2. Each VPN Connection itself provisions 2 tunnels to 2 AWS endpoints
#      in different availability zones (AWS manages this internally), so
#      a single AWS-side endpoint failure doesn't take down that
#      connection either.
#
# That's up to 4 tunnels across 2 on-prem devices. See
# docs/decisions/0001-redundant-site-to-site-vpn.md for why this was chosen
# over a single Direct Connect circuit for a portfolio-scale reference.

resource "aws_vpn_gateway" "this" {
  vpc_id          = var.vpc_id
  amazon_side_asn = var.amazon_side_asn

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-vgw"
  })
}

resource "aws_customer_gateway" "this" {
  for_each = { for g in var.on_prem_gateways : g.name => g }

  bgp_asn     = var.static_routes_only ? null : each.value.bgp_asn
  ip_address  = each.value.ip_address
  type        = "ipsec.1"
  device_name = each.value.name

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-cgw-${each.value.name}"
  })
}

resource "aws_vpn_connection" "this" {
  for_each = aws_customer_gateway.this

  vpn_gateway_id      = aws_vpn_gateway.this.id
  customer_gateway_id = each.value.id
  type                = "ipsec.1"
  static_routes_only  = var.static_routes_only

  # Explicit inside CIDRs make the tunnel topology reproducible; omit to
  # let AWS assign them. Index 0/1 of each connection's pair of tunnels.
  tunnel1_inside_cidr = length(var.tunnel_inside_cidr_blocks) > 0 ? var.tunnel_inside_cidr_blocks[(index(keys(aws_customer_gateway.this), each.key) * 2)] : null
  tunnel2_inside_cidr = length(var.tunnel_inside_cidr_blocks) > 0 ? var.tunnel_inside_cidr_blocks[(index(keys(aws_customer_gateway.this), each.key) * 2) + 1] : null

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-vpn-${each.key}"
  })
}

# Static routes to each on-prem CIDR when not using BGP. With BGP the
# on-prem router advertises these instead.
resource "aws_vpn_connection_route" "this" {
  for_each = var.static_routes_only ? { for g in var.on_prem_gateways : g.name => g } : {}

  vpn_connection_id      = aws_vpn_connection.this[each.key].id
  destination_cidr_block = each.value.on_prem_cidr_block
}

# Propagate on-prem routes (learned via BGP, or the static routes above)
# into every route table that needs to reach systems of record on-prem --
# normally just the "regulated" subnets' route table(s), not the public
# edge subnets.
resource "aws_vpn_gateway_route_propagation" "this" {
  for_each = toset(var.route_table_ids)

  vpn_gateway_id = aws_vpn_gateway.this.id
  route_table_id = each.value
}
