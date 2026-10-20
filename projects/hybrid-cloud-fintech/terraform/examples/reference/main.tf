# Reference wiring of the connectivity and segmentation modules into one
# root so `terraform validate` exercises the whole graph. A real deployment
# splits this across separate state (edge VPC/EKS, regulated VPC/RDS,
# connectivity) -- see docs/decisions/0002-separate-state-per-boundary.md.
# This root never ties into the EKS/RDS Terraform in
# ../../../aws-multi-region-eks-dr or ../../../aws-landing-zone; it only
# proves the hybrid boundary (connectivity + segmentation) composes and
# validates on its own.

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr_block
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.name_prefix}-vpc"
  }
}

resource "aws_subnet" "edge" {
  vpc_id            = aws_vpc.this.id
  cidr_block        = var.edge_subnet_cidr_block
  availability_zone = "${var.region}a"

  tags = {
    Name = "${var.name_prefix}-edge-subnet"
    Zone = "edge"
  }
}

resource "aws_subnet" "regulated" {
  vpc_id            = aws_vpc.this.id
  cidr_block        = var.regulated_subnet_cidr_block
  availability_zone = "${var.region}a"

  tags = {
    Name = "${var.name_prefix}-regulated-subnet"
    Zone = "regulated"
  }
}

resource "aws_route_table" "edge" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${var.name_prefix}-edge-rt"
  }
}

resource "aws_route_table" "regulated" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${var.name_prefix}-regulated-rt"
  }
}

resource "aws_route_table_association" "edge" {
  subnet_id      = aws_subnet.edge.id
  route_table_id = aws_route_table.edge.id
}

resource "aws_route_table_association" "regulated" {
  subnet_id      = aws_subnet.regulated.id
  route_table_id = aws_route_table.regulated.id
}

# --- Connectivity: redundant Site-to-Site VPN to the on-prem VMware DCs ---
# Only the regulated route table propagates on-prem routes: the edge zone
# never gets a direct route to on-prem, it only reaches the regulated zone
# through the security-group-gated flow below.
module "connectivity" {
  source = "../../modules/connectivity"

  name_prefix      = var.name_prefix
  vpc_id           = aws_vpc.this.id
  on_prem_gateways = var.on_prem_gateways
  route_table_ids  = [aws_route_table.regulated.id]
}

# --- Segmentation: edge zone (customer-facing) ---
module "edge_zone" {
  source = "../../modules/segmentation"

  name_prefix      = var.name_prefix
  vpc_id           = aws_vpc.this.id
  zone             = "edge"
  subnet_ids       = [aws_subnet.edge.id]
  zone_cidr_blocks = [var.edge_subnet_cidr_block]

  allowed_ingress = [
    {
      description = "HTTPS from the public internet via CloudFront/ALB"
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    },
  ]

  allowed_egress = [
    {
      # Addressed by the regulated subnet's CIDR, not its security-group id:
      # referencing module.regulated_zone's output here would make this
      # module depend on regulated_zone while regulated_zone's ingress rule
      # below depends on edge_zone, a module dependency cycle Terraform
      # rejects outright. The regulated zone's own security group (not this
      # rule) is still what actually gates the inbound side.
      description = "Edge services call the regulated zone's internal API on 8443"
      from_port   = 8443
      to_port     = 8443
      protocol    = "tcp"
      cidr_blocks = [var.regulated_subnet_cidr_block]
    },
    {
      description = "Outbound HTTPS for third-party/card-network API calls and package pulls"
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    },
  ]
}

# --- Segmentation: regulated zone (CDE-equivalent systems of record) ---
# Every ingress/egress entry here is either from/to the edge zone's security
# group or a documentation-safe on-prem/controls CIDR -- never 0.0.0.0/0.
# The segmentation module's own preconditions fail `terraform plan` if that
# is violated; tests/test_terraform_static.py checks the text stays that way.
module "regulated_zone" {
  source = "../../modules/segmentation"

  name_prefix      = var.name_prefix
  vpc_id           = aws_vpc.this.id
  zone             = "regulated"
  subnet_ids       = [aws_subnet.regulated.id]
  zone_cidr_blocks = [var.regulated_subnet_cidr_block]

  allowed_ingress = [
    {
      description              = "Internal API from the edge zone only"
      from_port                = 8443
      to_port                  = 8443
      protocol                 = "tcp"
      source_security_group_id = module.edge_zone.security_group_id
    },
  ]

  allowed_egress = [
    {
      description = "Database replication to the on-prem systems of record over the private VPN link"
      from_port   = 5432
      to_port     = 5432
      protocol    = "tcp"
      cidr_blocks = [for g in var.on_prem_gateways : g.on_prem_cidr_block]
    },
    {
      description = "Log shipping to the SIEM/SOC collector (controls zone, documentation-safe CIDR)"
      from_port   = 6514
      to_port     = 6514
      protocol    = "tcp"
      cidr_blocks = ["192.0.2.0/24"]
    },
  ]
}
