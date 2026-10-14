# Spoke VPC in a workload account: private subnets only, no internet
# gateway, default route to the Transit Gateway (egress is centralized in
# the network hub). The hub associates the attachment with the route table
# of this spoke's environment once its ID is recorded there.

locals {
  spoke       = var.cidr_plan[var.name]
  cidr        = local.spoke.cidr
  environment = local.spoke.environment

  # Two networks overlap when they are equal after truncating both to the
  # shorter prefix.
  reserved_clash = [
    for k, r in var.reserved_cidrs : k
    if try(
      cidrsubnet("${cidrhost(r, 0)}/${min(16, tonumber(split("/", r)[1]))}", 0, 0)
      == cidrsubnet("${cidrhost(local.cidr, 0)}/${min(16, tonumber(split("/", r)[1]))}", 0, 0),
      false
    )
  ]
}

resource "aws_vpc" "this" {
  cidr_block           = local.cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(var.tags, { Name = var.name, Environment = local.environment })

  lifecycle {
    precondition {
      condition     = contains(keys(var.cidr_plan), var.name)
      error_message = "Spoke ${var.name} is not in the address plan."
    }
    precondition {
      condition     = length(local.reserved_clash) == 0
      error_message = "Spoke ${var.name} (${local.cidr}) overlaps reserved block(s): ${join(", ", local.reserved_clash)}."
    }
  }
}

# Workload subnets: /20s from the bottom of the /16.
resource "aws_subnet" "private" {
  count = length(var.azs)

  vpc_id            = aws_vpc.this.id
  availability_zone = var.azs[count.index]
  cidr_block        = cidrsubnet(local.cidr, 4, count.index)
  tags              = merge(var.tags, { Name = "${var.name}-private-${var.azs[count.index]}", Tier = "private" })
}

# Attachment subnets: /28s from the top of the /16, TGW ENIs only.
resource "aws_subnet" "tgw" {
  count = length(var.azs)

  vpc_id            = aws_vpc.this.id
  availability_zone = var.azs[count.index]
  cidr_block        = cidrsubnet(local.cidr, 12, 4095 - count.index)
  tags              = merge(var.tags, { Name = "${var.name}-tgw-${var.azs[count.index]}", Tier = "transit" })
}

# Route table settings (association/propagation) are controlled by the hub
# account; the TGW has no default route table, so nothing is set here.
resource "aws_ec2_transit_gateway_vpc_attachment" "this" {
  transit_gateway_id = var.transit_gateway_id
  vpc_id             = aws_vpc.this.id
  subnet_ids         = aws_subnet.tgw[*].id
  tags               = merge(var.tags, { Name = "${var.name}-attachment", Environment = local.environment })
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "${var.name}-private" })
}

resource "aws_route" "default_to_tgw" {
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  transit_gateway_id     = var.transit_gateway_id

  depends_on = [aws_ec2_transit_gateway_vpc_attachment.this]
}

resource "aws_route_table_association" "private" {
  count = length(var.azs)

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_flow_log" "this" {
  vpc_id               = aws_vpc.this.id
  traffic_type         = "REJECT"
  log_destination_type = "cloud-watch-logs"
  log_destination      = aws_cloudwatch_log_group.flow.arn
  iam_role_arn         = aws_iam_role.flow.arn
  tags                 = var.tags
}

resource "aws_cloudwatch_log_group" "flow" {
  name              = "/vpc/${var.name}/flow-rejects"
  retention_in_days = 30
  tags              = var.tags
}

data "aws_iam_policy_document" "flow_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "flow" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["${aws_cloudwatch_log_group.flow.arn}:*"]
  }
}

resource "aws_iam_role" "flow" {
  name               = "${var.name}-flow-logs"
  assume_role_policy = data.aws_iam_policy_document.flow_trust.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "flow" {
  name   = "write-flow-logs"
  role   = aws_iam_role.flow.id
  policy = data.aws_iam_policy_document.flow.json
}
